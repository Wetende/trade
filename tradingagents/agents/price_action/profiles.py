"""Entry profile configuration for deterministic price-action engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EntryProfile:
    name: str
    timeframe: str
    confirmation_timeframe: str
    zone_timeframes: tuple[str, ...]
    context_timeframes: tuple[str, ...]
    governing_timeframes: tuple[str, ...]
    activation_window_minutes: int
    independent_direction: bool = False
    counter_bias_minimum_grade: str = "A_PLUS"


def normal_profile(config: dict[str, Any] | None = None) -> EntryProfile:
    cfg = config or {}
    return EntryProfile(
        name="normal",
        timeframe=str(cfg.get("timeframe", "15m")),
        confirmation_timeframe=str(cfg.get("confirmation_timeframe", "30m")),
        zone_timeframes=("30m",),
        context_timeframes=("1d", "4h", "1h"),
        governing_timeframes=(str(cfg.get("confirmation_timeframe", "30m")),),
        activation_window_minutes=int(cfg.get("normal_activation_window_minutes", 30)),
        independent_direction=False,
    )


def fast_profile(config: dict[str, Any] | None = None) -> EntryProfile:
    cfg = config or {}
    return EntryProfile(
        name="fast",
        timeframe=str(cfg.get("fast_timeframe", "1m")),
        confirmation_timeframe=str(cfg.get("fast_confirmation_timeframe", "3m")),
        zone_timeframes=("30m", "15m"),
        context_timeframes=("30m", "15m"),
        governing_timeframes=("30m", "15m"),
        activation_window_minutes=int(cfg.get("fast_activation_window_minutes", 6)),
        independent_direction=True,
        counter_bias_minimum_grade=str(
            cfg.get("fast_counter_bias_minimum_grade", "A_PLUS")
        ),
    )
