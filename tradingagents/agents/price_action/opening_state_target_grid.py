"""Walk-forward target-grid screening for queued opening-state candidates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tradingagents.agents.price_action.evidence_gate import ScreeningRow
from tradingagents.agents.price_action.evidence_metrics import (
    HistoricalGateResult,
    VariantMetrics,
    evaluate_historical_gate,
    summarize_variant,
)
from tradingagents.agents.price_action.opening_state_queue_fast_target import (
    QUEUE_POLICY_VERSION,
    baseline_rows_with_config,
    replay_queue_fast_target_fixture,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
    _day,
    _source_hash,
)
from tradingagents.agents.price_action.opening_tick_replay import ReplayConfig


TARGET_GRID_CANDIDATE_NAME = "OPENING_STATE_QUEUE_TARGET_GRID_V1"
TARGET_GRID = (0.60, 0.75, 0.90, 1.00)
TARGET_GRID_VERSION = 1


def _fixture(value: str | Path | OpeningResearchFixture) -> OpeningResearchFixture:
    if isinstance(value, OpeningResearchFixture):
        return value
    return OpeningResearchFixture.model_validate_json(
        Path(value).read_text(encoding="utf-8")
    )


def _metric_value(metrics: VariantMetrics | dict[str, Any], name: str) -> Any:
    if isinstance(metrics, VariantMetrics):
        return getattr(metrics, name)
    return metrics[name]


def _profit_factor_score(metrics: VariantMetrics | dict[str, Any]) -> float:
    no_gross_loss = bool(_metric_value(metrics, "no_gross_loss"))
    net_profit = float(_metric_value(metrics, "net_profit"))
    expectancy = float(_metric_value(metrics, "expectancy"))
    profit_factor = _metric_value(metrics, "profit_factor")
    if no_gross_loss and net_profit > 0 and expectancy > 0:
        return float("inf")
    return float(profit_factor or 0.0)


def _gate_passed(gate: HistoricalGateResult | dict[str, Any]) -> bool:
    if isinstance(gate, HistoricalGateResult):
        return bool(gate.passed)
    return bool(gate["passed"])


def rank_training_targets(
    candidates: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Return eligible target evaluations in deterministic freeze order."""
    eligible = [candidate for candidate in candidates if _gate_passed(candidate["gate"])]
    return tuple(
        sorted(
            eligible,
            key=lambda candidate: (
                -_profit_factor_score(candidate["metrics"]),
                -float(_metric_value(candidate["metrics"], "expectancy")),
                -int(_metric_value(candidate["metrics"], "fills")),
                -float(candidate["target"]),
            ),
        )
    )


def _rows_for_days(
    rows: tuple[ScreeningRow, ...],
    days: set[str],
) -> tuple[ScreeningRow, ...]:
    return tuple(row for row in rows if row.session_id in days)


def _filled_count(rows: tuple[ScreeningRow, ...]) -> int:
    return sum(row.accepted and row.filled and row.profit is not None for row in rows)


def _summarize_pair(
    *,
    name: str,
    baseline_rows: tuple[ScreeningRow, ...],
    candidate_rows: tuple[ScreeningRow, ...],
) -> tuple[VariantMetrics, VariantMetrics, HistoricalGateResult]:
    baseline_fills = _filled_count(baseline_rows)
    baseline = summarize_variant(
        f"{name}_baseline",
        baseline_rows,
        baseline_fill_count=max(1, baseline_fills),
    )
    metrics = summarize_variant(
        name,
        candidate_rows,
        baseline_fill_count=max(1, baseline_fills),
    )
    gate = evaluate_historical_gate(metrics, baseline)
    return baseline, metrics, gate


def _target_payload(
    *,
    target: float,
    baseline_rows: tuple[ScreeningRow, ...],
    candidate_rows: tuple[ScreeningRow, ...],
    name: str,
) -> dict[str, Any]:
    baseline, metrics, gate = _summarize_pair(
        name=name,
        baseline_rows=baseline_rows,
        candidate_rows=candidate_rows,
    )
    return {
        "target": float(target),
        "baseline": baseline.model_dump(mode="json"),
        "metrics": metrics.model_dump(mode="json"),
        "gate": gate.model_dump(mode="json"),
    }


def _precompute_rows(
    fixture: OpeningResearchFixture,
) -> dict[float, dict[str, tuple[ScreeningRow, ...]]]:
    rows_by_target: dict[float, dict[str, tuple[ScreeningRow, ...]]] = {}
    for target in TARGET_GRID:
        config = ReplayConfig(risk_reward=target)
        rows_by_target[float(target)] = {
            "baseline": baseline_rows_with_config(fixture, config),
            "candidate": replay_queue_fast_target_fixture(fixture, config=config),
        }
    return rows_by_target


def _all_days(fixture: OpeningResearchFixture) -> tuple[str, ...]:
    return tuple(sorted({_day(str(candle.timestamp)) for candle in fixture.candles}))


def screen_target_grid_fixture(
    fixture_or_path: str | Path | OpeningResearchFixture,
) -> dict[str, Any]:
    fixture = _fixture(fixture_or_path)
    days = _all_days(fixture)
    rows_by_target = _precompute_rows(fixture)
    folds: list[dict[str, Any]] = []
    combined_baseline_rows: list[ScreeningRow] = []
    combined_candidate_rows: list[ScreeningRow] = []
    missing_fold_targets = False

    for held_out_day in days:
        training_days = set(days) - {held_out_day}
        training_payloads = []
        for target in TARGET_GRID:
            target_rows = rows_by_target[float(target)]
            training_payloads.append(
                _target_payload(
                    target=float(target),
                    baseline_rows=_rows_for_days(
                        target_rows["baseline"],
                        training_days,
                    ),
                    candidate_rows=_rows_for_days(
                        target_rows["candidate"],
                        training_days,
                    ),
                    name=f"train_target_{target:.2f}",
                )
            )

        ranked = rank_training_targets(training_payloads)
        if not ranked:
            missing_fold_targets = True
            folds.append(
                {
                    "held_out_day": held_out_day,
                    "selected_target": None,
                    "reason": "NO_ELIGIBLE_TARGET_FOR_FOLD",
                    "training": training_payloads,
                    "held_out": None,
                }
            )
            continue

        selected_target = float(ranked[0]["target"])
        selected_rows = rows_by_target[selected_target]
        held_out_baseline = _rows_for_days(selected_rows["baseline"], {held_out_day})
        held_out_candidate = _rows_for_days(selected_rows["candidate"], {held_out_day})
        combined_baseline_rows.extend(held_out_baseline)
        combined_candidate_rows.extend(held_out_candidate)
        held_out_payload = _target_payload(
            target=selected_target,
            baseline_rows=held_out_baseline,
            candidate_rows=held_out_candidate,
            name=f"held_out_{held_out_day}_target_{selected_target:.2f}",
        )
        folds.append(
            {
                "held_out_day": held_out_day,
                "selected_target": selected_target,
                "reason": None,
                "training": training_payloads,
                "held_out": held_out_payload,
            }
        )

    baseline, metrics, gate = _summarize_pair(
        name=TARGET_GRID_CANDIDATE_NAME,
        baseline_rows=tuple(combined_baseline_rows),
        candidate_rows=tuple(combined_candidate_rows),
    )
    reasons = list(gate.reasons)
    if missing_fold_targets:
        reasons.append("NO_ELIGIBLE_TARGET_FOR_FOLD")
    combined_gate = HistoricalGateResult(
        passed=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
    )

    all_day_payloads = []
    all_days_set = set(days)
    for target in TARGET_GRID:
        target_rows = rows_by_target[float(target)]
        all_day_payloads.append(
            _target_payload(
                target=float(target),
                baseline_rows=_rows_for_days(target_rows["baseline"], all_days_set),
                candidate_rows=_rows_for_days(target_rows["candidate"], all_days_set),
                name=f"all_days_target_{target:.2f}",
            )
        )
    ranked_all_days = rank_training_targets(all_day_payloads)
    final_target = float(ranked_all_days[0]["target"]) if ranked_all_days else None

    source_hash = _source_hash(fixture)
    frozen_manifest = None
    if combined_gate.passed and final_target is not None:
        frozen_manifest = {
            "candidate": TARGET_GRID_CANDIDATE_NAME,
            "target_grid_version": TARGET_GRID_VERSION,
            "target_grid": [float(target) for target in TARGET_GRID],
            "fold_targets": [
                fold["selected_target"]
                for fold in folds
                if fold["selected_target"] is not None
            ],
            "final_target": final_target,
            "queue_policy_version": QUEUE_POLICY_VERSION,
            "source_fixture_hash": source_hash,
            "historical_metrics": metrics.model_dump(mode="json"),
            "broker_mutation_enabled": False,
            "next_stage": "READ_ONLY_PROSPECTIVE_SHADOW",
        }

    return {
        "schema_version": 1,
        "candidate": TARGET_GRID_CANDIDATE_NAME,
        "target_grid_version": TARGET_GRID_VERSION,
        "target_grid": [float(target) for target in TARGET_GRID],
        "queue_policy_version": QUEUE_POLICY_VERSION,
        "broker_mutation_enabled": False,
        "source_fixture_hash": source_hash,
        "folds": folds,
        "all_days_training": all_day_payloads,
        "final_target": final_target,
        "baseline": baseline.model_dump(mode="json"),
        "metrics": metrics.model_dump(mode="json"),
        "gate": combined_gate.model_dump(mode="json"),
        "decision": (
            "FREEZE_OPENING_STATE_QUEUE_TARGET_GRID"
            if combined_gate.passed
            else "NO_OPENING_STATE_QUEUE_TARGET_GRID_EDGE"
        ),
        "frozen_manifest": frozen_manifest,
    }


__all__ = [
    "TARGET_GRID",
    "TARGET_GRID_CANDIDATE_NAME",
    "TARGET_GRID_VERSION",
    "rank_training_targets",
    "screen_target_grid_fixture",
]
