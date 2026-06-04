"""MT5 executor for two-leg straddle breakout pairs."""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.straddle_breakout import (
    StraddleBreakoutConfig,
    StraddlePairProposal,
    build_straddle_breakout_pair,
)
from tradingagents.brokers.execution_journal import ExecutionJournal
from tradingagents.brokers.mt5 import MT5Broker, MT5ConnectionConfig, MT5OrderRequestBuilder
from tradingagents.brokers.straddle_state import StraddleStateStore


class MT5StraddleExecutor:
    """Build, dry-run, and place isolated MT5 straddle pending-order pairs."""

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
        self.state = StraddleStateStore(results_dir, config.symbol)
        self.heartbeat_path = self.state.directory / "mt5_straddle_heartbeat.json"

    def build_pair(self, straddle_config: StraddleBreakoutConfig) -> StraddlePairProposal:
        connection = self.broker.connect()
        self.journal.append("STRADDLE_CONNECTED", connection)
        candles = self.broker.fetch_rates(
            straddle_config.timeframe,
            straddle_config.lookback_candles + 1,
        )
        closed_candles = _closed_candles(candles, straddle_config.lookback_candles)
        pair = build_straddle_breakout_pair(
            closed_candles,
            connection["symbol"],
            straddle_config,
        )
        self.journal.append("STRADDLE_PAIR_BUILT", pair.model_dump(mode="json"))
        return pair

    def watch_once(
        self,
        straddle_config: StraddleBreakoutConfig,
        *,
        live: bool = False,
        now_utc: datetime | str | None = None,
    ) -> dict[str, Any]:
        """Advance the straddle watch state once.

        If an active pair is already open, reconcile it first. Otherwise build
        and optionally place a new pair from the latest closed candles.
        """

        monitor_result = self.monitor_pair(now_utc=now_utc)
        if monitor_result.get("status") != "NO_ACTIVE_PAIR":
            return monitor_result

        pair = self.build_pair(straddle_config)
        return self.execute_pair(pair, live=live)

    def watch_forever(
        self,
        straddle_config: StraddleBreakoutConfig,
        *,
        live: bool = False,
        poll_seconds: int = 30,
        max_cycles: int = 0,
        max_runtime_seconds: int = 0,
    ) -> dict[str, Any]:
        """Continuously watch the market and place a straddle when ready."""

        cycles = 0
        last_result: dict[str, Any] = {"status": "NOT_STARTED"}
        deadline = (
            time.monotonic() + int(max_runtime_seconds)
            if int(max_runtime_seconds) > 0
            else None
        )
        while True:
            cycles += 1
            try:
                cycle_result = self.watch_once(straddle_config, live=live)
            except Exception as exc:
                cycle_result = {
                    "status": "STRADDLE_WATCH_ERROR",
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                self.journal.append("STRADDLE_WATCH_ERROR", cycle_result)
            last_result = self._write_heartbeat(
                cycle_result,
                cycle=cycles,
                live=live,
            )
            if deadline is not None and time.monotonic() >= deadline:
                return {
                    "status": "STOPPED_MAX_RUNTIME_SECONDS",
                    "last_result": last_result,
                }
            if max_cycles and cycles >= int(max_cycles):
                return {"status": "STOPPED_MAX_CYCLES", "last_result": last_result}
            if poll_seconds > 0:
                time.sleep(int(poll_seconds))

    def _write_heartbeat(
        self,
        result: dict[str, Any],
        *,
        cycle: int,
        live: bool,
    ) -> dict[str, Any]:
        payload = {
            **result,
            "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
            "heartbeat_path": str(self.heartbeat_path),
            "symbol": self.config.symbol,
            "cycle": int(cycle),
            "live": bool(live),
        }
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        self.journal.append("STRADDLE_WATCH_HEARTBEAT", payload)
        return payload

    def execute_pair(
        self,
        pair: StraddlePairProposal,
        *,
        live: bool = False,
    ) -> dict[str, Any]:
        connection = self.broker.connect()
        self.journal.append("STRADDLE_CONNECTED", connection)

        if pair.status != "PROPOSED" or pair.buy_stop is None or pair.sell_stop is None:
            result = {
                "status": "STRADDLE_NO_TRADE",
                "reason": pair.reason,
                "pair": pair.model_dump(mode="json"),
            }
            self.journal.append("STRADDLE_NO_TRADE", result)
            return result

        if self._active_trade_exists():
            result = {"status": "SKIPPED_ACTIVE_TRADE", "symbol": self.config.symbol}
            self.journal.append("STRADDLE_SKIPPED_ACTIVE_TRADE", result)
            return result

        try:
            requests = [
                self._request_for(pair.buy_stop, connection["symbol"]),
                self._request_for(pair.sell_stop, connection["symbol"]),
            ]
        except ValueError as exc:
            result = {
                "status": "STRADDLE_SKIPPED_INVALID_ENTRY",
                "error": str(exc),
                "pair": pair.model_dump(mode="json"),
            }
            self.journal.append("STRADDLE_ORDER_SKIPPED", result)
            return result
        self.journal.append("STRADDLE_REQUESTS_BUILT", {"requests": requests})

        if not live:
            self.state.record_pair(pair, dry_run=True, requests=requests)
            result = {
                "status": "DRY_RUN_PAIR_READY",
                "symbol": self.config.symbol,
                "requests": requests,
                "pair": pair.model_dump(mode="json"),
            }
            self.journal.append("STRADDLE_PAIR_DRY_RUN", result)
            return result

        buy_result = self.broker.place_pending_order(requests[0])
        if not buy_result.get("ok"):
            result = {
                "status": "PAIR_REJECTED",
                "buy_result": buy_result,
                "sell_result": None,
                "requests": requests,
            }
            self.journal.append("STRADDLE_PAIR_REJECTED", result)
            return result

        sell_result = self.broker.place_pending_order(requests[1])
        if not sell_result.get("ok"):
            buy_ticket = buy_result.get("order")
            rollback = None
            if buy_ticket is not None:
                rollback = self.broker.cancel_order(int(buy_ticket))
            self.state.clear_pair()
            result = {
                "status": "PAIR_REJECTED_ROLLBACK",
                "buy_result": buy_result,
                "sell_result": sell_result,
                "rollback": rollback,
                "requests": requests,
            }
            self.journal.append("STRADDLE_PAIR_REJECTED_ROLLBACK", result)
            return result

        self.state.record_pair(
            pair,
            dry_run=False,
            buy_ticket=int(buy_result["order"]),
            sell_ticket=int(sell_result["order"]),
            requests=requests,
        )
        result = {
            "status": "PAIR_PLACED",
            "buy_result": buy_result,
            "sell_result": sell_result,
            "requests": requests,
            "pair": pair.model_dump(mode="json"),
        }
        self.journal.append("STRADDLE_PAIR_PLACED", result)
        return result

    def monitor_pair(self, now_utc: datetime | str | None = None) -> dict[str, Any]:
        """Clear dry-run state or cancel live pending legs after expiry."""

        self.broker.connect()
        state = self.state.load()
        active = state.get("active_pair")
        if not active:
            result = {"status": "NO_ACTIVE_PAIR", "symbol": self.config.symbol}
            self.journal.append("STRADDLE_MONITOR_SKIPPED", result)
            return result

        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        open_order_tickets = {
            int(order["ticket"])
            for order in orders
            if order.get("ticket") is not None
        }
        open_position_tickets = {
            int(position["ticket"])
            for position in positions
            if position.get("ticket") is not None
        }
        tracked_tickets = {
            int(ticket)
            for ticket in (active.get("buy_ticket"), active.get("sell_ticket"))
            if ticket is not None
        }
        cancel_after_raw = active.get("cancel_after_utc")
        current = _utc_datetime(now_utc)
        cancel_after = _utc_datetime(cancel_after_raw) if cancel_after_raw else current

        if positions:
            cancelled = []
            for ticket in sorted(tracked_tickets & open_order_tickets):
                cancelled.append(self.broker.cancel_order(int(ticket)))
            self.state.clear_pair()
            result = {
                "status": "PAIR_RESOLVED",
                "symbol": self.config.symbol,
                "open_positions": positions,
                "results": cancelled,
            }
            self.journal.append("STRADDLE_PAIR_RESOLVED", result)
            return result

        if cancel_after_raw and current >= cancel_after:
            cancelled = []
            for ticket in sorted(tracked_tickets & open_order_tickets):
                cancelled.append(self.broker.cancel_order(int(ticket)))
            if active.get("dry_run"):
                self.state.clear_pair()
                result = {
                    "status": "DRY_RUN_PAIR_EXPIRED",
                    "symbol": self.config.symbol,
                    "results": cancelled,
                }
            else:
                if cancelled or not open_order_tickets:
                    self.state.clear_pair()
                result = {
                    "status": "PAIR_CANCELLED",
                    "symbol": self.config.symbol,
                    "results": cancelled,
                }
            self.journal.append("STRADDLE_PAIR_CANCELLED", result)
            return result

        if open_order_tickets & tracked_tickets:
            result = {
                "status": "PAIR_STILL_ACTIVE",
                "cancel_after_utc": cancel_after.isoformat(),
            }
            self.journal.append("STRADDLE_MONITOR_SKIPPED", result)
            return result

        self.state.clear_pair()
        result = {
            "status": "PAIR_RESOLVED",
            "symbol": self.config.symbol,
            "results": [],
        }
        self.journal.append("STRADDLE_PAIR_RESOLVED", result)
        return result

    def _active_trade_exists(self) -> bool:
        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        return bool(orders or positions)

    def _request_for(
        self,
        proposal,
        symbol_info: dict[str, Any],
    ) -> dict[str, Any]:
        request = self.builder.build_pending_order_request(proposal, symbol_info)
        if proposal.setup_name:
            request["comment"] = proposal.setup_name
        return request


def _utc_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        current = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        current = value
    else:
        current = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _closed_candles(
    candles: list[dict[str, Any]],
    lookback_candles: int,
) -> list[dict[str, Any]]:
    ordered = sorted(candles, key=lambda candle: str(candle.get("timestamp") or ""))
    if len(ordered) > lookback_candles:
        ordered = ordered[:-1]
    return ordered[-lookback_candles:]
