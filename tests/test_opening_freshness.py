from copy import deepcopy

import pytest

from tradingagents.brokers.opening_freshness import (
    same_opening_zone,
    stale_consumed_opening,
)


BASE = {
    "model_name": "One Minute Scalper",
    "direction": "BUY",
    "trigger": "FAILED_LOW_BREAK_BUY",
    "reaction_type": "fakeout",
    "confirmation_type": "rejection",
    "level": 4035.4433,
    "level_side": "low",
    "level_type": "three_touch",
    "tolerance": 0.238,
    "touch_count": 3,
    "first_touch_timestamp": "2026-07-01T23:10:00+00:00",
    "last_touch_timestamp": "2026-07-01T23:40:00+00:00",
    "confirmation_timestamp": "2026-07-01T23:41:00+00:00",
}


def test_identical_consumed_opening_is_stale():
    consumed = {"opening_context": deepcopy(BASE), "consumed_at_utc": "later"}

    assert stale_consumed_opening(BASE, [consumed]) == consumed


def test_same_zone_uses_larger_candidate_tolerance():
    previous = {**BASE, "level": 4035.44, "tolerance": 0.20}
    current = {**BASE, "level": 4035.67, "tolerance": 0.24}

    assert same_opening_zone(current, previous) is True


def test_level_outside_both_tolerances_is_a_new_zone():
    previous = {**BASE, "level": 4035.44, "tolerance": 0.20}
    current = {**BASE, "level": 4035.69, "tolerance": 0.24}

    assert same_opening_zone(current, previous) is False


@pytest.mark.parametrize(
    "change",
    [
        {"confirmation_timestamp": "2026-07-01T23:42:00+00:00"},
        {"last_touch_timestamp": "2026-07-01T23:41:00+00:00"},
        {"touch_count": 4},
        {"reaction_type": "respect"},
        {"trigger": "LOW_RESPECT_BUY"},
        {"direction": "SELL"},
        {"level_side": "high"},
        {"level": 4036.00},
    ],
)
def test_structural_change_rearms_consumed_opening(change):
    current = {**BASE, **change}

    assert stale_consumed_opening(
        current,
        [{"opening_context": BASE}],
    ) is None


def test_older_confirmation_and_touch_remain_stale():
    current = {
        **BASE,
        "confirmation_timestamp": "2026-07-01T23:40:00+00:00",
        "last_touch_timestamp": "2026-07-01T23:39:00+00:00",
    }

    assert stale_consumed_opening(
        current,
        [{"opening_context": BASE}],
    ) is not None


@pytest.mark.parametrize(
    "context",
    [
        {},
        None,
        {**BASE, "level": None},
        {**BASE, "tolerance": float("nan")},
        {**BASE, "direction": ""},
    ],
)
def test_invalid_or_missing_context_is_not_classified_as_stale(context):
    assert stale_consumed_opening(
        context,
        [{"opening_context": BASE}],
    ) is None


def test_newest_matching_record_is_returned_deterministically():
    older = {
        "opening_context": deepcopy(BASE),
        "consumed_at_utc": "2026-07-01T23:42:00+00:00",
    }
    newer = {
        "opening_context": deepcopy(BASE),
        "consumed_at_utc": "2026-07-01T23:43:00+00:00",
    }

    assert stale_consumed_opening(BASE, [older, newer]) == newer
