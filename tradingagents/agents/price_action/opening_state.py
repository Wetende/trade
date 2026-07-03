"""Broker-free M1 repeated-level opening-state research."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    _consolidate_candidate_levels,
    _detect_equal_levels,
    _recent_tolerance,
)


class OpeningTemplate(StrEnum):
    REJECTION = "REJECTION"
    BREAK_HOLD = "BREAK_HOLD"
    BREAK_RETEST_HOLD = "BREAK_RETEST_HOLD"
    FAILED_BREAK = "FAILED_BREAK"


class OpeningOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template: OpeningTemplate
    direction: Literal["BUY", "SELL"]
    signal_time: str
    level_side: Literal["high", "low"]
    level: float
    touch_count: int = Field(ge=2)
    tolerance: float = Field(ge=0)
    used_candle_indexes: tuple[int, ...]
    entry_kind: Literal["reaction", "continuation"]


def _margin(tolerance: float) -> float:
    return max(0.05, tolerance * 0.25)


def _is_beyond(candle: Candle, *, side: str, level: float, tolerance: float) -> bool:
    margin = _margin(tolerance)
    if side == "high":
        return float(candle.close) > level + margin
    return float(candle.close) < level - margin


def _closed_inside(candle: Candle, *, side: str, level: float) -> bool:
    if side == "high":
        return float(candle.close) <= level
    return float(candle.close) >= level


def _reversal_close(candle: Candle, *, side: str) -> bool:
    if side == "high":
        return float(candle.close) < float(candle.open)
    return float(candle.close) > float(candle.open)


def _initial_touch(
    candle: Candle,
    *,
    side: str,
    level: float,
    tolerance: float,
) -> bool:
    if side == "high":
        return float(candle.high) >= level - tolerance
    return float(candle.low) <= level + tolerance


def _retest_from_beyond(candle: Candle, *, side: str, level: float) -> bool:
    if side == "high":
        return float(candle.low) <= level
    return float(candle.high) >= level


def _direction(template: OpeningTemplate, side: str) -> Literal["BUY", "SELL"]:
    if template in {OpeningTemplate.BREAK_HOLD, OpeningTemplate.BREAK_RETEST_HOLD}:
        return "BUY" if side == "high" else "SELL"
    return "SELL" if side == "high" else "BUY"


def _entry_kind(template: OpeningTemplate) -> Literal["reaction", "continuation"]:
    if template in {OpeningTemplate.REJECTION, OpeningTemplate.FAILED_BREAK}:
        return "reaction"
    return "continuation"


def _opportunity(
    template: OpeningTemplate,
    *,
    side: str,
    level: float,
    touch_count: int,
    tolerance: float,
    signal: Candle,
    used_indexes: tuple[int, ...],
) -> OpeningOpportunity:
    return OpeningOpportunity(
        template=template,
        direction=_direction(template, side),
        signal_time=str(signal.timestamp),
        level_side=side,
        level=round(float(level), 4),
        touch_count=int(touch_count),
        tolerance=round(float(tolerance), 4),
        used_candle_indexes=used_indexes,
        entry_kind=_entry_kind(template),
    )


def _rank_opportunities(items: list[OpeningOpportunity]) -> list[OpeningOpportunity]:
    return sorted(
        items,
        key=lambda item: (
            datetime.fromisoformat(item.signal_time),
            -item.touch_count,
            item.template.value,
            item.level_side,
            round(item.level, 4),
        ),
    )


def _candidate_levels(
    candles: list[Candle],
    *,
    tolerance: float,
):
    return _consolidate_candidate_levels(
        [
            *_detect_equal_levels(candles, tolerance, side="low"),
            *_detect_equal_levels(candles, tolerance, side="high"),
        ],
        tolerance=tolerance,
        current_spread_price=0.0,
    )


def detect_opening_opportunities(
    candles: list[Candle] | tuple[Candle, ...],
    *,
    lookback: int = 60,
) -> tuple[OpeningOpportunity, ...]:
    """Detect pre-registered closed-M1 opening templates without future leakage."""
    closed = list(candles)
    if len(closed) < 3:
        return ()

    opportunities: list[OpeningOpportunity] = []
    for first_index in range(2, len(closed)):
        start = max(0, first_index - lookback)
        prior = closed[start:first_index]
        tolerance = _recent_tolerance(prior)
        first = closed[first_index]
        previous = closed[first_index - 1] if first_index else None
        for level in _candidate_levels(prior, tolerance=tolerance):
            side = level.side
            if (
                _initial_touch(
                    first,
                    side=side,
                    level=level.level,
                    tolerance=tolerance,
                )
                and _closed_inside(first, side=side, level=level.level)
                and _reversal_close(first, side=side)
                and not (
                    previous is not None
                    and _is_beyond(
                        previous,
                        side=side,
                        level=level.level,
                        tolerance=tolerance,
                    )
                )
            ):
                opportunities.append(
                    _opportunity(
                        OpeningTemplate.REJECTION,
                        side=side,
                        level=level.level,
                        touch_count=level.touch_count,
                        tolerance=tolerance,
                        signal=first,
                        used_indexes=(first_index,),
                    )
                )

            if not _is_beyond(first, side=side, level=level.level, tolerance=tolerance):
                continue
            if previous is not None and _is_beyond(
                previous,
                side=side,
                level=level.level,
                tolerance=tolerance,
            ):
                continue
            if first_index + 1 >= len(closed):
                continue
            second = closed[first_index + 1]
            if _closed_inside(second, side=side, level=level.level) and _reversal_close(
                second,
                side=side,
            ):
                opportunities.append(
                    _opportunity(
                        OpeningTemplate.FAILED_BREAK,
                        side=side,
                        level=level.level,
                        touch_count=level.touch_count,
                        tolerance=tolerance,
                        signal=second,
                        used_indexes=(first_index, first_index + 1),
                    )
                )
                continue
            if not _is_beyond(second, side=side, level=level.level, tolerance=tolerance):
                continue
            if _retest_from_beyond(second, side=side, level=level.level):
                if first_index + 2 >= len(closed):
                    continue
                third = closed[first_index + 2]
                if _is_beyond(
                    third,
                    side=side,
                    level=level.level,
                    tolerance=tolerance,
                ):
                    opportunities.append(
                        _opportunity(
                            OpeningTemplate.BREAK_RETEST_HOLD,
                            side=side,
                            level=level.level,
                            touch_count=level.touch_count,
                            tolerance=tolerance,
                            signal=third,
                            used_indexes=(
                                first_index,
                                first_index + 1,
                                first_index + 2,
                            ),
                        )
                    )
                continue
            opportunities.append(
                _opportunity(
                    OpeningTemplate.BREAK_HOLD,
                    side=side,
                    level=level.level,
                    touch_count=level.touch_count,
                    tolerance=tolerance,
                    signal=second,
                    used_indexes=(first_index, first_index + 1),
                )
            )

    unique = {item.model_dump_json(): item for item in opportunities}
    return tuple(_rank_opportunities(list(unique.values())))


__all__ = [
    "OpeningOpportunity",
    "OpeningTemplate",
    "detect_opening_opportunities",
]
