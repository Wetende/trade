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


def categorize_hold_reason(reason: str, telemetry: dict[str, Any] | None = None) -> str:
    telemetry = telemetry or {}
    stage = str(telemetry.get("decision_stage") or "").lower()
    text = " ".join(
        [
            str(reason or ""),
            str(telemetry.get("primary_hold_reason") or ""),
            stage,
        ]
    ).lower()

    if "data" in stage or "insufficient" in text or "stale" in text or "no price data" in text:
        return "data_health"
    if "higher" in stage or "daily blocks" in text or "h4 blocks" in text or "h1 must agree" in text:
        return "higher_timeframe"
    if "time" in stage or "time filter" in text or "session" in text or "last 15" in text or "pre-open" in text:
        return "time_filter"
    if "m15" in text or "no valid" in text or "playbook setup" in text:
        return "no_m15_setup"
    if "risk" in stage or "clean range" in text or "1.5r" in text:
        return "risk_or_range"
    if "wick" in text:
        return "wick_quality"
    if "active trade" in text:
        return "active_trade"
    if "already processed" in text:
        return "duplicate_candle"
    return "other"


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
            "hold_reason_counts": {},
            "orders_placed": 0,
            "orders_rejected": 0,
            "broker_rejections": 0,
            "data_health": {
                "healthy_checks": 0,
                "unhealthy_checks": 0,
                "latest_status": {},
            },
            "latest_cycle": {},
        }

    def record_cycle(self, result: dict[str, Any]) -> dict[str, Any]:
        summary = _read_json(self.summary_path, self._empty_summary())
        status = str(result.get("status") or "UNKNOWN")
        analysis = result.get("analysis") or {}
        telemetry = analysis.get("telemetry") or {}
        proposal = result.get("proposal") or {}
        reason = str(proposal.get("reason") or telemetry.get("primary_hold_reason") or status)

        status_counts = Counter(summary.get("status_counts", {}))
        status_counts[status] += 1
        summary["status_counts"] = dict(status_counts)
        summary["total_checks"] = int(summary.get("total_checks", 0)) + 1
        summary["updated_at_utc"] = _utc_now()

        if status == "NO_TRADE":
            hold_reason = categorize_hold_reason(reason, telemetry)
            hold_counts = Counter(summary.get("hold_reason_counts", {}))
            hold_counts[hold_reason] += 1
            summary["hold_reason_counts"] = dict(hold_counts)

        execution = result.get("execution") or {}
        if status == "ORDER_PLACED":
            summary["orders_placed"] = int(summary.get("orders_placed", 0)) + 1
        if status == "ORDER_NOT_PLACED":
            summary["orders_rejected"] = int(summary.get("orders_rejected", 0)) + 1
        if execution.get("status") == "REJECTED":
            summary["broker_rejections"] = int(summary.get("broker_rejections", 0)) + 1

        data_status = analysis.get("data_status") or {}
        if data_status:
            data_health = summary.setdefault("data_health", {})
            data_health["latest_status"] = data_status
            if data_status.get("healthy", True):
                data_health["healthy_checks"] = int(data_health.get("healthy_checks", 0)) + 1
            else:
                data_health["unhealthy_checks"] = int(data_health.get("unhealthy_checks", 0)) + 1

        summary["latest_cycle"] = {
            "status": status,
            "as_of": result.get("as_of"),
            "heartbeat_utc": result.get("heartbeat_utc"),
            "hold_reason": categorize_hold_reason(reason, telemetry) if status == "NO_TRADE" else None,
        }
        self._append_cycle(result)
        self._write_summary(summary)
        return summary

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
