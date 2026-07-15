"""Causal symmetric M1 impulse-inside-pullback signal detection."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from statistics import median
from typing import Iterable

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PostCloseArm,
    parse_utc,
)


CANDIDATE_NAME = "ONE_MINUTE_IMPULSE_INSIDE_PULLBACK_V7"
IMPULSE_INSIDE_PULLBACK_BUY = "IMPULSE_INSIDE_PULLBACK_BUY"
IMPULSE_INSIDE_PULLBACK_SELL = "IMPULSE_INSIDE_PULLBACK_SELL"
MAXIMUM_HISTORY_CANDLES = 60
BASELINE_WINDOW = 36
IMPULSE_RANGE_BASELINE_MINIMUM = 1.25
IMPULSE_BODY_FRACTION_MINIMUM = 0.60
IMPULSE_CLOSE_LOCATION_MINIMUM = 0.75
PULLBACK_RANGE_BASELINE_MAXIMUM = 0.75
PULLBACK_BODY_FRACTION_MINIMUM = 0.25
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


def detect_impulse_inside_pullback_arms(
    candles: Iterable[Candle],
    *,
    candidate_name: str = CANDIDATE_NAME,
) -> tuple[PostCloseArm, ...]:
    """Return at most one V7 arm from the latest fully closed pullback."""
    closed = list(candles)[-MAXIMUM_HISTORY_CANDLES:]
    required = BASELINE_WINDOW + 2
    if len(closed) < required:
        return ()

    baseline = closed[-required:-2]
    impulse = closed[-2]
    pullback = closed[-1]
    baseline_range = _positive_median_range(baseline)
    if baseline_range is None:
        return ()

    impulse_range, impulse_body = _range_and_body(impulse)
    pullback_range, pullback_body = _range_and_body(pullback)
    if impulse_range <= 0 or pullback_range <= 0:
        return ()
    if impulse_range < IMPULSE_RANGE_BASELINE_MINIMUM * baseline_range:
        return ()
    if impulse_body / impulse_range < IMPULSE_BODY_FRACTION_MINIMUM:
        return ()
    if pullback_range > PULLBACK_RANGE_BASELINE_MAXIMUM * baseline_range:
        return ()
    if pullback_body / pullback_range < PULLBACK_BODY_FRACTION_MINIMUM:
        return ()
    if (
        float(pullback.high) > float(impulse.high)
        or float(pullback.low) < float(impulse.low)
    ):
        return ()

    impulse_close_from_low = (
        float(impulse.close) - float(impulse.low)
    ) / impulse_range
    impulse_midpoint = (float(impulse.high) + float(impulse.low)) / 2.0
    buy = (
        float(impulse.close) > float(impulse.open)
        and impulse_close_from_low >= IMPULSE_CLOSE_LOCATION_MINIMUM
        and float(pullback.close) < float(pullback.open)
        and float(pullback.close) >= impulse_midpoint
    )
    sell = (
        float(impulse.close) < float(impulse.open)
        and impulse_close_from_low <= 1.0 - IMPULSE_CLOSE_LOCATION_MINIMUM
        and float(pullback.close) > float(pullback.open)
        and float(pullback.close) <= impulse_midpoint
    )
    if buy == sell:
        return ()

    direction = "BUY" if buy else "SELL"
    family = (
        IMPULSE_INSIDE_PULLBACK_BUY
        if buy
        else IMPULSE_INSIDE_PULLBACK_SELL
    )
    level_side = "high" if buy else "low"
    level = float(pullback.high) if buy else float(pullback.low)
    invalidation = float(pullback.low) if buy else float(pullback.high)
    confirmation_time = parse_utc(pullback.timestamp)
    closed_at = confirmation_time + timedelta(minutes=1)
    arm = PostCloseArm(
        candidate=candidate_name,
        arm_id=_arm_id(
            (
                candidate_name,
                family,
                round(level, 6),
                impulse.timestamp,
                pullback.timestamp,
                round(baseline_range, 6),
            )
        ),
        family=family,
        direction=direction,
        level_side=level_side,
        level=round(level, 6),
        touch_count=0,
        tolerance=round(pullback_range / 2.0, 6),
        break_margin=0.0,
        zone_low=round(float(pullback.low), 6),
        zone_high=round(float(pullback.high), 6),
        confirmation_type="inside_pullback",
        confirmation_time=str(pullback.timestamp),
        confirmation_closed_at=closed_at.isoformat(),
        trigger_eligible_at=(closed_at + timedelta(seconds=5)).isoformat(),
        expires_at=(closed_at + timedelta(seconds=ARM_EXPIRY_SECONDS)).isoformat(),
        invalidation=round(invalidation, 6),
        confirmation_open=float(pullback.open),
        confirmation_high=float(pullback.high),
        confirmation_low=float(pullback.low),
        confirmation_close=float(pullback.close),
    )
    return (arm,)


__all__ = [
    "BASELINE_WINDOW",
    "CANDIDATE_NAME",
    "IMPULSE_INSIDE_PULLBACK_BUY",
    "IMPULSE_INSIDE_PULLBACK_SELL",
    "detect_impulse_inside_pullback_arms",
]
