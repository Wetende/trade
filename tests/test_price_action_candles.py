import pytest

from tradingagents.agents.price_action.candles import (
    atr,
    lower_wick,
    parse_ohlcv_text,
    resample_candles,
    upper_wick,
    wick_ratio,
)


def test_parse_ohlcv_text_skips_comments_and_normalizes_columns():
    raw = "\n".join(
        [
            "# OHLCV data for XAUUSD",
            "Datetime,Open,High,Low,Close,Volume",
            "2026-05-18 08:00:00,2350,2355,2348,2354,1000",
        ]
    )

    candles = parse_ohlcv_text(raw)

    assert candles[0].timestamp == "2026-05-18 08:00:00"
    assert candles[0].open == 2350
    assert candles[0].high == 2355
    assert candles[0].low == 2348
    assert candles[0].close == 2354


def test_parse_ohlcv_text_defaults_empty_volume_to_zero():
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:00:00,2350,2355,2348,2354,"
    )

    assert candles[0].volume == 0.0


def test_parse_ohlcv_text_defaults_missing_volume_column_to_zero():
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close\n"
        "2026-05-18 08:00:00,2350,2355,2348,2354"
    )

    assert candles[0].volume == 0.0


def test_wick_helpers_measure_top_and_bottom_wicks():
    candle = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:00:00,2350,2356,2348,2354,1000"
    )[0]

    assert upper_wick(candle) == 2
    assert lower_wick(candle) == 2
    assert wick_ratio(candle, "upper") == pytest.approx(0.25)
    assert wick_ratio(candle, "lower") == pytest.approx(0.25)


def test_atr_uses_recent_true_ranges():
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:00:00,100,110,95,105,1000\n"
        "2026-05-18 09:00:00,105,112,101,110,1000\n"
        "2026-05-18 10:00:00,110,118,108,117,1000"
    )

    assert atr(candles, period=2) == pytest.approx(10.5)


def test_resample_1h_candles_to_4h():
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 00:00:00,100,102,99,101,10\n"
        "2026-05-18 01:00:00,101,103,100,102,20\n"
        "2026-05-18 02:00:00,102,105,101,104,30\n"
        "2026-05-18 03:00:00,104,106,103,105,40"
    )

    result = resample_candles(candles, "4h")

    assert len(result) == 1
    assert result[0].open == 100
    assert result[0].high == 106
    assert result[0].low == 99
    assert result[0].close == 105
    assert result[0].volume == 100


@pytest.mark.parametrize("timeframe", ["0m", "0h", "0d", "-1h"])
def test_resample_rejects_non_positive_timeframes(timeframe):
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 00:00:00,100,102,99,101,10"
    )

    with pytest.raises(ValueError, match="positive"):
        resample_candles(candles, timeframe)
