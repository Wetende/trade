"""Causal symmetric M1 compression-expansion signal detection."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from statistics import median
from typing import Iterable

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    HIGH_BREAK_BUY,
    LOW_BREAK_SELL,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PostCloseArm,
    parse_utc,
)


CANDIDATE_NAME = "ONE_MINUTE_COMPRESSION_EXPANSION_V5"
BASELINE_WINDOW = 36
COMPRESSION_WINDOW = 12
COMPRESSION_RATIO_MAXIMUM = 0.70
BOX_WIDTH_BASELINE_RANGE_MAXIMUM = 3.0
COMPRESSION_EFFICIENCY_MAXIMUM = 0.40
BODY_FRACTION_MINIMUM = 0.60
CLOSE_LOCATION_MINIMUM = 0.80
EXPANSION_COMPRESSION_RANGE_MINIMUM = 1.25
EXPANSION_BASELINE_RANGE_MAXIMUM = 3.0
ARM_EXPIRY_SECONDS = 120


def _positive_median_range(candles: list[Candle]) -> float | None:
    values = [float(item.high) - float(item.low) for item in candles]
    positive = [value for value in values if value > 0]
    return float(median(positive)) if positive else None


def _efficiency(candles: list[Candle]) -> float:
    travelled = sum(abs(float(item.close) - float(item.open)) for item in candles)
    if travelled <= 0:
        return 0.0
    displacement = abs(float(candles[-1].close) - float(candles[0].open))
    return displacement / travelled


def _strong_expansion(
    candle: Candle,
    *,
    direction: str,
    compression_range: float,
    baseline_range: float,
) -> bool:
    candle_range = float(candle.high) - float(candle.low)
    if candle_range <= 0:
        return False
    body = abs(float(candle.close) - float(candle.open))
    if body / candle_range < BODY_FRACTION_MINIMUM:
        return False
    if candle_range < EXPANSION_COMPRESSION_RANGE_MINIMUM * compression_range:
        return False
    if candle_range > EXPANSION_BASELINE_RANGE_MAXIMUM * baseline_range:
        return False
    if direction == "BUY":
        close_location = (float(candle.close) - float(candle.low)) / candle_range
        return float(candle.close) > float(candle.open) and close_location >= CLOSE_LOCATION_MINIMUM
    close_location = (float(candle.high) - float(candle.close)) / candle_range
    return float(candle.close) < float(candle.open) and close_location >= CLOSE_LOCATION_MINIMUM


def _arm_id(parts: tuple[object, ...]) -> str:
    raw = "\0".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def detect_compression_expansion_arms(
    candles: Iterable[Candle],
    *,
    candidate_name: str = CANDIDATE_NAME,
) -> tuple[PostCloseArm, ...]:
    """Return at most one V5 arm using only the latest closed candle."""
    required = BASELINE_WINDOW + COMPRESSION_WINDOW + 1
    closed = list(candles)[-required:]
    if len(closed) < required:
        return ()
    baseline = closed[:BASELINE_WINDOW]
    compression = closed[BASELINE_WINDOW:-1]
    confirmation = closed[-1]
    baseline_range = _positive_median_range(baseline)
    compression_range = _positive_median_range(compression)
    if baseline_range is None or compression_range is None:
        return ()
    if compression_range > COMPRESSION_RATIO_MAXIMUM * baseline_range:
        return ()

    box_high = max(float(item.high) for item in compression)
    box_low = min(float(item.low) for item in compression)
    if box_high - box_low > BOX_WIDTH_BASELINE_RANGE_MAXIMUM * baseline_range:
        return ()
    if _efficiency(compression) > COMPRESSION_EFFICIENCY_MAXIMUM:
        return ()

    tolerance = max(0.10, 0.10 * baseline_range)
    break_margin = max(0.05, 0.10 * baseline_range)
    buy = (
        float(confirmation.close) > box_high + tolerance + break_margin
        and _strong_expansion(
            confirmation,
            direction="BUY",
            compression_range=compression_range,
            baseline_range=baseline_range,
        )
    )
    sell = (
        float(confirmation.close) < box_low - tolerance - break_margin
        and _strong_expansion(
            confirmation,
            direction="SELL",
            compression_range=compression_range,
            baseline_range=baseline_range,
        )
    )
    if not buy and not sell:
        return ()

    direction = "BUY" if buy else "SELL"
    family = HIGH_BREAK_BUY if buy else LOW_BREAK_SELL
    side = "high" if buy else "low"
    level = box_high if buy else box_low
    invalidation_offset = max(0.20, 0.50 * compression_range)
    invalidation = (
        box_high - invalidation_offset if buy else box_low + invalidation_offset
    )
    confirmation_time = parse_utc(confirmation.timestamp)
    closed_at = confirmation_time + timedelta(minutes=1)
    arm = PostCloseArm(
        candidate=candidate_name,
        arm_id=_arm_id(
            (
                candidate_name,
                family,
                round(level, 4),
                confirmation.timestamp,
                round(baseline_range, 4),
                round(compression_range, 4),
            )
        ),
        family=family,
        direction=direction,
        level_side=side,
        level=round(level, 4),
        touch_count=COMPRESSION_WINDOW,
        tolerance=round(tolerance, 4),
        break_margin=round(break_margin, 4),
        zone_low=round(level - tolerance, 4),
        zone_high=round(level + tolerance, 4),
        confirmation_type="strong_close",
        confirmation_time=str(confirmation.timestamp),
        confirmation_closed_at=closed_at.isoformat(),
        trigger_eligible_at=(closed_at + timedelta(seconds=5)).isoformat(),
        expires_at=(closed_at + timedelta(seconds=ARM_EXPIRY_SECONDS)).isoformat(),
        invalidation=round(invalidation, 4),
        confirmation_open=float(confirmation.open),
        confirmation_high=float(confirmation.high),
        confirmation_low=float(confirmation.low),
        confirmation_close=float(confirmation.close),
    )
    return (arm,)


__all__ = [
    "BASELINE_WINDOW",
    "CANDIDATE_NAME",
    "COMPRESSION_WINDOW",
    "detect_compression_expansion_arms",
]
