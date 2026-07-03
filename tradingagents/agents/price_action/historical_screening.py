"""Deterministic historical screening for pre-registered scalper variants."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from tradingagents.agents.price_action.evidence_gate import (
    EvidenceSession,
    VariantName,
    evaluate_session,
)
from tradingagents.agents.price_action.evidence_metrics import (
    evaluate_historical_gate,
    summarize_variant,
)


VARIANTS: tuple[tuple[VariantName, ...], ...] = (
    (VariantName.BASELINE,),
    (VariantName.H1_TOUCH_MATURITY,),
    (VariantName.H2_EXHAUSTION,),
    (VariantName.H3_POST_LOSS_CLUSTER,),
    (VariantName.H1_TOUCH_MATURITY, VariantName.H2_EXHAUSTION),
    (VariantName.H1_TOUCH_MATURITY, VariantName.H3_POST_LOSS_CLUSTER),
    (VariantName.H2_EXHAUSTION, VariantName.H3_POST_LOSS_CLUSTER),
)


def _name(variants: tuple[VariantName, ...]) -> str:
    return "+".join(item.value for item in variants)


def screen_evidence_dir(evidence_dir: str | Path) -> dict[str, Any]:
    root = Path(evidence_dir)
    files = sorted(root.glob("*.json"))
    sessions = [
        EvidenceSession.model_validate_json(path.read_text(encoding="utf-8"))
        for path in files
    ]
    hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    rows_by_name = {
        _name(variant): tuple(
            row
            for session in sessions
            for row in evaluate_session(session, variant)
        )
        for variant in VARIANTS
    }
    baseline_rows = rows_by_name[VariantName.BASELINE.value]
    baseline_fills = sum(row.filled for row in baseline_rows)
    baseline_metrics = summarize_variant(
        VariantName.BASELINE.value,
        baseline_rows,
        baseline_fill_count=baseline_fills,
    )

    variants: dict[str, Any] = {}
    qualifying: list[str] = []
    for variant in VARIANTS:
        name = _name(variant)
        rows = rows_by_name[name]
        metrics = summarize_variant(
            name,
            rows,
            baseline_fill_count=baseline_fills,
        )
        if variant == (VariantName.BASELINE,):
            gate = {
                "passed": False,
                "reasons": ["BASELINE_REFERENCE_ONLY"],
            }
        else:
            evaluated = evaluate_historical_gate(metrics, baseline_metrics)
            reasons = list(evaluated.reasons)
            if any(
                "INSUFFICIENT_IMPULSE_BODY_EVIDENCE" in row.reasons
                for row in rows
            ):
                reasons.append("INSUFFICIENT_HISTORICAL_EVIDENCE")
            gate = {"passed": not reasons, "reasons": reasons}
            if gate["passed"]:
                qualifying.append(name)
        variants[name] = {
            "metrics": metrics.model_dump(mode="json"),
            "gate": gate,
        }

    return {
        "schema_version": 1,
        "broker_mutation_enabled": False,
        "source_fixture_hashes": hashes,
        "variants": variants,
        "qualifying_candidates": qualifying,
    }
