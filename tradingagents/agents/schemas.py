"""Structured outputs for the price-action playbook pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TradeAction(str, Enum):
    """Directional trade decision emitted by the Trader."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class OrderStatus(str, Enum):
    """Local order proposal state. No live broker action is taken."""

    PROPOSED = "PROPOSED"
    NO_TRADE = "NO_TRADE"


class TradePlan(BaseModel):
    """Trader output for the price-action playbook."""

    action: TradeAction = Field(
        description="Exactly one of BUY, SELL, or HOLD.",
    )
    setup_name: str = Field(
        description=(
            "The playbook setup driving the decision, such as The Breakout, "
            "S/R Bounce, Break and Retest, Impulse, or No Valid Setup."
        ),
    )
    confidence: str = Field(
        description="A plain-language confidence level, e.g. High, Medium, Low, or None.",
    )
    checklist_status: str = Field(
        description="Concise status of the A+ setup checklist and any failed rule.",
    )
    reason: str = Field(
        description="Two to four sentences explaining the price-action decision.",
    )
    entry_price: Optional[float] = Field(
        default=None,
        description="Proposed limit entry price. Null for HOLD.",
    )
    stop_loss: Optional[float] = Field(
        default=None,
        description="Protective stop loss price. Null for HOLD.",
    )
    take_profit: Optional[float] = Field(
        default=None,
        description="Primary take-profit price. Null for HOLD.",
    )


def render_trade_plan(plan: TradePlan) -> str:
    """Render a TradePlan to stable markdown for reports and parsing."""
    parts = [
        f"**Action**: {plan.action.value}",
        "",
        f"**Setup**: {plan.setup_name}",
        "",
        f"**Confidence**: {plan.confidence}",
        "",
        f"**Checklist Status**: {plan.checklist_status}",
        "",
        f"**Reason**: {plan.reason}",
    ]
    if plan.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {plan.entry_price}"])
    if plan.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {plan.stop_loss}"])
    if plan.take_profit is not None:
        parts.extend(["", f"**Take Profit**: {plan.take_profit}"])
    return "\n".join(parts)


class OrderProposal(BaseModel):
    """Local execution artifact for a proposed limit order."""

    symbol: str
    side: TradeAction
    order_type: str = "LIMIT"
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    timeframe: str = "15m"
    confirmation_timeframe: str = "30m"
    valid_until: str
    status: OrderStatus
    reason: str


def render_order_proposal(proposal: OrderProposal) -> str:
    """Render an OrderProposal to markdown."""
    parts = [
        f"**Status**: {proposal.status.value}",
        "",
        f"**Symbol**: {proposal.symbol}",
        "",
        f"**Side**: {proposal.side.value}",
        "",
        f"**Order Type**: {proposal.order_type}",
        "",
        f"**Timeframe**: {proposal.timeframe}",
        "",
        f"**Confirmation Timeframe**: {proposal.confirmation_timeframe}",
        "",
        f"**Valid Until**: {proposal.valid_until}",
        "",
        f"**Reason**: {proposal.reason}",
    ]
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.take_profit is not None:
        parts.extend(["", f"**Take Profit**: {proposal.take_profit}"])
    return "\n".join(parts)
