from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_compression_expansion import (
    CANDIDATE_NAME,
    detect_compression_expansion_arms,
)
from tradingagents.agents.price_action.one_minute_entry_model import (
    HIGH_BREAK_BUY,
    LOW_BREAK_SELL,
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


def _base_and_compression(*, trending=False, wide=False):
    candles = [
        _candle(index, 100.0, 101.0, 99.0, 100.1 if index % 2 else 99.9)
        for index in range(36)
    ]
    for offset in range(12):
        index = 36 + offset
        if wide:
            candles.append(_candle(index, 100.0, 100.9, 99.1, 100.1))
        elif trending:
            open_ = 98.0 + offset * 0.2
            candles.append(_candle(index, open_, open_ + 0.5, open_ - 0.3, open_ + 0.2))
        else:
            candles.append(
                _candle(index, 100.0, 100.4, 99.6, 100.1 if offset % 2 else 99.9)
            )
    return candles


def test_detects_symmetric_buy_compression_expansion():
    candles = _base_and_compression()
    candles.append(_candle(48, 100.0, 102.0, 99.8, 101.8))

    arms = detect_compression_expansion_arms(candles)

    assert len(arms) == 1
    arm = arms[0]
    assert arm.candidate == CANDIDATE_NAME
    assert arm.family == HIGH_BREAK_BUY
    assert arm.direction == "BUY"
    assert arm.level == 100.4
    assert arm.invalidation == 100.0
    assert arm.confirmation_closed_at == (START + timedelta(minutes=49)).isoformat()


def test_detects_symmetric_sell_compression_expansion():
    candles = _base_and_compression()
    candles.append(_candle(48, 100.0, 100.2, 98.0, 98.2))

    arms = detect_compression_expansion_arms(candles)

    assert len(arms) == 1
    arm = arms[0]
    assert arm.family == LOW_BREAK_SELL
    assert arm.direction == "SELL"
    assert arm.level == 99.6
    assert arm.invalidation == 100.0


def test_rejects_non_compressed_box():
    candles = _base_and_compression(wide=True)
    candles.append(_candle(48, 100.0, 102.0, 99.8, 101.8))

    assert detect_compression_expansion_arms(candles) == ()


def test_rejects_directional_drift_mislabeled_as_compression():
    candles = _base_and_compression(trending=True)
    candles.append(_candle(48, 100.2, 102.2, 100.0, 102.0))

    assert detect_compression_expansion_arms(candles) == ()


def test_rejects_weak_breakout_close():
    candles = _base_and_compression()
    candles.append(_candle(48, 100.0, 101.2, 99.8, 100.9))

    assert detect_compression_expansion_arms(candles) == ()


def test_requires_only_past_and_latest_closed_candles():
    candles = _base_and_compression()
    candles.append(_candle(48, 100.0, 102.0, 99.8, 101.8))
    first = detect_compression_expansion_arms(candles)
    candles.append(_candle(49, 101.8, 103.0, 101.0, 102.8))

    assert first[0].confirmation_time == (START + timedelta(minutes=48)).isoformat()
    assert detect_compression_expansion_arms(candles) == ()
