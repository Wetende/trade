from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
    HIGH_BREAK_BUY,
    HIGH_RESPECT_SELL,
    LOW_BREAK_SELL,
    LOW_RESPECT_BUY,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PostCloseArm,
    QuoteObservation,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import (
    AtomicV8StateStore,
    CANDIDATE_NAME,
    V8Config,
    V8Phase,
    V8State,
    evaluate_v8_stop_order,
    expire_v8_pending,
    mark_v8_placed,
    observe_v8_quote,
    start_v8_state,
)


START = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _time(seconds: float) -> str:
    return (START + timedelta(seconds=seconds)).isoformat()


def _arm(family: str) -> PostCloseArm:
    buy = family in {HIGH_BREAK_BUY, LOW_RESPECT_BUY, FAILED_LOW_BREAK_BUY}
    high = family in {HIGH_BREAK_BUY, HIGH_RESPECT_SELL, FAILED_HIGH_BREAK_SELL}
    return PostCloseArm(
        candidate=CANDIDATE_NAME,
        arm_id=f"v8-{family}",
        family=family,
        direction="BUY" if buy else "SELL",
        level_side="high" if high else "low",
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
        expires_at=_time(60),
        invalidation=99.7 if buy else 100.3,
        confirmation_open=100.0,
        confirmation_high=100.25,
        confirmation_low=99.75,
        confirmation_close=100.0,
    )


def _quote(seconds: float, mid: float, spread: float = 0.04) -> QuoteObservation:
    return QuoteObservation(
        time=_time(seconds),
        bid=round(mid - spread / 2.0, 10),
        ask=round(mid + spread / 2.0, 10),
    )


def _start_pressure(family: str):
    state = start_v8_state(_arm(family), _quote(0, 100.0))
    if family in {HIGH_RESPECT_SELL, FAILED_HIGH_BREAK_SELL}:
        state = observe_v8_quote(state, _quote(5, 100.0)).state
        transition = observe_v8_quote(state, _quote(6, 99.72))
    elif family in {LOW_RESPECT_BUY, FAILED_LOW_BREAK_BUY}:
        state = observe_v8_quote(state, _quote(5, 100.0)).state
        transition = observe_v8_quote(state, _quote(6, 100.28))
    elif family == HIGH_BREAK_BUY:
        state = observe_v8_quote(state, _quote(5, 100.24)).state
        transition = observe_v8_quote(state, _quote(6.1, 100.25))
    else:
        state = observe_v8_quote(state, _quote(5, 99.76)).state
        transition = observe_v8_quote(state, _quote(6.1, 99.75))
    assert transition.event == "PRESSURE_WINDOW_STARTED"
    return transition.state


def _complete_pressure(state, *, favorable_step: float = 0.01):
    sign = 1.0 if state.arm.direction == "BUY" else -1.0
    baseline = state.pressure_mids[0]
    started = (
        datetime.fromisoformat(state.pressure_started_at).astimezone(timezone.utc)
        - START
    ).total_seconds()
    transition = None
    for index in range(1, 21):
        transition = observe_v8_quote(
            state,
            _quote(started + index * 0.1, baseline + sign * favorable_step * index),
        )
        state = transition.state
    assert transition is not None
    return transition


@pytest.mark.parametrize(
    "family",
    [
        HIGH_BREAK_BUY,
        LOW_BREAK_SELL,
        HIGH_RESPECT_SELL,
        LOW_RESPECT_BUY,
        FAILED_HIGH_BREAK_SELL,
        FAILED_LOW_BREAK_BUY,
    ],
)
def test_all_six_mirrored_families_require_structural_test_then_pressure(family):
    transition = _complete_pressure(_start_pressure(family))

    assert transition.event == "PRESSURE_ACCEPTED"
    assert transition.state.phase == V8Phase.WAITING
    assert transition.state.change_count == 20
    assert transition.state.pressure_score == 1.0
    assert transition.state.placement_due_at is not None


def test_twenty_distinct_changes_must_complete_inside_three_seconds():
    state = _start_pressure(LOW_RESPECT_BUY)
    baseline = state.pressure_mids[0]
    for index in range(1, 20):
        state = observe_v8_quote(
            state,
            _quote(6 + index * 0.1, baseline + index * 0.01),
        ).state

    timed_out = observe_v8_quote(state, _quote(9.001, baseline + 0.20))

    assert timed_out.event == "PRESSURE_SAMPLE_TIMEOUT"
    assert timed_out.state.phase == V8Phase.REJECTED


def test_duplicate_and_unchanged_mid_quotes_do_not_inflate_sample_count():
    state = _start_pressure(LOW_RESPECT_BUY)
    duplicate = observe_v8_quote(state, _quote(6.01, state.pressure_mids[0]))
    same_mid_new_spread = observe_v8_quote(state, _quote(6.1, state.pressure_mids[0], 0.02))

    assert duplicate.event == "DUPLICATE_QUOTE_IGNORED"
    assert duplicate.state == state
    assert same_mid_new_spread.event == "UNCHANGED_MID_IGNORED"
    assert same_mid_new_spread.state.change_count == 0


def test_pressure_boundary_of_sixty_percent_is_accepted():
    state = _start_pressure(LOW_RESPECT_BUY)
    baseline = state.pressure_mids[0]
    current = baseline
    # Exactly 12 favorable and 8 adverse changes; favorable changes are larger
    # so displacement remains above both the spread and 0.10R boundaries.
    moves = [0.03] * 12 + [-0.005] * 8
    transition = None
    for index, move in enumerate(moves, start=1):
        current += move
        transition = observe_v8_quote(state, _quote(6 + index * 0.1, current))
        state = transition.state

    assert transition is not None
    assert transition.event == "PRESSURE_ACCEPTED"
    assert transition.state.pressure_score == pytest.approx(0.60)


def test_pressure_rejects_weak_displacement_adverse_and_spread_independently():
    policy = V8Config(minimum_stop_distance=0.10)

    weak = _start_pressure(LOW_RESPECT_BUY)
    current = weak.pressure_mids[0]
    for index in range(1, 21):
        current += 0.003 if index % 2 else -0.002
        weak_transition = observe_v8_quote(
            weak, _quote(6 + index * 0.1, current), config=policy
        )
        weak = weak_transition.state
    assert weak_transition.event in {
        "DIRECTIONAL_PRESSURE_BELOW_MINIMUM",
        "DIRECTIONAL_DISPLACEMENT_BELOW_MINIMUM",
    }

    adverse = _start_pressure(LOW_RESPECT_BUY)
    baseline = adverse.pressure_mids[0]
    mids = [baseline - 0.20] + [baseline - 0.20 + index * 0.025 for index in range(1, 20)]
    for index, mid in enumerate(mids, start=1):
        adverse_transition = observe_v8_quote(
            adverse, _quote(6 + index * 0.1, mid), config=policy
        )
        adverse = adverse_transition.state
    assert adverse_transition.event == "ADVERSE_MOVEMENT_ABOVE_MAXIMUM"

    wide = _start_pressure(LOW_RESPECT_BUY)
    baseline = wide.pressure_mids[0]
    for index in range(1, 21):
        wide_transition = observe_v8_quote(
            wide,
            _quote(6 + index * 0.1, baseline + index * 0.01, spread=0.05),
            config=policy,
        )
        wide = wide_transition.state
    assert wide_transition.event == "PRESSURE_SPREAD_ABOVE_MAXIMUM"


def test_stop_order_waits_five_seconds_snaps_outward_and_expires_in_twenty():
    state = _complete_pressure(_start_pressure(LOW_RESPECT_BUY)).state
    due = datetime.fromisoformat(state.placement_due_at)
    seconds = (due - START).total_seconds()
    before = evaluate_v8_stop_order(state, _quote(seconds - 0.001, state.pressure_mids[-1]))
    decision = evaluate_v8_stop_order(
        state,
        _quote(seconds, state.pressure_mids[-1]),
        config=V8Config(tick_size=0.05),
    )

    assert before.reason == "PLACEMENT_DELAY_PENDING"
    assert decision.accepted is True
    assert decision.order_kind == "BUY_STOP"
    assert decision.entry > state.pressure_max_ask
    assert decision.entry / 0.05 == pytest.approx(round(decision.entry / 0.05))
    assert datetime.fromisoformat(decision.expires_at) - due == timedelta(seconds=20)

    placed = mark_v8_placed(state, decision)
    recovered = V8State.from_dict(placed.as_dict())
    assert expire_v8_pending(recovered, decision.expires_at).phase == V8Phase.EXPIRED


def test_crossed_and_moved_away_stories_are_rejected_during_wait():
    waiting = _complete_pressure(_start_pressure(LOW_RESPECT_BUY)).state
    crossed_entry = round(waiting.pressure_max_ask + 0.01, 10)
    crossed = observe_v8_quote(
        waiting,
        QuoteObservation(
            time=_time(9),
            bid=crossed_entry - 0.04,
            ask=crossed_entry,
        ),
    )
    assert crossed.event == "BUY_STOP_ALREADY_CROSSED"

    moved_state = replace(
        waiting,
        last_quote_at=_time(8.5),
        last_bid=100.45,
        last_ask=100.49,
    )
    moved = observe_v8_quote(moved_state, _quote(9, 100.10))
    assert moved.event == "BUY_STORY_MOVED_AWAY"


def test_state_and_cooldown_persist_atomically_without_deadline_extension(tmp_path):
    state = _complete_pressure(_start_pressure(LOW_RESPECT_BUY)).state
    store = AtomicV8StateStore(tmp_path / "v8-state.json")
    cooldown = _time(1_000)
    store.save(
        {
            "state": state.as_dict(),
            "cooldown_until": cooldown,
            "consecutive_losses": 2,
        }
    )

    payload = store.load()
    recovered = V8State.from_dict(payload["state"])

    assert recovered == state
    assert recovered.placement_due_at == state.placement_due_at
    assert payload["cooldown_until"] == cooldown
    assert payload["consecutive_losses"] == 2
    assert not list(tmp_path.glob("*.tmp"))


def test_pre_causal_and_non_monotonic_quotes_are_idempotent():
    armed = start_v8_state(_arm(HIGH_RESPECT_SELL), _quote(0, 100.0))
    early = observe_v8_quote(armed, _quote(4.999, 100.0))
    observed = observe_v8_quote(armed, _quote(5, 100.0))
    repeated = observe_v8_quote(observed.state, _quote(5, 99.72))

    assert early.event == "PRE_CAUSAL_QUOTE_IGNORED"
    assert early.state == armed
    assert repeated.event == "NON_MONOTONIC_QUOTE_IGNORED"
    assert repeated.state == observed.state
