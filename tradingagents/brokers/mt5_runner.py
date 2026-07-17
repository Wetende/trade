"""Unattended MT5 automation loop."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from tradingagents.agents.schemas import OrderProposal
from tradingagents.brokers.mode_gate import TradingMode, health_gate, mode_value
from tradingagents.brokers.mt5 import MT5BrokerError
from tradingagents.brokers.runner_summary import RunnerSummaryStore


@dataclass(frozen=True)
class MT5RunnerConfig:
    results_dir: str | Path
    poll_seconds: int = 30
    maintenance_poll_seconds: float = 1.0
    max_cycles: int = 0
    max_runtime_seconds: int = 0
    max_session_loss: float = 0.0
    post_close_cooldown_seconds: int = 0
    loss_cooldown_seconds: int = 0
    loss_streak_cooldown_count: int = 0
    loss_streak_cooldown_seconds: int = 0
    blocked_strategy_rules: tuple[str, ...] = ()
    trading_mode: str = TradingMode.ENTRY_ONLY.value
    drain_on_stop: bool = False
    shutdown_grace_seconds: int = 120
    flat_verification_count: int = 2
    history_owned_orders_only: bool = False

    def __post_init__(self) -> None:
        poll_seconds = int(self.poll_seconds)
        maintenance_poll_seconds = float(self.maintenance_poll_seconds)
        max_cycles = int(self.max_cycles)
        max_runtime_seconds = int(self.max_runtime_seconds)
        max_session_loss = float(self.max_session_loss)
        post_close_cooldown_seconds = _nonnegative_int(
            self.post_close_cooldown_seconds,
            "post_close_cooldown_seconds",
        )
        loss_cooldown_seconds = _nonnegative_int(
            self.loss_cooldown_seconds,
            "loss_cooldown_seconds",
        )
        loss_streak_cooldown_count = _nonnegative_int(
            self.loss_streak_cooldown_count,
            "loss_streak_cooldown_count",
        )
        loss_streak_cooldown_seconds = _nonnegative_int(
            self.loss_streak_cooldown_seconds,
            "loss_streak_cooldown_seconds",
        )
        shutdown_grace_seconds = _nonnegative_int(
            self.shutdown_grace_seconds,
            "shutdown_grace_seconds",
        )
        flat_verification_count = _nonnegative_int(
            self.flat_verification_count,
            "flat_verification_count",
        )
        trading_mode = mode_value(self.trading_mode)
        if poll_seconds < 5:
            raise ValueError("poll_seconds must be at least 5")
        if (
            not math.isfinite(maintenance_poll_seconds)
            or maintenance_poll_seconds <= 0
        ):
            raise ValueError(
                "maintenance_poll_seconds must be a finite positive number"
            )
        if max_cycles < 0:
            raise ValueError("max_cycles must be non-negative")
        if max_runtime_seconds < 0:
            raise ValueError("max_runtime_seconds must be non-negative")
        if not math.isfinite(max_session_loss) or max_session_loss < 0:
            raise ValueError("max_session_loss must be a finite non-negative number")
        if bool(self.drain_on_stop) and shutdown_grace_seconds <= 0:
            raise ValueError("shutdown_grace_seconds must be positive when draining")
        if bool(self.drain_on_stop) and flat_verification_count <= 0:
            raise ValueError("flat_verification_count must be positive when draining")
        object.__setattr__(self, "poll_seconds", poll_seconds)
        object.__setattr__(
            self,
            "maintenance_poll_seconds",
            maintenance_poll_seconds,
        )
        object.__setattr__(self, "max_cycles", max_cycles)
        object.__setattr__(self, "max_runtime_seconds", max_runtime_seconds)
        object.__setattr__(self, "max_session_loss", max_session_loss)
        object.__setattr__(
            self,
            "post_close_cooldown_seconds",
            post_close_cooldown_seconds,
        )
        object.__setattr__(self, "loss_cooldown_seconds", loss_cooldown_seconds)
        object.__setattr__(
            self,
            "loss_streak_cooldown_count",
            loss_streak_cooldown_count,
        )
        object.__setattr__(
            self,
            "loss_streak_cooldown_seconds",
            loss_streak_cooldown_seconds,
        )
        object.__setattr__(self, "trading_mode", trading_mode)
        object.__setattr__(
            self,
            "blocked_strategy_rules",
            _normalize_rule_list(self.blocked_strategy_rules),
        )
        object.__setattr__(self, "drain_on_stop", bool(self.drain_on_stop))
        object.__setattr__(
            self,
            "history_owned_orders_only",
            bool(self.history_owned_orders_only),
        )
        object.__setattr__(
            self,
            "shutdown_grace_seconds",
            shutdown_grace_seconds,
        )
        object.__setattr__(
            self,
            "flat_verification_count",
            flat_verification_count,
        )


class MT5Runner:
    """Run analysis and guarded MT5 execution on a repeating cadence."""

    def __init__(
        self,
        config: MT5RunnerConfig,
        *,
        executor,
        analysis_func: Callable[[], tuple[str, OrderProposal] | list],
        current_as_of_func: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.executor = executor
        self.analysis_func = analysis_func
        self.current_as_of_func = current_as_of_func
        self.runner_dir = Path(config.results_dir) / "mt5_runner"
        self.runner_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path = self.runner_dir / "heartbeat.json"
        self.state_path = self.runner_dir / "state.json"
        self.summary_store = RunnerSummaryStore(config.results_dir)
        self.history_since_utc = self._load_history_since_utc()

    def run_once(self) -> dict:
        started_at = datetime.now(timezone.utc).isoformat()
        state = self._load_state()
        snapshot = self.executor.snapshot_state()
        self.executor.cancel_stale_pending_orders()
        position_management = self.executor.manage_open_positions()
        history_reconciliation = self._reconcile_trade_history(state)

        if snapshot.get("orders") or snapshot.get("positions"):
            return self._write_heartbeat(
                {
                    "status": "ACTIVE_TRADE_MONITORED",
                    "started_at_utc": started_at,
                    "position_management": position_management,
                    "history_reconciliation": history_reconciliation,
                }
            )

        risk_limit = self._session_loss_limit(history_reconciliation)
        if risk_limit is not None:
            return self._write_heartbeat(
                {
                    "status": "RISK_LIMIT_REACHED",
                    "started_at_utc": started_at,
                    "risk_limit": risk_limit,
                    "position_management": position_management,
                    "history_reconciliation": history_reconciliation,
                }
            )

        entry_cooldown = self._entry_cooldown_payload(history_reconciliation, state)
        if entry_cooldown is not None:
            return self._write_heartbeat(
                {
                    "status": "NO_TRADE",
                    "started_at_utc": started_at,
                    "selected_method": "HOLD",
                    "selected_profile": None,
                    "mode_decision": "ENTRY_COOLDOWN_ACTIVE",
                    "mode_rejection_reason": entry_cooldown["reason"],
                    "health_gate": health_gate(False, ["entry_cooldown"]),
                    "position_management": position_management,
                    "history_reconciliation": history_reconciliation,
                    "entry_cooldown": entry_cooldown,
                }
            )
        if self.current_as_of_func is not None:
            current_as_of = self.current_as_of_func()
            if state.get("last_processed_as_of") == current_as_of:
                return self._write_heartbeat(
                    {
                        "status": "CANDLE_ALREADY_PROCESSED",
                        "started_at_utc": started_at,
                        "as_of": current_as_of,
                        "position_management": position_management,
                        "history_reconciliation": history_reconciliation,
                    }
                )

        try:
            analysis_result = self.analysis_func()
            analysis_rows = self._parse_analysis_results(analysis_result)
        except Exception as exc:
            return self._write_heartbeat(
                {
                    "status": "RUNNER_ERROR",
                    "started_at_utc": started_at,
                    "position_management": position_management,
                    "history_reconciliation": history_reconciliation,
                    "analysis": {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                }
            )

        multi_profile_result = isinstance(analysis_result, list)
        last_processed_by_profile = dict(state.get("last_processed_by_profile") or {})
        processed_rows = []
        legacy_last_processed = state.get("last_processed_as_of")

        for profile, as_of, proposal, analysis in analysis_rows:
            if last_processed_by_profile.get(profile) == as_of or (
                profile == "normal" and legacy_last_processed == as_of
            ):
                continue

            status = str(getattr(proposal.status, "value", proposal.status)).upper()
            processed_rows.append((profile, as_of, proposal, analysis, status))
            last_processed_by_profile[profile] = as_of

        if not processed_rows:
            return self._write_heartbeat(
                {
                    "status": "CANDLE_ALREADY_PROCESSED",
                    "started_at_utc": started_at,
                    "profiles": [],
                    "position_management": position_management,
                    "history_reconciliation": history_reconciliation,
                }
            )

        latest_as_of = processed_rows[-1][1]
        state.update(
            {
                "last_processed_as_of": latest_as_of,
                "last_processed_by_profile": last_processed_by_profile,
            }
        )
        self._save_state(state)

        selected, decision, rejection_reason = self._select_directional_candidate(
            processed_rows
        )
        analysis_health_gate = self._analysis_health_gate(processed_rows)
        if decision == "DIRECTIONAL_CONFLICT_HOLD":
            conflict_reasons = [
                *analysis_health_gate["reasons"],
                "directional_conflict",
            ]
            return self._write_heartbeat(
                {
                    "status": "NO_TRADE",
                    "started_at_utc": started_at,
                    "selected_method": "HOLD",
                    "selected_profile": None,
                    "mode_decision": decision,
                    "mode_rejection_reason": rejection_reason,
                    "health_gate": health_gate(False, conflict_reasons),
                    "position_management": position_management,
                    "history_reconciliation": history_reconciliation,
                    "candidate_methods": self._candidate_methods(processed_rows),
                    "profiles": [
                        {
                            "entry_profile": profile,
                            "as_of": as_of,
                            "proposal": proposal.model_dump(mode="json"),
                            "analysis": analysis,
                            "status": status,
                        }
                        for profile, as_of, proposal, analysis, status in processed_rows
                    ],
                }
            )

        if selected is None:
            if not multi_profile_result and len(processed_rows) == 1:
                profile, as_of, proposal, analysis, _status = processed_rows[0]
                return self._write_heartbeat(
                    {
                        "status": "NO_TRADE",
                        "started_at_utc": started_at,
                        "selected_method": "HOLD",
                        "selected_profile": None,
                        "mode_decision": decision,
                        "mode_rejection_reason": rejection_reason,
                        "health_gate": analysis_health_gate,
                        "candidate_methods": self._candidate_methods(processed_rows),
                        "as_of": as_of,
                        "proposal": proposal.model_dump(mode="json"),
                        "analysis": analysis,
                        "position_management": position_management,
                        "history_reconciliation": history_reconciliation,
                    }
                )
            return self._write_heartbeat(
                {
                    "status": "NO_TRADE",
                    "started_at_utc": started_at,
                    "selected_method": "HOLD",
                    "selected_profile": None,
                    "mode_decision": decision,
                    "mode_rejection_reason": rejection_reason,
                    "health_gate": analysis_health_gate,
                    "candidate_methods": self._candidate_methods(processed_rows),
                    "position_management": position_management,
                    "history_reconciliation": history_reconciliation,
                    "profiles": [
                        {
                            "entry_profile": profile,
                            "as_of": as_of,
                            "proposal": proposal.model_dump(mode="json"),
                            "analysis": analysis,
                            "status": status,
                        }
                        for profile, as_of, proposal, analysis, status in processed_rows
                    ],
                }
            )

        profile, as_of, proposal, analysis = selected
        selected_method = _method_for_profile(profile)
        block = self._blocked_strategy(proposal)
        if block is not None:
            execution = {
                "status": "SKIPPED_BLOCKED_STRATEGY",
                "reason": "BLOCKED_STRATEGY_RULE",
                "matched_rule": block,
                "proposal": proposal.model_dump(mode="json"),
            }
            payload = {
                "status": "ORDER_BLOCKED_STRATEGY",
                "started_at_utc": started_at,
                "entry_profile": profile,
                "selected_method": selected_method,
                "selected_profile": profile,
                "mode_decision": f"{selected_method}_BLOCKED",
                "mode_rejection_reason": "BLOCKED_STRATEGY_RULE",
                "health_gate": analysis_health_gate,
                "candidate_methods": self._candidate_methods(processed_rows),
                "as_of": as_of,
                "proposal": proposal.model_dump(mode="json"),
                "execution": execution,
                "analysis": analysis,
                "position_management": position_management,
                "history_reconciliation": history_reconciliation,
            }
            if not multi_profile_result:
                payload.pop("entry_profile", None)
            return self._write_heartbeat(payload)

        execution = self.executor.execute_proposal(proposal)
        if execution.get("status") == "PLACED":
            self._record_owned_entry_order(state, execution)
        payload = {
            "status": (
                "ORDER_PLACED"
                if execution.get("status") == "PLACED"
                else "ORDER_NOT_PLACED"
            ),
            "started_at_utc": started_at,
            "entry_profile": profile,
            "selected_method": selected_method,
            "selected_profile": profile,
            "mode_decision": decision,
            "mode_rejection_reason": rejection_reason,
            "health_gate": analysis_health_gate,
            "candidate_methods": self._candidate_methods(processed_rows),
            "as_of": as_of,
            "proposal": proposal.model_dump(mode="json"),
            "execution": execution,
            "analysis": analysis,
            "position_management": position_management,
            "history_reconciliation": history_reconciliation,
        }
        if not multi_profile_result:
            payload.pop("entry_profile", None)
        return self._write_heartbeat(payload)

    def run_maintenance_once(self) -> dict:
        return {
            "status": "ACTIVE_TRADE_MAINTENANCE",
            "cancel_stale": self.executor.cancel_stale_pending_orders(),
            "position_management": self.executor.manage_open_positions(),
        }

    def _reconcile_trade_history(self, state: dict[str, Any]) -> dict:
        reconcile = getattr(self.executor, "reconcile_trade_history", None)
        if not callable(reconcile):
            return {"status": "UNAVAILABLE"}
        try:
            result = reconcile(
                since_utc=self.history_since_utc,
                now_utc=datetime.now(timezone.utc),
            )
            if self.config.history_owned_orders_only:
                return self._owned_trade_history(result, state)
            return result
        except Exception as exc:
            return {
                "status": "RECONCILE_ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    @staticmethod
    def _owned_trade_history(
        reconciliation: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Limit session accounting to orders durably placed by this runner.

        MT5 history can expose broker-local deal times while the runner clock is
        UTC.  A time-window query alone can therefore include a close owned by
        an earlier bounded session.  The persisted order ticket is the causal
        session boundary; unknown broker records remain in the execution
        journal but cannot affect this session's risk, cooldown, or evidence.
        """
        if reconciliation.get("status") != "RECONCILED":
            return reconciliation
        owned_orders = {
            int(value)
            for value in state.get("owned_entry_orders", [])
            if str(value).strip().isdigit() and int(value) > 0
        }

        def is_owned(trade: dict[str, Any]) -> bool:
            try:
                return int(trade.get("entry_order")) in owned_orders
            except (TypeError, ValueError):
                return False

        filled = [
            trade for trade in reconciliation.get("filled_trades") or []
            if is_owned(trade)
        ]
        closed = [
            trade for trade in reconciliation.get("closed_trades") or []
            if is_owned(trade)
        ]
        wins = sum(float(trade.get("profit") or 0.0) > 0 for trade in closed)
        losses = sum(float(trade.get("profit") or 0.0) < 0 for trade in closed)
        net_profit = round(sum(float(trade.get("profit") or 0.0) for trade in closed), 2)
        return {
            **reconciliation,
            "filled_trade_count": len(filled),
            "closed_trade_count": len(closed),
            "wins": wins,
            "losses": losses,
            "break_even": len(closed) - wins - losses,
            "net_profit": net_profit,
            "filled_trades": filled,
            "closed_trades": closed,
            "latest_closed_trade": closed[-1] if closed else {},
            "excluded_unowned_filled_trades": len(
                reconciliation.get("filled_trades") or []
            ) - len(filled),
            "excluded_unowned_closed_trades": len(
                reconciliation.get("closed_trades") or []
            ) - len(closed),
        }

    def _record_owned_entry_order(
        self,
        state: dict[str, Any],
        execution: dict[str, Any],
    ) -> None:
        try:
            order = int(execution.get("order"))
        except (TypeError, ValueError):
            return
        if order <= 0:
            return
        owned = {
            int(value)
            for value in state.get("owned_entry_orders", [])
            if str(value).strip().isdigit() and int(value) > 0
        }
        if order in owned:
            return
        state["owned_entry_orders"] = sorted((*owned, order))
        self._save_state(state)

    def _session_loss_limit(self, history_reconciliation: dict) -> dict | None:
        max_session_loss = self.config.max_session_loss
        if max_session_loss <= 0:
            return None
        if history_reconciliation.get("status") != "RECONCILED":
            return None
        try:
            net_profit = float(history_reconciliation.get("net_profit", 0.0))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(net_profit) or net_profit > -max_session_loss:
            return None
        return {
            "max_session_loss": max_session_loss,
            "net_profit": net_profit,
            "closed_trade_count": history_reconciliation.get("closed_trade_count", 0),
            "wins": history_reconciliation.get("wins", 0),
            "losses": history_reconciliation.get("losses", 0),
        }

    def _entry_cooldown_payload(
        self,
        history_reconciliation: dict,
        state: dict,
    ) -> dict[str, Any] | None:
        now_utc = datetime.now(timezone.utc)
        cooldown_until = _parse_utc_datetime(
            state.get("entry_cooldown_until_utc")
        )
        if cooldown_until is not None and now_utc < cooldown_until:
            return {
                "reason": state.get("entry_cooldown_reason")
                or "POST_CLOSE_COOLDOWN",
                "cooldown_until_utc": cooldown_until.isoformat(),
                "exit_ticket": state.get("entry_cooldown_exit_ticket"),
                "profit": state.get("entry_cooldown_profit"),
            }
        if cooldown_until is not None:
            state.pop("entry_cooldown_until_utc", None)
            state.pop("entry_cooldown_reason", None)
            self._save_state(state)

        if history_reconciliation.get("status") != "RECONCILED":
            return None
        latest = history_reconciliation.get("latest_closed_trade")
        if not isinstance(latest, dict) or not latest:
            return None

        exit_ticket = _closed_trade_exit_ticket(latest)
        if exit_ticket is None:
            return None
        if str(state.get("entry_cooldown_exit_ticket") or "") == str(exit_ticket):
            return None

        profit = _closed_trade_profit(latest)
        loss_streak = _closed_loss_streak(history_reconciliation)
        seconds = self.config.post_close_cooldown_seconds
        reason = "POST_CLOSE_COOLDOWN"
        if profit is not None and profit < 0 and self.config.loss_cooldown_seconds > 0:
            seconds = self.config.loss_cooldown_seconds
            reason = "LOSS_COOLDOWN"
        if (
            self.config.loss_streak_cooldown_count > 0
            and self.config.loss_streak_cooldown_seconds > 0
            and loss_streak >= self.config.loss_streak_cooldown_count
        ):
            seconds = self.config.loss_streak_cooldown_seconds
            reason = "LOSS_STREAK_COOLDOWN"
        if seconds <= 0:
            state["entry_cooldown_exit_ticket"] = exit_ticket
            state["entry_cooldown_profit"] = profit
            self._save_state(state)
            return None

        closed_at = _parse_utc_datetime(latest.get("closed_at_utc")) or now_utc
        cooldown_until = closed_at + timedelta(seconds=seconds)
        state["entry_cooldown_exit_ticket"] = exit_ticket
        state["entry_cooldown_profit"] = profit
        state["entry_cooldown_started_at_utc"] = now_utc.isoformat()
        if now_utc >= cooldown_until:
            self._save_state(state)
            return None

        state["entry_cooldown_until_utc"] = cooldown_until.isoformat()
        state["entry_cooldown_reason"] = reason
        self._save_state(state)
        return {
            "reason": reason,
            "seconds": seconds,
            "cooldown_until_utc": cooldown_until.isoformat(),
            "exit_ticket": exit_ticket,
            "profit": profit,
            "loss_streak": loss_streak,
        }

    def _load_history_since_utc(self) -> datetime:
        if self.summary_store.summary_path.exists():
            try:
                summary = json.loads(
                    self.summary_store.summary_path.read_text(encoding="utf-8")
                )
                started_at = datetime.fromisoformat(str(summary["started_at_utc"]))
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                started_at = datetime.now(timezone.utc)
        else:
            started_at = datetime.now(timezone.utc)
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        return started_at.astimezone(timezone.utc)

    def run_forever(self) -> dict:
        cycles = 0
        last_result = {"status": "NOT_STARTED"}
        consecutive_broker_errors = 0
        deadline = (
            time.monotonic() + self.config.max_runtime_seconds
            if self.config.max_runtime_seconds
            else None
        )
        while True:
            try:
                last_result = self.run_once()
                consecutive_broker_errors = 0
            except MT5BrokerError as exc:
                consecutive_broker_errors += 1
                last_result = self._write_heartbeat(
                    {
                        "status": "RUNNER_BROKER_ERROR",
                        "started_at_utc": datetime.now(timezone.utc).isoformat(),
                        "selected_method": "HOLD",
                        "selected_profile": None,
                        "mode_decision": "BROKER_CONNECTION_RETRY",
                        "mode_rejection_reason": "MT5_BROKER_ERROR",
                        "health_gate": health_gate(
                            False,
                            ["mt5_broker_connection"],
                        ),
                        "broker_error": {
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                            "consecutive_failures": consecutive_broker_errors,
                            "order_attempted": False,
                        },
                    }
                )
            cycles += 1
            if last_result.get("status") == "RISK_LIMIT_REACHED":
                return self._stop_result(
                    "STOPPED_RISK_LIMIT",
                    last_result,
                )
            if (
                deadline is None
                and self.config.max_cycles
                and cycles >= self.config.max_cycles
            ):
                return self._stop_result(
                    "STOPPED_MAX_CYCLES",
                    last_result,
                )
            if deadline is not None:
                if time.monotonic() >= deadline:
                    return self._stop_result(
                        "STOPPED_MAX_RUNTIME_SECONDS",
                        last_result,
                    )
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    return self._stop_result(
                        "STOPPED_MAX_RUNTIME_SECONDS",
                        last_result,
                    )
                wait_seconds = min(self.config.poll_seconds, remaining_seconds)
                self._wait_between_cycles(last_result, wait_seconds)
            else:
                self._wait_between_cycles(last_result, self.config.poll_seconds)

    def _stop_result(self, status: str, last_result: dict) -> dict:
        if not self.config.drain_on_stop:
            return {"status": status, "last_result": last_result}
        return self._drain_to_flat(status, last_result)

    def _drain_to_flat(self, stop_status: str, last_result: dict) -> dict:
        grace_deadline = time.monotonic() + self.config.shutdown_grace_seconds
        flat_verifications = 0
        drain_cycles = 0
        latest = None
        while True:
            drain_cycles += 1
            cancel_result = None
            management_result = None
            close_result = None
            errors = []
            try:
                snapshot = self.executor.snapshot_state()
                if snapshot.get("orders"):
                    cancel_all = getattr(
                        self.executor,
                        "cancel_all_pending_orders",
                        None,
                    )
                    cancel_result = (
                        cancel_all(reason=stop_status)
                        if callable(cancel_all)
                        else self.executor.cancel_stale_pending_orders()
                    )
                if snapshot.get("positions"):
                    if time.monotonic() < grace_deadline:
                        management_result = self.executor.manage_open_positions()
                    else:
                        close_all = getattr(
                            self.executor,
                            "close_all_positions",
                            None,
                        )
                        if not callable(close_all):
                            raise RuntimeError(
                                "drain deadline requires close_all_positions"
                            )
                        close_result = close_all(reason=stop_status)
                fresh = self.executor.snapshot_state()
            except Exception as exc:  # pragma: no cover - defensive live retry
                errors.append(
                    {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
                fresh = {"orders": ["UNKNOWN"], "positions": ["UNKNOWN"]}

            if not fresh.get("orders") and not fresh.get("positions"):
                flat_verifications += 1
            else:
                flat_verifications = 0
            complete = flat_verifications >= self.config.flat_verification_count
            latest = self._write_heartbeat(
                {
                    "status": "DRAINED_FLAT" if complete else "DRAINING",
                    "stop_status": stop_status,
                    "drain_cycle": drain_cycles,
                    "flat_verification_count": flat_verifications,
                    "required_flat_verifications": (
                        self.config.flat_verification_count
                    ),
                    "cancel_result": cancel_result,
                    "management_result": management_result,
                    "close_result": close_result,
                    "errors": errors,
                    "orders": fresh.get("orders"),
                    "positions": fresh.get("positions"),
                }
            )
            if complete:
                return {
                    "status": f"{stop_status}_DRAINED_FLAT",
                    "last_result": last_result,
                    "drain_result": latest,
                }
            time.sleep(self.config.maintenance_poll_seconds)

    def _wait_between_cycles(
        self,
        last_result: dict,
        wait_seconds: float,
    ) -> None:
        if last_result.get("status") not in {
            "ACTIVE_TRADE_MONITORED",
            "ORDER_PLACED",
        }:
            time.sleep(wait_seconds)
            return

        remaining = float(wait_seconds)
        cadence = min(
            self.config.maintenance_poll_seconds,
            float(self.config.poll_seconds),
        )
        while remaining > 0:
            sleep_seconds = min(cadence, remaining)
            time.sleep(sleep_seconds)
            remaining -= sleep_seconds
            if remaining > 1e-9:
                self.run_maintenance_once()

    def _write_heartbeat(self, result: dict) -> dict:
        account_safety = self._nested_account_safety(result)
        payload = {
            "trading_mode": self.config.trading_mode,
            "selected_method": result.get("selected_method", "HOLD"),
            "selected_profile": result.get("selected_profile"),
            "mode_decision": result.get("mode_decision") or result.get("status"),
            "mode_rejection_reason": result.get("mode_rejection_reason"),
            "health_gate": result.get("health_gate") or health_gate(True, []),
            "account_safety": account_safety or {},
            **result,
            "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
            "heartbeat_path": str(self.heartbeat_path),
        }
        summary = self.summary_store.record_cycle(payload)
        payload["summary_path"] = str(self.summary_store.summary_path)
        payload["summary"] = summary
        self.heartbeat_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return payload


    def _nested_account_safety(self, result: dict) -> dict | None:
        account_safety = result.get("account_safety")
        if account_safety is not None:
            return account_safety
        for key in (
            "execution",
            "position_management",
            "stale_orders",
            "straddle_monitor",
            "snapshot",
        ):
            nested = result.get(key)
            if isinstance(nested, dict) and nested.get("account_safety") is not None:
                return nested["account_safety"]
        return None

    def _parse_analysis_result(self, result) -> tuple[str, OrderProposal, dict]:
        if not isinstance(result, tuple):
            raise ValueError("analysis_func must return a tuple")
        if len(result) == 2:
            as_of, proposal = result
            return as_of, proposal, {}
        if len(result) == 3:
            as_of, proposal, analysis = result
            return as_of, proposal, dict(analysis or {})
        raise ValueError(
            "analysis_func must return (as_of, proposal) or (as_of, proposal, analysis)"
        )

    def _parse_analysis_results(self, result) -> list[tuple[str, str, OrderProposal, dict]]:
        if isinstance(result, list):
            rows = []
            for item in result:
                if not isinstance(item, tuple):
                    raise ValueError("analysis profile rows must be tuples")
                if len(item) == 4:
                    profile, as_of, proposal, analysis = item
                    rows.append((str(profile), as_of, proposal, dict(analysis or {})))
                else:
                    as_of, proposal, analysis = self._parse_analysis_result(item)
                    rows.append(("normal", as_of, proposal, analysis))
            return rows

        as_of, proposal, analysis = self._parse_analysis_result(result)
        return [(_profile_from_analysis(analysis), as_of, proposal, analysis)]

    def _blocked_strategy(self, proposal: OrderProposal) -> str | None:
        side = _strategy_token(getattr(proposal.side, "value", proposal.side))
        strategy = _strategy_token(proposal.strategy_type)
        setup = _strategy_token(proposal.setup_name)
        for rule in self.config.blocked_strategy_rules:
            strategy_rule, side_rule = _split_block_rule(rule)
            strategy_match = strategy_rule == "*" or strategy_rule in {strategy, setup}
            side_match = side_rule == "*" or side_rule == side
            if strategy_match and side_match:
                return rule
        return None

    def _select_directional_candidate(
        self,
        processed_rows: list[tuple[str, str, OrderProposal, dict, str]],
    ) -> tuple[tuple[str, str, OrderProposal, dict] | None, str, str | None]:
        proposed = [row for row in processed_rows if row[4] == "PROPOSED"]
        normal = next((row for row in proposed if row[0] == "normal"), None)
        fast = next((row for row in proposed if row[0] == "fast"), None)
        if normal and fast and _proposal_side(normal[2]) != _proposal_side(fast[2]):
            return None, "DIRECTIONAL_CONFLICT_HOLD", "FAST_NORMAL_DIRECTION_CONFLICT"
        if fast is not None:
            return fast[:4], "ENTRY_FAST_SELECTED", None
        if normal is not None:
            return normal[:4], "ENTRY_NORMAL_SELECTED", None
        return None, "NO_DIRECTIONAL_CANDIDATE", "NO_PROPOSED_DIRECTIONAL_PROFILE"

    @staticmethod
    def _analysis_health_gate(
        processed_rows: list[tuple[str, str, OrderProposal, dict, str]],
    ) -> dict:
        blocking: list[str] = []
        for _profile, _as_of, _proposal, analysis, _status in processed_rows:
            data_status = (analysis or {}).get("data_status") or {}
            if data_status.get("healthy") is False:
                blocking.extend(
                    f"data_health:{timeframe}"
                    for timeframe in data_status.get("blocking_timeframes") or []
                )
        reasons = list(dict.fromkeys(blocking))
        return health_gate(not reasons, reasons)

    def _candidate_methods(
        self,
        processed_rows: list[tuple[str, str, OrderProposal, dict, str]],
    ) -> dict:
        candidates = {}
        for profile, _as_of, proposal, analysis, status in processed_rows:
            method = _method_for_profile(profile)
            telemetry = (analysis or {}).get("telemetry") or {}
            candidates[method] = {
                "status": status,
                "reason": getattr(proposal, "reason", None)
                or telemetry.get("primary_hold_reason"),
                "selected_profile": profile,
            }
        return candidates

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"last_processed_by_profile": {}}
        return {
            "last_processed_by_profile": {},
            **json.loads(self.state_path.read_text(encoding="utf-8")),
        }

    def _save_state(self, state: dict) -> dict:
        self.state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return state


def _normalize_rule_list(value) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        raw_items = value.split(",")
    else:
        raw_items = list(value)
    normalized = []
    for item in raw_items:
        text = str(item).strip()
        if text:
            normalized.append(text.upper())
    return tuple(normalized)


def _nonnegative_int(value, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a non-negative integer") from exc
    if number < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return number


def _closed_trade_exit_ticket(trade: dict[str, Any]) -> int | None:
    for key in ("exit_deal_ticket", "exit_ticket", "deal", "ticket"):
        value = trade.get(key)
        try:
            ticket = int(value)
        except (TypeError, ValueError):
            continue
        if ticket > 0:
            return ticket
    return None


def _closed_trade_profit(trade: dict[str, Any]) -> float | None:
    try:
        profit = float(trade.get("profit"))
    except (TypeError, ValueError):
        return None
    return profit if math.isfinite(profit) else None


def _closed_loss_streak(history_reconciliation: dict) -> int:
    trades = [
        trade
        for trade in history_reconciliation.get("closed_trades") or []
        if isinstance(trade, dict)
    ]
    latest = history_reconciliation.get("latest_closed_trade")
    if not trades and isinstance(latest, dict) and latest:
        trades = [latest]
    if not trades:
        return 0

    epoch = datetime.min.replace(tzinfo=timezone.utc)
    indexed = list(enumerate(trades))
    ordered = sorted(
        indexed,
        key=lambda item: (
            _parse_utc_datetime(item[1].get("closed_at_utc")) or epoch,
            item[0],
        ),
    )
    streak = 0
    for _index, trade in reversed(ordered):
        profit = _closed_trade_profit(trade)
        if profit is None or profit >= 0:
            break
        streak += 1
    return streak


def _parse_utc_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _split_block_rule(rule: str) -> tuple[str, str]:
    if ":" in rule:
        strategy, side = rule.split(":", 1)
    else:
        strategy, side = rule, "*"
    return _strategy_token(strategy) or "*", _strategy_token(side) or "*"


def _strategy_token(value) -> str:
    text = str(value or "").strip().upper()
    if text == "*":
        return "*"
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _method_for_profile(profile: str) -> str:
    return "ENTRY_FAST" if str(profile).lower() == "fast" else "ENTRY_NORMAL"


def _profile_from_analysis(analysis: dict[str, Any]) -> str:
    telemetry = (analysis or {}).get("telemetry") or {}
    profile = str(
        (analysis or {}).get("entry_profile")
        or telemetry.get("entry_profile")
        or "normal"
    ).strip().lower()
    return "fast" if profile == "fast" else "normal"


def _proposal_side(proposal: OrderProposal) -> str:
    return str(getattr(proposal.side, "value", proposal.side)).upper()
