"""Local order proposal writer.

This node deliberately does not place live orders. It creates a local JSON
artifact that a human or future broker adapter can inspect.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas import (
    OrderProposal,
    OrderStatus,
    TradeAction,
    render_order_proposal,
)
from tradingagents.agents.utils.action_parsing import parse_trade_action
from tradingagents.dataflows.utils import safe_ticker_component


_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(?P<label>[A-Za-z][A-Za-z0-9 /_-]*?)(?:\*\*)?"
    r"\s*:\s*(?P<value>.+?)\s*$"
)


def _field(markdown: str, label: str) -> Optional[str]:
    label_lower = label.lower()
    for line in markdown.splitlines():
        match = _LABEL_RE.search(line.strip())
        if not match:
            continue
        if match.group("label").strip().lower() == label_lower:
            return match.group("value").strip()
    return None


def _float_field(markdown: str, label: str) -> Optional[float]:
    raw = _field(markdown, label)
    if raw is None:
        return None
    try:
        return float(raw.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _parse_action(markdown: str) -> TradeAction:
    return TradeAction(parse_trade_action(markdown))


def _timeframe_minutes(timeframe: str) -> int:
    match = re.fullmatch(r"(\d+)\s*m", timeframe.strip().lower())
    if not match:
        return 15
    return int(match.group(1))


def _valid_until(as_of: str, timeframe: str, market_timezone: str) -> str:
    minutes = _timeframe_minutes(timeframe)
    return _minutes_after(as_of, minutes, market_timezone)


def _minutes_after(as_of: str, minutes: int, market_timezone: str) -> str:
    try:
        tz = ZoneInfo(market_timezone)
        parsed = datetime.fromisoformat(as_of.replace(" ", "T"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        else:
            parsed = parsed.astimezone(tz)
        return (parsed + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return as_of


def build_order_proposal(state: dict) -> OrderProposal:
    trade_plan = state.get("trade_plan", "")
    action = _parse_action(trade_plan)
    entry = _float_field(trade_plan, "Entry Price")
    stop = _float_field(trade_plan, "Stop Loss")
    target = _float_field(trade_plan, "Take Profit")
    reason = _field(trade_plan, "Reason") or "No trader reason supplied."

    has_required_levels = entry is not None and stop is not None and target is not None
    status = (
        OrderStatus.PROPOSED
        if action in {TradeAction.BUY, TradeAction.SELL} and has_required_levels
        else OrderStatus.NO_TRADE
    )

    if action in {TradeAction.BUY, TradeAction.SELL} and not has_required_levels:
        reason = "No order proposed because the trade plan is missing entry, stop, or target."

    as_of = state.get("as_of", "")
    market_timezone = state.get("market_timezone", "America/New_York")
    activation_window_minutes = 10 if status == OrderStatus.PROPOSED else None

    return OrderProposal(
        symbol=state["company_of_interest"],
        side=action,
        order_type="LIMIT",
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        timeframe=state.get("timeframe", "15m"),
        confirmation_timeframe=state.get("confirmation_timeframe", "30m"),
        valid_until=_valid_until(
            as_of,
            state.get("timeframe", "15m"),
            market_timezone,
        ),
        activation_window_minutes=activation_window_minutes,
        cancel_if_not_triggered_after=(
            _minutes_after(as_of, activation_window_minutes, market_timezone)
            if activation_window_minutes is not None
            else None
        ),
        status=status,
        reason=reason,
    )


def create_order_proposal_executor(config: dict):
    def order_proposal_node(state):
        proposal = build_order_proposal(state)
        rendered = render_order_proposal(proposal)

        safe_symbol = safe_ticker_component(state["company_of_interest"])
        safe_as_of = re.sub(r"[^0-9A-Za-z_-]+", "_", state.get("as_of", "unknown")).strip("_")
        proposal_dir = Path(config["results_dir"]) / safe_symbol / "order_proposals"
        proposal_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = proposal_dir / f"order_proposal_{safe_as_of}.json"
        proposal_path.write_text(
            json.dumps(proposal.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        return {
            "order_proposal": rendered,
            "order_proposal_path": str(proposal_path),
            "sender": "Order Proposal",
        }

    return order_proposal_node
