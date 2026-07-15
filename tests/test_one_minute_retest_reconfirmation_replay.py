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
        arm_id="v3-arm",
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


def _config():
    return PostCloseReplayConfig(
        placement=PlacementConfig(
            minimum_stop_distance=0.35,
            maximum_stop_distance=1.0,
            tick_size=0.01,
        ),
        entry_policy="RETEST_RECONFIRM_STOP_V3",
        reconfirmation_stop_expiry_seconds=15,
        state_cap_seconds_after_confirmation_close=90,
        cost_per_fill_r=0.05,
    )


def _prefix():
    return [
        _tick(5, 100.21, 100.25),
        _tick(6, 100.22, 100.26),
        _tick(11, 100.25, 100.30),
        _tick(12, 100.15, 100.20),
    ]


def test_v3_requires_validation_retest_delayed_stop_placement_and_later_fill():
    result = replay_post_close_arms(
        [_arm()],
        [
            *_prefix(),
            _tick(16.9, 100.15, 100.20),
            _tick(17, 100.15, 100.20),
            _tick(18, 100.20, 100.25),
            _tick(19, 100.60, 100.65),
            _tick(20, 100.80, 100.85),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.triggered_at == _time(6)
    assert row.retest_at == _time(12)
    assert row.placed_at == _time(17)
    assert row.filled_at == _time(18)
    assert row.profit_r is not None and row.profit_r > 0
    assert any(event["event"] == "RETEST_OBSERVED" for event in result.events)


def test_v3_rejects_reconfirmation_that_crossed_during_placement_delay():
    result = replay_post_close_arms(
        [_arm()],
        [*_prefix(), _tick(17, 100.25, 100.30)],
        config=_config(),
    )

    row = result.rows[0]
    assert row.reason == "BUY_RECONFIRMATION_ALREADY_CROSSED_AT_PLACEMENT"
    assert row.retest_at == _time(12)
    assert row.filled is False


def test_v3_never_uses_retest_quote_as_a_fill():
    result = replay_post_close_arms(
        [_arm()],
        [*_prefix(), _tick(17, 100.15, 100.20), _tick(32, 100.15, 100.20)],
        config=_config(),
    )

    row = result.rows[0]
    assert row.reason == "PENDING_RETEST_EXPIRED"
    assert row.retest_at == _time(12)
    assert row.filled is False


def test_v3_expires_when_no_retest_arrives_before_absolute_state_cap():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(11, 100.25, 100.30),
            _tick(90, 100.25, 100.30),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.reason == "RECONFIRMATION_STATE_EXPIRED"
    assert row.retest_at is None


def test_v3_invalidates_during_retest_watch_before_order_placement():
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
    assert row.reason == "BUY_STORY_INVALIDATED_DURING_RETEST_WATCH"
    assert row.filled is False
