from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from cli.utils import (
    last_closed_candle,
    normalize_as_of_timestamp,
    timeframe_to_minutes,
    validate_ticker_symbol,
)
from tradingagents.default_config import DEFAULT_CONFIG


@pytest.mark.unit
def test_price_action_timeframe_defaults():
    assert DEFAULT_CONFIG["timeframe"] == "15m"
    assert DEFAULT_CONFIG["confirmation_timeframe"] == "30m"
    assert DEFAULT_CONFIG["market_timezone"] == "America/New_York"


@pytest.mark.unit
def test_timeframe_to_minutes():
    assert timeframe_to_minutes("15m") == 15
    assert timeframe_to_minutes("30m") == 30


@pytest.mark.unit
def test_last_closed_candle_uses_market_timezone():
    now = datetime(2026, 5, 17, 10, 22, tzinfo=ZoneInfo("America/New_York"))
    assert last_closed_candle("15m", "America/New_York", now=now) == "2026-05-17 10:00"


@pytest.mark.unit
def test_last_closed_candle_at_exact_boundary_returns_previous_bucket():
    now = datetime(2026, 5, 17, 10, 15, tzinfo=ZoneInfo("America/New_York"))
    assert last_closed_candle("15m", "America/New_York", now=now) == "2026-05-17 10:00"


@pytest.mark.unit
def test_normalize_as_of_timestamp_accepts_space_or_t_separator():
    assert normalize_as_of_timestamp("2026-05-17 10:15", "America/New_York") == "2026-05-17 10:15"
    assert normalize_as_of_timestamp("2026-05-17T10:15", "America/New_York") == "2026-05-17 10:15"


@pytest.mark.unit
def test_normalize_as_of_timestamp_rejects_date_only():
    with pytest.raises(ValueError):
        normalize_as_of_timestamp("2026-05-17", "America/New_York")


@pytest.mark.unit
def test_validate_ticker_symbol_accepts_common_symbols():
    for ticker in ("SPY", "qqq", "ES=F", "BTC-USD", "0700.HK", "^GSPC"):
        assert validate_ticker_symbol(ticker) is True


@pytest.mark.unit
def test_validate_ticker_symbol_rejects_invalid_symbols():
    for ticker in ("A/B", "AAP L", "\tAAPL", "AAPL\n", "", ".", ".."):
        assert validate_ticker_symbol(ticker) is not True
