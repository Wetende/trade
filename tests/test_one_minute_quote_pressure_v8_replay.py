from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.agents.price_action.one_minute_entry_model import (
    HIGH_RESPECT_SELL,
    LOW_RESPECT_BUY,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PostCloseArm,
    QuoteObservation,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import (
    CANDIDATE_NAME,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_replay import (
    V8ReplayConfig,
    replay_v8_arms,
)


START = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)


def _time(seconds):
    return (START + timedelta(seconds=seconds)).isoformat()


def _quote(seconds, mid, spread=0.04):
    return QuoteObservation(
        time=_time(seconds),
        bid=round(mid - spread / 2, 10),
        ask=round(mid + spread / 2, 10),
    )


def _arm(direction="BUY", *, offset=0, suffix="1"):
    buy = direction == "BUY"
    return PostCloseArm(
        candidate=CANDIDATE_NAME,
        arm_id=f"arm-{direction}-{suffix}",
        family=LOW_RESPECT_BUY if buy else HIGH_RESPECT_SELL,
        direction=direction,
        level_side="low" if buy else "high",
        level=100.0,
        touch_count=2,
        tolerance=0.2,
        break_margin=0.05,
        zone_low=99.8,
        zone_high=100.2,
        confirmation_type="rejection",
        confirmation_time=_time(offset - 60),
        confirmation_closed_at=_time(offset),
        trigger_eligible_at=_time(offset + 5),
        expires_at=_time(offset + 60),
        invalidation=99.7 if buy else 100.3,
        confirmation_open=100.0,
        confirmation_high=100.25,
        confirmation_low=99.75,
        confirmation_close=100.0,
    )


def _entry_sequence(direction="BUY", *, offset=0):
    sign = 1 if direction == "BUY" else -1
    trigger = 100.28 if direction == "BUY" else 99.72
    quotes = [
        _quote(offset, 100.0),
        _quote(offset + 5, 100.0),
        _quote(offset + 6, trigger),
    ]
    for index in range(1, 21):
        quotes.append(_quote(offset + 6 + index * 0.1, trigger + sign * index * 0.01))
    final_mid = trigger + sign * 0.20
    quotes.append(_quote(offset + 13, final_mid))
    return quotes


@pytest.mark.parametrize("direction", ["BUY", "SELL"])
def test_replay_places_direction_safe_stop_fills_and_closes_at_target(direction):
    quotes = _entry_sequence(direction)
    if direction == "BUY":
        quotes.extend([_quote(13.1, 100.50), _quote(14, 101.75)])
    else:
        quotes.extend([_quote(13.1, 99.50), _quote(14, 98.25)])

    result = replay_v8_arms([_arm(direction)], quotes)

    assert result.broker_mutation_enabled is False
    assert result.counters.valid_triggers == 1
    assert result.counters.placements == 1
    assert result.counters.fills == 1
    assert len(result.rows) == 1
    assert result.rows[0].outcome == "WIN"
    assert result.rows[0].profit_r >= 1.4
    assert result.rows[0].profit_r < 1.6


def test_pending_order_expires_after_twenty_seconds_without_extension():
    quotes = _entry_sequence("BUY")
    quotes.extend([_quote(32.999, 100.48), _quote(33, 100.48)])

    result = replay_v8_arms([_arm("BUY")], quotes)

    assert result.rows[0].outcome == "EXPIRED"
    assert result.rows[0].reason == "PENDING_ORDER_EXPIRED"
    assert result.rows[0].closed_at == _time(33)


def test_second_arm_is_skipped_while_first_lifecycle_is_active():
    first = _arm("BUY", suffix="first")
    second = _arm("SELL", suffix="second")
    quotes = _entry_sequence("BUY")

    result = replay_v8_arms([first, second], quotes)

    skipped = [row for row in result.rows if row.arm_id == second.arm_id]
    assert len(skipped) == 1
    assert skipped[0].reason == "ONE_ACTIVE_LIFECYCLE_BLOCK"


def test_future_arm_cannot_be_seen_by_earlier_quotes():
    result = replay_v8_arms(
        [_arm("BUY", offset=100)],
        [_quote(0, 100.0), _quote(50, 100.2)],
    )

    assert result.counters.arms_detected == 1
    assert result.counters.valid_triggers == 0
    assert result.rows[0].reason == "NO_POST_CLOSE_QUOTES"


def test_replay_is_deterministic_and_duplicate_ticks_are_idempotent():
    quotes = _entry_sequence("BUY")
    quotes.insert(8, quotes[7])
    first = replay_v8_arms([_arm("BUY")], quotes)
    second = replay_v8_arms([_arm("BUY")], list(reversed(quotes)))

    assert first.as_dict() == second.as_dict()
    duplicate_events = [
        event for event in first.events if event.get("event") == "NON_MONOTONIC_QUOTE_IGNORED"
    ]
    assert duplicate_events


def test_replay_applies_frozen_cost_per_fill():
    quotes = _entry_sequence("BUY") + [_quote(13.1, 100.50), _quote(14, 101.75)]

    cheap = replay_v8_arms(
        [_arm("BUY")],
        quotes,
        config=V8ReplayConfig(cost_per_fill_r=0.05),
    )
    expensive = replay_v8_arms(
        [_arm("BUY")],
        quotes,
        config=V8ReplayConfig(cost_per_fill_r=0.10),
    )

    assert cheap.rows[0].profit_r - expensive.rows[0].profit_r == pytest.approx(0.05)


def test_ordered_stream_matches_buffered_replay_without_materializing_ticks():
    quotes = _entry_sequence("BUY") + [_quote(13.1, 100.50), _quote(14, 101.75)]

    buffered = replay_v8_arms([_arm("BUY")], quotes)
    streamed = replay_v8_arms(
        [_arm("BUY")],
        (quote for quote in quotes),
        ordered_ticks=True,
    )

    assert streamed.as_dict() == buffered.as_dict()


def test_ordered_stream_rejects_non_monotonic_source_quotes():
    with pytest.raises(ValueError, match="not monotonic"):
        replay_v8_arms(
            [_arm("BUY")],
            [_quote(1, 100.0), _quote(0, 100.0)],
            ordered_ticks=True,
        )
