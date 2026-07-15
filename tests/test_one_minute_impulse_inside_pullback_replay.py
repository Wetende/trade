from dataclasses import replace
from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.one_minute_impulse_inside_pullback import (
    IMPULSE_INSIDE_PULLBACK_BUY,
    IMPULSE_INSIDE_PULLBACK_SELL,
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
        candidate="ONE_MINUTE_IMPULSE_INSIDE_PULLBACK_V7",
        arm_id=f"inside-{direction.lower()}",
        family=(
            IMPULSE_INSIDE_PULLBACK_BUY
            if buy
            else IMPULSE_INSIDE_PULLBACK_SELL
        ),
        direction=direction,
        level_side="high" if buy else "low",
        level=100.0,
        touch_count=0,
        tolerance=0.25,
        break_margin=0.0,
        zone_low=99.5 if buy else 100.0,
        zone_high=100.0 if buy else 100.5,
        confirmation_type="inside_pullback",
        confirmation_time=_time(-60),
        confirmation_closed_at=_time(0),
        trigger_eligible_at=_time(5),
        expires_at=_time(90),
        invalidation=99.5 if buy else 100.5,
        confirmation_open=99.9 if buy else 100.1,
        confirmation_high=100.0 if buy else 100.5,
        confirmation_low=99.5 if buy else 100.0,
        confirmation_close=99.8 if buy else 100.2,
    )


def _tick(seconds, bid, ask):
    return MarketTick(time=_time(seconds), bid=bid, ask=ask)


def _config(**updates):
    values = {
        "entry_policy": "INSIDE_BREAKOUT_STOP_V7",
        "placement": PlacementConfig(
            minimum_stop_distance=0.35,
            maximum_stop_distance=1.5,
            tick_size=0.01,
        ),
        "inside_stop_expiry_seconds": 20,
        "maximum_inside_entry_drift_r": 0.15,
    }
    values.update(updates)
    return PostCloseReplayConfig(**values)


def test_buy_inside_hold_resets_then_places_and_fills_on_later_tick():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 99.80, 99.84),
            _tick(5.5, 99.70, 99.74),
            _tick(6, 99.80, 99.84),
            _tick(7, 99.81, 99.85),
            _tick(12, 99.86, 99.90),
            _tick(13, 99.98, 100.02),
            _tick(14, 100.85, 100.89),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.triggered_at == _time(7)
    assert row.placed_at == _time(12)
    assert row.filled_at == _time(13)
    assert row.direction == "BUY"
    assert row.outcome == "WIN"
    assert row.entry_drift_r is not None
    assert row.entry_drift_r <= 0.35


def test_sell_inside_breakout_is_exact_execution_mirror():
    result = replay_post_close_arms(
        [_arm("SELL")],
        [
            _tick(5, 100.16, 100.20),
            _tick(6, 100.15, 100.19),
            _tick(11, 100.10, 100.14),
            _tick(12, 99.98, 100.02),
            _tick(13, 99.10, 99.14),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.triggered_at == _time(6)
    assert row.placed_at == _time(11)
    assert row.filled_at == _time(12)
    assert row.direction == "SELL"
    assert row.outcome == "WIN"


def test_inside_breakout_rejects_already_crossed_placement():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 99.80, 99.84),
            _tick(6, 99.81, 99.85),
            _tick(11, 99.98, 100.02),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.reason == "BUY_INSIDE_BREAKOUT_ALREADY_CROSSED_AT_PLACEMENT"
    assert summarize_executability(result)["crossed_count"] == 1


def test_inside_breakout_stop_expires_without_future_cross():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 99.80, 99.84),
            _tick(6, 99.81, 99.85),
            _tick(11, 99.86, 99.90),
            _tick(31, 99.88, 99.92),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.reason == "PENDING_INSIDE_BREAKOUT_STOP_EXPIRED"
    assert summarize_executability(result)["pending_expiry_rate"] == 1.0


def test_inside_breakout_rejects_final_grid_risk_above_cap():
    result = replay_post_close_arms(
        [replace(_arm(), invalidation=98.4, zone_low=98.4)],
        [
            _tick(5, 99.80, 99.84),
            _tick(6, 99.81, 99.85),
            _tick(11, 99.86, 99.90),
        ],
        config=_config(),
    )

    assert result.rows[0].reason == "STOP_DISTANCE_ABOVE_MAXIMUM"


def test_inside_breakout_rejects_boundary_drift_after_grid_snap():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 99.80, 99.84),
            _tick(6, 99.81, 99.85),
            _tick(11, 99.82, 99.86),
        ],
        config=_config(
            placement=PlacementConfig(
                minimum_stop_distance=0.35,
                maximum_stop_distance=1.5,
                tick_size=0.10,
            )
        ),
    )

    assert result.rows[0].reason == "INSIDE_ENTRY_DRIFT_ABOVE_MAXIMUM"
