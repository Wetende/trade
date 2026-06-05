"""MT5 execution service for local order proposals."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
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

    def _sync_tracked_ticket(self, ticket: int) -> dict[str, Any] | None:
        """Clear stale local state when MT5 no longer has the pending ticket."""
        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        open_order_tickets = {
            int(order["ticket"]) for order in orders if order.get("ticket")
        }
        open_position_tickets = {
            int(position["ticket"]) for position in positions if position.get("ticket")
        }

        if ticket in open_order_tickets:
            return None
        if ticket in open_position_tickets:
            self.state.clear_pending_order()
            result = {
                "status": "ORDER_ALREADY_FILLED",
                "ticket": ticket,
                "symbol": self.config.symbol,
            }
            self.journal.append("ORDER_STATE_SYNCED", result)
            return result

        self.state.clear_pending_order()
        result = {
            "status": "ORDER_NOT_OPEN",
            "ticket": ticket,
            "symbol": self.config.symbol,
        }
        self.journal.append("ORDER_STATE_SYNCED", result)
        return result

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
        ticket = int(ticket)
        sync_result = self._sync_tracked_ticket(ticket)
        if sync_result is not None:
            return sync_result

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

    def reconcile_trade_history(
        self,
        *,
        lookback_hours: int = 24,
        since_utc: datetime | str | None = None,
        now_utc: datetime | None = None,
    ) -> dict[str, Any]:
        """Summarize recently filled and closed MT5 deals for this bot."""
        self.broker.connect()
        current = now_utc or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        if since_utc is None:
            start = current - timedelta(hours=int(lookback_hours))
        elif isinstance(since_utc, str):
            start = datetime.fromisoformat(since_utc)
        else:
            start = since_utc
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        start = start.astimezone(timezone.utc)
        deals = self.broker.history_deals(self.config.symbol, start, current)
        result = self._summarize_trade_history(deals, start, current)
        self.journal.append("TRADE_HISTORY_RECONCILED", result)
        return result

    def _summarize_trade_history(
        self,
        deals: list[dict[str, Any]],
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[str, Any]:
        bot_position_ids = {
            self._deal_position_id(deal)
            for deal in deals
            if self._is_bot_entry_deal(deal)
        }
        bot_position_ids.discard(None)

        grouped: dict[int, list[dict[str, Any]]] = {}
        for deal in deals:
            position_id = self._deal_position_id(deal)
            if position_id in bot_position_ids:
                grouped.setdefault(position_id, []).append(deal)

        filled_trades = []
        closed_trades = []
        for position_id, position_deals in grouped.items():
            ordered = sorted(position_deals, key=self._deal_sort_key)
            entry_deal = next(
                (deal for deal in ordered if self._is_entry_deal(deal)),
                ordered[0],
            )
            exit_deals = [deal for deal in ordered if self._is_exit_deal(deal)]
            filled_trades.append(self._trade_fill_summary(position_id, entry_deal))
            if exit_deals:
                closed_trades.append(
                    self._closed_trade_summary(position_id, entry_deal, exit_deals)
                )

        net_profit = round(
            sum(float(trade.get("profit") or 0.0) for trade in closed_trades),
            2,
        )
        wins = sum(1 for trade in closed_trades if float(trade["profit"]) > 0)
        losses = sum(1 for trade in closed_trades if float(trade["profit"]) < 0)
        break_even = len(closed_trades) - wins - losses

        return {
            "status": "RECONCILED",
            "symbol": self.config.symbol,
            "lookback_start_utc": start_utc.isoformat(),
            "lookback_end_utc": end_utc.isoformat(),
            "deal_count": len(deals),
            "filled_trade_count": len(filled_trades),
            "closed_trade_count": len(closed_trades),
            "wins": wins,
            "losses": losses,
            "break_even": break_even,
            "net_profit": net_profit,
            "filled_trades": filled_trades,
            "closed_trades": closed_trades,
            "latest_closed_trade": closed_trades[-1] if closed_trades else {},
        }

    def _is_bot_entry_deal(self, deal: dict[str, Any]) -> bool:
        if not self._is_entry_deal(deal):
            return False
        if self._deal_int(deal.get("magic")) == int(self.config.magic):
            return True
        comment = str(deal.get("comment") or "")
        return bool(self.config.order_comment and self.config.order_comment in comment)

    @staticmethod
    def _deal_position_id(deal: dict[str, Any]) -> int | None:
        value = deal.get("position_id") or deal.get("position") or deal.get("order")
        try:
            position_id = int(value)
        except (TypeError, ValueError):
            return None
        return position_id if position_id > 0 else None

    @staticmethod
    def _deal_int(value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _deal_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _is_entry_deal(cls, deal: dict[str, Any]) -> bool:
        value = str(deal.get("entry", "")).upper()
        return value in {"0", "IN", "DEAL_ENTRY_IN"}

    @classmethod
    def _is_exit_deal(cls, deal: dict[str, Any]) -> bool:
        value = str(deal.get("entry", "")).upper()
        return value in {"1", "OUT", "DEAL_ENTRY_OUT"}

    @classmethod
    def _deal_sort_key(cls, deal: dict[str, Any]) -> tuple[int, int]:
        return (
            cls._deal_int(deal.get("time")) or 0,
            cls._deal_int(deal.get("ticket")) or 0,
        )

    @classmethod
    def _deal_time_utc(cls, deal: dict[str, Any]) -> str | None:
        normalized = deal.get("time_utc")
        if normalized:
            return str(normalized)
        timestamp = cls._deal_int(deal.get("time"))
        if timestamp is None:
            return None
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()

    @classmethod
    def _deal_side(cls, deal: dict[str, Any]) -> str | None:
        value = str(deal.get("type", "")).upper()
        if value in {"0", "BUY", "DEAL_TYPE_BUY"}:
            return "BUY"
        if value in {"1", "SELL", "DEAL_TYPE_SELL"}:
            return "SELL"
        return None

    def _trade_fill_summary(
        self,
        position_id: int,
        entry_deal: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "position_id": position_id,
            "entry_deal_ticket": self._deal_int(entry_deal.get("ticket")),
            "entry_order": self._deal_int(entry_deal.get("order")),
            "side": self._deal_side(entry_deal),
            "volume": self._deal_float(entry_deal.get("volume")),
            "entry_price": self._deal_float(entry_deal.get("price")),
            "opened_at_utc": self._deal_time_utc(entry_deal),
        }

    def _closed_trade_summary(
        self,
        position_id: int,
        entry_deal: dict[str, Any],
        exit_deals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        last_exit = sorted(exit_deals, key=self._deal_sort_key)[-1]
        all_deals = [entry_deal, *exit_deals]
        profit = round(
            sum(
                self._deal_float(deal.get("profit"))
                + self._deal_float(deal.get("commission"))
                + self._deal_float(deal.get("swap"))
                for deal in all_deals
            ),
            2,
        )
        return {
            **self._trade_fill_summary(position_id, entry_deal),
            "exit_deal_ticket": self._deal_int(last_exit.get("ticket")),
            "exit_order": self._deal_int(last_exit.get("order")),
            "exit_price": self._deal_float(last_exit.get("price")),
            "closed_at_utc": self._deal_time_utc(last_exit),
            "profit": profit,
            "outcome": self._deal_outcome(last_exit, profit),
            "exit_comment": last_exit.get("comment"),
        }

    @staticmethod
    def _deal_outcome(exit_deal: dict[str, Any], profit: float) -> str:
        comment = str(exit_deal.get("comment") or "").lower()
        if "[tp" in comment or "tp " in comment:
            return "TP"
        if "[sl" in comment or "sl " in comment:
            return "SL"
        if profit > 0:
            return "PROFIT"
        if profit < 0:
            return "LOSS"
        return "BREAK_EVEN"

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
