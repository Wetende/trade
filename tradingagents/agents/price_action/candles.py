"""Candle parsing, normalization, and measurement helpers."""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from tradingagents.agents.price_action.models import Candle


def _float(value: Any) -> float:
    if value is None or value == "":
        return math.nan
    return float(value)


def _volume(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def _normalize_row(row: dict[str, Any]) -> Candle | None:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    timestamp = (
        lowered.get("timestamp")
        or lowered.get("datetime")
        or lowered.get("date")
        or lowered.get("")
    )

    try:
        candle = Candle(
            timestamp=str(timestamp) if timestamp is not None else "",
            open=_float(lowered.get("open")),
            high=_float(lowered.get("high")),
            low=_float(lowered.get("low")),
            close=_float(lowered.get("close")),
            volume=_volume(lowered.get("volume", 0)),
        )
    except (TypeError, ValueError):
        return None

    if any(
        math.isnan(value)
        for value in (candle.open, candle.high, candle.low, candle.close)
    ):
        return None
    return candle


def parse_ohlcv_text(raw_data: str | None) -> list[Candle]:
    """Parse CSV-like OHLCV text into normalized candles."""
    if not isinstance(raw_data, str) or not raw_data.strip():
        return []
    if raw_data.lstrip().startswith("No data found"):
        return []

    data_lines = [
        line
        for line in raw_data.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not data_lines:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(data_lines)))
    candles: list[Candle] = []
    for row in reader:
        candle = _normalize_row(row)
        if candle is not None:
            candles.append(candle)
    return candles


def normalize_candles(data: str | Iterable[dict[str, Any] | Candle] | None) -> list[Candle]:
    """Normalize supported candle inputs to ``Candle`` instances."""
    if isinstance(data, str):
        return parse_ohlcv_text(data)
    if data is None:
        return []

    candles: list[Candle] = []
    for row in data:
        if isinstance(row, Candle):
            candles.append(row)
        elif isinstance(row, dict):
            candle = _normalize_row(row)
            if candle is not None:
                candles.append(candle)
    return candles


def candle_range(candle: Candle) -> float:
    return max(float(candle.high) - float(candle.low), 0.0)


def body_high(candle: Candle) -> float:
    return max(float(candle.open), float(candle.close))


def body_low(candle: Candle) -> float:
    return min(float(candle.open), float(candle.close))


def upper_wick(candle: Candle) -> float:
    return max(float(candle.high) - body_high(candle), 0.0)


def lower_wick(candle: Candle) -> float:
    return max(body_low(candle) - float(candle.low), 0.0)


def wick_ratio(candle: Candle, side: str) -> float:
    total_range = candle_range(candle)
    if total_range <= 0:
        return 0.0
    if side == "upper":
        wick = upper_wick(candle)
    elif side == "lower":
        wick = lower_wick(candle)
    else:
        raise ValueError("side must be 'upper' or 'lower'")
    return wick / total_range


def is_bullish(candle: Candle) -> bool:
    return float(candle.close) > float(candle.open)


def is_bearish(candle: Candle) -> bool:
    return float(candle.close) < float(candle.open)


def atr(candles: Iterable[Candle], period: int = 14) -> float:
    normalized = normalize_candles(candles)
    if not normalized or period <= 0:
        return 0.0

    ranges: list[float] = []
    previous_close: float | None = None
    for candle in normalized:
        high = float(candle.high)
        low = float(candle.low)
        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        ranges.append(true_range)
        previous_close = float(candle.close)

    recent = ranges[-period:]
    return sum(recent) / len(recent) if recent else 0.0


def _parse_timestamp(timestamp: str) -> datetime:
    cleaned = timestamp.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    return datetime.fromisoformat(cleaned)


def _parse_timeframe(timeframe: str) -> timedelta:
    value = str(timeframe).strip().lower()
    if value.endswith("h"):
        amount = int(value[:-1])
        interval = timedelta(hours=amount)
    elif value.endswith("m"):
        amount = int(value[:-1])
        interval = timedelta(minutes=amount)
    elif value.endswith("d"):
        amount = int(value[:-1])
        interval = timedelta(days=amount)
    else:
        raise ValueError("timeframe must use an 'm', 'h', or 'd' suffix")

    if amount <= 0:
        raise ValueError("timeframe interval must be positive")
    return interval


def _bucket_start(timestamp: datetime, interval: timedelta) -> datetime:
    day_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = timestamp - day_start
    bucket_index = elapsed // interval
    return day_start + (bucket_index * interval)


def resample_candles(candles: Iterable[Candle], timeframe: str) -> list[Candle]:
    """Resample candles into clock-boundary OHLCV buckets."""
    normalized = normalize_candles(candles)
    if not normalized:
        return []

    interval = _parse_timeframe(timeframe)
    parsed = sorted(
        ((_parse_timestamp(candle.timestamp), candle) for candle in normalized),
        key=lambda item: item[0],
    )

    buckets: dict[datetime, list[Candle]] = {}
    for timestamp, candle in parsed:
        buckets.setdefault(_bucket_start(timestamp, interval), []).append(candle)

    resampled: list[Candle] = []
    for bucket_timestamp in sorted(buckets):
        bucket = buckets[bucket_timestamp]
        resampled.append(
            Candle(
                timestamp=bucket_timestamp.isoformat(sep=" "),
                open=bucket[0].open,
                high=max(candle.high for candle in bucket),
                low=min(candle.low for candle in bucket),
                close=bucket[-1].close,
                volume=sum(candle.volume for candle in bucket),
            )
        )
    return resampled
