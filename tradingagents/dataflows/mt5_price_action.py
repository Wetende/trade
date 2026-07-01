"""MT5-backed price-action data fetching helpers."""

from __future__ import annotations

from typing import Any

from tradingagents.agents.price_action.candles import resample_candles
from tradingagents.agents.price_action.models import Candle
from tradingagents.dataflows.data_health import build_data_status
from tradingagents.dataflows.price_action import PriceActionSnapshot


MT5_TIMEFRAME_COUNTS = {
    "1d": 260,
    "1h": 1200,
    "30m": 500,
    "15m": 1000,
    "3m": 1200,
    "1m": 1500,
}


def mt5_health_reference(
    market_metadata: dict[str, Any],
    fallback_as_of: str,
) -> tuple[str, str]:
    tick = market_metadata.get("tick") or {}
    tick_time = tick.get("time_utc")
    if tick_time:
        return str(tick_time), "mt5_tick"
    return fallback_as_of, "runner_clock"


def _to_candle(row: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=str(row["timestamp"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0)),
    )


def fetch_mt5_price_action_snapshot(
    broker: Any,
    *,
    as_of: str,
    market_timezone: str = "America/New_York",
) -> PriceActionSnapshot:
    fetch_closed_rates = getattr(broker, "fetch_closed_rates", None)
    if not callable(fetch_closed_rates):
        raise AttributeError("broker must provide fetch_closed_rates for MT5 analysis")

    candles_by_timeframe = {
        timeframe: [_to_candle(row) for row in fetch_closed_rates(timeframe, count)]
        for timeframe, count in MT5_TIMEFRAME_COUNTS.items()
    }
    candles_by_timeframe["4h"] = resample_candles(candles_by_timeframe["1h"], "4h")

    candles = {
        "1d": candles_by_timeframe["1d"],
        "4h": candles_by_timeframe["4h"],
        "1h": candles_by_timeframe["1h"],
        "30m": candles_by_timeframe["30m"],
        "15m": candles_by_timeframe["15m"],
        "3m": candles_by_timeframe["3m"],
        "1m": candles_by_timeframe["1m"],
    }
    market_metadata = _market_metadata(broker)
    health_as_of, reference_source = mt5_health_reference(
        market_metadata,
        as_of,
    )
    data_status = build_data_status(
        candles,
        health_as_of,
        market_timezone,
        required_timeframes=tuple(candles),
        trading_timeframe="15m",
        confirmation_timeframe="30m",
    )
    data_status["reference_timestamp"] = health_as_of
    data_status["reference_source"] = reference_source
    return PriceActionSnapshot(
        candles=candles,
        data_status=data_status,
        market_metadata=market_metadata,
    )


def _market_metadata(broker: Any) -> dict[str, Any]:
    snapshot = getattr(broker, "current_symbol_snapshot", None)
    if not callable(snapshot):
        return {}
    try:
        data = snapshot()
    except Exception as exc:  # pragma: no cover - defensive telemetry only
        return {"error": str(exc)}
    return data if isinstance(data, dict) else {}
