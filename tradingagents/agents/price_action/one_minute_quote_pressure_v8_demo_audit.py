"""Audit completed 0.01-volume V8 DEMO sessions for volume-one promotion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import (
    CANDIDATE_NAME,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_evidence import (
    V8EvidenceCounters,
    V8EvidenceRow,
    evaluate_v8_evidence,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_promotion import (
    sha256_file,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_screening import (
    validate_v8_manifest,
)


def audit_v8_demo_sessions(
    session_paths: Iterable[str | Path],
    *,
    manifest_path: str | Path,
) -> dict[str, Any]:
    """Produce the hash-addressed frozen ``DEMO_0_01`` evidence report."""
    manifest_file = Path(manifest_path).resolve()
    validate_v8_manifest(manifest_file)
    sessions = tuple(Path(value).resolve() for value in session_paths)
    if not sessions:
        raise ValueError("at least one completed V8 DEMO session is required")

    rows: list[V8EvidenceRow] = []
    sources: list[dict[str, Any]] = []
    totals = {field: 0 for field in V8EvidenceCounters.__dataclass_fields__}
    violations: list[str] = []
    manifest_hash = sha256_file(manifest_file)

    for session in sessions:
        runner = session / "mt5_one_minute_v8"
        state_path = runner / "state.json"
        receipt_path = runner / "promotion_receipt.json"
        events_path = runner / "events.jsonl"
        for artifact in (state_path, receipt_path, events_path):
            if not artifact.is_file():
                raise ValueError(f"V8 DEMO session artifact is missing: {artifact}")
        state = _object(state_path)
        receipt = _object(receipt_path)
        events, event_errors = _events(events_path)
        local_violations: list[str] = []

        if state.get("candidate") != CANDIDATE_NAME:
            local_violations.append("candidate_mismatch")
        if state.get("phase") != "COMPLETE":
            local_violations.append("session_not_drained_flat")
        if float(state.get("volume") or 0.0) != 0.01:
            local_violations.append("volume_not_0_01")
        if state.get("manifest_sha256") != manifest_hash:
            local_violations.append("state_manifest_hash_mismatch")
        if receipt.get("manifest_sha256") != manifest_hash:
            local_violations.append("receipt_manifest_hash_mismatch")
        if receipt.get("approved_volume_cap") != 0.01:
            local_violations.append("initial_demo_promotion_missing")
        safety = receipt.get("account_safety") or {}
        if safety.get("passed") is not True or safety.get("trade_mode") != "DEMO":
            local_violations.append("demo_account_proof_failed")
        if receipt.get("zero_initial_orders") is not True:
            local_violations.append("initial_orders_not_zero")
        if receipt.get("zero_initial_positions") is not True:
            local_violations.append("initial_positions_not_zero")

        history = state.get("last_history") or {}
        if history.get("status") != "RECONCILED":
            local_violations.append("broker_reconciliation_incomplete")
        session_rows = []
        for raw in state.get("evidence_rows") or []:
            try:
                row = V8EvidenceRow(**dict(raw))
            except (TypeError, ValueError):
                event_errors += 1
                continue
            if row.session_id != session.name:
                local_violations.append("session_id_mismatch")
            session_rows.append(row)
        closed_rows = [row for row in session_rows if row.closed_at and row.profit_r is not None]
        if int(history.get("closed_trade_count") or 0) != len(closed_rows):
            local_violations.append("closed_trade_reconciliation_mismatch")
        submissions = state.get("submissions") or {}
        for submission in submissions.values():
            if submission.get("filled_at") and submission.get("entry_drift_compliant") is not True:
                local_violations.append("live_entry_drift_noncompliant")
        rows.extend(session_rows)

        totals["arms_detected"] += len(
            {str(event.get("arm_id")) for event in events if event.get("event") == "ARMED"}
        )
        totals["valid_triggers"] += len(submissions)
        totals["placements"] += len(submissions)
        totals["fills"] += sum(row.filled for row in session_rows)
        reconciliation_violations = sum(
            value in {
                "broker_reconciliation_incomplete",
                "closed_trade_reconciliation_mismatch",
            }
            for value in local_violations
        )
        drift_violations = sum(
            value == "live_entry_drift_noncompliant" for value in local_violations
        )
        safety_violations = sum(
            value
            in {
                "candidate_mismatch",
                "session_not_drained_flat",
                "volume_not_0_01",
                "state_manifest_hash_mismatch",
                "receipt_manifest_hash_mismatch",
                "initial_demo_promotion_missing",
                "demo_account_proof_failed",
                "initial_orders_not_zero",
                "initial_positions_not_zero",
            }
            for value in local_violations
        )
        lifecycle_violations = sum(
            value == "session_id_mismatch" for value in local_violations
        )
        totals["safety_failures"] += int(state.get("safety_failures") or 0) + safety_violations
        totals["telemetry_failures"] += int(
            state.get("telemetry_failures") or 0
        ) + event_errors
        totals["reconciliation_failures"] += max(
            int(state.get("reconciliation_failures") or 0),
            reconciliation_violations,
        )
        totals["entry_drift_failures"] += max(
            int(state.get("entry_drift_failures") or 0),
            drift_violations,
        )
        totals["lifecycle_failures"] += int(
            state.get("lifecycle_failures") or 0
        ) + lifecycle_violations
        totals["restart_failures"] += int(state.get("restart_failures") or 0)
        violations.extend(f"{session.name}:{value}" for value in local_violations)
        sources.append(
            {
                "session": session.name,
                "path": str(session),
                "started_at_utc": state.get("started_at_utc"),
                "completed_at_utc": state.get("completed_at_utc"),
                "volume": state.get("volume"),
                "account_mode": safety.get("trade_mode"),
                "state_sha256": sha256_file(state_path),
                "promotion_receipt_sha256": sha256_file(receipt_path),
                "events_sha256": sha256_file(events_path),
                "closed_trade_count": len(closed_rows),
                "violations": local_violations,
            }
        )

    counters = V8EvidenceCounters(**totals)
    gate = evaluate_v8_evidence("DEMO_0_01", rows, counters).as_dict()
    gate.update(
        {
            "schema_version": 1,
            "manifest_path": str(manifest_file),
            "manifest_sha256": manifest_hash,
            "broker_mutation_enabled": True,
            "account_mode": "DEMO_ONLY",
            "real_account_mutations": 0,
            "sources": sources,
            "rows": [row.as_dict() for row in rows],
            "audit_violations": violations,
            "complete_broker_reconciliation": counters.reconciliation_failures == 0,
            "compliant_live_entry_drift": counters.entry_drift_failures == 0,
            "failed_gate_action": "VOLUME_ONE_NOT_APPROVED" if gate["retired"] else None,
        }
    )
    return gate


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read V8 DEMO artifact: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"V8 DEMO artifact must be an object: {path}")
    return value


def _events(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    errors = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            errors += 1
            continue
        if isinstance(value, dict):
            events.append(value)
        else:
            errors += 1
    return events, errors


__all__ = ["audit_v8_demo_sessions"]
