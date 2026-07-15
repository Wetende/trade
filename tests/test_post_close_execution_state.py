from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.brokers.execution_state import ExecutionStateStore


NOW = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _lifecycle(*, expires_at=None):
    return {
        "phase": "ARMED",
        "arm": {
            "arm_id": "arm-1",
            "candidate": "ONE_MINUTE_SYMMETRIC_POST_CLOSE_STATE_V1",
            "expires_at": (expires_at or NOW + timedelta(seconds=45)).isoformat(),
        },
        "sequence": 0,
    }


def test_post_close_lifecycle_survives_restart_without_extending_expiry(tmp_path):
    first = ExecutionStateStore(tmp_path, "XAUUSD")
    first.record_post_close_lifecycle(_lifecycle())

    restarted = ExecutionStateStore(tmp_path, "XAUUSD")
    recovered = restarted.recover_post_close_lifecycle(
        now_utc=NOW + timedelta(seconds=10)
    )

    assert recovered["status"] == "ACTIVE"
    assert recovered["lifecycle"] == _lifecycle()


def test_recovery_expires_arm_at_original_absolute_time(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_post_close_lifecycle(_lifecycle())

    recovered = store.recover_post_close_lifecycle(
        now_utc=NOW + timedelta(seconds=45)
    )

    assert recovered["status"] == "EXPIRED"
    assert "post_close_lifecycle" not in store.load()


def test_active_broker_state_orphans_and_clears_local_arm(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_post_close_lifecycle(_lifecycle())
    state = store.load()
    state["active_order_ticket"] = 123
    store.save(state)

    recovered = store.recover_post_close_lifecycle(now_utc=NOW)

    assert recovered["status"] == "ORPHANED_BY_ACTIVE_BROKER_STATE"
    assert "post_close_lifecycle" not in store.load()


def test_store_refuses_new_arm_with_active_order_or_position(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    state = store.load()
    state["active_order_ticket"] = 123
    store.save(state)

    with pytest.raises(ValueError, match="active order"):
        store.record_post_close_lifecycle(_lifecycle())

    state = store.load()
    state["active_order_ticket"] = None
    state["active_position_ticket"] = 456
    store.save(state)
    with pytest.raises(ValueError, match="active position"):
        store.record_post_close_lifecycle(_lifecycle())


def test_two_loss_pause_requires_both_time_and_structural_reset_after_restart(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_post_close_trade_outcome(-0.7, closed_at_utc=NOW)
    store.record_post_close_trade_outcome(
        -0.8,
        closed_at_utc=NOW + timedelta(minutes=1),
    )

    restarted = ExecutionStateStore(tmp_path, "XAUUSD")
    during_time = restarted.post_close_entry_gate(
        now_utc=NOW + timedelta(minutes=10)
    )
    after_time = restarted.post_close_entry_gate(
        now_utc=NOW + timedelta(minutes=16)
    )
    restarted.mark_post_close_structural_reset()
    allowed = restarted.post_close_entry_gate(
        now_utc=NOW + timedelta(minutes=16)
    )

    assert during_time["reason"] == "TWO_LOSS_TIME_PAUSE"
    assert after_time["reason"] == "TWO_LOSS_RESET_REQUIRED"
    assert allowed == {"allowed": True, "reason": None}

    restarted.complete_post_close_pause(now_utc=NOW + timedelta(minutes=16))
    assert restarted.load()["post_close_loss_control"]["loss_streak"] == 0


def test_clear_trade_preserves_post_close_safety_state(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_post_close_consumed_zone(_lifecycle()["arm"], consumed_at_utc=NOW)
    store.record_post_close_trade_outcome(-0.5, closed_at_utc=NOW)
    store.record_post_close_lifecycle(_lifecycle())

    cleared = store.clear_trade()

    assert "post_close_lifecycle" in cleared
    assert "post_close_loss_control" in cleared
    assert "post_close_consumed_zones" in cleared


def test_win_resets_loss_streak_without_erasing_consumed_zones(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_post_close_consumed_zone(_lifecycle()["arm"], consumed_at_utc=NOW)
    store.record_post_close_trade_outcome(-0.5, closed_at_utc=NOW)

    state = store.record_post_close_trade_outcome(
        0.4,
        closed_at_utc=NOW + timedelta(minutes=1),
    )

    assert state["post_close_loss_control"]["loss_streak"] == 0
    assert len(state["post_close_consumed_zones"]) == 1
