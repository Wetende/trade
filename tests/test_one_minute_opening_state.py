from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_state import (
    OpeningTemplate,
    detect_opening_opportunities,
)


START = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _candle(index, open_, high, low, close):
    return Candle(
        timestamp=(START + timedelta(minutes=index)).isoformat(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


def _seed_high_level():
    return [
        _candle(0, 100.0, 101.0, 99.5, 100.5),
        _candle(1, 100.4, 101.02, 100.0, 100.2),
        _candle(2, 100.1, 100.6, 99.9, 100.1),
    ]


def test_rejection_template_uses_latest_closed_candle_only():
    candles = _seed_high_level() + [
        _candle(3, 100.4, 101.03, 100.0, 100.05),
        _candle(4, 100.0, 102.0, 99.0, 101.9),
    ]

    opportunities = detect_opening_opportunities(candles[:-1], lookback=10)

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.template == OpeningTemplate.REJECTION
    assert opportunity.direction == "SELL"
    assert opportunity.signal_time == candles[3].timestamp
    assert opportunity.level_side == "high"
    assert opportunity.used_candle_indexes == (3,)


def test_break_hold_requires_second_closed_candle_beyond_level():
    candles = _seed_high_level() + [
        _candle(3, 100.5, 101.8, 100.4, 101.35),
        _candle(4, 101.3, 101.7, 101.1, 101.45),
    ]

    opportunities = detect_opening_opportunities(candles, lookback=10)

    assert len(opportunities) == 1
    assert opportunities[0].template == OpeningTemplate.BREAK_HOLD
    assert opportunities[0].direction == "BUY"
    assert opportunities[0].signal_time == candles[4].timestamp
    assert opportunities[0].used_candle_indexes == (3, 4)


def test_failed_break_completes_only_after_close_back_inside():
    candles = _seed_high_level() + [
        _candle(3, 100.5, 101.8, 100.4, 101.35),
        _candle(4, 101.3, 101.4, 100.2, 100.45),
    ]

    opportunities = detect_opening_opportunities(candles, lookback=10)

    assert len(opportunities) == 1
    assert opportunities[0].template == OpeningTemplate.FAILED_BREAK
    assert opportunities[0].direction == "SELL"
    assert opportunities[0].signal_time == candles[4].timestamp
    assert opportunities[0].used_candle_indexes == (3, 4)


def test_break_retest_hold_uses_three_closed_candle_lifecycle():
    candles = _seed_high_level() + [
        _candle(3, 100.5, 101.8, 100.4, 101.35),
        _candle(4, 101.3, 101.5, 100.98, 101.25),
        _candle(5, 101.2, 101.9, 101.1, 101.55),
    ]

    opportunities = detect_opening_opportunities(candles, lookback=10)

    assert len(opportunities) == 1
    assert opportunities[0].template == OpeningTemplate.BREAK_RETEST_HOLD
    assert opportunities[0].direction == "BUY"
    assert opportunities[0].signal_time == candles[5].timestamp
    assert opportunities[0].used_candle_indexes == (3, 4, 5)


def test_latest_signal_fast_path_is_exact_for_all_template_lengths():
    scenarios = [
        _seed_high_level() + [_candle(3, 100.4, 101.03, 100.0, 100.05)],
        _seed_high_level()
        + [
            _candle(3, 100.5, 101.8, 100.4, 101.35),
            _candle(4, 101.3, 101.7, 101.1, 101.45),
        ],
        _seed_high_level()
        + [
            _candle(3, 100.5, 101.8, 100.4, 101.35),
            _candle(4, 101.3, 101.4, 100.2, 100.45),
        ],
        _seed_high_level()
        + [
            _candle(3, 100.5, 101.8, 100.4, 101.35),
            _candle(4, 101.3, 101.5, 100.98, 101.25),
            _candle(5, 101.2, 101.9, 101.1, 101.55),
        ],
    ]
    for candles in scenarios:
        latest_time = candles[-1].timestamp
        expected = tuple(
            opportunity
            for opportunity in detect_opening_opportunities(candles, lookback=10)
            if opportunity.signal_time == latest_time
        )
        optimized = detect_opening_opportunities(
            candles,
            lookback=10,
            latest_signal_only=True,
        )
        assert optimized == expected
