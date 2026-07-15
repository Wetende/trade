"""Bounded offline learning memory for the One Minute Scalper.

This module may summarize completed run evidence and retired-candidate reports.
It deliberately cannot edit strategy configuration, contact a broker, create a
promotion record, or authorize an order-capable process.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from tradingagents.agents.price_action.evidence_export import export_session
from tradingagents.agents.price_action.evidence_gate import EvidenceSession
from tradingagents.agents.price_action.failure_learning import build_learning_report


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _as_utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise ValueError("learning timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _collect_timestamps(value: Any) -> list[datetime]:
    timestamps: list[datetime] = []
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if isinstance(nested, str) and (
                key.endswith("_utc") or key == "frozen_at_utc"
            ):
                try:
                    timestamps.append(_as_utc(nested))
                except (TypeError, ValueError):
                    continue
            else:
                timestamps.extend(_collect_timestamps(nested))
    elif isinstance(value, list):
        for nested in value:
            timestamps.extend(_collect_timestamps(nested))
    return timestamps


def _session_observed_through(session: EvidenceSession) -> datetime:
    values = [decision.as_of for decision in session.decisions]
    for trade in session.trades:
        values.extend(
            value
            for value in (trade.placed_at, trade.filled_at, trade.closed_at)
            if value is not None
        )
    if not values:
        raise ValueError(f"session {session.session_id!r} has no observations")
    return max(_as_utc(value) for value in values)


def _session_source(root: Path, session: EvidenceSession) -> dict[str, Any]:
    files = {
        "cycles.jsonl": root / "mt5_runner" / "cycles.jsonl",
        "summary.json": root / "mt5_runner" / "summary.json",
    }
    missing = [str(path) for path in files.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "completed learning session is missing required artifacts: "
            + ", ".join(missing)
        )
    hashes = {name: _sha256(path) for name, path in sorted(files.items())}
    combined = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return {
        "session_id": session.session_id,
        "path": root.as_posix(),
        "source_role": "HYPOTHESIS_GENERATION_ONLY",
        "observed_through_utc": _iso_utc(_session_observed_through(session)),
        "filled_trades": sum(trade.filled for trade in session.trades),
        "artifact_hashes": hashes,
        "combined_sha256": combined,
    }


def _candidate_name(payload: Mapping[str, Any]) -> str:
    candidate = payload.get("candidate")
    if isinstance(candidate, str) and candidate:
        return candidate
    if isinstance(candidate, Mapping):
        for key in ("name", "candidate", "candidate_id"):
            value = candidate.get(key)
            if isinstance(value, str) and value:
                return value
    raise ValueError("retired-candidate report is missing a candidate name")


def _retired_candidate_source(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidate = _candidate_name(payload)
    candidate_status = str(payload.get("candidate_status") or payload.get("status") or "")
    retired = bool(payload.get("retired")) or candidate_status in {
        "RETIRED_READ_ONLY",
        "FAIL",
    }
    if not retired:
        raise ValueError(
            f"candidate report for {candidate} is not explicitly retired or failed"
        )
    if payload.get("order_capability") is True:
        raise ValueError(f"retired candidate {candidate} cannot have order capability")
    if payload.get("promotion_record_generated") is True:
        raise ValueError(f"retired candidate {candidate} cannot have a promotion record")

    discovery = payload.get("discovery")
    if not isinstance(discovery, Mapping):
        discovery = {}
    policy = payload.get("policy_result")
    if not isinstance(policy, Mapping):
        policy = {}
    if policy.get("demo_start_allowed") is True:
        raise ValueError(f"retired candidate {candidate} cannot authorize DEMO start")

    referenced_hashes: set[str] = {_sha256(path)}
    for container in (payload, discovery, payload.get("manifest") or {}):
        if not isinstance(container, Mapping):
            continue
        for key, value in container.items():
            if (key.endswith("sha256") or key.endswith("_sha256")) and isinstance(
                value, str
            ):
                referenced_hashes.add(value)

    timestamps = _collect_timestamps(payload)
    return {
        "candidate": candidate,
        "path": path.as_posix(),
        "source_role": "HYPOTHESIS_GENERATION_ONLY",
        "status": candidate_status or "RETIRED",
        "retired": True,
        "order_capability": False,
        "report_sha256": _sha256(path),
        "referenced_hashes": sorted(referenced_hashes),
        "observed_through_utc": _iso_utc(max(timestamps)) if timestamps else None,
        "discovery": {
            "source_candles": int(discovery.get("source_candles") or 0),
            "source_quotes": int(discovery.get("source_quotes") or 0),
            "arms_detected": int(discovery.get("arms_detected") or 0),
            "valid_triggers": int(discovery.get("valid_triggers") or 0),
            "placements": int(discovery.get("placements") or 0),
            "fills": int(discovery.get("fills") or 0),
            "top_skip_rejection_counts": dict(
                sorted((discovery.get("top_skip_rejection_counts") or {}).items())
            ),
        },
        "policy": {
            "held_out_must_remain_unopened": bool(
                policy.get("held_out_must_remain_unopened", True)
            ),
            "demo_start_allowed": False,
            "tuning_on_failed_window_allowed": False,
        },
    }


def _verified_patterns(
    learning_report: Mapping[str, Any],
    candidate_sources: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    patterns: list[dict[str, Any]] = []
    summary = learning_report["summary"]
    failure_counts = learning_report["failure_taxonomy_counts"]
    data_quality = learning_report["data_quality"]
    losses = int(summary["losses"])
    losses_with_mfe = int(data_quality["losses_with_mfe"])
    zero_mfe_losses = int(failure_counts.get("ZERO_MFE_REVERSAL", 0))
    if losses:
        patterns.append(
            {
                "key": "LEGACY_IMMEDIATE_ADVERSE_SELECTION",
                "certainty": "VERIFIED_DESCRIPTIVE",
                "fills": int(summary["fills"]),
                "losses": losses,
                "losses_with_mfe": losses_with_mfe,
                "zero_mfe_losses": zero_mfe_losses,
                "zero_mfe_share_of_all_losses": round(
                    zero_mfe_losses / losses, 4
                ),
                "zero_mfe_share_of_losses_with_mfe": (
                    round(zero_mfe_losses / losses_with_mfe, 4)
                    if losses_with_mfe
                    else None
                ),
                "mfe_sampling_caveat": (
                    "MFE coverage is incomplete and uses sampled observations, "
                    "not a tick-complete excursion path."
                ),
                "interpretation": (
                    "Outcome diagnostics indicate an entry-admission problem; "
                    "MFE itself is not an entry-time feature."
                ),
            }
        )

    trigger_stats = learning_report["by_trigger"]
    negative = sorted(
        trigger
        for trigger, stats in trigger_stats.items()
        if int(stats["fills"]) > 0 and float(stats["net_profit"]) < 0
    )
    if negative:
        patterns.append(
            {
                "key": "LEGACY_TRIGGER_GROUPS_NEGATIVE",
                "certainty": "VERIFIED_DESCRIPTIVE",
                "negative_trigger_groups": negative,
                "negative_group_count": len(negative),
                "observed_group_count": len(trigger_stats),
                "all_observed_groups_negative": len(negative) == len(trigger_stats),
                "interpretation": (
                    "The included run population does not support restarting the "
                    "unchanged classifier or claiming that one shallow filter fixes it."
                ),
            }
        )

    for source in candidate_sources:
        discovery = source["discovery"]
        if discovery["arms_detected"] and discovery["valid_triggers"] == 0:
            patterns.append(
                {
                    "key": f"{source['candidate']}_TRIGGER_FEASIBILITY_FAILURE",
                    "certainty": "FROZEN_GATE_RESULT",
                    "arms_detected": discovery["arms_detected"],
                    "valid_triggers": 0,
                    "placements": discovery["placements"],
                    "fills": discovery["fills"],
                    "top_skip_rejection_counts": discovery[
                        "top_skip_rejection_counts"
                    ],
                    "interpretation": (
                        "The retired candidate failed before economic evaluation; "
                        "its failed window may generate a new hypothesis but cannot "
                        "validate or tune the retired candidate."
                    ),
                }
            )
    return patterns


def build_controlled_learning_ledger(
    session_roots: Iterable[str | Path],
    retired_candidate_reports: Iterable[str | Path],
    *,
    min_samples: int = 3,
) -> dict[str, Any]:
    """Build a deterministic research-only ledger from explicit frozen sources."""
    roots = sorted({Path(root) for root in session_roots}, key=lambda path: path.as_posix())
    report_paths = sorted(
        {Path(path) for path in retired_candidate_reports},
        key=lambda path: path.as_posix(),
    )
    if not roots:
        raise ValueError("at least one completed session is required")

    sessions = [export_session(root) for root in roots]
    session_ids = [session.session_id for session in sessions]
    if len(session_ids) != len(set(session_ids)):
        raise ValueError("learning sources require unique session ids")
    session_sources = [
        _session_source(root, session)
        for root, session in zip(roots, sessions, strict=True)
    ]
    candidate_sources = [_retired_candidate_source(path) for path in report_paths]
    candidate_names = [source["candidate"] for source in candidate_sources]
    if len(candidate_names) != len(set(candidate_names)):
        raise ValueError("learning sources require unique retired candidates")

    learning_report = build_learning_report(sessions, min_samples=min_samples)
    timestamps = [
        _as_utc(source["observed_through_utc"]) for source in session_sources
    ]
    timestamps.extend(
        _as_utc(source["observed_through_utc"])
        for source in candidate_sources
        if source["observed_through_utc"] is not None
    )
    observed_through = max(timestamps)
    new_evidence_not_before = observed_through + timedelta(microseconds=1)

    hypothesis_hashes: set[str] = set()
    for source in session_sources:
        hypothesis_hashes.add(source["combined_sha256"])
        hypothesis_hashes.update(source["artifact_hashes"].values())
    for source in candidate_sources:
        hypothesis_hashes.update(source["referenced_hashes"])

    return {
        "schema_version": 1,
        "strategy_scope": "one_minute_scalper",
        "learning_mode": "OFFLINE_HYPOTHESIS_GENERATION_ONLY",
        "as_of_utc": _iso_utc(observed_through),
        "broker_mutation_enabled": False,
        "live_rule_mutation_enabled": False,
        "automatic_promotion_enabled": False,
        "source_registry": {
            "sessions": session_sources,
            "retired_candidates": candidate_sources,
            "hypothesis_source_hashes": sorted(hypothesis_hashes),
        },
        "verified_patterns": _verified_patterns(
            learning_report,
            candidate_sources,
        ),
        "diagnostics": learning_report,
        "candidate_incubation": {
            "status": "NEW_NAMED_CANDIDATE_REQUIRES_PREREGISTRATION",
            "suggested_research_question": (
                "Can a new symmetric, closed-candle setup create a feasible "
                "post-close entry event that avoids immediate adverse selection "
                "without reusing V8 or adding another shallow legacy filter?"
            ),
            "allowed_actions": [
                "generate a separately named causal hypothesis",
                "freeze detector, lifecycle, cost model, gates, and hashes",
                "evaluate only on chronologically later, disjoint evidence",
            ],
            "prohibited_actions": [
                "mutate live rules from this ledger",
                "auto-promote any hypothesis",
                "tune or revive a retired candidate on its failed window",
                "use post-fill or outcome data as an entry-time feature",
                "increase volume or weaken risk and safety gates",
            ],
            "evidence_isolation": {
                "hypothesis_generation_cutoff_utc": _iso_utc(observed_through),
                "new_evidence_must_start_at_or_after_utc": _iso_utc(
                    new_evidence_not_before
                ),
                "forbidden_evaluation_source_hashes": sorted(hypothesis_hashes),
                "held_out_must_remain_unopened_until_discovery_passes": True,
            },
        },
        "operational_permissions": {
            "read_completed_artifacts": True,
            "write_research_ledger": True,
            "place_or_modify_orders": False,
            "change_strategy_configuration": False,
            "create_promotion_record": False,
            "authorize_demo_start": False,
            "authorize_real_start": False,
        },
    }


def _resolve_source(reference: str, manifest_path: Path) -> Path:
    path = Path(reference)
    if path.is_absolute() or path.exists():
        return path
    relative_to_manifest = manifest_path.parent / path
    if relative_to_manifest.exists():
        return relative_to_manifest
    return path


def build_controlled_learning_ledger_from_manifest(
    manifest_path: str | Path,
) -> dict[str, Any]:
    """Load an explicit source registry and build its controlled ledger."""
    path = Path(manifest_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError("learning source manifest schema_version must be 1")
    if payload.get("strategy_scope") != "one_minute_scalper":
        raise ValueError("learning source manifest must be M1-only")
    sessions = payload.get("sessions") or []
    retired_reports = payload.get("retired_candidate_reports") or []
    ledger = build_controlled_learning_ledger(
        (_resolve_source(value, path) for value in sessions),
        (_resolve_source(value, path) for value in retired_reports),
        min_samples=int(payload.get("min_samples") or 3),
    )
    ledger["source_registry"]["manifest"] = {
        "path": path.as_posix(),
        "sha256": _sha256(path),
    }
    return ledger


def validate_evaluation_source_isolation(
    ledger: Mapping[str, Any],
    *,
    evaluation_source_hashes: Iterable[str],
    evaluation_start_utc: str | datetime,
) -> dict[str, Any]:
    """Reject evaluation evidence that overlaps hypothesis-generation sources."""
    isolation = ledger["candidate_incubation"]["evidence_isolation"]
    forbidden = set(isolation["forbidden_evaluation_source_hashes"])
    supplied = set(evaluation_source_hashes)
    overlaps = sorted(forbidden & supplied)
    minimum = _as_utc(isolation["new_evidence_must_start_at_or_after_utc"])
    start = _as_utc(evaluation_start_utc)
    reasons: list[str] = []
    if overlaps:
        reasons.append("HYPOTHESIS_SOURCE_HASH_REUSED_FOR_EVALUATION")
    if start < minimum:
        reasons.append("EVALUATION_WINDOW_NOT_CHRONOLOGICALLY_NEW")
    return {
        "passed": not reasons,
        "reasons": reasons,
        "overlapping_hashes": overlaps,
        "evaluation_start_utc": _iso_utc(start),
        "minimum_evaluation_start_utc": _iso_utc(minimum),
    }
