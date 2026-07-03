"""Strict, broker-identifier-free evidence models for scalper screening."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class EvidenceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    as_of: datetime
    trigger: str
    direction: Literal["BUY", "SELL"]
    reaction_type: Literal["impulse_break", "respect", "fakeout"]
    approved: bool
    touch_count: int = Field(ge=2)
    body_ratio: float = Field(ge=0)


class EvidenceTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_index: int = Field(ge=0)
    filled: bool
    placed_at: datetime
    filled_at: datetime | None
    closed_at: datetime | None
    profit: float | None
    spread: float = Field(ge=0)
    mfe: float | None
    mae: float | None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "EvidenceTrade":
        outcome = (self.filled_at, self.closed_at, self.profit, self.mfe, self.mae)
        if not self.filled:
            if any(value is not None for value in outcome):
                raise ValueError("unfilled evidence cannot contain an outcome")
            return self
        if any(value is None for value in outcome):
            raise ValueError("filled evidence requires a complete outcome")
        if self.filled_at < self.placed_at:
            raise ValueError("filled_at cannot precede placed_at")
        if self.closed_at < self.filled_at:
            raise ValueError("closed_at cannot precede filled_at")
        return self


class EvidenceSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    decisions: tuple[EvidenceDecision, ...]
    trades: tuple[EvidenceTrade, ...]
