"""Aggregate MT5 runner cycle summaries."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def categorize_hold_reason(
    reason: str,
    telemetry: dict[str, Any] | None = None,
    data_status: dict[str, Any] | None = None,
) -> str:
    telemetry = telemetry or {}
    stage = str(telemetry.get("decision_stage") or "").lower()
    primary = str(telemetry.get("primary_hold_reason") or "").lower()

    if data_status and data_status.get("healthy") is False:
        return "data_health"
    if "data" in stage or "insufficient" in stage:
        return "data_health"
    if "higher" in stage:
        return "higher_timeframe"
    if "time" in stage:
        return "time_filter"
    if "m15" in stage or "playbook" in stage:
        return "no_m15_setup"
    if "risk" in stage or "range" in stage:
        return "risk_or_range"

    telemetry_text = " ".join([primary, stage]).lower()
    if "insufficient" in telemetry_text or "stale" in telemetry_text or "no price data" in telemetry_text:
        return "data_health"
    if "daily blocks" in telemetry_text or "h4 blocks" in telemetry_text or "h1 must agree" in telemetry_text:
        return "higher_timeframe"
    if "time filter" in telemetry_text or "session" in telemetry_text or "last 15" in telemetry_text or "pre-open" in telemetry_text:
        return "time_filter"
    if "m15" in telemetry_text or "no valid" in telemetry_text or "playbook setup" in telemetry_text:
        return "no_m15_setup"
    if "clean range" in telemetry_text or "1.5r" in telemetry_text or "risk" in telemetry_text:
        return "risk_or_range"
    if "wick" in telemetry_text:
        return "wick_quality"

    text = str(reason or "").lower()
    if "insufficient" in text or "stale" in text or "no price data" in text:
        return "data_health"
    if "daily blocks" in text or "h4 blocks" in text or "h1 must agree" in text:
        return "higher_timeframe"
    if "time filter" in text or "session" in text or "last 15" in text or "pre-open" in text:
        return "time_filter"
    if "m15" in text or "no valid" in text or "playbook setup" in text:
        return "no_m15_setup"
    if "clean range" in text or "1.5r" in text or "risk" in text:
        return "risk_or_range"
    if "wick" in text:
        return "wick_quality"
    if "active trade" in text:
        return "active_trade"
    if "already processed" in text:
        return "duplicate_candle"
    return "other"


def _latest_market_health(
    telemetry_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    for telemetry in reversed(telemetry_sources):
        market_health = telemetry.get("market_health")
        if isinstance(market_health, dict):
            return market_health
    return {}


def _trade_profit(trade: dict[str, Any]) -> float:
    try:
        return float(trade.get("profit") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _closed_trade_identity(trade: dict[str, Any]) -> str | None:
    position_id = trade.get("position_id")
    if position_id not in (None, ""):
        return f"position:{position_id}"
    entry_ticket = trade.get("entry_deal_ticket")
    if entry_ticket not in (None, ""):
        return f"entry:{entry_ticket}"
    return None


def _closed_exit_key(trade: dict[str, Any]) -> str:
    return str(
        trade.get("exit_deal_ticket")
        or f"position:{trade.get('position_id')}:exit"
    )


def _apply_closed_trade_stats(
    history: dict[str, Any],
    profit: float,
    multiplier: int,
) -> None:
    history["closed_trade_count"] = max(
        0,
        int(history["closed_trade_count"]) + multiplier,
    )
    history["net_profit"] = round(
        float(history["net_profit"]) + (profit * multiplier),
        2,
    )
    if profit > 0:
        history["wins"] = max(0, int(history["wins"]) + multiplier)
        history["gross_profit"] = round(
            float(history["gross_profit"]) + (profit * multiplier),
            2,
        )
    elif profit < 0:
        history["losses"] = max(0, int(history["losses"]) + multiplier)
        history["gross_loss"] = round(
            float(history["gross_loss"]) + (profit * multiplier),
            2,
        )
    else:
        history["break_even"] = max(0, int(history["break_even"]) + multiplier)


class RunnerSummaryStore:
    """Write one JSON summary and one JSONL cycle log for MT5 runner checks."""

    def __init__(self, results_dir: str | Path) -> None:
        self.runner_dir = Path(results_dir) / "mt5_runner"
        self.runner_dir.mkdir(parents=True, exist_ok=True)
        self.summary_path = self.runner_dir / "summary.json"
        self.cycles_path = self.runner_dir / "cycles.jsonl"

    def _empty_summary(self) -> dict[str, Any]:
        now = _utc_now()
        return {
            "started_at_utc": now,
            "updated_at_utc": now,
            "total_checks": 0,
            "status_counts": {},
            "profile_status_counts": {},
            "hold_reason_counts": {},
            "orders_placed": 0,
            "orders_rejected": 0,
            "orders_skipped": 0,
            "broker_rejections": 0,
            "execution_skip_counts": {},
            "candidate_strategy_counts": {},
            "approved_candidate_strategy_counts": {},
            "candidate_rejection_reason_counts": {},
            "market_state_counts": {},
            "market_health_reason_counts": {},
            "data_health": {
                "healthy_checks": 0,
                "unhealthy_checks": 0,
                "latest_status": {},
            },
            "trade_history": {
                "filled_trade_count": 0,
                "closed_trade_count": 0,
                "wins": 0,
                "losses": 0,
                "break_even": 0,
                "net_profit": 0.0,
                "gross_profit": 0.0,
                "gross_loss": 0.0,
                "processed_entry_deal_tickets": [],
                "processed_exit_deal_tickets": [],
                "filled_trades": [],
                "closed_trades": [],
                "latest_filled_trade": {},
                "latest_closed_trade": {},
                "latest_reconciliation": {},
            },
            "latest_execution": {},
            "latest_cycle": {},
        }

    def _record_profile_status(self, summary: dict, profile: str, status: str) -> None:
        profile_counts = summary.setdefault("profile_status_counts", {})
        counts = profile_counts.setdefault(profile, {})
        counts[status] = int(counts.get(status, 0)) + 1

    def record_cycle(self, result: dict[str, Any]) -> dict[str, Any]:
        summary = _read_json(self.summary_path, self._empty_summary())
        status = str(result.get("status") or "UNKNOWN")
        countable_check = status != "CANDLE_ALREADY_PROCESSED"
        analysis = result.get("analysis") or {}
        telemetry = analysis.get("telemetry") or {}
        data_status = analysis.get("data_status") or {}
        proposal = result.get("proposal") or {}
        reason = str(proposal.get("reason") or telemetry.get("primary_hold_reason") or status)
        profile_rows = [
            row for row in (result.get("profiles") or []) if isinstance(row, dict)
        ]

        hold_contexts: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        data_statuses: list[dict[str, Any]] = []
        telemetry_sources: list[dict[str, Any]] = []
        if profile_rows:
            for profile_row in profile_rows:
                profile_analysis = profile_row.get("analysis") or {}
                profile_telemetry = profile_analysis.get("telemetry") or {}
                profile_data_status = profile_analysis.get("data_status") or {}
                profile_proposal = profile_row.get("proposal") or {}
                telemetry_sources.append(profile_telemetry)
                if profile_data_status:
                    data_statuses.append(profile_data_status)
                if str(profile_row.get("status") or "").upper() == "NO_TRADE":
                    profile_reason = str(
                        profile_proposal.get("reason")
                        or profile_telemetry.get("primary_hold_reason")
                        or profile_row.get("status")
                        or status
                    )
                    hold_contexts.append(
                        (profile_reason, profile_telemetry, profile_data_status)
                    )
        else:
            telemetry_sources.append(telemetry)
            if data_status:
                data_statuses.append(data_status)
            if status == "NO_TRADE":
                hold_contexts.append((reason, telemetry, data_status))

        if countable_check:
            status_counts = Counter(summary.get("status_counts", {}))
            status_counts[status] += 1
            summary["status_counts"] = dict(status_counts)
            summary["total_checks"] = int(summary.get("total_checks", 0)) + 1
            if result.get("entry_profile"):
                self._record_profile_status(
                    summary,
                    str(result["entry_profile"]),
                    status,
                )
            for profile_row in result.get("profiles") or []:
                self._record_profile_status(
                    summary,
                    str(profile_row.get("entry_profile", "normal")),
                    str(profile_row.get("status", "UNKNOWN")),
                )
        summary["updated_at_utc"] = _utc_now()

        candidate_counts = Counter(summary.get("candidate_strategy_counts", {}))
        approved_candidate_counts = Counter(
            summary.get("approved_candidate_strategy_counts", {})
        )
        rejection_reason_counts = Counter(
            summary.get("candidate_rejection_reason_counts", {})
        )
        market_state_counts = Counter(summary.get("market_state_counts", {}))
        market_health_reason_counts = Counter(
            summary.get("market_health_reason_counts", {})
        )
        for telemetry_source in telemetry_sources:
            for item in telemetry_source.get("candidate_evaluations") or []:
                setup = item.get("setup") or {}
                setup_name = str(setup.get("name") or "unknown")
                candidate_counts[setup_name] += 1
                if item.get("approved") is True:
                    approved_candidate_counts[setup_name] += 1
                else:
                    reason = str(item.get("rejection_reason") or "UNKNOWN")
                    rejection_reason_counts[reason] += 1
            for timeframe, state in (telemetry_source.get("market_state") or {}).items():
                if not isinstance(state, dict):
                    continue
                trend = str(state.get("trend_state") or "UNKNOWN")
                direction = str(state.get("direction") or "NEUTRAL")
                market_state_counts[f"{timeframe}:{trend}:{direction}"] += 1
            market_health = telemetry_source.get("market_health") or {}
            if market_health.get("passed") is False:
                for reason in market_health.get("reasons") or ["market_health_failed"]:
                    market_health_reason_counts[str(reason)] += 1
        summary["candidate_strategy_counts"] = dict(candidate_counts)
        summary["approved_candidate_strategy_counts"] = dict(approved_candidate_counts)
        summary["candidate_rejection_reason_counts"] = dict(rejection_reason_counts)
        summary["market_state_counts"] = dict(market_state_counts)
        summary["market_health_reason_counts"] = dict(market_health_reason_counts)

        if countable_check and status == "NO_TRADE":
            hold_counts = Counter(summary.get("hold_reason_counts", {}))
            for hold_reason, hold_telemetry, hold_data_status in hold_contexts:
                hold_counts[
                    categorize_hold_reason(
                        hold_reason,
                        hold_telemetry,
                        hold_data_status,
                    )
                ] += 1
            summary["hold_reason_counts"] = dict(hold_counts)

        execution = result.get("execution") or {}
        if status == "ORDER_PLACED":
            summary["orders_placed"] = int(summary.get("orders_placed", 0)) + 1
        if status == "ORDER_NOT_PLACED":
            summary["orders_rejected"] = int(summary.get("orders_rejected", 0)) + 1
        if execution.get("status") == "REJECTED":
            summary["broker_rejections"] = int(summary.get("broker_rejections", 0)) + 1
        execution_status = str(execution.get("status") or "")
        if execution_status.startswith("SKIPPED"):
            summary["orders_skipped"] = int(summary.get("orders_skipped", 0)) + 1
            reason_key = str(execution.get("reason") or "UNKNOWN")
            skip_counts = Counter(summary.get("execution_skip_counts", {}))
            skip_counts[reason_key] += 1
            summary["execution_skip_counts"] = dict(skip_counts)

        if execution:
            broker_result = execution.get("broker_result") or {}
            request = broker_result.get("request") or {}
            execution_proposal = (
                execution.get("proposal")
                or proposal
                or {}
            )
            summary["latest_execution"] = {
                "status": execution_status or None,
                "reason": execution.get("reason"),
                "error": execution.get("error"),
                "retcode": broker_result.get("retcode"),
                "comment": broker_result.get("comment"),
                "order_check": execution.get("order_check_result") or {},
                "request_type": request.get("type"),
                "order": execution.get("order"),
                "setup_name": execution_proposal.get("setup_name"),
                "strategy_type": execution_proposal.get("strategy_type"),
                "side": execution_proposal.get("side"),
                "order_type": execution_proposal.get("order_type"),
                "as_of": result.get("as_of"),
                "heartbeat_utc": result.get("heartbeat_utc"),
            }

        if countable_check and data_statuses:
            data_health = summary.setdefault("data_health", {})
            for current_data_status in data_statuses:
                data_health["latest_status"] = current_data_status
                if current_data_status.get("healthy", True):
                    data_health["healthy_checks"] = int(data_health.get("healthy_checks", 0)) + 1
                else:
                    data_health["unhealthy_checks"] = int(data_health.get("unhealthy_checks", 0)) + 1

        self._record_trade_history(
            summary,
            result.get("history_reconciliation") or {},
        )

        latest_hold_reason = None
        if status == "NO_TRADE":
            categorized_reasons = [
                categorize_hold_reason(
                    hold_reason,
                    hold_telemetry,
                    hold_data_status,
                )
                for hold_reason, hold_telemetry, hold_data_status in hold_contexts
            ]
            unique_reasons = sorted(set(categorized_reasons))
            if len(unique_reasons) == 1:
                latest_hold_reason = unique_reasons[0]
            elif len(unique_reasons) > 1:
                latest_hold_reason = "mixed"

        summary["latest_cycle"] = {
            "status": status,
            "as_of": result.get("as_of"),
            "heartbeat_utc": result.get("heartbeat_utc"),
            "hold_reason": latest_hold_reason,
            "trading_mode": result.get("trading_mode"),
            "selected_method": result.get("selected_method"),
            "selected_profile": result.get("selected_profile"),
            "mode_decision": result.get("mode_decision"),
            "mode_rejection_reason": result.get("mode_rejection_reason"),
            "health_gate": result.get("health_gate") or {},
            "market_health": _latest_market_health(telemetry_sources),
            "account_safety": result.get("account_safety") or {},
        }
        self._append_cycle(result)
        self._write_summary(summary)
        return summary

    def _record_trade_history(
        self,
        summary: dict[str, Any],
        reconciliation: dict[str, Any],
    ) -> None:
        if not reconciliation:
            return

        history = summary.setdefault("trade_history", {})
        history.setdefault("filled_trade_count", 0)
        history.setdefault("closed_trade_count", 0)
        history.setdefault("wins", 0)
        history.setdefault("losses", 0)
        history.setdefault("break_even", 0)
        history.setdefault("net_profit", 0.0)
        history.setdefault("gross_profit", 0.0)
        history.setdefault("gross_loss", 0.0)
        history.setdefault("processed_entry_deal_tickets", [])
        history.setdefault("processed_exit_deal_tickets", [])
        history.setdefault("filled_trades", [])
        history.setdefault("closed_trades", [])
        history["latest_reconciliation"] = {
            key: value
            for key, value in reconciliation.items()
            if key not in {"filled_trades", "closed_trades"}
        }

        seen_entries = {
            str(ticket) for ticket in history.get("processed_entry_deal_tickets", [])
        }
        seen_exits = {
            str(ticket) for ticket in history.get("processed_exit_deal_tickets", [])
        }
        closed_index_by_identity = {
            identity: index
            for index, closed_trade in enumerate(history["closed_trades"])
            if (identity := _closed_trade_identity(closed_trade)) is not None
        }

        for trade in reconciliation.get("filled_trades") or []:
            entry_key = str(
                trade.get("entry_deal_ticket")
                or f"position:{trade.get('position_id')}:entry"
            )
            if entry_key not in seen_entries:
                seen_entries.add(entry_key)
                history["filled_trade_count"] = int(history["filled_trade_count"]) + 1
                history["filled_trades"].append(trade)
                history["latest_filled_trade"] = trade

        for trade in reconciliation.get("closed_trades") or []:
            entry_key = str(
                trade.get("entry_deal_ticket")
                or f"position:{trade.get('position_id')}:entry"
            )
            if entry_key not in seen_entries:
                seen_entries.add(entry_key)
                history["filled_trade_count"] = int(history["filled_trade_count"]) + 1
                fill_trade = {
                    key: trade.get(key)
                    for key in (
                        "position_id",
                        "entry_deal_ticket",
                        "entry_order",
                        "side",
                        "volume",
                        "entry_price",
                        "opened_at_utc",
                    )
                    if key in trade
                }
                history["filled_trades"].append(fill_trade)
                history["latest_filled_trade"] = fill_trade

            exit_key = _closed_exit_key(trade)
            closed_identity = _closed_trade_identity(trade)
            existing_index = (
                closed_index_by_identity.get(closed_identity)
                if closed_identity is not None
                else None
            )
            if exit_key in seen_exits and existing_index is None:
                continue

            profit = _trade_profit(trade)
            if existing_index is not None:
                existing_trade = history["closed_trades"][existing_index]
                if _closed_exit_key(existing_trade) == exit_key:
                    continue
                _apply_closed_trade_stats(
                    history,
                    _trade_profit(existing_trade),
                    -1,
                )
                history["closed_trades"][existing_index] = trade
                _apply_closed_trade_stats(history, profit, 1)
            else:
                history["closed_trades"].append(trade)
                _apply_closed_trade_stats(history, profit, 1)
                if closed_identity is not None:
                    closed_index_by_identity[closed_identity] = (
                        len(history["closed_trades"]) - 1
                    )
            seen_exits.add(exit_key)
            history["latest_closed_trade"] = trade

        history["processed_entry_deal_tickets"] = sorted(seen_entries)
        history["processed_exit_deal_tickets"] = sorted(seen_exits)

    def _append_cycle(self, result: dict[str, Any]) -> None:
        line = json.dumps(result, sort_keys=True, default=str) + "\n"
        with self.cycles_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _write_summary(self, summary: dict[str, Any]) -> None:
        temp_path = self.summary_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        temp_path.replace(self.summary_path)
