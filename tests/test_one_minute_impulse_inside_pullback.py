from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_impulse_inside_pullback import (
    CANDIDATE_NAME,
    IMPULSE_INSIDE_PULLBACK_BUY,
    IMPULSE_INSIDE_PULLBACK_SELL,
    detect_impulse_inside_pullback_arms,
)


START = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


def _candle(index, open_, high, low, close):
    return Candle(
        timestamp=(START + timedelta(minutes=index)).isoformat(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


def _baseline():
    return [
        _candle(index, 100.0, 101.0, 99.0, 100.1 if index % 2 else 99.9)
        for index in range(36)
    ]


def _buy_setup():
    return _baseline() + [
        _candle(36, 100.0, 103.0, 99.8, 102.8),
        _candle(37, 102.7, 102.9, 101.5, 101.8),
    ]


def _sell_setup():
    return _baseline() + [
        _candle(36, 100.0, 100.2, 97.0, 97.2),
        _candle(37, 97.3, 98.5, 97.1, 98.2),
    ]


def test_detects_bullish_impulse_inside_pullback_buy():
    arm = detect_impulse_inside_pullback_arms(_buy_setup())[0]

    assert arm.candidate == CANDIDATE_NAME
    assert arm.family == IMPULSE_INSIDE_PULLBACK_BUY
    assert arm.direction == "BUY"
    assert arm.level == 102.9
    assert arm.invalidation == 101.5
    assert arm.zone_low == 101.5
    assert arm.zone_high == 102.9
    assert arm.confirmation_type == "inside_pullback"
    assert arm.confirmation_closed_at == (
        START + timedelta(minutes=38)
    ).isoformat()


def test_detects_exact_bearish_impulse_inside_pullback_sell_mirror():
    arm = detect_impulse_inside_pullback_arms(_sell_setup())[0]

    assert arm.family == IMPULSE_INSIDE_PULLBACK_SELL
    assert arm.direction == "SELL"
    assert arm.level == 97.1
    assert arm.invalidation == 98.5


def test_requires_baseline_impulse_and_closed_pullback():
    assert detect_impulse_inside_pullback_arms(_buy_setup()[:-1]) == ()


def test_rejects_weak_impulse():
    candles = _baseline() + [
        _candle(36, 100.0, 102.0, 99.8, 101.8),
        _candle(37, 101.7, 101.9, 101.0, 101.2),
    ]

    assert detect_impulse_inside_pullback_arms(candles) == ()


def test_rejects_pullback_outside_impulse():
    candles = _buy_setup()
    candles[-1] = _candle(37, 102.7, 103.1, 101.5, 101.8)

    assert detect_impulse_inside_pullback_arms(candles) == ()


def test_rejects_pullback_that_loses_impulse_midpoint():
    candles = _buy_setup()
    candles[-1] = _candle(37, 102.7, 102.9, 101.0, 101.2)

    assert detect_impulse_inside_pullback_arms(candles) == ()


def test_rejects_same_color_or_wide_pullback():
    same_color = _buy_setup()
    same_color[-1] = _candle(37, 101.8, 102.9, 101.5, 102.7)
    wide = _buy_setup()
    wide[-1] = _candle(37, 102.8, 102.9, 101.3, 101.6)

    assert detect_impulse_inside_pullback_arms(same_color) == ()
    assert detect_impulse_inside_pullback_arms(wide) == ()


def test_is_deterministic_and_does_not_consume_a_future_candle():
    candles = _buy_setup()
    first = detect_impulse_inside_pullback_arms(candles)
    second = detect_impulse_inside_pullback_arms(candles)
    candles.append(_candle(38, 101.8, 102.0, 101.5, 101.9))

    assert first == second
    assert first[0].confirmation_time == (
        START + timedelta(minutes=37)
    ).isoformat()
    assert detect_impulse_inside_pullback_arms(candles) == ()
