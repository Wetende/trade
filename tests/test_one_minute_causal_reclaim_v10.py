from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_causal_reclaim_v10 import (
    CANDIDATE_NAME,
    detect_causal_reclaim_arms,
)
from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
)


def _candle(index, open_, high, low, close):
    timestamp = datetime(2026, 7, 22, tzinfo=timezone.utc) + timedelta(minutes=index)
    return Candle(
        timestamp=timestamp.isoformat(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1.0,
    )


def _baseline():
    return [
        _candle(index, 100.0, 100.5, 99.5, 100.0)
        for index in range(30)
    ]


def test_v10_arms_failed_high_reclaim_after_close():
    candles = _baseline() + [_candle(30, 100.45, 100.70, 99.85, 99.95)]
    arms = detect_causal_reclaim_arms(candles)
    assert len(arms) == 1
    arm = arms[0]
    assert arm.candidate == CANDIDATE_NAME
    assert arm.family == FAILED_HIGH_BREAK_SELL
    assert arm.direction == "SELL"
    assert arm.confirmation_closed_at == "2026-07-22T00:31:00+00:00"
    assert arm.trigger_eligible_at == "2026-07-22T00:31:01+00:00"


def test_v10_arms_mirrored_failed_low_reclaim():
    candles = _baseline() + [_candle(30, 99.55, 100.15, 99.30, 100.05)]
    arms = detect_causal_reclaim_arms(candles)
    assert len(arms) == 1
    assert arms[0].family == FAILED_LOW_BREAK_BUY
    assert arms[0].direction == "BUY"


def test_v10_rejects_unclosed_or_non_reclaim_story():
    baseline = _baseline()
    assert detect_causal_reclaim_arms(baseline[:30]) == ()
    continuation = baseline + [_candle(30, 100.1, 100.7, 99.9, 100.6)]
    assert detect_causal_reclaim_arms(continuation) == ()


def test_v10_uses_only_the_latest_sixty_closed_candles():
    irrelevant = [
        _candle(index - 80, 1000.0, 1200.0, 800.0, 1000.0)
        for index in range(49)
    ]
    candles = irrelevant + _baseline() + [_candle(30, 100.45, 100.70, 99.85, 99.95)]
    assert len(detect_causal_reclaim_arms(candles)) == 1
