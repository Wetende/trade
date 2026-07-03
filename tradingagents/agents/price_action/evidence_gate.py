"""Strict, broker-identifier-free evidence models for scalper screening."""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
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
    body_ratio: float | None = Field(default=None, ge=0)


class EvidenceTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_index: int = Field(ge=0)
    filled: bool
    placed_at: datetime
    filled_at: datetime | None
    closed_at: datetime | None
    profit: float | None
    spread: float | None = Field(default=None, ge=0)
    mfe: float | None
    mae: float | None

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "EvidenceTrade":
        outcome = (self.filled_at, self.closed_at, self.profit, self.mfe, self.mae)
        if not self.filled:
            if any(value is not None for value in outcome):
                raise ValueError("unfilled evidence cannot contain an outcome")
            return self
        if any(value is None for value in outcome[:3]):
            raise ValueError("filled evidence requires fill, close, and profit")
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


class VariantName(StrEnum):
    BASELINE = "baseline"
    H1_TOUCH_MATURITY = "h1_touch_maturity"
    H2_EXHAUSTION = "h2_exhaustion"
    H3_POST_LOSS_CLUSTER = "h3_post_loss_cluster"


class VariantDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: bool
    reason: str | None = None


class ScreeningRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    session_id: str
    decision_index: int
    accepted: bool
    filled: bool
    profit: float | None
    reasons: tuple[str, ...] = ()


def evaluate_variant(
    decision: EvidenceDecision,
    variant: VariantName | str,
) -> VariantDecision:
    selected = VariantName(variant)
    if not decision.approved:
        return VariantDecision(accepted=False, reason="BASELINE_REJECTED")
    if decision.reaction_type != "impulse_break":
        return VariantDecision(accepted=True)
    if selected == VariantName.H1_TOUCH_MATURITY and decision.touch_count < 3:
        return VariantDecision(
            accepted=False,
            reason="SHADOW_IMPULSE_REQUIRES_THIRD_TOUCH",
        )
    if selected == VariantName.H2_EXHAUSTION:
        if decision.body_ratio is None:
            return VariantDecision(
                accepted=False,
                reason="INSUFFICIENT_IMPULSE_BODY_EVIDENCE",
            )
        if decision.body_ratio > 1.20:
            return VariantDecision(
                accepted=False,
                reason="SHADOW_IMPULSE_BODY_EXHAUSTED",
            )
    return VariantDecision(accepted=True)


def evaluate_session(
    session: EvidenceSession,
    variants: tuple[VariantName | str, ...],
) -> tuple[ScreeningRow, ...]:
    selected = tuple(VariantName(item) for item in variants)
    if len(selected) > 2:
        raise ValueError("historical screening accepts at most two variants")
    trades = {trade.decision_index: trade for trade in session.trades}
    last_loss_closed_at: datetime | None = None
    rows: list[ScreeningRow] = []

    indexed_decisions = sorted(
        enumerate(session.decisions),
        key=lambda item: (item[1].as_of, item[0]),
    )
    for index, decision in indexed_decisions:
        reasons: list[str] = []
        for variant in selected:
            result = evaluate_variant(decision, variant)
            if not result.accepted and result.reason not in reasons:
                reasons.append(str(result.reason))
        if (
            VariantName.H3_POST_LOSS_CLUSTER in selected
            and last_loss_closed_at is not None
            and decision.as_of < last_loss_closed_at + timedelta(minutes=5)
        ):
            reasons.append("SHADOW_POST_LOSS_CLUSTER")

        trade = trades.get(index)
        accepted = not reasons
        filled = bool(accepted and trade is not None and trade.filled)
        profit = trade.profit if filled else None
        rows.append(
            ScreeningRow(
                session_id=session.session_id,
                decision_index=index,
                accepted=accepted,
                filled=filled,
                profit=profit,
                reasons=tuple(reasons),
            )
        )
        if filled and profit is not None and profit < 0:
            last_loss_closed_at = trade.closed_at
    return tuple(rows)
