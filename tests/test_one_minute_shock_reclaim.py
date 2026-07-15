from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
)
from tradingagents.agents.price_action.one_minute_shock_reclaim import (
    CANDIDATE_NAME,
    detect_shock_reclaim_arms,
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


def _high_reclaim():
    return _baseline() + [
        _candle(36, 100.8, 104.0, 100.5, 103.8),
        _candle(37, 103.6, 103.8, 99.8, 100.5),
    ]


def _low_reclaim():
    return _baseline() + [
        _candle(36, 99.2, 99.5, 96.0, 96.2),
        _candle(37, 96.4, 100.2, 96.2, 99.5),
    ]


def test_detects_high_shock_reclaim_sell():
    arm = detect_shock_reclaim_arms(_high_reclaim())[0]

    assert arm.candidate == CANDIDATE_NAME
    assert arm.family == FAILED_HIGH_BREAK_SELL
    assert arm.direction == "SELL"
    assert arm.level == 101.0
    assert arm.invalidation == 101.2
    assert arm.touch_count == 0
    assert arm.confirmation_type == "shock_reclaim"
    assert arm.confirmation_closed_at == (
        START + timedelta(minutes=38)
    ).isoformat()


def test_detects_exact_low_shock_reclaim_buy_mirror():
    arm = detect_shock_reclaim_arms(_low_reclaim())[0]

    assert arm.family == FAILED_LOW_BREAK_BUY
    assert arm.direction == "BUY"
    assert arm.level == 99.0
    assert arm.invalidation == 98.8


def test_requires_baseline_shock_and_fully_closed_reclaim():
    assert detect_shock_reclaim_arms(_high_reclaim()[:-1]) == ()


def test_rejects_weak_shock_body():
    candles = _baseline() + [
        _candle(36, 101.6, 103.2, 100.0, 103.0),
        _candle(37, 102.8, 103.0, 99.8, 100.5),
    ]

    assert detect_shock_reclaim_arms(candles) == ()


def test_rejects_weak_reclaim_close():
    candles = _baseline() + [
        _candle(36, 100.8, 104.0, 100.5, 103.8),
        _candle(37, 103.6, 103.8, 99.8, 101.0),
    ]

    assert detect_shock_reclaim_arms(candles) == ()


def test_rejects_shock_without_true_reference_extension():
    candles = _baseline() + [
        _candle(36, 98.0, 101.3, 97.8, 101.1),
        _candle(37, 101.8, 102.0, 99.5, 100.0),
    ]

    assert detect_shock_reclaim_arms(candles) == ()


def test_is_deterministic_and_does_not_consume_a_future_candle():
    candles = _high_reclaim()
    first = detect_shock_reclaim_arms(candles)
    second = detect_shock_reclaim_arms(candles)
    candles.append(_candle(38, 100.5, 101.0, 100.0, 100.6))

    assert first == second
    assert first[0].confirmation_time == (
        START + timedelta(minutes=37)
    ).isoformat()
    assert detect_shock_reclaim_arms(candles) == ()
