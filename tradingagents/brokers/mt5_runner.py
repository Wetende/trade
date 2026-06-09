"""Unattended MT5 automation loop."""

from __future__ import annotations

import json
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from tradingagents.agents.schemas import OrderProposal
from tradingagents.brokers.mode_gate import TradingMode, health_gate, mode_value
from tradingagents.brokers.runner_summary import RunnerSummaryStore


@dataclass(frozen=True)
class MT5RunnerConfig:
    results_dir: str | Path
    poll_seconds: int = 30
    max_cycles: int = 0
    max_runtime_seconds: int = 0
    max_session_loss: float = 0.0
    blocked_strategy_rules: tuple[str, ...] = ()
    trading_mode: str = TradingMode.ENTRY_ONLY.value

    def __post_init__(self) -> None:
        poll_seconds = int(self.poll_seconds)
        max_cycles = int(self.max_cycles)
        max_runtime_seconds = int(self.max_runtime_seconds)
        max_session_loss = float(self.max_session_loss)
        trading_mode = mode_value(self.trading_mode)
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
        object.__setattr__(self, "trading_mode", trading_mode)
        object.__setattr__(
            self,
            "blocked_strategy_rules",
            _normalize_rule_list(self.blocked_strategy_rules),
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
        snapshot = self.executor.snapshot_state()
        self.executor.cancel_stale_pending_orders()
        position_management = self.executor.manage_open_positions()
        history_reconciliation = self._reconcile_trade_history()

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

        state = self._load_state()
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
        self._save_state(
            {
                "last_processed_as_of": latest_as_of,
                "last_processed_by_profile": last_processed_by_profile,
            }
        )

        selected, decision, rejection_reason = self._select_directional_candidate(
            processed_rows
        )
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

    def _reconcile_trade_history(self) -> dict:
        reconcile = getattr(self.executor, "reconcile_trade_history", None)
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
            if deadline is not None:
                if time.monotonic() >= deadline:
                    return {
                        "status": "STOPPED_MAX_RUNTIME_SECONDS",
                        "last_result": last_result,
                    }
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    return {
                        "status": "STOPPED_MAX_RUNTIME_SECONDS",
                        "last_result": last_result,
                    }
                time.sleep(min(self.config.poll_seconds, remaining_seconds))
            else:
                time.sleep(self.config.poll_seconds)

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
        return [("normal", as_of, proposal, analysis)]

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


def _proposal_side(proposal: OrderProposal) -> str:
    return str(getattr(proposal.side, "value", proposal.side)).upper()
