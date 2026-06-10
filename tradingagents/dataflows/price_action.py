"""Top-down price-action data fetching helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from tradingagents.agents.price_action.candles import parse_ohlcv_text, resample_candles
from tradingagents.agents.price_action.models import Candle
from tradingagents.dataflows.data_health import build_data_status
from tradingagents.dataflows.interface import route_to_vendor


TIMEFRAME_FETCHES = {
    "1d": ("1y", "1d"),
    "1h": ("60d", "1h"),
    "30m": ("10d", "30m"),
    "15m": ("10d", "15m"),
}


@dataclass(frozen=True)
class PriceActionSnapshot:
    candles: dict[str, list[Candle]]
    data_status: dict[str, Any]
    market_metadata: dict[str, Any] = field(default_factory=dict)


def _fetch_candles(symbol: str, period: str, interval: str) -> list[Candle]:
    raw_data = route_to_vendor("get_intraday_price_data", symbol, period, interval)
    return parse_ohlcv_text(raw_data)


def fetch_price_action_timeframes(symbol: str) -> dict[str, list[Candle]]:
    """Fetch normalized top-down price-action timeframes for analysis.

    The 4h view is derived from the fetched 1h candles to avoid introducing a
    separate broker/vendor execution path.
    """
    candles_by_timeframe = {
        timeframe: _fetch_candles(symbol, period, interval)
        for timeframe, (period, interval) in TIMEFRAME_FETCHES.items()
    }
    candles_by_timeframe["4h"] = resample_candles(candles_by_timeframe["1h"], "4h")

    return {
        "1d": candles_by_timeframe["1d"],
        "4h": candles_by_timeframe["4h"],
        "1h": candles_by_timeframe["1h"],
        "30m": candles_by_timeframe["30m"],
        "15m": candles_by_timeframe["15m"],
    }


def fetch_price_action_snapshot(
    symbol: str,
    *,
    as_of: str,
    market_timezone: str = "America/New_York",
) -> PriceActionSnapshot:
    candles = fetch_price_action_timeframes(symbol)
    return PriceActionSnapshot(
        candles=candles,
        data_status=build_data_status(candles, as_of, market_timezone),
    )
