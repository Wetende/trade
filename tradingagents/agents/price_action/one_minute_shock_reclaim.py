"""Causal symmetric M1 shock-and-reclaim signal detection."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from statistics import median
from typing import Iterable

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PostCloseArm,
    parse_utc,
)


CANDIDATE_NAME = "ONE_MINUTE_SHOCK_RECLAIM_V6"
MAXIMUM_HISTORY_CANDLES = 60
BASELINE_WINDOW = 36
REFERENCE_WINDOW = 12
SHOCK_RANGE_BASELINE_MINIMUM = 1.50
SHOCK_BODY_FRACTION_MINIMUM = 0.60
SHOCK_CLOSE_LOCATION_MINIMUM = 0.80
EXTENSION_BASELINE_FRACTION = 0.10
RECLAIM_BODY_FRACTION_MINIMUM = 0.50
RECLAIM_CLOSE_LOCATION_MINIMUM = 0.70
ARM_EXPIRY_SECONDS = 90


def _positive_median_range(candles: list[Candle]) -> float | None:
    positive = [
        float(candle.high) - float(candle.low)
        for candle in candles
        if float(candle.high) - float(candle.low) > 0
    ]
    return float(median(positive)) if positive else None


def _range_and_body(candle: Candle) -> tuple[float, float]:
    candle_range = float(candle.high) - float(candle.low)
    return candle_range, abs(float(candle.close) - float(candle.open))


def _arm_id(parts: tuple[object, ...]) -> str:
    raw = "\0".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def detect_shock_reclaim_arms(
    candles: Iterable[Candle],
    *,
    candidate_name: str = CANDIDATE_NAME,
) -> tuple[PostCloseArm, ...]:
    """Return at most one V6 arm from the latest fully closed reclaim candle."""
    closed = list(candles)[-MAXIMUM_HISTORY_CANDLES:]
    required = BASELINE_WINDOW + 2
    if len(closed) < required:
        return ()

    baseline = closed[-required:-2]
    reference = baseline[-REFERENCE_WINDOW:]
    shock = closed[-2]
    reclaim = closed[-1]
    baseline_range = _positive_median_range(baseline)
    if baseline_range is None:
        return ()

    shock_range, shock_body = _range_and_body(shock)
    reclaim_range, reclaim_body = _range_and_body(reclaim)
    if shock_range <= 0 or reclaim_range <= 0:
        return ()
    if shock_range < SHOCK_RANGE_BASELINE_MINIMUM * baseline_range:
        return ()
    if shock_body / shock_range < SHOCK_BODY_FRACTION_MINIMUM:
        return ()
    if reclaim_body / reclaim_range < RECLAIM_BODY_FRACTION_MINIMUM:
        return ()

    reference_high = max(float(candle.high) for candle in reference)
    reference_low = min(float(candle.low) for candle in reference)
    margin = EXTENSION_BASELINE_FRACTION * baseline_range
    shock_close_from_low = (
        float(shock.close) - float(shock.low)
    ) / shock_range
    reclaim_close_from_low = (
        float(reclaim.close) - float(reclaim.low)
    ) / reclaim_range

    high_reclaim = (
        float(shock.close) > float(shock.open)
        and float(shock.close) >= reference_high + margin
        and shock_close_from_low >= SHOCK_CLOSE_LOCATION_MINIMUM
        and float(reclaim.close) < float(reclaim.open)
        and float(reclaim.high) >= reference_high
        and float(reclaim.close) <= reference_high - margin
        and reclaim_close_from_low <= 1.0 - RECLAIM_CLOSE_LOCATION_MINIMUM
    )
    low_reclaim = (
        float(shock.close) < float(shock.open)
        and float(shock.close) <= reference_low - margin
        and shock_close_from_low <= 1.0 - SHOCK_CLOSE_LOCATION_MINIMUM
        and float(reclaim.close) > float(reclaim.open)
        and float(reclaim.low) <= reference_low
        and float(reclaim.close) >= reference_low + margin
        and reclaim_close_from_low >= RECLAIM_CLOSE_LOCATION_MINIMUM
    )
    if high_reclaim == low_reclaim:
        return ()

    sell = high_reclaim
    direction = "SELL" if sell else "BUY"
    family = FAILED_HIGH_BREAK_SELL if sell else FAILED_LOW_BREAK_BUY
    level_side = "high" if sell else "low"
    level = reference_high if sell else reference_low
    invalidation = level + margin if sell else level - margin
    confirmation_time = parse_utc(reclaim.timestamp)
    closed_at = confirmation_time + timedelta(minutes=1)
    arm = PostCloseArm(
        candidate=candidate_name,
        arm_id=_arm_id(
            (
                candidate_name,
                family,
                round(level, 6),
                shock.timestamp,
                reclaim.timestamp,
                round(baseline_range, 6),
            )
        ),
        family=family,
        direction=direction,
        level_side=level_side,
        level=round(level, 6),
        touch_count=0,
        tolerance=round(margin, 6),
        break_margin=round(margin, 6),
        zone_low=round(level - margin, 6),
        zone_high=round(level + margin, 6),
        confirmation_type="shock_reclaim",
        confirmation_time=str(reclaim.timestamp),
        confirmation_closed_at=closed_at.isoformat(),
        trigger_eligible_at=(closed_at + timedelta(seconds=5)).isoformat(),
        expires_at=(closed_at + timedelta(seconds=ARM_EXPIRY_SECONDS)).isoformat(),
        invalidation=round(invalidation, 6),
        confirmation_open=float(reclaim.open),
        confirmation_high=float(reclaim.high),
        confirmation_low=float(reclaim.low),
        confirmation_close=float(reclaim.close),
    )
    return (arm,)


__all__ = [
    "BASELINE_WINDOW",
    "CANDIDATE_NAME",
    "REFERENCE_WINDOW",
    "detect_shock_reclaim_arms",
]
