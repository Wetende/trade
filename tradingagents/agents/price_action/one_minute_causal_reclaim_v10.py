"""Closed-candle failed-break reclaim arms for the M1 V10 candidate."""

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


CANDIDATE_NAME = "ONE_MINUTE_CAUSAL_RECLAIM_V10"
MAXIMUM_HISTORY_CANDLES = 60
BASELINE_WINDOW = 30
REFERENCE_WINDOW = 12
MINIMUM_RANGE_BASELINE = 0.60
MAXIMUM_RANGE_BASELINE = 1.60
MINIMUM_BODY_FRACTION = 0.30
MINIMUM_REJECTION_WICK_FRACTION = 0.25
MINIMUM_SWEEP_BASELINE = 0.08
MAXIMUM_SWEEP_BASELINE = 0.75
MINIMUM_CLOSE_INSIDE_BASELINE = 0.02
ZONE_TOLERANCE_BASELINE = 0.05
BREAK_MARGIN_BASELINE = 0.05
TRIGGER_DELAY_SECONDS = 1
ARM_EXPIRY_SECONDS = 45


def _median_range(candles: list[Candle]) -> float | None:
    values = [
        float(candle.high) - float(candle.low)
        for candle in candles
        if float(candle.high) > float(candle.low)
    ]
    return float(median(values)) if values else None


def _arm_id(parts: tuple[object, ...]) -> str:
    raw = "\0".join(str(value) for value in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def detect_causal_reclaim_arms(
    candles: Iterable[Candle],
    *,
    candidate_name: str = CANDIDATE_NAME,
) -> tuple[PostCloseArm, ...]:
    """Arm one mirrored reclaim using only the latest fully closed candle."""
    closed = list(candles)[-MAXIMUM_HISTORY_CANDLES:]
    if len(closed) < BASELINE_WINDOW + 1:
        return ()
    baseline = closed[-(BASELINE_WINDOW + 1) : -1]
    latest = closed[-1]
    baseline_range = _median_range(baseline)
    if baseline_range is None or baseline_range <= 0:
        return ()

    candle_range = float(latest.high) - float(latest.low)
    if candle_range <= 0:
        return ()
    range_ratio = candle_range / baseline_range
    if not MINIMUM_RANGE_BASELINE <= range_ratio <= MAXIMUM_RANGE_BASELINE:
        return ()
    body = abs(float(latest.close) - float(latest.open))
    if body / candle_range < MINIMUM_BODY_FRACTION:
        return ()

    reference = baseline[-REFERENCE_WINDOW:]
    reference_high = max(float(candle.high) for candle in reference)
    reference_low = min(float(candle.low) for candle in reference)
    minimum_sweep = MINIMUM_SWEEP_BASELINE * baseline_range
    maximum_sweep = MAXIMUM_SWEEP_BASELINE * baseline_range
    close_inside = MINIMUM_CLOSE_INSIDE_BASELINE * baseline_range
    upper_wick = float(latest.high) - max(float(latest.open), float(latest.close))
    lower_wick = min(float(latest.open), float(latest.close)) - float(latest.low)

    failed_high = (
        float(latest.close) < float(latest.open)
        and minimum_sweep
        <= float(latest.high) - reference_high
        <= maximum_sweep
        and float(latest.close) <= reference_high - close_inside
        and upper_wick / candle_range >= MINIMUM_REJECTION_WICK_FRACTION
    )
    failed_low = (
        float(latest.close) > float(latest.open)
        and minimum_sweep
        <= reference_low - float(latest.low)
        <= maximum_sweep
        and float(latest.close) >= reference_low + close_inside
        and lower_wick / candle_range >= MINIMUM_REJECTION_WICK_FRACTION
    )
    if failed_high == failed_low:
        return ()

    direction = "SELL" if failed_high else "BUY"
    family = FAILED_HIGH_BREAK_SELL if failed_high else FAILED_LOW_BREAK_BUY
    level_side = "high" if failed_high else "low"
    level = reference_high if failed_high else reference_low
    tolerance = max(0.01, ZONE_TOLERANCE_BASELINE * baseline_range)
    break_margin = max(0.01, BREAK_MARGIN_BASELINE * baseline_range)
    invalidation = float(latest.high) if failed_high else float(latest.low)
    confirmation_time = parse_utc(latest.timestamp)
    closed_at = confirmation_time + timedelta(minutes=1)
    arm = PostCloseArm(
        candidate=candidate_name,
        arm_id=_arm_id(
            (
                candidate_name,
                family,
                latest.timestamp,
                round(level, 6),
                round(baseline_range, 6),
            )
        ),
        family=family,
        direction=direction,
        level_side=level_side,
        level=round(level, 6),
        touch_count=0,
        tolerance=round(tolerance, 6),
        break_margin=round(break_margin, 6),
        zone_low=round(level - tolerance, 6),
        zone_high=round(level + tolerance, 6),
        confirmation_type="failed_break_reclaim",
        confirmation_time=str(latest.timestamp),
        confirmation_closed_at=closed_at.isoformat(),
        trigger_eligible_at=(
            closed_at + timedelta(seconds=TRIGGER_DELAY_SECONDS)
        ).isoformat(),
        expires_at=(closed_at + timedelta(seconds=ARM_EXPIRY_SECONDS)).isoformat(),
        invalidation=round(invalidation, 6),
        confirmation_open=float(latest.open),
        confirmation_high=float(latest.high),
        confirmation_low=float(latest.low),
        confirmation_close=float(latest.close),
    )
    return (arm,)


__all__ = [
    "BASELINE_WINDOW",
    "CANDIDATE_NAME",
    "REFERENCE_WINDOW",
    "detect_causal_reclaim_arms",
]
