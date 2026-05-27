"""Typed price-action data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass(frozen=True)
class Zone:
    type: str
    timeframe: str
    low: float
    high: float
    midpoint: float
    touches: int = 0
    score: float = 0.0
    source: str = ""
    reactions: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class Setup:
    name: str
    direction: str
    zone: Zone
    entry_price: float
    stop_loss: float
    confirmation_candle: Candle
    retest_depth: float | None = None


@dataclass(frozen=True)
class PendingOrder:
    symbol: str
    side: str
    entry_price: float
    stop_loss: float
    take_profit: float
    candle_open: str
    expires_at: str
    volume: float | None = None
    setup: Setup | None = None
    status: str = "PENDING"

    @property
    def direction(self) -> str:
        return self.side
