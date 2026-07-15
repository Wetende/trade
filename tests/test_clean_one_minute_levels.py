from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.clean_one_minute_levels import (
    detect_clean_equal_levels,
)
from tradingagents.agents.price_action.models import Candle


START = datetime(2026, 6, 15, tzinfo=timezone.utc)


def _candle(index, open_, high, low, close):
    return Candle(
        timestamp=(START + timedelta(minutes=index)).isoformat(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


def test_adjacent_clustered_highs_are_one_interaction_not_two_touches():
    candles = [
        _candle(0, 100.0, 101.0, 99.8, 100.8),
        _candle(1, 100.8, 101.02, 100.6, 100.9),
        _candle(2, 100.9, 101.01, 100.7, 100.8),
        _candle(3, 100.8, 100.9, 100.0, 100.1),
    ]

    assert detect_clean_equal_levels(candles, 0.2, side="high") == []


def test_clean_high_requires_separation_and_visible_reaction_after_each_touch():
    candles = [
        _candle(0, 100.0, 101.0, 99.8, 100.8),
        _candle(1, 100.8, 100.9, 100.2, 100.3),
        _candle(2, 100.3, 100.7, 100.0, 100.2),
        _candle(3, 100.2, 101.02, 100.1, 100.8),
        _candle(4, 100.8, 100.9, 100.3, 100.4),
        _candle(5, 100.4, 100.6, 100.0, 100.1),
    ]

    levels = detect_clean_equal_levels(candles, 0.2, side="high")

    assert len(levels) == 1
    assert levels[0].touch_count == 2
    assert levels[0].first_touch_index == 0
    assert levels[0].last_touch_index == 3


def test_time_separation_without_visible_reaction_is_not_clean():
    candles = [
        _candle(0, 100.0, 101.0, 99.8, 100.8),
        _candle(1, 100.8, 100.95, 100.6, 100.85),
        _candle(2, 100.85, 100.96, 100.7, 100.9),
        _candle(3, 100.9, 101.02, 100.7, 100.8),
        _candle(4, 100.8, 100.9, 100.6, 100.7),
    ]

    assert detect_clean_equal_levels(candles, 0.2, side="high") == []


def test_interim_excursion_can_separate_touches_with_short_bar_gap():
    candles = [
        _candle(0, 100.0, 101.0, 99.8, 100.8),
        _candle(1, 100.8, 100.9, 100.0, 100.1),
        _candle(2, 100.1, 101.01, 100.0, 100.8),
        _candle(3, 100.8, 100.9, 100.2, 100.3),
    ]

    levels = detect_clean_equal_levels(candles, 0.2, side="high")

    assert len(levels) == 1
    assert levels[0].touch_count == 2


def test_clean_low_detection_is_symmetric():
    candles = [
        _candle(0, 100.0, 100.2, 99.0, 99.2),
        _candle(1, 99.2, 99.8, 99.1, 99.7),
        _candle(2, 99.7, 100.0, 99.3, 99.8),
        _candle(3, 99.8, 99.9, 98.98, 99.2),
        _candle(4, 99.2, 99.8, 99.1, 99.7),
    ]

    levels = detect_clean_equal_levels(candles, 0.2, side="low")

    assert len(levels) == 1
    assert levels[0].touch_count == 2


def test_last_touch_without_a_later_reaction_is_not_yet_a_level():
    candles = [
        _candle(0, 100.0, 101.0, 99.8, 100.8),
        _candle(1, 100.8, 100.9, 100.2, 100.3),
        _candle(2, 100.3, 100.7, 100.0, 100.2),
        _candle(3, 100.2, 101.02, 100.1, 100.8),
    ]

    assert detect_clean_equal_levels(candles, 0.2, side="high") == []
