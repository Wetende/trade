"""Playbook-compliant clean repeated-level detection for closed M1 candles."""

from __future__ import annotations

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import OneMinuteLevel


MINIMUM_BAR_SEPARATION = 3
MINIMUM_REACTION_TOLERANCE_MULTIPLE = 1.5
INTERIM_EXCURSION_TOLERANCE_MULTIPLE = 2.0


def _price(candle: Candle, side: str) -> float:
    return float(candle.high if side == "high" else candle.low)


def _moved_away(
    candles: list[Candle],
    *,
    side: str,
    level: float,
    distance: float,
) -> bool:
    if side == "high":
        return any(float(candle.close) <= level - distance for candle in candles)
    return any(float(candle.close) >= level + distance for candle in candles)


def detect_clean_equal_levels(
    candles: list[Candle],
    tolerance: float,
    *,
    side: str,
    minimum_bar_separation: int = MINIMUM_BAR_SEPARATION,
    reaction_tolerance_multiple: float = MINIMUM_REACTION_TOLERANCE_MULTIPLE,
    excursion_tolerance_multiple: float = INTERIM_EXCURSION_TOLERANCE_MULTIPLE,
) -> list[OneMinuteLevel]:
    """Detect levels with separated touches and closed-candle reactions."""
    if side not in {"high", "low"}:
        raise ValueError("side must be high or low")
    if len(candles) < 4:
        return []
    tolerance = max(0.0, float(tolerance))
    if tolerance <= 0:
        return []
    reaction_distance = tolerance * float(reaction_tolerance_multiple)
    excursion_distance = tolerance * float(excursion_tolerance_multiple)
    minimum_gap = max(1, int(minimum_bar_separation))
    prices = [_price(candle, side) for candle in candles]
    candidates: list[OneMinuteLevel] = []

    for anchor_index, anchor in enumerate(prices):
        accepted = [anchor_index]
        level = anchor
        for index in range(anchor_index + 1, len(candles)):
            if abs(prices[index] - level) > tolerance:
                continue
            previous = accepted[-1]
            interim = candles[previous + 1 : index]
            time_separated = index - previous >= minimum_gap
            movement_separated = _moved_away(
                interim,
                side=side,
                level=level,
                distance=excursion_distance,
            )
            visible_reaction = _moved_away(
                interim,
                side=side,
                level=level,
                distance=reaction_distance,
            )
            if not visible_reaction or not (time_separated or movement_separated):
                continue
            accepted.append(index)
            level = sum(prices[item] for item in accepted) / len(accepted)

        if len(accepted) < 2:
            continue
        after_last = candles[accepted[-1] + 1 :]
        if not _moved_away(
            after_last,
            side=side,
            level=level,
            distance=reaction_distance,
        ):
            continue
        touch_prices = [prices[index] for index in accepted]
        if any(
            existing.side == side and abs(existing.level - level) <= tolerance
            for existing in candidates
        ):
            continue
        candidates.append(
            OneMinuteLevel(
                side=side,
                level=level,
                touch_count=len(accepted),
                first_touch_index=accepted[0],
                last_touch_index=accepted[-1],
                spread=max(touch_prices) - min(touch_prices),
                tolerance=tolerance,
            )
        )
    return sorted(
        candidates,
        key=lambda item: (-item.last_touch_index, -item.touch_count, item.spread, item.level),
    )


__all__ = [
    "INTERIM_EXCURSION_TOLERANCE_MULTIPLE",
    "MINIMUM_BAR_SEPARATION",
    "MINIMUM_REACTION_TOLERANCE_MULTIPLE",
    "detect_clean_equal_levels",
]
