"""MT5 executor for two-leg straddle breakout pairs."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
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


@dataclass(frozen=True)
class StraddleExitManagementConfig:
    """Deterministic trade management for active straddle positions."""

    enabled: bool = True
    break_even_trigger_points: float = 3.0
    break_even_lock_points: float = 0.30
    trailing_trigger_points: float = 5.0
    trailing_distance_points: float = 2.0
    min_stop_update_points: float = 0.50
    early_loss_exit_points: float = 4.0
    scalp_profit_points: float = 0.0

    def __post_init__(self) -> None:
        for name in (
            "break_even_trigger_points",
            "break_even_lock_points",
            "trailing_trigger_points",
            "trailing_distance_points",
            "min_stop_update_points",
            "early_loss_exit_points",
            "scalp_profit_points",
        ):
            value = _nonnegative_float(getattr(self, name), name)
            object.__setattr__(self, name, value)


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
        exit_management: StraddleExitManagementConfig | None = None,
    ) -> dict[str, Any]:
        """Advance the straddle watch state once.

        If an active pair is already open, reconcile it first. Otherwise build
        and optionally place a new pair from the latest closed candles.
        """

        monitor_result = self.monitor_pair(now_utc=now_utc)
        if (
            monitor_result.get("status") != "NO_ACTIVE_PAIR"
            and not monitor_result.get("open_positions")
        ):
            return monitor_result

        management = exit_management or StraddleExitManagementConfig()
        if live and management.enabled:
            management_result = self.manage_open_positions(management)
            if management_result.get("status") != "NO_OPEN_POSITION":
                if (
                    monitor_result.get("status") != "NO_ACTIVE_PAIR"
                    and management_result.get("status") == "POSITION_MONITORED"
                ):
                    return monitor_result
                return management_result

        if self._active_trade_exists():
            result = {"status": "SKIPPED_ACTIVE_TRADE", "symbol": self.config.symbol}
            self.journal.append("STRADDLE_SKIPPED_ACTIVE_TRADE", result)
            return result

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
        exit_management: StraddleExitManagementConfig | None = None,
    ) -> dict[str, Any]:
        """Continuously watch the market and place a straddle when ready."""

        cycles = 0
        last_result: dict[str, Any] = {"status": "NOT_STARTED"}
        management = exit_management or StraddleExitManagementConfig()
        deadline = (
            time.monotonic() + int(max_runtime_seconds)
            if int(max_runtime_seconds) > 0
            else None
        )
        while True:
            cycles += 1
            try:
                cycle_result = self.watch_once(
                    straddle_config,
                    live=live,
                    exit_management=management,
                )
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

    def manage_open_positions(
        self,
        exit_management: StraddleExitManagementConfig | None = None,
    ) -> dict[str, Any]:
        """Move stops or close active straddle positions before placing new pairs."""

        management = exit_management or StraddleExitManagementConfig()
        connection = self.broker.connect()
        self.journal.append("STRADDLE_CONNECTED", connection)
        positions = self.broker.open_positions(self.config.symbol)
        if not positions:
            result = {"status": "NO_OPEN_POSITION", "symbol": self.config.symbol}
            self.journal.append("STRADDLE_POSITION_MONITOR_SKIPPED", result)
            return result

        symbol_info = connection["symbol"]
        actions = []
        closed = False
        closed_scalp = False
        moved = False
        for position in positions:
            action = self._manage_position(position, symbol_info, management)
            if action:
                actions.append(action)
                closed = closed or action.get("action") == "CLOSE_POSITION"
                closed_scalp = closed_scalp or (
                    action.get("reason") == "SCALP_PROFIT_EXIT"
                )
                moved = moved or action.get("action") == "MODIFY_STOP"

        if closed_scalp:
            status = "POSITION_CLOSED_SCALP"
        elif closed:
            status = "POSITION_CLOSED_EARLY"
        elif moved:
            status = "POSITION_STOP_MOVED"
        else:
            status = "POSITION_MONITORED"
        result = {
            "status": status,
            "symbol": self.config.symbol,
            "open_positions": positions,
            "actions": actions,
        }
        self.journal.append("STRADDLE_POSITION_MANAGED", result)
        return result

    def _manage_position(
        self,
        position: dict[str, Any],
        symbol_info: dict[str, Any],
        management: StraddleExitManagementConfig,
    ) -> dict[str, Any] | None:
        side = str(position.get("side") or "").upper()
        if side not in {"BUY", "SELL"}:
            return {
                "action": "SKIP_POSITION",
                "reason": "UNKNOWN_SIDE",
                "position": position,
            }

        entry = _first_float(position, "entry_price", "price_open")
        current = _first_float(position, "current_price", "price_current")
        if entry is None or current is None:
            return {
                "action": "SKIP_POSITION",
                "reason": "MISSING_PRICE",
                "position": position,
            }

        favorable_points = current - entry if side == "BUY" else entry - current
        if (
            management.scalp_profit_points > 0
            and favorable_points >= management.scalp_profit_points
        ):
            close_result = self.broker.close_position(
                position,
                comment="Straddle scalp profit exit",
            )
            return {
                "action": "CLOSE_POSITION",
                "reason": "SCALP_PROFIT_EXIT",
                "ticket": position.get("ticket"),
                "favorable_points": round(favorable_points, 2),
                "result": close_result,
            }

        if (
            management.early_loss_exit_points > 0
            and favorable_points <= -management.early_loss_exit_points
        ):
            close_result = self.broker.close_position(
                position,
                comment="Straddle early loss exit",
            )
            return {
                "action": "CLOSE_POSITION",
                "reason": "EARLY_LOSS_EXIT",
                "ticket": position.get("ticket"),
                "favorable_points": round(favorable_points, 2),
                "result": close_result,
            }

        target = _first_float(position, "take_profit", "tp")
        if target is None:
            return {
                "action": "SKIP_POSITION",
                "reason": "MISSING_TAKE_PROFIT",
                "position": position,
            }

        candidate, reason = self._managed_stop_candidate(
            side,
            entry,
            current,
            favorable_points,
            management,
        )
        if candidate is None or reason is None:
            return {
                "action": "HOLD_POSITION",
                "reason": "NO_STOP_CHANGE",
                "ticket": position.get("ticket"),
                "favorable_points": round(favorable_points, 2),
            }

        stop = _first_float(position, "stop_loss", "sl")
        rounded_stop = self.builder._round_price(candidate, symbol_info)
        rounded_target = self.builder._round_price(target, symbol_info)
        if not _is_valid_managed_stop(side, rounded_stop, current):
            return {
                "action": "HOLD_POSITION",
                "reason": "STOP_TOO_CLOSE_TO_PRICE",
                "ticket": position.get("ticket"),
                "candidate_stop": rounded_stop,
                "favorable_points": round(favorable_points, 2),
            }
        if stop is not None:
            improvement = _stop_improvement_points(side, rounded_stop, stop)
            if improvement < management.min_stop_update_points:
                return {
                    "action": "HOLD_POSITION",
                    "reason": "STOP_ALREADY_MANAGED",
                    "ticket": position.get("ticket"),
                    "candidate_stop": rounded_stop,
                    "current_stop": stop,
                    "favorable_points": round(favorable_points, 2),
                }

        ticket = position.get("ticket")
        if ticket in (None, ""):
            return {
                "action": "SKIP_POSITION",
                "reason": "MISSING_TICKET",
                "position": position,
            }
        result = self.broker.modify_position_stops(ticket, rounded_stop, rounded_target)
        return {
            "action": "MODIFY_STOP",
            "reason": reason,
            "ticket": position.get("ticket"),
            "stop_loss": rounded_stop,
            "take_profit": rounded_target,
            "favorable_points": round(favorable_points, 2),
            "result": result,
        }

    def _managed_stop_candidate(
        self,
        side: str,
        entry: float,
        current: float,
        favorable_points: float,
        management: StraddleExitManagementConfig,
    ) -> tuple[float | None, str | None]:
        candidate = None
        reason = None
        if (
            management.break_even_trigger_points > 0
            and favorable_points >= management.break_even_trigger_points
        ):
            candidate = (
                entry + management.break_even_lock_points
                if side == "BUY"
                else entry - management.break_even_lock_points
            )
            reason = "BREAK_EVEN"
        if (
            management.trailing_trigger_points > 0
            and favorable_points >= management.trailing_trigger_points
        ):
            trailing = (
                current - management.trailing_distance_points
                if side == "BUY"
                else current + management.trailing_distance_points
            )
            if candidate is None or _stop_improvement_points(
                side,
                trailing,
                candidate,
            ) > 0:
                candidate = trailing
                reason = "TRAILING_STOP"
        return candidate, reason

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


def _nonnegative_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be non-negative")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be non-negative") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{name} must be non-negative")
    return number


def _optional_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _first_float(item: dict[str, Any], *names: str) -> float | None:
    for name in names:
        number = _optional_float(item.get(name))
        if number is not None:
            return number
    return None


def _stop_improvement_points(side: str, candidate: float, current: float) -> float:
    if side == "BUY":
        return candidate - current
    return current - candidate


def _is_valid_managed_stop(side: str, stop: float, current: float) -> bool:
    if side == "BUY":
        return stop < current
    return stop > current
