"""Closed-candle arming for the independently preregistered M1 V9 candidate."""

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


CANDIDATE_NAME = "ONE_MINUTE_CAUSAL_MICROBURST_V9_1"
MAXIMUM_HISTORY_CANDLES = 60
BASELINE_WINDOW = 30
REFERENCE_WINDOW = 12
MINIMUM_LATEST_RANGE_BASELINE = 0.75
MAXIMUM_LATEST_RANGE_BASELINE = 1.50
MINIMUM_BODY_FRACTION = 0.55
MINIMUM_CLOSE_LOCATION = 0.75
MINIMUM_THREE_BAR_DISPLACEMENT_BASELINE = 0.75
BREAK_MARGIN_BASELINE = 0.05
ZONE_TOLERANCE_BASELINE = 0.05
TRIGGER_DELAY_SECONDS = 1
ARM_EXPIRY_SECONDS = 30


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


def detect_causal_microburst_arms(
    candles: Iterable[Candle],
    *,
    candidate_name: str = CANDIDATE_NAME,
) -> tuple[PostCloseArm, ...]:
    """Arm one symmetric continuation only after the latest M1 candle closes.

    V9 deliberately ignores repeated levels and outcome-derived labels.  It
    requires a three-close staircase followed by a bounded, decisive break of
    the preceding twelve-candle range.  Quotes after the close must still pass
    the independent path-pressure lifecycle before a stop can be proposed.
    """
    closed = list(candles)[-MAXIMUM_HISTORY_CANDLES:]
    required = BASELINE_WINDOW + 3
    if len(closed) < required:
        return ()
    baseline = closed[-required:-3]
    staircase = closed[-3:]
    latest = staircase[-1]
    baseline_range = _median_range(baseline)
    if baseline_range is None or baseline_range <= 0:
        return ()

    candle_range = float(latest.high) - float(latest.low)
    body = abs(float(latest.close) - float(latest.open))
    if candle_range <= 0:
        return ()
    range_ratio = candle_range / baseline_range
    if not (
        MINIMUM_LATEST_RANGE_BASELINE
        <= range_ratio
        <= MAXIMUM_LATEST_RANGE_BASELINE
    ):
        return ()
    if body / candle_range < MINIMUM_BODY_FRACTION:
        return ()

    reference = baseline[-REFERENCE_WINDOW:]
    reference_high = max(float(candle.high) for candle in reference)
    reference_low = min(float(candle.low) for candle in reference)
    margin = BREAK_MARGIN_BASELINE * baseline_range
    closes = [float(candle.close) for candle in staircase]
    displacement = closes[-1] - float(staircase[0].open)
    close_from_low = (float(latest.close) - float(latest.low)) / candle_range
    bullish_bodies = sum(
        float(candle.close) > float(candle.open) for candle in staircase
    )
    bearish_bodies = sum(
        float(candle.close) < float(candle.open) for candle in staircase
    )

    bullish = (
        closes[0] < closes[1] < closes[2]
        and bullish_bodies >= 2
        and displacement >= MINIMUM_THREE_BAR_DISPLACEMENT_BASELINE * baseline_range
        and close_from_low >= MINIMUM_CLOSE_LOCATION
        and float(latest.close) >= reference_high + margin
    )
    bearish = (
        closes[0] > closes[1] > closes[2]
        and bearish_bodies >= 2
        and -displacement >= MINIMUM_THREE_BAR_DISPLACEMENT_BASELINE * baseline_range
        and close_from_low <= 1.0 - MINIMUM_CLOSE_LOCATION
        and float(latest.close) <= reference_low - margin
    )
    if bullish == bearish:
        return ()

    direction = "BUY" if bullish else "SELL"
    family = HIGH_BREAK_BUY if bullish else LOW_BREAK_SELL
    level_side = "high" if bullish else "low"
    level = reference_high if bullish else reference_low
    tolerance = max(0.01, ZONE_TOLERANCE_BASELINE * baseline_range)
    break_margin = max(0.01, margin)
    confirmation_time = parse_utc(latest.timestamp)
    closed_at = confirmation_time + timedelta(minutes=1)
    invalidation = (
        (float(latest.open) + float(latest.close)) / 2.0
    )
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
        confirmation_type="causal_microburst",
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
    "detect_causal_microburst_arms",
]
