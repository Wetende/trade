"""Data availability and freshness checks for price-action timeframes."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


MAX_AGE_MINUTES = {
    "1d": 4320,
    "4h": 480,
    "1h": 180,
    "30m": 90,
    "15m": 45,
}

REQUIRED_TIMEFRAMES = ("1d", "4h", "1h", "30m", "15m")


def _parse_timestamp(value: Any, market_timezone: str) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    tz = ZoneInfo(market_timezone)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _latest_timestamp(candles: list[Any], market_timezone: str) -> datetime | None:
    if not candles:
        return None
    latest = getattr(candles[-1], "timestamp", None)
    return _parse_timestamp(latest, market_timezone)


def build_data_status(
    timeframe_data: dict[str, list[Any]],
    as_of: str,
    market_timezone: str,
) -> dict[str, Any]:
    as_of_dt = _parse_timestamp(as_of, market_timezone)
    statuses: dict[str, dict[str, Any]] = {}
    blocking: list[str] = []

    for timeframe in REQUIRED_TIMEFRAMES:
        candles = timeframe_data.get(timeframe, [])
        latest = _latest_timestamp(candles, market_timezone)
        available = bool(candles)
        age_minutes = None
        fresh = False
        if as_of_dt is not None and latest is not None:
            age_minutes = int((as_of_dt - latest).total_seconds() // 60)
            fresh = 0 <= age_minutes <= MAX_AGE_MINUTES[timeframe]
        status = {
            "interval": timeframe,
            "available": available,
            "rows": len(candles),
            "latest_timestamp": latest.isoformat() if latest else None,
            "latest_age_minutes": age_minutes,
            "fresh": fresh,
            "max_age_minutes": MAX_AGE_MINUTES[timeframe],
        }
        statuses[timeframe] = status
        if not available or not fresh:
            blocking.append(timeframe)

    return {
        "healthy": not blocking,
        "blocking_timeframes": blocking,
        "timeframes": statuses,
        "trading_timeframe": statuses["15m"],
        "confirmation_timeframe": statuses["30m"],
    }


def data_is_healthy(status: dict[str, Any]) -> bool:
    return bool(status.get("healthy"))
