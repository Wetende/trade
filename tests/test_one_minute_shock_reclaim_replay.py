from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
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


def _arm(direction="SELL"):
    sell = direction == "SELL"
    return PostCloseArm(
        candidate="ONE_MINUTE_SHOCK_RECLAIM_V6",
        arm_id=f"reclaim-{direction.lower()}",
        family=FAILED_HIGH_BREAK_SELL if sell else FAILED_LOW_BREAK_BUY,
        direction=direction,
        level_side="high" if sell else "low",
        level=100.0,
        touch_count=0,
        tolerance=0.2,
        break_margin=0.2,
        zone_low=99.8,
        zone_high=100.2,
        confirmation_type="shock_reclaim",
        confirmation_time=_time(-60),
        confirmation_closed_at=_time(0),
        trigger_eligible_at=_time(5),
        expires_at=_time(90),
        invalidation=100.2 if sell else 99.8,
        confirmation_open=100.8 if sell else 99.2,
        confirmation_high=101.0,
        confirmation_low=99.0,
        confirmation_close=99.5 if sell else 100.5,
    )


def _tick(seconds, bid, ask):
    return MarketTick(time=_time(seconds), bid=bid, ask=ask)


def _config(**updates):
    values = {
        "entry_policy": "SHOCK_RECLAIM_STOP_V6",
        "placement": PlacementConfig(
            minimum_stop_distance=0.35,
            maximum_stop_distance=1.5,
            tick_size=0.01,
        ),
        "reclaim_stop_expiry_seconds": 20,
        "maximum_reclaim_entry_drift_r": 0.75,
    }
    values.update(updates)
    return PostCloseReplayConfig(**values)


def test_sell_reclaim_resets_hold_then_places_and_fills_on_later_tick():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 99.95, 99.99),
            _tick(5.5, 99.97, 100.01),
            _tick(6, 99.95, 99.99),
            _tick(7, 99.94, 99.98),
            _tick(12, 99.90, 99.94),
            _tick(13, 99.88, 99.92),
            _tick(14, 99.20, 99.24),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.triggered_at == _time(7)
    assert row.placed_at == _time(12)
    assert row.filled_at == _time(13)
    assert row.direction == "SELL"
    assert row.filled is True
    assert row.outcome == "WIN"
    assert row.entry_drift_r is not None
    assert row.entry_drift_r <= 0.75


def test_buy_reclaim_is_exact_execution_mirror():
    result = replay_post_close_arms(
        [_arm("BUY")],
        [
            _tick(5, 100.01, 100.05),
            _tick(6, 100.02, 100.06),
            _tick(11, 100.06, 100.10),
            _tick(12, 100.08, 100.12),
            _tick(13, 100.76, 100.80),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.triggered_at == _time(6)
    assert row.placed_at == _time(11)
    assert row.filled_at == _time(12)
    assert row.direction == "BUY"
    assert row.outcome == "WIN"


def test_reclaim_stop_expires_without_future_cross():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 99.95, 99.99),
            _tick(6, 99.94, 99.98),
            _tick(11, 99.90, 99.94),
            _tick(31, 99.91, 99.95),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.filled is False
    assert row.reason == "PENDING_RECLAIM_STOP_EXPIRED"
    assert summarize_executability(result)["pending_expiry_rate"] == 1.0


def test_reclaim_stop_rejects_risk_after_outward_grid_snap():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 99.95, 99.99),
            _tick(6, 99.94, 99.98),
            _tick(11, 98.65, 98.69),
        ],
        config=_config(),
    )

    assert result.rows[0].reason == "STOP_DISTANCE_ABOVE_MAXIMUM"


def test_reclaim_stop_rejects_level_to_entry_drift():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 99.95, 99.99),
            _tick(6, 99.94, 99.98),
            _tick(11, 98.95, 98.99),
        ],
        config=_config(
            placement=PlacementConfig(
                minimum_stop_distance=0.35,
                maximum_stop_distance=10.0,
                tick_size=0.01,
            )
        ),
    )

    assert result.rows[0].reason == "RECLAIM_ENTRY_DRIFT_ABOVE_MAXIMUM"
