"""Deterministic MT5 AutoGate coordinator."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tradingagents.agents.schemas import OrderProposal
from tradingagents.brokers.mode_gate import TradingMode, health_gate, mode_value
from tradingagents.brokers.mt5_runner import (
    _method_for_profile,
    _normalize_rule_list,
    _proposal_side,
)
from tradingagents.brokers.runner_summary import RunnerSummaryStore


@dataclass(frozen=True)
class MT5AutoGateConfig:
    results_dir: str | Path
    poll_seconds: int = 30
    max_cycles: int = 0
    max_runtime_seconds: int = 0
    max_session_loss: float = 0.0
    blocked_strategy_rules: tuple[str, ...] = ()
    trading_mode: str = TradingMode.AUTO_GATED.value

    def __post_init__(self) -> None:
        poll_seconds = int(self.poll_seconds)
        max_cycles = int(self.max_cycles)
        max_runtime_seconds = int(self.max_runtime_seconds)
        max_session_loss = float(self.max_session_loss)
        if poll_seconds < 5:
            raise ValueError("poll_seconds must be at least 5")
        if max_cycles < 0:
            raise ValueError("max_cycles must be non-negative")
        if max_runtime_seconds < 0:
            raise ValueError("max_runtime_seconds must be non-negative")
        if not math.isfinite(max_session_loss) or max_session_loss < 0:
            raise ValueError("max_session_loss must be a finite non-negative number")
        object.__setattr__(self, "poll_seconds", poll_seconds)
        object.__setattr__(self, "max_cycles", max_cycles)
        object.__setattr__(self, "max_runtime_seconds", max_runtime_seconds)
        object.__setattr__(self, "max_session_loss", max_session_loss)
        object.__setattr__(self, "trading_mode", mode_value(self.trading_mode))
        object.__setattr__(
            self,
            "blocked_strategy_rules",
            _normalize_rule_list(self.blocked_strategy_rules),
        )


class MT5AutoGateRunner:
    """Coordinate directional and straddle candidates with one execution path."""

    def __init__(
        self,
        config: MT5AutoGateConfig,
        *,
        directional_executor: Any,
        straddle_executor: Any,
        directional_analysis_func: Callable[[], tuple[str, OrderProposal] | list],
        straddle_config: Any,
        current_as_of_func: Callable[[], str] | None = None,
        straddle_exit_management: Any | None = None,
        straddle_entry_regime: Any | None = None,
    ) -> None:
        self.config = config
        self.directional_executor = directional_executor
        self.straddle_executor = straddle_executor
        self.directional_analysis_func = directional_analysis_func
        self.straddle_config = straddle_config
        self.current_as_of_func = current_as_of_func
        self.straddle_exit_management = straddle_exit_management
        self.straddle_entry_regime = straddle_entry_regime
        self.runner_dir = Path(config.results_dir) / "mt5_autogate"
        self.runner_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path = self.runner_dir / "heartbeat.json"
        self.summary_store = RunnerSummaryStore(config.results_dir)
        self.history_since_utc = datetime.now(timezone.utc)

    def run_once(self) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc).isoformat()
        snapshot = self.directional_executor.snapshot_state()
        stale_orders = self.directional_executor.cancel_stale_pending_orders()
        straddle_monitor = self._call_straddle_monitor()
        position_management = self.directional_executor.manage_open_positions()
        history_reconciliation = self._reconcile_trade_history()

        if snapshot.get("orders") or snapshot.get("positions"):
            return self._write_heartbeat(
                {
                    "status": "ACTIVE_TRADE_MONITORED",
                    "started_at_utc": started_at,
                    "selected_method": "HOLD",
                    "selected_profile": None,
                    "mode_decision": "ACTIVE_TRADE_MANAGED",
                    "mode_rejection_reason": "ACTIVE_TRADE_EXISTS",
                    "health_gate": health_gate(False, ["active_trade"]),
                    "stale_orders": stale_orders,
                    "straddle_monitor": straddle_monitor,
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
                    "selected_method": "HOLD",
                    "selected_profile": None,
                    "mode_decision": "RISK_LIMIT_REACHED",
                    "mode_rejection_reason": "SESSION_LOSS_LIMIT",
                    "health_gate": health_gate(False, ["session_loss_limit"]),
                    "risk_limit": risk_limit,
                    "stale_orders": stale_orders,
                    "straddle_monitor": straddle_monitor,
                    "position_management": position_management,
                    "history_reconciliation": history_reconciliation,
                }
            )

        try:
            analysis_result = self.directional_analysis_func()
            directional_rows = self._parse_analysis_results(analysis_result)
        except Exception as exc:
            return self._write_heartbeat(
                {
                    "status": "AUTOGATE_ERROR",
                    "started_at_utc": started_at,
                    "selected_method": "HOLD",
                    "selected_profile": None,
                    "mode_decision": "DIRECTIONAL_ANALYSIS_ERROR",
                    "mode_rejection_reason": type(exc).__name__,
                    "health_gate": health_gate(False, ["directional_analysis_error"]),
                    "analysis": {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                    "history_reconciliation": history_reconciliation,
                }
            )

        selected, decision, rejection_reason = self._select_directional_candidate(
            directional_rows
        )
        candidate_methods = self._candidate_methods(directional_rows)
        if decision == "DIRECTIONAL_CONFLICT_HOLD":
            return self._write_heartbeat(
                {
                    "status": "NO_TRADE",
                    "started_at_utc": started_at,
                    "selected_method": "HOLD",
                    "selected_profile": None,
                    "mode_decision": decision,
                    "mode_rejection_reason": rejection_reason,
                    "health_gate": health_gate(False, ["directional_conflict"]),
                    "candidate_methods": candidate_methods,
                    "history_reconciliation": history_reconciliation,
                }
            )

        straddle_candidate = self._evaluate_straddle_candidate()
        candidate_methods["STRADDLE"] = _straddle_candidate_summary(
            straddle_candidate
        )

        if selected is not None:
            profile, as_of, proposal, analysis = selected
            selected_method = _method_for_profile(profile)
            execution = self.directional_executor.execute_proposal(proposal)
            return self._write_heartbeat(
                {
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
                    "candidate_methods": candidate_methods,
                    "as_of": as_of,
                    "proposal": proposal.model_dump(mode="json"),
                    "analysis": analysis,
                    "execution": execution,
                    "history_reconciliation": history_reconciliation,
                }
            )

        if str(straddle_candidate.get("status") or "").upper() == "PROPOSED":
            pair = straddle_candidate.get("pair")
            execution = self.straddle_executor.execute_pair(pair, live=True)
            return self._write_heartbeat(
                {
                    "status": (
                        "STRADDLE_ORDER_PLACED"
                        if execution.get("status") == "PAIR_PLACED"
                        else "STRADDLE_ORDER_NOT_PLACED"
                    ),
                    "started_at_utc": started_at,
                    "selected_method": "STRADDLE",
                    "selected_profile": None,
                    "mode_decision": "STRADDLE_SELECTED",
                    "mode_rejection_reason": None,
                    "candidate_methods": candidate_methods,
                    "straddle_candidate": _jsonable_candidate(straddle_candidate),
                    "execution": execution,
                    "history_reconciliation": history_reconciliation,
                }
            )

        return self._write_heartbeat(
            {
                "status": "NO_TRADE",
                "started_at_utc": started_at,
                "selected_method": "HOLD",
                "selected_profile": None,
                "mode_decision": "NO_AUTOGATE_CANDIDATE",
                "mode_rejection_reason": "NO_METHOD_QUALIFIED",
                "candidate_methods": candidate_methods,
                "history_reconciliation": history_reconciliation,
            }
        )

    def run_forever(self) -> dict[str, Any]:
        cycles = 0
        last_result: dict[str, Any] = {"status": "NOT_STARTED"}
        deadline = (
            time.monotonic() + self.config.max_runtime_seconds
            if self.config.max_runtime_seconds
            else None
        )
        while True:
            last_result = self.run_once()
            cycles += 1
            if last_result.get("status") == "RISK_LIMIT_REACHED":
                return {"status": "STOPPED_RISK_LIMIT", "last_result": last_result}
            if (
                deadline is None
                and self.config.max_cycles
                and cycles >= self.config.max_cycles
            ):
                return {"status": "STOPPED_MAX_CYCLES", "last_result": last_result}
            if deadline is not None and time.monotonic() >= deadline:
                return {
                    "status": "STOPPED_MAX_RUNTIME_SECONDS",
                    "last_result": last_result,
                }
            if deadline is not None:
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    return {
                        "status": "STOPPED_MAX_RUNTIME_SECONDS",
                        "last_result": last_result,
                    }
                time.sleep(min(self.config.poll_seconds, remaining_seconds))
            else:
                time.sleep(self.config.poll_seconds)

    def _call_straddle_monitor(self) -> dict[str, Any]:
        monitor = getattr(self.straddle_executor, "monitor_pair", None)
        if not callable(monitor):
            return {"status": "UNAVAILABLE"}
        return monitor()

    def _evaluate_straddle_candidate(self) -> dict[str, Any]:
        evaluate = getattr(self.straddle_executor, "evaluate_entry_candidate", None)
        if not callable(evaluate):
            return {
                "status": "STRADDLE_SKIPPED",
                "reason": "STRADDLE_CANDIDATE_EVALUATOR_UNAVAILABLE",
            }
        return evaluate(
            self.straddle_config,
            exit_management=self.straddle_exit_management,
            entry_regime=self.straddle_entry_regime,
        )

    def _reconcile_trade_history(self) -> dict[str, Any]:
        reconcile = getattr(self.directional_executor, "reconcile_trade_history", None)
        if not callable(reconcile):
            return {"status": "UNAVAILABLE"}
        try:
            return reconcile(
                since_utc=self.history_since_utc,
                now_utc=datetime.now(timezone.utc),
            )
        except Exception as exc:
            return {
                "status": "RECONCILE_ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }

    def _session_loss_limit(self, history_reconciliation: dict[str, Any]) -> dict | None:
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

    def _parse_analysis_results(
        self,
        result,
    ) -> list[tuple[str, str, OrderProposal, dict, str]]:
        if isinstance(result, list):
            rows = []
            for item in result:
                if not isinstance(item, tuple):
                    raise ValueError("analysis profile rows must be tuples")
                if len(item) == 4:
                    profile, as_of, proposal, analysis = item
                else:
                    as_of, proposal, analysis = self._parse_analysis_result(item)
                    profile = "normal"
                status = str(getattr(proposal.status, "value", proposal.status)).upper()
                rows.append((str(profile), as_of, proposal, dict(analysis or {}), status))
            return rows
        as_of, proposal, analysis = self._parse_analysis_result(result)
        status = str(getattr(proposal.status, "value", proposal.status)).upper()
        return [("normal", as_of, proposal, analysis, status)]

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

    def _candidate_methods(
        self,
        processed_rows: list[tuple[str, str, OrderProposal, dict, str]],
    ) -> dict[str, Any]:
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

    def _write_heartbeat(self, result: dict[str, Any]) -> dict[str, Any]:
        account_safety = result.get("account_safety")
        execution = result.get("execution")
        if account_safety is None and isinstance(execution, dict):
            account_safety = execution.get("account_safety")
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
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        return payload


def _straddle_candidate_summary(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": str(candidate.get("status") or "UNKNOWN"),
        "reason": candidate.get("reason") or candidate.get("error"),
        "selected_profile": None,
    }


def _jsonable_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(candidate)
    pair = cleaned.get("pair")
    if hasattr(pair, "model_dump"):
        cleaned["pair"] = pair.model_dump(mode="json")
    elif pair is not None:
        cleaned["pair"] = str(pair)
    return cleaned
