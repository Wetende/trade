from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
    HIGH_BREAK_BUY,
    HIGH_RESPECT_SELL,
    LOW_BREAK_SELL,
    LOW_RESPECT_BUY,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    CANDIDATE_NAME,
    PlacementConfig,
    PostCloseArm,
    PostClosePhase,
    PostCloseState,
    QuoteObservation,
    detect_post_close_arms,
    evaluate_post_close_placement,
    observe_post_close_quote,
)


START = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _time(seconds: float) -> str:
    return (START + timedelta(seconds=seconds)).isoformat()


def _arm(family: str) -> PostCloseArm:
    buy = family in {HIGH_BREAK_BUY, LOW_RESPECT_BUY, FAILED_LOW_BREAK_BUY}
    level_side = "high" if family in {
        HIGH_BREAK_BUY,
        HIGH_RESPECT_SELL,
        FAILED_HIGH_BREAK_SELL,
    } else "low"
    invalidation = 99.7 if buy else 100.3
    return PostCloseArm(
        candidate=CANDIDATE_NAME,
        arm_id=f"arm-{family}",
        family=family,
        direction="BUY" if buy else "SELL",
        level_side=level_side,
        level=100.0,
        touch_count=2,
        tolerance=0.2,
        break_margin=0.05,
        zone_low=99.8,
        zone_high=100.2,
        confirmation_type="rejection",
        confirmation_time=_time(-60),
        confirmation_closed_at=_time(0),
        trigger_eligible_at=_time(5),
        expires_at=_time(45 if family not in {HIGH_BREAK_BUY, LOW_BREAK_SELL} else 60),
        invalidation=invalidation,
        confirmation_open=100.0,
        confirmation_high=100.25,
        confirmation_low=99.75,
        confirmation_close=100.0,
    )


def _quote(seconds: float, bid: float, ask: float) -> QuoteObservation:
    return QuoteObservation(time=_time(seconds), bid=bid, ask=ask)


def _candle(index: int, open_: float, high: float, low: float, close: float) -> Candle:
    return Candle(
        timestamp=(START + timedelta(minutes=index)).isoformat(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


def test_detects_latest_closed_high_respect_arm_without_using_future_candle():
    candles = [
        _candle(0, 100.0, 101.0, 99.5, 100.5),
        _candle(1, 100.4, 101.02, 100.0, 100.2),
        _candle(2, 100.1, 100.6, 99.9, 100.1),
        _candle(3, 100.4, 101.03, 100.0, 100.05),
    ]

    arms = detect_post_close_arms(candles)

    assert len(arms) == 1
    assert arms[0].family == HIGH_RESPECT_SELL
    assert arms[0].confirmation_time == candles[-1].timestamp
    assert arms[0].trigger_eligible_at == (
        START + timedelta(minutes=4, seconds=5)
    ).isoformat()


def test_pre_causal_quote_cannot_change_armed_state():
    state = PostCloseState(_arm(HIGH_RESPECT_SELL))

    result = observe_post_close_quote(state, _quote(4.999, 100.0, 100.1))

    assert result.event == "PRE_CAUSAL_QUOTE_IGNORED"
    assert result.state == state


@pytest.mark.parametrize(
    ("family", "zone_quote", "trigger_quote"),
    [
        (HIGH_RESPECT_SELL, (99.95, 100.05), (99.70, 99.75)),
        (FAILED_HIGH_BREAK_SELL, (99.95, 100.05), (99.70, 99.75)),
        (LOW_RESPECT_BUY, (99.95, 100.05), (100.25, 100.30)),
        (FAILED_LOW_BREAK_BUY, (99.95, 100.05), (100.25, 100.30)),
    ],
)
def test_reaction_families_require_zone_observation_before_trigger(
    family,
    zone_quote,
    trigger_quote,
):
    state = PostCloseState(_arm(family))
    too_early = observe_post_close_quote(
        state,
        _quote(5, trigger_quote[0], trigger_quote[1]),
    )
    assert too_early.event == "POST_CLOSE_OBSERVATION"

    observed = observe_post_close_quote(
        state,
        _quote(5, zone_quote[0], zone_quote[1]),
    )
    triggered = observe_post_close_quote(
        observed.state,
        _quote(6, trigger_quote[0], trigger_quote[1]),
    )

    assert observed.state.zone_observed is True
    assert triggered.event == "TRIGGER_SATISFIED"
    assert triggered.state.phase == PostClosePhase.TRIGGERED
    assert triggered.state.placement_due_at == _time(11)


@pytest.mark.parametrize(
    ("family", "first", "second"),
    [
        (HIGH_BREAK_BUY, (100.21, 100.25), (100.22, 100.26)),
        (LOW_BREAK_SELL, (99.75, 99.79), (99.74, 99.78)),
    ],
)
def test_break_hold_requires_two_observations_at_least_one_second_apart(
    family,
    first,
    second,
):
    state = PostCloseState(_arm(family))
    one = observe_post_close_quote(state, _quote(5, *first))
    too_soon = observe_post_close_quote(one.state, _quote(5.9, *second))
    triggered = observe_post_close_quote(too_soon.state, _quote(6.1, *second))

    assert one.state.first_hold_at == _time(5)
    assert too_soon.state.phase == PostClosePhase.ARMED
    assert triggered.state.phase == PostClosePhase.TRIGGERED


@pytest.mark.parametrize(
    ("family", "bad_quote", "reason"),
    [
        (HIGH_RESPECT_SELL, (100.25, 100.31), "SELL_STORY_INVALIDATED"),
        (FAILED_HIGH_BREAK_SELL, (100.25, 100.31), "SELL_STORY_INVALIDATED"),
        (LOW_RESPECT_BUY, (99.65, 99.70), "BUY_STORY_INVALIDATED"),
        (FAILED_LOW_BREAK_BUY, (99.65, 99.70), "BUY_STORY_INVALIDATED"),
        (HIGH_BREAK_BUY, (99.65, 99.70), "HIGH_BREAK_INVALIDATED"),
        (LOW_BREAK_SELL, (100.25, 100.31), "LOW_BREAK_INVALIDATED"),
    ],
)
def test_all_families_have_symmetric_structural_invalidation(
    family,
    bad_quote,
    reason,
):
    result = observe_post_close_quote(
        PostCloseState(_arm(family)),
        _quote(5, *bad_quote),
    )

    assert result.event == reason
    assert result.state.phase == PostClosePhase.INVALIDATED


def test_absolute_expiry_is_not_extended_by_observations_or_recovery():
    state = PostCloseState(_arm(HIGH_RESPECT_SELL))
    observed = observe_post_close_quote(state, _quote(5, 99.95, 100.05))
    recovered = PostCloseState.from_dict(observed.state.as_dict())

    expired = observe_post_close_quote(recovered, _quote(45, 99.95, 100.05))

    assert recovered.arm.expires_at == state.arm.expires_at
    assert expired.state.phase == PostClosePhase.EXPIRED
    assert expired.event == "ARM_EXPIRED"


def test_non_monotonic_quote_is_idempotently_ignored():
    state = PostCloseState(_arm(HIGH_RESPECT_SELL))
    observed = observe_post_close_quote(state, _quote(6, 99.95, 100.05))

    repeated = observe_post_close_quote(observed.state, _quote(6, 99.7, 99.75))

    assert repeated.event == "NON_MONOTONIC_QUOTE_IGNORED"
    assert repeated.state == observed.state


def test_placement_uses_current_ask_and_waits_full_delay():
    arm = replace(_arm(LOW_RESPECT_BUY), invalidation=99.75)
    state = PostCloseState(
        arm,
        phase=PostClosePhase.TRIGGERED,
        triggered_at=_time(6),
        placement_due_at=_time(11),
    )

    pending = evaluate_post_close_placement(state, _quote(10.999, 100.25, 100.30))
    placed = evaluate_post_close_placement(
        state,
        _quote(11, 100.25, 100.30),
        config=PlacementConfig(minimum_stop_distance=0.35, tick_size=0.01),
    )

    assert pending.reason == "PLACEMENT_DELAY_PENDING"
    assert placed.accepted is True
    assert placed.entry == 100.30
    assert placed.stop_loss == 99.75
    assert placed.risk_distance == pytest.approx(0.55)
    assert placed.take_profit == 101.12


def test_placement_rejects_story_loss_stop_and_drift_instead_of_chasing():
    triggered = PostCloseState(
        _arm(HIGH_BREAK_BUY),
        phase=PostClosePhase.TRIGGERED,
        triggered_at=_time(6),
        placement_due_at=_time(11),
    )

    crossed = evaluate_post_close_placement(
        triggered,
        _quote(11, 100.0, 100.05),
    )
    too_wide = evaluate_post_close_placement(
        triggered,
        _quote(11, 100.6, 100.7),
        config=PlacementConfig(maximum_stop_distance=0.5),
    )
    drifting_arm = replace(triggered.arm, invalidation=100.25)
    drifting = evaluate_post_close_placement(
        replace(triggered, arm=drifting_arm),
        _quote(11, 100.8, 100.9),
        config=PlacementConfig(maximum_stop_distance=1.0),
    )

    assert crossed.reason == "BUY_TRIGGER_CROSSED_AT_PLACEMENT"
    assert too_wide.reason == "STOP_DISTANCE_ABOVE_MAXIMUM"
    assert drifting.reason == "ENTRY_DRIFT_ABOVE_MAXIMUM"


def test_state_serialization_is_deterministic_and_preserves_arm_identity():
    original = PostCloseState(_arm(LOW_BREAK_SELL), sequence=7)

    recovered = PostCloseState.from_dict(original.as_dict())

    assert recovered == original
    assert recovered.as_dict() == original.as_dict()


def test_future_candle_mutation_cannot_change_an_already_created_arm():
    candles = [
        _candle(0, 100.0, 101.0, 99.5, 100.5),
        _candle(1, 100.4, 101.02, 100.0, 100.2),
        _candle(2, 100.1, 100.6, 99.9, 100.1),
        _candle(3, 100.4, 101.03, 100.0, 100.05),
    ]
    original = detect_post_close_arms(candles)

    with_future_a = detect_post_close_arms(candles + [_candle(4, 100, 110, 90, 109)])
    with_future_b = detect_post_close_arms(candles + [_candle(4, 100, 101, 99, 99.1)])

    assert len(original) == 1
    assert original[0].arm_id not in {arm.arm_id for arm in with_future_a}
    assert original[0].arm_id not in {arm.arm_id for arm in with_future_b}
    assert detect_post_close_arms(candles) == original


def test_only_latest_sixty_closed_candles_can_affect_detection():
    recent = [
        _candle(100, 100.0, 101.0, 99.5, 100.5),
        _candle(101, 100.4, 101.02, 100.0, 100.2),
        _candle(102, 100.1, 100.6, 99.9, 100.1),
        _candle(103, 100.4, 101.03, 100.0, 100.05),
    ]
    padding = [
        _candle(index, 200.0, 200.3, 199.7, 200.1)
        for index in range(44, 100)
    ]
    old_a = [_candle(index, 500, 510, 490, 505) for index in range(44)]
    old_b = [_candle(index, 50, 51, 49, 50.5) for index in range(44)]

    assert detect_post_close_arms(old_a + padding + recent) == detect_post_close_arms(
        old_b + padding + recent
    )
