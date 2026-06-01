"""MT5 execution service for local order proposals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.price_action.lifecycle import move_stop_to_break_even
from tradingagents.agents.schemas import OrderProposal
from tradingagents.brokers.execution_journal import ExecutionJournal
from tradingagents.brokers.execution_state import ExecutionStateStore
from tradingagents.brokers.mt5 import (
    MT5Broker,
    MT5ConnectionConfig,
    MT5OrderRequestBuilder,
)


def load_order_proposal(path: str | Path) -> OrderProposal:
    """Load an order proposal JSON artifact from disk."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return OrderProposal.model_validate(data)


class MT5Executor:
    """Coordinate one-symbol guarded MT5 proposal execution."""

    def __init__(
        self,
        config: MT5ConnectionConfig,
        results_dir: str | Path,
        broker: Any | None = None,
        journal: ExecutionJournal | None = None,
    ) -> None:
        self.config = config
        self.broker = broker or MT5Broker(config)
        self.builder = MT5OrderRequestBuilder(config)
        self.journal = journal or ExecutionJournal(results_dir, config.symbol)
        self.state = ExecutionStateStore(results_dir, config.symbol)

    def _active_trade_exists(self) -> bool:
        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        return bool(orders or positions)

    def execute_proposal(self, proposal: OrderProposal) -> dict[str, Any]:
        """Place a pending order when no active trade exists."""
        connection = self.broker.connect()
        self.journal.append("CONNECTED", connection)

        if self._active_trade_exists():
            result = {
                "status": "SKIPPED_ACTIVE_TRADE",
                "symbol": self.config.symbol,
            }
            self.journal.append("SKIPPED_ACTIVE_TRADE", result)
            return result

        try:
            request = self.builder.build_pending_order_request(
                proposal,
                connection["symbol"],
            )
        except ValueError as exc:
            result = {
                "status": "SKIPPED_INVALID_ENTRY",
                "reason": "ENTRY_PRICE_STALE_OR_INVALID",
                "error": str(exc),
                "proposal": proposal.model_dump(mode="json"),
            }
            self.journal.append("ORDER_SKIPPED", result)
            return result
        self.journal.append("ORDER_REQUEST_BUILT", request)

        broker_result = self.broker.place_pending_order(request)
        ok = bool(broker_result.get("ok"))
        event_type = "ORDER_PLACED" if ok else "ORDER_REJECTED"
        self.journal.append(event_type, broker_result)
        if ok:
            self.state.record_pending_order(broker_result["order"], proposal)

        return {
            "status": "PLACED" if ok else "REJECTED",
            "order": broker_result.get("order"),
            "broker_result": broker_result,
        }

    def cancel_stale_pending_orders(
        self,
        now_utc: str | None = None,
    ) -> dict[str, Any]:
        """Cancel the tracked pending order after its activation window expires."""
        self.broker.connect()
        state = self.state.load()
        ticket = state.get("active_order_ticket")
        if ticket is None:
            result = {"status": "NO_ACTIVE_ORDER", "symbol": self.config.symbol}
            self.journal.append("ORDER_CANCEL_SKIPPED", result)
            return result

        current = (
            datetime.fromisoformat(now_utc)
            if now_utc
            else datetime.now(timezone.utc)
        )
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        cancel_after = datetime.fromisoformat(state["cancel_after_utc"])
        if cancel_after.tzinfo is None:
            cancel_after = cancel_after.replace(tzinfo=timezone.utc)
        cancel_after = cancel_after.astimezone(timezone.utc)
        if current < cancel_after:
            result = {
                "status": "ORDER_STILL_ACTIVE",
                "ticket": ticket,
                "cancel_after_utc": cancel_after.isoformat(),
            }
            self.journal.append("ORDER_CANCEL_SKIPPED", result)
            return result

        broker_result = self.broker.cancel_order(ticket)
        ok = bool(broker_result.get("ok"))
        if ok:
            self.state.clear_pending_order()
        result = {
            "status": "CANCELLED" if ok else "CANCEL_FAILED",
            "ticket": ticket,
            "result": broker_result,
        }
        self.journal.append("ORDER_CANCELLED" if ok else "ORDER_CANCEL_FAILED", result)
        return result

    def manage_open_positions(
        self,
        break_even_threshold_pips: float = 20.0,
    ) -> dict[str, Any]:
        """Move stops to break-even when open positions meet playbook rules."""
        self.broker.connect()
        positions = self.broker.open_positions(self.config.symbol)
        actions = []
        for position in positions:
            managed = move_stop_to_break_even(position, break_even_threshold_pips)
            if managed.get("management_action") != "MOVE_TO_BREAK_EVEN":
                continue
            ticket = int(position["ticket"])
            stop_loss = float(managed["stop_loss"])
            take_profit = float(position["take_profit"])
            result = self.broker.modify_position_stops(
                ticket,
                stop_loss,
                take_profit,
            )
            action_name = "MOVE_TO_BREAK_EVEN"
            event_type = "POSITION_STOP_MOVED"
            action = {
                "ticket": position["ticket"],
                "action": action_name,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "result": result,
            }
            actions.append(action)
            self.journal.append(event_type, action)

        return {
            "status": "MANAGED" if actions else "NO_POSITION_ACTION",
            "actions": actions,
        }

    def snapshot_state(self) -> dict[str, Any]:
        """Read current broker orders and positions without placing orders."""
        connection = self.broker.connect()
        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        state = {
            "connection": connection,
            "orders": orders,
            "positions": positions,
        }
        self.journal.append("STATE_SNAPSHOT", state)
        return state
