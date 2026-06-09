"""MT5 executor for two-leg straddle breakout pairs."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.straddle_breakout import (
    StraddleBreakoutConfig,
    StraddlePairProposal,
    build_straddle_breakout_pair,
)
from tradingagents.brokers.execution_journal import ExecutionJournal
from tradingagents.brokers.mode_gate import (
    TradingMode,
    account_safety_from_connection,
    health_gate,
    mode_value,
)
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


@dataclass(frozen=True)
class StraddleEntryRegimeConfig:
    """Pause straddle entries after hostile market conditions."""

    enabled: bool = True
    loss_streak_limit: int = 2
    loss_cooldown_minutes: float = 10.0
    loss_history_lookback_minutes: float = 240.0
    wide_box_streak_limit: int = 3
    wide_box_cooldown_minutes: float = 5.0
    post_cooldown_momentum_body_points: float = 0.80
    post_cooldown_momentum_breakout_points: float = 0.20

    def __post_init__(self) -> None:
        if not isinstance(self.enabled, bool):
            raise ValueError("enabled must be a boolean")
        for name in ("loss_streak_limit", "wide_box_streak_limit"):
            value = getattr(self, name)
            if isinstance(value, bool):
                raise ValueError(f"{name} must be non-negative")
            try:
                number = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be non-negative") from exc
            if number < 0:
                raise ValueError(f"{name} must be non-negative")
            object.__setattr__(self, name, number)
        for name in (
            "loss_cooldown_minutes",
            "loss_history_lookback_minutes",
            "wide_box_cooldown_minutes",
            "post_cooldown_momentum_body_points",
            "post_cooldown_momentum_breakout_points",
        ):
            value = _nonnegative_float(getattr(self, name), name)
            object.__setattr__(self, name, value)


@dataclass
class _EntryRegimeState:
    cooldown_until_utc: datetime | None = None
    cooldown_reason: str | None = None
    requires_momentum: bool = False
    consecutive_losses: int = 0
    loss_cooldown_exit_ticket: int | None = None
    seen_exit_tickets: set[int] | None = None
    wide_box_streak: int = 0
    last_wide_box_signature: tuple[Any, ...] | None = None

    def __post_init__(self) -> None:
        if self.seen_exit_tickets is None:
            self.seen_exit_tickets = set()


class MT5StraddleExecutor:
    """Build, dry-run, and place isolated MT5 straddle pending-order pairs."""

    def __init__(
        self,
        config: MT5ConnectionConfig,
        results_dir: str | Path,
        broker: Any | None = None,
        journal: ExecutionJournal | None = None,
        trading_mode: str = TradingMode.STRADDLE_ONLY.value,
    ) -> None:
        self.config = config
        self.broker = broker or MT5Broker(config)
        self.builder = MT5OrderRequestBuilder(config)
        self.journal = journal or ExecutionJournal(results_dir, config.symbol)
        self.state = StraddleStateStore(results_dir, config.symbol)
        self.heartbeat_path = self.state.directory / "mt5_straddle_heartbeat.json"
        self.trading_mode = mode_value(trading_mode)
        self._entry_regime = _EntryRegimeState()
        self._last_closed_candles: list[dict[str, Any]] = []

    def build_pair(
        self,
        straddle_config: StraddleBreakoutConfig,
        *,
        now_utc: datetime | str | None = None,
    ) -> StraddlePairProposal:
        connection, _account_safety = self._connect_and_record()
        candles = self.broker.fetch_rates(
            straddle_config.timeframe,
            straddle_config.lookback_candles + 1,
        )
        closed_candles = _closed_candles(candles, straddle_config.lookback_candles)
        self._last_closed_candles = closed_candles
        pair = build_straddle_breakout_pair(
            closed_candles,
            connection["symbol"],
            straddle_config,
            now_utc=now_utc,
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
        entry_regime: StraddleEntryRegimeConfig | None = None,
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

        current = _utc_datetime(now_utc)
        regime = entry_regime or StraddleEntryRegimeConfig()
        regime_result = self._entry_regime_pre_build(regime, current)
        if regime_result:
            return regime_result

        pair = self.build_pair(straddle_config, now_utc=current)
        regime_result = self._entry_regime_after_pair(
            pair,
            regime,
            current,
        )
        if regime_result:
            return regime_result
        return self.execute_pair(pair, live=live)

    def evaluate_entry_candidate(
        self,
        straddle_config: StraddleBreakoutConfig,
        *,
        now_utc: datetime | str | None = None,
        exit_management: StraddleExitManagementConfig | None = None,
        entry_regime: StraddleEntryRegimeConfig | None = None,
    ) -> dict[str, Any]:
        """Build and validate a straddle candidate without placing or storing it."""

        if self._active_trade_exists():
            result = {"status": "SKIPPED_ACTIVE_TRADE", "symbol": self.config.symbol}
            self.journal.append("STRADDLE_CANDIDATE_SKIPPED_ACTIVE_TRADE", result)
            return result

        current = _utc_datetime(now_utc)
        regime = entry_regime or StraddleEntryRegimeConfig()
        regime_result = self._entry_regime_pre_build(regime, current)
        if regime_result:
            return regime_result

        pair = self.build_pair(straddle_config, now_utc=current)
        regime_result = self._entry_regime_after_pair(pair, regime, current)
        if regime_result:
            return regime_result
        if pair.status != "PROPOSED" or pair.buy_stop is None or pair.sell_stop is None:
            result = {
                "status": "STRADDLE_NO_TRADE",
                "reason": pair.reason,
                "pair": pair,
            }
            self.journal.append("STRADDLE_CANDIDATE_NO_TRADE", _jsonable_pair_result(result))
            return result

        connection, account_safety = self._connect_and_record()
        if not account_safety["passed"]:
            result = {
                "status": "STRADDLE_SKIPPED_ACCOUNT_SAFETY",
                "reason": "ACCOUNT_SAFETY_FAILED",
                "symbol": self.config.symbol,
                "pair": pair,
                "account_safety": account_safety,
            }
            self.journal.append(
                "STRADDLE_CANDIDATE_SKIPPED",
                _jsonable_pair_result(result),
            )
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
                "pair": pair,
            }
            self.journal.append("STRADDLE_CANDIDATE_SKIPPED", _jsonable_pair_result(result))
            return result

        result = {
            "status": "PROPOSED",
            "symbol": self.config.symbol,
            "pair": pair,
            "requests": requests,
            "account_safety": account_safety,
        }
        self.journal.append("STRADDLE_CANDIDATE_PROPOSED", _jsonable_pair_result(result))
        return result

    def watch_forever(
        self,
        straddle_config: StraddleBreakoutConfig,
        *,
        live: bool = False,
        poll_seconds: int = 30,
        max_cycles: int = 0,
        max_runtime_seconds: int = 0,
        exit_management: StraddleExitManagementConfig | None = None,
        entry_regime: StraddleEntryRegimeConfig | None = None,
    ) -> dict[str, Any]:
        """Continuously watch the market and place a straddle when ready."""

        cycles = 0
        last_result: dict[str, Any] = {"status": "NOT_STARTED"}
        management = exit_management or StraddleExitManagementConfig()
        regime = entry_regime or StraddleEntryRegimeConfig()
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
                    entry_regime=regime,
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
        connection, account_safety = self._connect_and_record()
        if not account_safety["passed"]:
            result = {
                "status": "STRADDLE_SKIPPED_ACCOUNT_SAFETY",
                "reason": "ACCOUNT_SAFETY_FAILED",
                "symbol": self.config.symbol,
                "account_safety": account_safety,
            }
            self.journal.append("STRADDLE_POSITION_MONITOR_SKIPPED", result)
            return result
        positions = self.broker.open_positions(self.config.symbol)
        if not positions:
            result = {
                "status": "NO_OPEN_POSITION",
                "symbol": self.config.symbol,
                "account_safety": account_safety,
            }
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
            "account_safety": account_safety,
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

    def _entry_regime_pre_build(
        self,
        regime: StraddleEntryRegimeConfig,
        now_utc: datetime,
    ) -> dict[str, Any] | None:
        if not regime.enabled:
            return None

        cooldown = self._entry_cooldown_result(now_utc)
        if cooldown:
            return cooldown

        self._reconcile_entry_losses(regime, now_utc)
        if (
            regime.loss_streak_limit > 0
            and self._entry_regime.consecutive_losses >= regime.loss_streak_limit
        ):
            last_ticket = max(self._entry_regime.seen_exit_tickets or {0})
            if last_ticket != self._entry_regime.loss_cooldown_exit_ticket:
                return self._start_entry_cooldown(
                    now_utc,
                    minutes=regime.loss_cooldown_minutes,
                    reason=(
                        f"loss streak {self._entry_regime.consecutive_losses} "
                        f"reached limit {regime.loss_streak_limit}"
                    ),
                    trigger="LOSS_STREAK",
                    exit_ticket=last_ticket,
                )
        return self._entry_cooldown_result(now_utc)

    def _entry_regime_after_pair(
        self,
        pair: StraddlePairProposal,
        regime: StraddleEntryRegimeConfig,
        now_utc: datetime,
    ) -> dict[str, Any] | None:
        if not regime.enabled:
            return None

        if _is_wide_box_no_trade(pair):
            signature = _wide_box_signature(pair)
            if signature != self._entry_regime.last_wide_box_signature:
                self._entry_regime.wide_box_streak += 1
                self._entry_regime.last_wide_box_signature = signature
            if (
                regime.wide_box_streak_limit > 0
                and self._entry_regime.wide_box_streak
                >= regime.wide_box_streak_limit
            ):
                self._entry_regime.wide_box_streak = 0
                return self._start_entry_cooldown(
                    now_utc,
                    minutes=regime.wide_box_cooldown_minutes,
                    reason=(
                        f"wide box streak {regime.wide_box_streak_limit} "
                        f"reached limit {regime.wide_box_streak_limit}"
                    ),
                    trigger="WIDE_BOX_STREAK",
                    pair=pair,
                )
            return None

        if pair.status == "PROPOSED":
            self._entry_regime.wide_box_streak = 0
            self._entry_regime.last_wide_box_signature = None
            if self._entry_regime.requires_momentum and not _has_clean_momentum(
                self._last_closed_candles,
                body_points=regime.post_cooldown_momentum_body_points,
                breakout_points=regime.post_cooldown_momentum_breakout_points,
            ):
                result = {
                    "status": "STRADDLE_ENTRY_WAIT_MOMENTUM",
                    "symbol": self.config.symbol,
                    "reason": "post-cooldown momentum confirmation not met",
                    "pair": pair.model_dump(mode="json"),
                    "closed_candles": self._last_closed_candles,
                }
                self.journal.append("STRADDLE_ENTRY_WAIT_MOMENTUM", result)
                return result
            self._entry_regime.requires_momentum = False
        return None

    def _reconcile_entry_losses(
        self,
        regime: StraddleEntryRegimeConfig,
        now_utc: datetime,
    ) -> None:
        if regime.loss_streak_limit <= 0:
            return
        start = now_utc - timedelta(minutes=regime.loss_history_lookback_minutes)
        deals = self.broker.history_deals(self.config.symbol, start, now_utc)
        for trade in _closed_straddle_trades(deals, self.config.magic):
            exit_ticket = trade["exit_ticket"]
            seen = self._entry_regime.seen_exit_tickets
            if seen is None or exit_ticket in seen:
                continue
            seen.add(exit_ticket)
            if trade["profit"] < 0:
                self._entry_regime.consecutive_losses += 1
            else:
                self._entry_regime.consecutive_losses = 0

    def _entry_cooldown_result(self, now_utc: datetime) -> dict[str, Any] | None:
        cooldown_until = self._entry_regime.cooldown_until_utc
        if cooldown_until is None:
            return None
        if now_utc < cooldown_until:
            result = {
                "status": "STRADDLE_ENTRY_COOLDOWN",
                "symbol": self.config.symbol,
                "reason": self._entry_regime.cooldown_reason,
                "cooldown_until_utc": cooldown_until.isoformat(),
            }
            self.journal.append("STRADDLE_ENTRY_COOLDOWN", result)
            return result
        self._entry_regime.cooldown_until_utc = None
        self._entry_regime.cooldown_reason = None
        return None

    def _start_entry_cooldown(
        self,
        now_utc: datetime,
        *,
        minutes: float,
        reason: str,
        trigger: str,
        exit_ticket: int | None = None,
        pair: StraddlePairProposal | None = None,
    ) -> dict[str, Any] | None:
        if minutes <= 0:
            return None
        cooldown_until = now_utc + timedelta(minutes=minutes)
        self._entry_regime.cooldown_until_utc = cooldown_until
        self._entry_regime.cooldown_reason = reason
        self._entry_regime.requires_momentum = True
        if exit_ticket is not None:
            self._entry_regime.loss_cooldown_exit_ticket = exit_ticket
        result = {
            "status": "STRADDLE_ENTRY_COOLDOWN",
            "symbol": self.config.symbol,
            "reason": reason,
            "trigger": trigger,
            "cooldown_until_utc": cooldown_until.isoformat(),
        }
        if pair is not None:
            result["pair"] = pair.model_dump(mode="json")
        self.journal.append("STRADDLE_ENTRY_COOLDOWN", result)
        return result

    def _write_heartbeat(
        self,
        result: dict[str, Any],
        *,
        cycle: int,
        live: bool,
    ) -> dict[str, Any]:
        account_safety = result.get("account_safety")
        payload = {
            "trading_mode": self.trading_mode,
            "selected_method": result.get("selected_method")
            or _selected_method_for_status(result.get("status")),
            "selected_profile": result.get("selected_profile"),
            "mode_decision": result.get("mode_decision")
            or _mode_decision_for_status(result.get("status")),
            "mode_rejection_reason": result.get("mode_rejection_reason"),
            "health_gate": result.get("health_gate") or health_gate(True, []),
            "account_safety": account_safety or {},
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
        connection, account_safety = self._connect_and_record()

        if pair.status != "PROPOSED" or pair.buy_stop is None or pair.sell_stop is None:
            result = {
                "status": "STRADDLE_NO_TRADE",
                "reason": pair.reason,
                "pair": pair.model_dump(mode="json"),
                "account_safety": account_safety,
            }
            self.journal.append("STRADDLE_NO_TRADE", result)
            return result

        if live and not account_safety["passed"]:
            result = {
                "status": "STRADDLE_SKIPPED_ACCOUNT_SAFETY",
                "reason": "ACCOUNT_SAFETY_FAILED",
                "symbol": self.config.symbol,
                "pair": pair.model_dump(mode="json"),
                "account_safety": account_safety,
            }
            self.journal.append("STRADDLE_ORDER_SKIPPED", result)
            return result

        if self._active_trade_exists():
            result = {
                "status": "SKIPPED_ACTIVE_TRADE",
                "symbol": self.config.symbol,
                "account_safety": account_safety,
            }
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
                "account_safety": account_safety,
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
                "account_safety": account_safety,
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
                "account_safety": account_safety,
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
                "account_safety": account_safety,
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
            "account_safety": account_safety,
        }
        self.journal.append("STRADDLE_PAIR_PLACED", result)
        return result

    def monitor_pair(self, now_utc: datetime | str | None = None) -> dict[str, Any]:
        """Clear dry-run state or cancel live pending legs after expiry."""

        _connection, account_safety = self._connect_and_record()
        state = self.state.load()
        active = state.get("active_pair")
        if not active:
            result = {
                "status": "NO_ACTIVE_PAIR",
                "symbol": self.config.symbol,
                "account_safety": account_safety,
            }
            self.journal.append("STRADDLE_MONITOR_SKIPPED", result)
            return result

        if not account_safety["passed"]:
            result = {
                "status": "STRADDLE_SKIPPED_ACCOUNT_SAFETY",
                "reason": "ACCOUNT_SAFETY_FAILED",
                "symbol": self.config.symbol,
                "account_safety": account_safety,
            }
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
                "account_safety": account_safety,
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
                    "account_safety": account_safety,
                }
            else:
                if cancelled or not open_order_tickets:
                    self.state.clear_pair()
                result = {
                    "status": "PAIR_CANCELLED",
                    "symbol": self.config.symbol,
                    "results": cancelled,
                    "account_safety": account_safety,
                }
            self.journal.append("STRADDLE_PAIR_CANCELLED", result)
            return result

        if open_order_tickets & tracked_tickets:
            result = {
                "status": "PAIR_STILL_ACTIVE",
                "cancel_after_utc": cancel_after.isoformat(),
                "account_safety": account_safety,
            }
            self.journal.append("STRADDLE_MONITOR_SKIPPED", result)
            return result

        self.state.clear_pair()
        result = {
            "status": "PAIR_RESOLVED",
            "symbol": self.config.symbol,
            "results": [],
            "account_safety": account_safety,
        }
        self.journal.append("STRADDLE_PAIR_RESOLVED", result)
        return result

    def _connect_and_record(self) -> tuple[dict[str, Any], dict[str, Any]]:
        connection = self.broker.connect()
        account_safety = account_safety_from_connection(
            connection,
            require_demo=bool(getattr(self.config, "require_demo_account", True)),
        )
        self.journal.append(
            "STRADDLE_CONNECTED",
            {**connection, "account_safety": account_safety},
        )
        return connection, account_safety

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


def _closed_straddle_trades(
    deals: list[dict[str, Any]],
    magic: int,
) -> list[dict[str, Any]]:
    grouped: dict[Any, list[dict[str, Any]]] = {}
    for deal in deals:
        position_id = deal.get("position_id")
        if position_id in (None, ""):
            continue
        grouped.setdefault(position_id, []).append(deal)

    closed = []
    for position_id, position_deals in grouped.items():
        if not _is_straddle_position(position_deals, magic):
            continue
        exits = [deal for deal in position_deals if _is_exit_deal(deal)]
        if not exits:
            continue
        ordered_exits = sorted(exits, key=_deal_sort_key)
        exit_ticket = _deal_int(ordered_exits[-1].get("ticket"))
        if exit_ticket is None:
            continue
        profit = sum(
            _deal_float(deal.get("profit"))
            + _deal_float(deal.get("commission"))
            + _deal_float(deal.get("swap"))
            + _deal_float(deal.get("fee"))
            for deal in exits
        )
        closed.append(
            {
                "position_id": position_id,
                "exit_ticket": exit_ticket,
                "profit": round(profit, 2),
                "exit_time": _deal_sort_key(ordered_exits[-1]),
            }
        )
    return sorted(closed, key=lambda trade: trade["exit_time"])


def _is_straddle_position(deals: list[dict[str, Any]], magic: int) -> bool:
    has_magic = any(_deal_int(deal.get("magic")) == magic for deal in deals)
    has_straddle_comment = any(
        "straddle" in str(deal.get("comment") or "").lower() for deal in deals
    )
    return has_magic and has_straddle_comment


def _is_exit_deal(deal: dict[str, Any]) -> bool:
    return _deal_int(deal.get("entry")) == 1


def _deal_sort_key(deal: dict[str, Any]) -> tuple[str, int, int]:
    return (
        str(deal.get("time_utc") or ""),
        _deal_int(deal.get("time_msc")) or _deal_int(deal.get("time")) or 0,
        _deal_int(deal.get("ticket")) or 0,
    )


def _deal_int(value: Any) -> int | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _deal_float(value: Any) -> float:
    if value in (None, "") or isinstance(value, bool):
        return 0.0
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) else 0.0


def _is_wide_box_no_trade(pair: StraddlePairProposal) -> bool:
    return (
        pair.status != "PROPOSED"
        and "box range" in pair.reason
        and "exceeds maximum" in pair.reason
    )


def _wide_box_signature(pair: StraddlePairProposal) -> tuple[Any, ...]:
    return (
        pair.box.get("high"),
        pair.box.get("low"),
        pair.box.get("range"),
        pair.box.get("spread"),
    )


def _has_clean_momentum(
    candles: list[dict[str, Any]],
    *,
    body_points: float,
    breakout_points: float,
) -> bool:
    if body_points <= 0 and breakout_points <= 0:
        return True
    if len(candles) < 2:
        return False
    previous = candles[-2]
    latest = candles[-1]
    latest_open = _optional_float(latest.get("open"))
    latest_close = _optional_float(latest.get("close"))
    previous_high = _optional_float(previous.get("high"))
    previous_low = _optional_float(previous.get("low"))
    if None in (latest_open, latest_close, previous_high, previous_low):
        return False

    body = abs(float(latest_close) - float(latest_open))
    if body < body_points:
        return False
    bullish_breakout = float(latest_close) >= float(previous_high) + breakout_points
    bearish_breakout = float(latest_close) <= float(previous_low) - breakout_points
    return bullish_breakout or bearish_breakout


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


def _selected_method_for_status(status: Any) -> str:
    text = str(status or "").upper()
    if text in {
        "PAIR_PLACED",
        "PAIR_STILL_ACTIVE",
        "PAIR_RESOLVED",
        "POSITION_CLOSED_SCALP",
        "POSITION_CLOSED_EARLY",
        "POSITION_STOP_MOVED",
        "POSITION_MONITORED",
    }:
        return "STRADDLE"
    return "HOLD"


def _mode_decision_for_status(status: Any) -> str:
    text = str(status or "UNKNOWN").upper()
    if text.startswith("STRADDLE_"):
        return text
    return "STRADDLE_" + text


def _jsonable_pair_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = dict(result)
    pair = payload.get("pair")
    if hasattr(pair, "model_dump"):
        payload["pair"] = pair.model_dump(mode="json")
    return payload
