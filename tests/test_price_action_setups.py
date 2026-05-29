from tradingagents.agents.price_action.candles import parse_ohlcv_text
from tradingagents.agents.price_action.models import Zone
from tradingagents.agents.price_action.setups import (
    detect_break_and_retest,
    detect_breakouts,
    detect_sr_bounce,
    is_strong_directional_close,
)


def _resistance_zone():
    return Zone(
        type="resistance",
        timeframe="30m",
        low=100,
        high=102,
        midpoint=101,
        touches=2,
        score=9,
        source="test",
    )


def test_strong_directional_close_accepts_bullish_step_candle():
    candle = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:15:00,102,108,101,107,1000"
    )[0]

    assert is_strong_directional_close(candle, "BUY") is True


def test_breakout_requires_close_outside_zone():
    candle = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:15:00,101,103,100,102.5,1000"
    )[0]

    result = detect_breakouts([candle], [_resistance_zone()])

    assert result[0].direction == "BUY"
    assert result[0].name == "Breakout"


def test_retest_requires_half_zone_coverage_and_close_in_direction():
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:15:00,103,104,101,103,1000"
    )

    result = detect_break_and_retest(candles, [_resistance_zone()], direction="BUY")

    assert result[0].retest_depth >= 0.5
    assert result[0].direction == "BUY"


def test_retest_rejects_full_close_back_inside_zone():
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:15:00,103,104,101,101.5,1000"
    )

    assert detect_break_and_retest(candles, [_resistance_zone()], direction="BUY") == []


def test_support_bounce_requires_wick_for_stop_loss():
    support = Zone(
        type="support",
        timeframe="1h",
        low=95,
        high=96,
        midpoint=95.5,
        touches=2,
        score=9,
        source="test",
    )
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:15:00,96,100,94.5,99,1000"
    )

    result = detect_sr_bounce(candles, [support])

    assert result[0].direction == "BUY"
    assert result[0].stop_loss < 94.5
