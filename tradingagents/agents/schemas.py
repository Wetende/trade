"""Structured outputs for the price-action playbook pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, model_validator


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
    """Local execution artifact for a proposed broker order."""

    symbol: str
    broker_symbol: Optional[str] = None
    side: TradeAction
    order_type: str = "LIMIT"
    setup_name: Optional[str] = None
    setup_grade: Optional[str] = None
    strategy_type: Optional[str] = None
    entry_price: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    volume: Optional[float] = None
    volume_multiplier: Optional[float] = None
    position_lifecycle: Optional[str] = None
    break_even_trigger_points: Optional[float] = None
    break_even_lock_points: Optional[float] = None
    trailing_trigger_points: Optional[float] = None
    trailing_distance_points: Optional[float] = None
    partial_first_trigger_points: Optional[float] = None
    partial_first_target_volume: Optional[float] = None
    partial_second_trigger_points: Optional[float] = None
    partial_second_target_volume: Optional[float] = None
    timeframe: str = "15m"
    confirmation_timeframe: str = "30m"
    valid_until: str
    activation_window_minutes: Optional[int] = None
    cancel_if_not_triggered_after: Optional[str] = None
    status: OrderStatus
    reason: str

    @model_validator(mode="after")
    def default_broker_symbol(self) -> "OrderProposal":
        if self.broker_symbol is None:
            self.broker_symbol = self.symbol
        for field_name in ("volume", "volume_multiplier"):
            value = getattr(self, field_name)
            if value is not None and value <= 0:
                raise ValueError(f"{field_name} must be positive when provided")
        for field_name in (
            "break_even_trigger_points",
            "break_even_lock_points",
            "trailing_trigger_points",
            "trailing_distance_points",
            "partial_first_trigger_points",
            "partial_first_target_volume",
            "partial_second_trigger_points",
            "partial_second_target_volume",
        ):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                raise ValueError(f"{field_name} must be non-negative when provided")
        return self


def render_order_proposal(proposal: OrderProposal) -> str:
    """Render an OrderProposal to markdown."""
    parts = [
        f"**Status**: {proposal.status.value}",
        "",
        f"**Symbol**: {proposal.symbol}",
        "",
        f"**Broker Symbol**: {proposal.broker_symbol}",
        "",
        f"**Side**: {proposal.side.value}",
        "",
        f"**Order Type**: {proposal.order_type}",
    ]
    if proposal.setup_name:
        parts.extend(["", f"**Setup Name**: {proposal.setup_name}"])
    if proposal.setup_grade:
        parts.extend(["", f"**Setup Grade**: {proposal.setup_grade}"])
    if proposal.strategy_type:
        parts.extend(["", f"**Strategy Type**: {proposal.strategy_type}"])
    secondary_timeframe_label = (
        "Scalper Memory"
        if str(proposal.timeframe).strip().lower() == "1m"
        else "Confirmation Timeframe"
    )
    parts.extend(
        [
            "",
            f"**Timeframe**: {proposal.timeframe}",
            "",
            f"**{secondary_timeframe_label}**: {proposal.confirmation_timeframe}",
            "",
            f"**Valid Until**: {proposal.valid_until}",
            "",
            f"**Reason**: {proposal.reason}",
        ]
    )
    if proposal.entry_price is not None:
        parts.extend(["", f"**Entry Price**: {proposal.entry_price}"])
    if proposal.stop_loss is not None:
        parts.extend(["", f"**Stop Loss**: {proposal.stop_loss}"])
    if proposal.take_profit is not None:
        parts.extend(["", f"**Take Profit**: {proposal.take_profit}"])
    if proposal.volume is not None:
        parts.extend(["", f"**Volume**: {proposal.volume}"])
    if proposal.volume_multiplier is not None:
        parts.extend(["", f"**Volume Multiplier**: {proposal.volume_multiplier}"])
    if proposal.position_lifecycle:
        parts.extend(["", f"**Position Lifecycle**: {proposal.position_lifecycle}"])
    for label, value in (
        ("Break Even Trigger Points", proposal.break_even_trigger_points),
        ("Break Even Lock Points", proposal.break_even_lock_points),
        ("Trailing Trigger Points", proposal.trailing_trigger_points),
        ("Trailing Distance Points", proposal.trailing_distance_points),
        ("Partial First Trigger Points", proposal.partial_first_trigger_points),
        ("Partial First Target Volume", proposal.partial_first_target_volume),
        ("Partial Second Trigger Points", proposal.partial_second_trigger_points),
        ("Partial Second Target Volume", proposal.partial_second_target_volume),
    ):
        if value is not None:
            parts.extend(["", f"**{label}**: {value}"])
    if proposal.activation_window_minutes is not None:
        parts.extend(
            [
                "",
                f"**Activation Window Minutes**: {proposal.activation_window_minutes}",
            ]
        )
    if proposal.cancel_if_not_triggered_after is not None:
        parts.extend(
            [
                "",
                f"**Cancel If Not Triggered After**: {proposal.cancel_if_not_triggered_after}",
            ]
        )
    return "\n".join(parts)
