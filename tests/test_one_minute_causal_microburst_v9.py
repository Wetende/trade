from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_causal_microburst_v9 import (
    CANDIDATE_NAME,
    detect_causal_microburst_arms,
)
from tradingagents.agents.price_action.one_minute_entry_model import (
    HIGH_BREAK_BUY,
    LOW_BREAK_SELL,
)


START = datetime(2026, 7, 18, 9, 0, tzinfo=timezone.utc)


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
        _candle(index, 100.0, 100.5, 99.5, 100.05 if index % 2 else 99.95)
        for index in range(30)
    ]


def _buy_setup():
    return _baseline() + [
        _candle(30, 100.0, 100.5, 99.9, 100.35),
        _candle(31, 100.3, 100.75, 100.2, 100.65),
        _candle(32, 100.6, 101.45, 100.55, 101.35),
    ]


def _sell_setup():
    return _baseline() + [
        _candle(30, 100.0, 100.1, 99.5, 99.65),
        _candle(31, 99.7, 99.8, 99.25, 99.35),
        _candle(32, 99.4, 99.45, 98.55, 98.65),
    ]


def test_detects_causal_buy_only_after_latest_candle_closes():
    arm = detect_causal_microburst_arms(_buy_setup())[0]

    assert arm.candidate == CANDIDATE_NAME
    assert arm.family == HIGH_BREAK_BUY
    assert arm.direction == "BUY"
    assert arm.confirmation_type == "causal_microburst"
    assert arm.confirmation_closed_at == (
        START + timedelta(minutes=33)
    ).isoformat()
    assert detect_causal_microburst_arms(_buy_setup()[:-1]) == ()


def test_detects_exact_bearish_mirror():
    arm = detect_causal_microburst_arms(_sell_setup())[0]

    assert arm.family == LOW_BREAK_SELL
    assert arm.direction == "SELL"
    assert arm.invalidation == 99.025


def test_rejects_non_staircase_and_exhausted_range():
    non_staircase = _buy_setup()
    non_staircase[-2] = _candle(31, 100.3, 100.75, 100.2, 100.2)
    exhausted = _buy_setup()
    exhausted[-1] = _candle(32, 100.6, 102.4, 100.55, 102.3)

    assert detect_causal_microburst_arms(non_staircase) == ()
    assert detect_causal_microburst_arms(exhausted) == ()


def test_rejects_weak_body_and_non_breaking_close():
    weak = _buy_setup()
    weak[-1] = _candle(32, 100.9, 101.45, 100.55, 101.1)
    no_break = _buy_setup()
    no_break[-1] = _candle(32, 100.6, 100.95, 100.05, 100.85)

    assert detect_causal_microburst_arms(weak) == ()
    assert detect_causal_microburst_arms(no_break) == ()


def test_detector_is_deterministic_and_ignores_future_data():
    candles = _buy_setup()
    first = detect_causal_microburst_arms(candles)
    second = detect_causal_microburst_arms(candles)
    candles.append(_candle(33, 101.3, 101.4, 100.8, 100.9))

    assert first == second
    assert detect_causal_microburst_arms(candles) == ()
