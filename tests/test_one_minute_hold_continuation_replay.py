from dataclasses import replace
from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.one_minute_entry_model import (
    HIGH_BREAK_BUY,
    LOW_BREAK_SELL,
)
from tradingagents.agents.price_action.one_minute_post_close_evaluation import (
    summarize_executability,
)
from tradingagents.agents.price_action.one_minute_post_close_replay import (
    PostCloseReplayConfig,
    replay_post_close_arms,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PlacementConfig,
    PostCloseArm,
)
from tradingagents.agents.price_action.opening_tick_replay import MarketTick


START = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _time(seconds):
    return (START + timedelta(seconds=seconds)).isoformat()


def _arm(direction="BUY"):
    buy = direction == "BUY"
    return PostCloseArm(
        candidate="ONE_MINUTE_COMPRESSION_HOLD_V5_1",
        arm_id=f"hold-{direction.lower()}",
        family=HIGH_BREAK_BUY if buy else LOW_BREAK_SELL,
        direction=direction,
        level_side="high" if buy else "low",
        level=100.0,
        touch_count=12,
        tolerance=0.2,
        break_margin=0.05,
        zone_low=99.8,
        zone_high=100.2,
        confirmation_type="strong_close",
        confirmation_time=_time(-60),
        confirmation_closed_at=_time(0),
        trigger_eligible_at=_time(5),
        expires_at=_time(120),
        invalidation=99.7 if buy else 100.3,
        confirmation_open=99.8 if buy else 100.2,
        confirmation_high=100.5,
        confirmation_low=99.5,
        confirmation_close=100.4 if buy else 99.6,
    )


def _tick(seconds, bid, ask):
    return MarketTick(time=_time(seconds), bid=bid, ask=ask)


def _config(**updates):
    values = {
        "entry_policy": "HOLD_CONTINUATION_STOP_V5_1",
        "placement": PlacementConfig(
            minimum_stop_distance=0.35,
            maximum_stop_distance=1.5,
            tick_size=0.01,
        ),
        "hold_stop_expiry_seconds": 20,
        "maximum_hold_entry_drift_r": 0.75,
    }
    values.update(updates)
    return PostCloseReplayConfig(**values)


def test_hold_stop_requires_post_close_hold_delay_and_later_tick_fill():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(10.9, 100.25, 100.29),
            _tick(11, 100.26, 100.30),
            _tick(12, 100.28, 100.32),
            _tick(13, 100.75, 100.79),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.triggered_at == _time(6)
    assert row.placed_at == _time(11)
    assert row.filled_at == _time(12)
    assert row.retest_at is None
    assert row.filled is True
    assert row.placement_delay_seconds == 5.0


def test_hold_stop_expires_without_future_cross():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(11, 100.26, 100.30),
            _tick(31, 100.24, 100.28),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.filled is False
    assert row.reason == "PENDING_HOLD_STOP_EXPIRED"
    assert summarize_executability(result)["pending_expiry_rate"] == 1.0


def test_hold_policy_does_not_inherit_retest_resume_trigger():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.00, 100.04),
            _tick(5.5, 100.21, 100.25),
            _tick(6.4, 100.22, 100.26),
            _tick(6.5, 100.23, 100.27),
            _tick(11.5, 100.26, 100.30),
            _tick(12, 100.28, 100.32),
            _tick(13, 100.75, 100.79),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.triggered_at == _time(6.5)
    assert row.placed_at == _time(11.5)
    assert row.filled_at == _time(12)


def test_triggered_hold_can_place_after_arm_timer_before_state_cap():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(115, 100.21, 100.25),
            _tick(116, 100.22, 100.26),
            _tick(121, 100.26, 100.30),
            _tick(122, 100.28, 100.32),
            _tick(123, 100.75, 100.79),
        ],
        config=_config(state_cap_seconds_after_confirmation_close=180),
    )

    row = result.rows[0]
    assert row.triggered_at == _time(116)
    assert row.placed_at == _time(121)
    assert row.filled_at == _time(122)


def test_hold_stop_snaps_outward_from_off_grid_structural_threshold():
    result = replay_post_close_arms(
        [replace(_arm(), break_margin=0.054)],
        [
            _tick(5, 100.21, 100.23),
            _tick(6, 100.22, 100.24),
            _tick(11, 100.22, 100.24),
            _tick(12, 100.23, 100.25),
            _tick(13, 100.24, 100.26),
            _tick(14, 100.75, 100.79),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.placed_at == _time(11)
    assert row.filled_at == _time(13)


def test_hold_stop_checks_maximum_risk_after_direction_safe_snapping():
    result = replay_post_close_arms(
        [replace(_arm(), break_margin=0.054, invalidation=98.755)],
        [
            _tick(5, 100.21, 100.23),
            _tick(6, 100.22, 100.24),
            _tick(11, 100.22, 100.24),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.filled is False
    assert row.reason == "STOP_DISTANCE_ABOVE_MAXIMUM"


def test_hold_stop_rejects_excessive_structural_drift():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(11, 101.96, 102.00),
        ],
        config=_config(
            placement=PlacementConfig(
                minimum_stop_distance=0.35,
                maximum_stop_distance=10.0,
                tick_size=0.01,
            )
        ),
    )

    row = result.rows[0]
    assert row.filled is False
    assert row.reason == "HOLD_ENTRY_DRIFT_ABOVE_MAXIMUM"


def test_hold_stop_sell_is_exact_execution_mirror():
    result = replay_post_close_arms(
        [_arm("SELL")],
        [
            _tick(5, 99.74, 99.78),
            _tick(6, 99.73, 99.77),
            _tick(11, 99.70, 99.74),
            _tick(12, 99.68, 99.72),
            _tick(13, 99.20, 99.24),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.filled is True
    assert row.direction == "SELL"
    assert row.placed_at == _time(11)
    assert row.filled_at == _time(12)
