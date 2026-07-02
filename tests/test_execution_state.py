from datetime import datetime, timezone

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.execution_state import ExecutionStateStore


def _proposal() -> OrderProposal:
    return OrderProposal(
        symbol="XAUUSD",
        side=TradeAction.BUY,
        order_type="LIMIT",
        entry_price=2450.0,
        stop_loss=2447.0,
        take_profit=2456.0,
        timeframe="15m",
        confirmation_timeframe="30m",
        valid_until="2026-05-27 10:15 EDT",
        activation_window_minutes=10,
        cancel_if_not_triggered_after="2026-05-27 10:10 EDT",
        status=OrderStatus.PROPOSED,
        reason="A+ setup passed.",
    )


def test_execution_state_records_active_pending_order(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")

    state = store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    assert state["active_order_ticket"] == 111222
    assert state["symbol"] == "XAUUSD"
    assert state["placed_at_utc"] == "2026-05-27T14:00:00+00:00"
    assert state["cancel_after_utc"] == "2026-05-27T14:10:00+00:00"
    assert state["proposal"]["symbol"] == "XAUUSD"


def test_execution_state_loads_default_when_missing(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")

    assert store.load() == {
        "symbol": "XAUUSD",
        "active_order_ticket": None,
        "active_position_ticket": None,
    }


def test_execution_state_store_has_one_state_filename():
    assert ExecutionStateStore.filename == "mt5_state.json"
    state_file_attrs = [
        name for name in vars(ExecutionStateStore) if name.endswith("filename")
    ]
    assert state_file_attrs == ["filename"]


def test_execution_state_clears_active_pending_order(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    state = store.clear_pending_order()

    assert state["active_order_ticket"] is None
    assert store.load()["active_order_ticket"] is None


def test_execution_state_marks_active_position_and_clears_trade(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    active = store.mark_position_active(333444)

    assert active["active_order_ticket"] is None
    assert active["active_position_ticket"] == 333444
    assert active["proposal"]["symbol"] == "XAUUSD"

    cleared = store.clear_trade()

    assert cleared == {
        "symbol": "XAUUSD",
        "active_order_ticket": None,
        "active_position_ticket": None,
    }


def test_execution_state_uses_default_activation_window(tmp_path):
    proposal = _proposal()
    proposal.activation_window_minutes = None
    store = ExecutionStateStore(tmp_path, "XAUUSD")

    state = store.record_pending_order(
        111222,
        proposal,
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    assert state["cancel_after_utc"] == "2026-05-27T14:10:00+00:00"


def test_execution_state_preserves_consumed_opening_when_trade_is_cleared(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    context = {
        "direction": "BUY",
        "trigger": "LOW_RESPECT_BUY",
        "reaction_type": "respect",
        "confirmation_type": "rejection",
        "level": 2450.0,
        "level_side": "low",
        "level_type": "three_touch",
        "tolerance": 0.2,
        "touch_count": 3,
        "first_touch_timestamp": "2026-07-01T12:00:00+00:00",
        "last_touch_timestamp": "2026-07-01T12:10:00+00:00",
        "confirmation_timestamp": "2026-07-01T12:11:00+00:00",
    }
    store.record_consumed_opening(
        context,
        consumed_at_utc=datetime(2026, 7, 1, 12, 11, 5, tzinfo=timezone.utc),
        order_ticket=111222,
        execution_timeline={"submitted_at_utc": "2026-07-01T12:11:05+00:00"},
    )
    store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 7, 1, 12, 11, 5, tzinfo=timezone.utc),
    )

    state = store.clear_trade()

    assert state["active_order_ticket"] is None
    assert state["active_position_ticket"] is None
    assert state["consumed_openings"][0]["opening_context"] == context
    assert state["consumed_openings"][0]["order_ticket"] == 111222


def test_execution_state_bounds_consumed_openings_to_newest_128(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")

    for index in range(130):
        store.record_consumed_opening(
            {"level": float(index)},
            consumed_at_utc=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        )

    records = store.load()["consumed_openings"]
    assert len(records) == 128
    assert records[0]["opening_context"]["level"] == 129.0
    assert records[-1]["opening_context"]["level"] == 2.0


def test_execution_state_archives_completed_position_telemetry(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    telemetry = {
        "position_id": "777034",
        "position_excursion": {"mfe_points": 0.8, "mae_points": -0.3},
    }

    state = store.archive_position_telemetry("777034", telemetry)
    cleared = store.clear_trade()

    assert state["completed_position_telemetry"]["777034"] == telemetry
    assert cleared["completed_position_telemetry"]["777034"] == telemetry


def test_record_pending_order_preserves_durable_state_and_timeline(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_consumed_opening(
        {"level": 2450.0},
        consumed_at_utc=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    timeline = {
        "submitted_at_utc": "2026-07-01T12:00:01+00:00",
        "acknowledged_at_utc": "2026-07-01T12:00:02+00:00",
    }

    state = store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
        execution_timeline=timeline,
    )

    assert state["execution_timeline"] == timeline
    assert len(state["consumed_openings"]) == 1
