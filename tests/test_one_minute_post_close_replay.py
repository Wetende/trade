from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import tradingagents.agents.price_action.one_minute_post_close_replay as replay_module
from tradingagents.agents.price_action.models import Candle
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


def _time(seconds: float) -> str:
    return (START + timedelta(seconds=seconds)).isoformat()


def _arm(offset: int = 0, suffix: str = "a") -> PostCloseArm:
    return PostCloseArm(
        candidate=CANDIDATE_NAME,
        arm_id=f"arm-{suffix}",
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
        confirmation_time=_time(offset - 60),
        confirmation_closed_at=_time(offset),
        trigger_eligible_at=_time(offset + 5),
        expires_at=_time(offset + 60),
        invalidation=99.7,
        confirmation_open=99.9,
        confirmation_high=100.3,
        confirmation_low=99.8,
        confirmation_close=100.28,
    )


def _tick(seconds: float, bid: float, ask: float) -> MarketTick:
    return MarketTick(time=_time(seconds), bid=bid, ask=ask)


def _config(**updates) -> PostCloseReplayConfig:
    values = {
        "placement": PlacementConfig(
            minimum_stop_distance=0.35,
            maximum_stop_distance=1.0,
            tick_size=0.01,
        ),
        "cost_per_fill_r": 0.05,
    }
    values.update(updates)
    return PostCloseReplayConfig(**values)


def test_replay_requires_post_close_hold_and_placement_delay_before_fill():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(4.9, 100.21, 100.25),
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(10.9, 100.25, 100.30),
            _tick(11, 100.25, 100.30),
            _tick(12, 100.70, 100.75),
            _tick(13, 100.90, 100.95),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.filled is True
    assert row.triggered_at == _time(6)
    assert row.placed_at == _time(11)
    assert row.reason == "SCALP_PROFIT_EXIT"
    assert row.profit_r is not None and row.profit_r > 0
    assert row.placement_delay_seconds == 5.0
    assert any(event["event"] == "PRE_CAUSAL_QUOTE_IGNORED" for event in result.events)


def test_replay_fast_adverse_exit_requires_two_consecutive_observations():
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(11, 100.25, 100.30),
            _tick(12, 99.90, 99.95),
            _tick(13, 99.89, 99.94),
        ],
        config=_config(),
    )

    row = result.rows[0]
    assert row.reason == "INTRABAR_ADVERSE_EXIT"
    assert row.outcome == "LOSS"
    assert row.closed_at == _time(13)
    assert row.profit_r is not None and -1.0 < row.profit_r < -0.65


def test_replay_enforces_one_active_lifecycle():
    second = replace(_arm(offset=7, suffix="b"), level=101.0, zone_low=100.8, zone_high=101.2)
    result = replay_post_close_arms(
        [_arm(), second],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(11, 100.25, 100.30),
            _tick(20, 100.90, 100.95),
        ],
        config=_config(),
    )

    skipped = next(row for row in result.rows if row.arm_id == "arm-b")
    assert skipped.reason == "ONE_ACTIVE_LIFECYCLE"
    assert skipped.filled is False


def test_replay_records_absolute_expiry_without_a_fill():
    result = replay_post_close_arms(
        [_arm()],
        [_tick(5, 100.0, 100.05), _tick(60, 100.0, 100.05)],
        config=_config(),
    )

    row = result.rows[0]
    assert row.outcome == "EXPIRED"
    assert row.reason == "ARM_EXPIRED"
    assert row.filled is False


def test_replay_candle_rejection_protects_profitable_position():
    bearish = Candle(
        timestamp=_time(-48),
        open=100.6,
        high=100.7,
        low=100.3,
        close=100.4,
        volume=100,
    )
    result = replay_post_close_arms(
        [_arm()],
        [
            _tick(5, 100.21, 100.25),
            _tick(6, 100.22, 100.26),
            _tick(11, 100.25, 100.30),
            _tick(11.5, 100.40, 100.45),
            _tick(13, 100.30, 100.35),
        ],
        candles=[bearish],
        config=_config(),
    )

    assert any(
        event.get("action") == "CANDLE_REJECTION_PARTIAL_EXIT"
        for event in result.events
    )


def test_replay_output_is_deterministic_for_identical_inputs():
    ticks = [
        _tick(5, 100.21, 100.25),
        _tick(6, 100.22, 100.26),
        _tick(11, 100.25, 100.30),
        _tick(12, 100.70, 100.75),
        _tick(13, 100.90, 100.95),
    ]

    first = replay_post_close_arms([_arm()], ticks, config=_config()).as_dict()
    second = replay_post_close_arms([_arm()], ticks, config=_config()).as_dict()

    assert first == second
    assert first["broker_mutation_enabled"] is False


def test_fixture_replay_enforces_start_inclusive_end_exclusive(monkeypatch):
    arms = (_arm(offset=-60, suffix="before"), _arm(), _arm(offset=60, suffix="end"))
    captured = {}

    monkeypatch.setattr(replay_module, "detect_replay_arms", lambda *args, **kwargs: arms)

    def capture(selected_arms, selected_ticks, **kwargs):
        captured["arms"] = tuple(selected_arms)
        captured["ticks"] = tuple(selected_ticks)
        return "captured"

    monkeypatch.setattr(replay_module, "replay_post_close_arms", capture)
    fixture = SimpleNamespace(
        candles=(),
        ticks=(_tick(-1, 1, 2), _tick(0, 1, 2), _tick(59, 1, 2), _tick(60, 1, 2)),
    )

    result = replay_module.replay_post_close_fixture(
        fixture,
        config=_config(evidence_start=_time(0), evidence_end=_time(60)),
    )

    assert result == "captured"
    assert [arm.arm_id for arm in captured["arms"]] == ["arm-a"]
    assert [tick.time for tick in captured["ticks"]] == [_time(0), _time(59)]
