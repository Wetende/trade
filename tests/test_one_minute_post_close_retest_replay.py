from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.one_minute_entry_model import HIGH_BREAK_BUY
from tradingagents.agents.price_action.one_minute_post_close_replay import (
    PostCloseReplayConfig,
    replay_post_close_arms,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    CANDIDATE_NAME,
    PlacementConfig,
    PostCloseArm,
)
from tradingagents.agents.price_action.opening_tick_replay import MarketTick


START = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _time(seconds):
    return (START + timedelta(seconds=seconds)).isoformat()


def _arm():
    return PostCloseArm(
        candidate=CANDIDATE_NAME,
        arm_id="v2-arm",
        family=HIGH_BREAK_BUY,
        direction="BUY",
        level_side="high",
        level=100.0,
        touch_count=2,
        tolerance=0.2,
        break_margin=0.05,
        zone_low=99.8,
        zone_high=100.2,
        confirmation_type="strong_close",
        confirmation_time=_time(-60),
        confirmation_closed_at=_time(0),
        trigger_eligible_at=_time(5),
        expires_at=_time(60),
        invalidation=99.7,
        confirmation_open=99.9,
        confirmation_high=100.3,
        confirmation_low=99.8,
        confirmation_close=100.28,
    )


def _tick(seconds, bid, ask):
    return MarketTick(time=_time(seconds), bid=bid, ask=ask)


def _config(**updates):
    values = {
        "placement": PlacementConfig(
            minimum_stop_distance=0.35,
            maximum_stop_distance=1.0,
            tick_size=0.01,
        ),
        "entry_policy": "RETEST_LIMIT_V2",
        "pending_expiry_seconds": 20,
        "cost_per_fill_r": 0.05,
    }
    values.update(updates)
    return PostCloseReplayConfig(**values)


def test_v2_places_after_trigger_then_fills_only_on_later_retest_tick():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(10, 100.18, 100.20),
            _tick(11, 100.25, 100.30),
            _tick(12, 100.15, 100.20),
            _tick(13, 100.55, 100.60),
            _tick(14, 100.75, 100.80),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.triggered_at == _time(6)
    assert row.placed_at == _time(11)
    assert row.filled_at == _time(12)
    assert row.reason == "SCALP_PROFIT_EXIT"
    assert row.profit_r is not None and row.profit_r > 0
    fill = next(event for event in result.events if event["event"] == "FILL_SIMULATED")
    assert fill["intended_entry"] == 100.2
    assert fill["entry"] == 100.2


def test_v2_quote_before_placement_cannot_fill_pending_order():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(10, 100.15, 100.20),
            _tick(11, 100.25, 100.30),
            _tick(32, 100.25, 100.30),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.filled is False
    assert row.reason == "PENDING_RETEST_EXPIRED"


def test_v2_rejects_when_retest_already_crossed_at_placement():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(11, 100.15, 100.20),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.outcome == "REJECTED"
    assert row.reason == "BUY_RETEST_ALREADY_CROSSED_AT_PLACEMENT"
    assert row.filled is False


def test_v2_cancels_pending_order_on_structural_invalidation():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(11, 100.25, 100.30),
            _tick(12, 99.65, 99.70),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.outcome == "INVALIDATED"
    assert row.reason == "BUY_STORY_INVALIDATED_BEFORE_FILL"
    assert row.filled is False


def test_v2_pending_expiry_is_absolute_across_sparse_ticks():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(11, 100.25, 100.30),
            _tick(31, 100.25, 100.30),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.reason == "PENDING_RETEST_EXPIRED"
    assert row.closed_at == _time(31)
