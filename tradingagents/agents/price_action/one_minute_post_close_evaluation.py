"""Frozen metrics, gates, and segmentation for post-close V1 evidence."""

from __future__ import annotations

import gc
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from tradingagents.agents.price_action.one_minute_post_close_replay import (
    PostCloseReplayConfig,
    PostCloseReplayResult,
    PostCloseReplayRow,
    replay_post_close_fixture,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PlacementConfig,
    parse_utc,
)


HELD_OUT_GATE = {
    "min_fills": 100,
    "min_sessions": 10,
    "min_profit_factor": 1.25,
    "min_expectancy_r": 0.10,
    "min_profitable_session_ratio": 0.60,
    "max_portfolio_drawdown_r": 8.0,
    "max_session_drawdown_r": 3.0,
    "max_loss_streak": 6,
    "max_best_session_profit_share": 0.30,
    "max_best_family_profit_share": 0.50,
    "max_best_direction_profit_share": 0.65,
}

PROSPECTIVE_GATE = {
    **HELD_OUT_GATE,
    "min_fills": 60,
    "min_profit_factor": 1.20,
    "min_expectancy_r": 0.08,
    "max_best_session_profit_share": 0.35,
    "max_best_family_profit_share": 0.60,
    "max_best_direction_profit_share": 0.70,
}

EXECUTION_GATE = {
    "min_trigger_rate": 0.15,
    "min_fill_rate": 0.85,
    "max_expiry_rate": 0.50,
    "max_crossed_rate": 0.15,
    "max_geometry_reject_rate": 0.05,
    "max_median_drift_r": 0.15,
    "max_p95_drift_r": 0.35,
}

RETEST_EXECUTION_GATE = {
    "min_trigger_rate": 0.15,
    "min_placement_rate": 0.70,
    "min_pending_fill_rate": 0.30,
    "max_pending_expiry_rate": 0.65,
    "max_crossed_rate": 0.20,
    "max_geometry_reject_rate": 0.05,
    "max_median_drift_r": 0.05,
    "max_p95_drift_r": 0.15,
}

RECONFIRMATION_EXECUTION_GATE = {
    "min_trigger_rate": 0.15,
    "min_retest_rate": 0.25,
    "min_retest_placement_rate": 0.60,
    "min_stop_fill_rate": 0.30,
    "max_crossed_rate": 0.20,
    "max_geometry_reject_rate": 0.05,
    "max_median_drift_r": 0.05,
    "max_p95_drift_r": 0.15,
}

HOLD_EXECUTION_GATE = {
    "min_trigger_rate": 0.15,
    "min_placement_rate": 0.60,
    "min_stop_fill_rate": 0.50,
    "max_crossed_rate": 0.05,
    "max_geometry_reject_rate": 0.10,
    "max_median_drift_r": 0.50,
    "max_p95_drift_r": 0.75,
}

HOLD_HELD_OUT_GATE = {
    **HELD_OUT_GATE,
    "min_fills": 15,
    "min_sessions": 5,
}

SHOCK_RECLAIM_EXECUTION_GATE = {
    "min_trigger_rate": 0.50,
    "min_placement_rate": 0.60,
    "min_stop_fill_rate": 0.50,
    "max_crossed_rate": 0.0,
    "max_geometry_reject_rate": 0.10,
    "max_median_drift_r": 0.50,
    "max_p95_drift_r": 0.75,
    "max_safety_failures": 0,
}

SHOCK_RECLAIM_HELD_OUT_GATE = {
    "min_fills": 15,
    "min_sessions": 5,
    "min_profit_factor": 1.25,
    "min_expectancy_r": 0.10,
    "min_profitable_session_ratio": 0.60,
    "max_portfolio_drawdown_r": 6.0,
    "max_loss_streak": 5,
    "max_best_session_profit_share": 0.50,
    "max_best_family_profit_share": 0.65,
    "max_best_direction_profit_share": 0.65,
}

SHOCK_RECLAIM_PROSPECTIVE_GATE = {
    **SHOCK_RECLAIM_HELD_OUT_GATE,
    "min_fills": 60,
    "min_sessions": 10,
    "min_profit_factor": 1.20,
    "min_expectancy_r": 0.08,
}


def _percentile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * probability
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    weight = index - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _drawdown(profits: Iterable[float]) -> float:
    equity = peak = maximum = 0.0
    for profit in profits:
        equity += float(profit)
        peak = max(peak, equity)
        maximum = max(maximum, peak - equity)
    return maximum


def _maximum_loss_streak(profits: Iterable[float]) -> int:
    current = maximum = 0
    for profit in profits:
        if float(profit) < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def summarize_post_close_rows(
    rows: Iterable[PostCloseReplayRow],
) -> dict[str, Any]:
    ordered = list(rows)
    filled = [row for row in ordered if row.filled and row.profit_r is not None]
    profits = [float(row.profit_r) for row in filled]
    wins = sum(profit > 0 for profit in profits)
    losses = sum(profit < 0 for profit in profits)
    gross_profit = sum(profit for profit in profits if profit > 0)
    gross_loss = sum(profit for profit in profits if profit < 0)
    net = sum(profits)
    profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else None

    session_profits: dict[str, float] = defaultdict(float)
    session_sequences: dict[str, list[float]] = defaultdict(list)
    family_profit: dict[str, float] = defaultdict(float)
    direction_profit: dict[str, float] = defaultdict(float)
    for row in filled:
        profit = float(row.profit_r)
        session_profits[row.session_id] += profit
        session_sequences[row.session_id].append(profit)
        family_profit[row.family] += profit
        direction_profit[row.direction] += profit
    profitable_sessions = sum(value > 0 for value in session_profits.values())
    session_count = len(session_profits)

    positive_session_profits = [max(0.0, value) for value in session_profits.values()]
    positive_family_profits = [max(0.0, value) for value in family_profit.values()]
    positive_direction_profits = [max(0.0, value) for value in direction_profit.values()]
    best_session_share = max(positive_session_profits, default=0.0) / gross_profit if gross_profit > 0 else None
    best_family_share = max(positive_family_profits, default=0.0) / gross_profit if gross_profit > 0 else None
    best_direction_share = max(positive_direction_profits, default=0.0) / gross_profit if gross_profit > 0 else None
    best_session = max(session_profits.values(), default=0.0)

    return {
        "fills": len(filled),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / len(filled), 6) if filled else 0.0,
        "net_r": round(net, 6),
        "gross_profit_r": round(gross_profit, 6),
        "gross_loss_r": round(gross_loss, 6),
        "profit_factor": round(profit_factor, 6) if profit_factor is not None else None,
        "expectancy_r": round(net / len(filled), 6) if filled else 0.0,
        "session_count": session_count,
        "profitable_session_count": profitable_sessions,
        "profitable_session_ratio": round(profitable_sessions / session_count, 6) if session_count else 0.0,
        "max_loss_streak": _maximum_loss_streak(profits),
        "max_portfolio_drawdown_r": round(_drawdown(profits), 6),
        "max_session_drawdown_r": round(max((_drawdown(items) for items in session_sequences.values()), default=0.0), 6),
        "best_session_profit_share": round(best_session_share, 6) if best_session_share is not None else None,
        "best_family_profit_share": round(best_family_share, 6) if best_family_share is not None else None,
        "best_direction_profit_share": round(best_direction_share, 6) if best_direction_share is not None else None,
        "net_without_best_session_r": round(net - max(0.0, best_session), 6),
        "net_with_extra_0_05r_cost": round(net - 0.05 * len(filled), 6),
    }


def summarize_executability(result: PostCloseReplayResult) -> dict[str, Any]:
    rows = list(result.rows)
    triggered = [row for row in rows if row.triggered_at is not None]
    filled = [row for row in rows if row.filled and row.profit_r is not None]
    placed = [row for row in rows if row.placed_at is not None]
    retested = [row for row in rows if row.retest_at is not None]
    expiries = [row for row in rows if row.outcome == "EXPIRED"]
    pending_expiries = [
        row
        for row in rows
        if row.reason
        in {
            "PENDING_RETEST_EXPIRED",
            "PENDING_HOLD_STOP_EXPIRED",
            "PENDING_RECLAIM_STOP_EXPIRED",
        }
    ]
    crossed = [
        row
        for row in rows
        if "CROSSED_AT_PLACEMENT" in row.reason
        or "RETEST_ALREADY_CROSSED_AT_PLACEMENT" in row.reason
        or "RECONFIRMATION_ALREADY_CROSSED_AT_PLACEMENT" in row.reason
    ]
    geometry = [
        row
        for row in rows
        if row.reason
        in {
            "INVALID_STOP_GEOMETRY",
            "STOP_DISTANCE_ABOVE_MAXIMUM",
            "ENTRY_DRIFT_ABOVE_MAXIMUM",
            "HOLD_ENTRY_DRIFT_ABOVE_MAXIMUM",
            "RECLAIM_ENTRY_DRIFT_ABOVE_MAXIMUM",
        }
    ]
    safety_failures = [
        row
        for row in rows
        if row.reason in {"INVALID_FILL_GEOMETRY", "AMBIGUOUS_STOP_TARGET"}
    ]
    drifts = [float(row.entry_drift_r) for row in filled if row.entry_drift_r is not None]
    return {
        "arms": result.arms_detected,
        "triggered": len(triggered),
        "placed": len(placed),
        "retested": len(retested),
        "fills": len(filled),
        "trigger_rate": round(len(triggered) / result.arms_detected, 6) if result.arms_detected else 0.0,
        "placement_rate": round(len(placed) / len(triggered), 6) if triggered else 0.0,
        "retest_rate": round(len(retested) / len(triggered), 6) if triggered else 0.0,
        "retest_placement_rate": round(len(placed) / len(retested), 6) if retested else 0.0,
        "fill_rate": round(len(filled) / len(placed), 6) if placed else 0.0,
        "trigger_fill_rate": round(len(filled) / len(triggered), 6) if triggered else 0.0,
        "expiry_rate": round(len(expiries) / result.arms_detected, 6) if result.arms_detected else 0.0,
        "pending_expiry_rate": round(len(pending_expiries) / len(placed), 6) if placed else 0.0,
        "crossed_rate": round(len(crossed) / len(triggered), 6) if triggered else 0.0,
        "crossed_count": len(crossed),
        "geometry_reject_rate": round(len(geometry) / len(triggered), 6) if triggered else 0.0,
        "safety_failure_count": len(safety_failures)
        + int(bool(result.broker_mutation_enabled)),
        "median_entry_drift_r": round(median(drifts), 6) if drifts else None,
        "p95_entry_drift_r": round(_percentile(drifts, 0.95), 6) if drifts else None,
    }


def _gate_reasons(
    metrics: dict[str, Any],
    execution: dict[str, Any],
    gate: dict[str, Any],
    candidate: str,
) -> list[str]:
    reasons: list[str] = []
    checks = [
        (metrics["fills"] >= gate["min_fills"], "INSUFFICIENT_FILLS"),
        (metrics["session_count"] >= gate["min_sessions"], "INSUFFICIENT_SESSIONS"),
        ((metrics["profit_factor"] or 0.0) >= gate["min_profit_factor"], "PROFIT_FACTOR_BELOW_GATE"),
        (metrics["expectancy_r"] >= gate["min_expectancy_r"], "EXPECTANCY_BELOW_GATE"),
        (metrics["net_r"] > 0, "NON_POSITIVE_NET_R"),
        (metrics["profitable_session_ratio"] >= gate["min_profitable_session_ratio"], "PROFITABLE_SESSION_RATIO_BELOW_GATE"),
        (metrics["max_portfolio_drawdown_r"] <= gate["max_portfolio_drawdown_r"], "PORTFOLIO_DRAWDOWN_ABOVE_GATE"),
        (metrics["max_loss_streak"] <= gate["max_loss_streak"], "LOSS_STREAK_ABOVE_GATE"),
        ((metrics["best_session_profit_share"] or 1.0) <= gate["max_best_session_profit_share"], "SESSION_PROFIT_CONCENTRATION"),
        ((metrics["best_family_profit_share"] or 1.0) <= gate["max_best_family_profit_share"], "FAMILY_PROFIT_CONCENTRATION"),
        ((metrics["best_direction_profit_share"] or 1.0) <= gate["max_best_direction_profit_share"], "DIRECTION_PROFIT_CONCENTRATION"),
        (metrics["net_without_best_session_r"] > 0, "NOT_PROFITABLE_WITHOUT_BEST_SESSION"),
        (metrics["net_with_extra_0_05r_cost"] > 0, "FAILS_EXTRA_COST_STRESS"),
    ]
    if "max_session_drawdown_r" in gate:
        checks.append(
            (
                metrics["max_session_drawdown_r"]
                <= gate["max_session_drawdown_r"],
                "SESSION_DRAWDOWN_ABOVE_GATE",
            )
        )
    for passed, reason in checks:
        if not passed:
            reasons.append(reason)
    if candidate == "ONE_MINUTE_SHOCK_RECLAIM_V6":
        execution_checks = (
            (execution["trigger_rate"] >= SHOCK_RECLAIM_EXECUTION_GATE["min_trigger_rate"], "TRIGGER_RATE_BELOW_GATE"),
            (execution["placement_rate"] >= SHOCK_RECLAIM_EXECUTION_GATE["min_placement_rate"], "PLACEMENT_RATE_BELOW_GATE"),
            (execution["fill_rate"] >= SHOCK_RECLAIM_EXECUTION_GATE["min_stop_fill_rate"], "STOP_FILL_RATE_BELOW_GATE"),
            (execution["crossed_rate"] <= SHOCK_RECLAIM_EXECUTION_GATE["max_crossed_rate"], "CROSSED_RATE_ABOVE_GATE"),
            (execution["geometry_reject_rate"] <= SHOCK_RECLAIM_EXECUTION_GATE["max_geometry_reject_rate"], "GEOMETRY_REJECT_RATE_ABOVE_GATE"),
            ((execution["median_entry_drift_r"] if execution["median_entry_drift_r"] is not None else float("inf")) <= SHOCK_RECLAIM_EXECUTION_GATE["max_median_drift_r"], "MEDIAN_DRIFT_ABOVE_GATE"),
            ((execution["p95_entry_drift_r"] if execution["p95_entry_drift_r"] is not None else float("inf")) <= SHOCK_RECLAIM_EXECUTION_GATE["max_p95_drift_r"], "P95_DRIFT_ABOVE_GATE"),
            (execution["safety_failure_count"] <= SHOCK_RECLAIM_EXECUTION_GATE["max_safety_failures"], "SAFETY_FAILURES_ABOVE_GATE"),
        )
    elif candidate == "ONE_MINUTE_COMPRESSION_HOLD_V5_1":
        execution_checks = (
            (execution["trigger_rate"] >= HOLD_EXECUTION_GATE["min_trigger_rate"], "TRIGGER_RATE_BELOW_GATE"),
            (execution["placement_rate"] >= HOLD_EXECUTION_GATE["min_placement_rate"], "PLACEMENT_RATE_BELOW_GATE"),
            (execution["fill_rate"] >= HOLD_EXECUTION_GATE["min_stop_fill_rate"], "STOP_FILL_RATE_BELOW_GATE"),
            (execution["crossed_rate"] <= HOLD_EXECUTION_GATE["max_crossed_rate"], "CROSSED_RATE_ABOVE_GATE"),
            (execution["geometry_reject_rate"] <= HOLD_EXECUTION_GATE["max_geometry_reject_rate"], "GEOMETRY_REJECT_RATE_ABOVE_GATE"),
            ((execution["median_entry_drift_r"] if execution["median_entry_drift_r"] is not None else float("inf")) <= HOLD_EXECUTION_GATE["max_median_drift_r"], "MEDIAN_DRIFT_ABOVE_GATE"),
            ((execution["p95_entry_drift_r"] if execution["p95_entry_drift_r"] is not None else float("inf")) <= HOLD_EXECUTION_GATE["max_p95_drift_r"], "P95_DRIFT_ABOVE_GATE"),
        )
    elif candidate in {
        "ONE_MINUTE_RETEST_RECONFIRMATION_V3",
        "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4",
        "ONE_MINUTE_COMPRESSION_EXPANSION_V5",
    }:
        execution_checks = (
            (execution["trigger_rate"] >= RECONFIRMATION_EXECUTION_GATE["min_trigger_rate"], "TRIGGER_RATE_BELOW_GATE"),
            (execution["retest_rate"] >= RECONFIRMATION_EXECUTION_GATE["min_retest_rate"], "RETEST_RATE_BELOW_GATE"),
            (execution["retest_placement_rate"] >= RECONFIRMATION_EXECUTION_GATE["min_retest_placement_rate"], "RETEST_PLACEMENT_RATE_BELOW_GATE"),
            (execution["fill_rate"] >= RECONFIRMATION_EXECUTION_GATE["min_stop_fill_rate"], "STOP_FILL_RATE_BELOW_GATE"),
            (execution["crossed_rate"] <= RECONFIRMATION_EXECUTION_GATE["max_crossed_rate"], "CROSSED_RATE_ABOVE_GATE"),
            (execution["geometry_reject_rate"] <= RECONFIRMATION_EXECUTION_GATE["max_geometry_reject_rate"], "GEOMETRY_REJECT_RATE_ABOVE_GATE"),
            ((execution["median_entry_drift_r"] if execution["median_entry_drift_r"] is not None else float("inf")) <= RECONFIRMATION_EXECUTION_GATE["max_median_drift_r"], "MEDIAN_DRIFT_ABOVE_GATE"),
            ((execution["p95_entry_drift_r"] if execution["p95_entry_drift_r"] is not None else float("inf")) <= RECONFIRMATION_EXECUTION_GATE["max_p95_drift_r"], "P95_DRIFT_ABOVE_GATE"),
        )
    elif candidate == "ONE_MINUTE_POST_CLOSE_RETEST_V2":
        execution_checks = (
            (execution["trigger_rate"] >= RETEST_EXECUTION_GATE["min_trigger_rate"], "TRIGGER_RATE_BELOW_GATE"),
            (execution["placement_rate"] >= RETEST_EXECUTION_GATE["min_placement_rate"], "PLACEMENT_RATE_BELOW_GATE"),
            (execution["fill_rate"] >= RETEST_EXECUTION_GATE["min_pending_fill_rate"], "PENDING_FILL_RATE_BELOW_GATE"),
            (execution["pending_expiry_rate"] <= RETEST_EXECUTION_GATE["max_pending_expiry_rate"], "PENDING_EXPIRY_RATE_ABOVE_GATE"),
            (execution["crossed_rate"] <= RETEST_EXECUTION_GATE["max_crossed_rate"], "CROSSED_RATE_ABOVE_GATE"),
            (execution["geometry_reject_rate"] <= RETEST_EXECUTION_GATE["max_geometry_reject_rate"], "GEOMETRY_REJECT_RATE_ABOVE_GATE"),
            ((execution["median_entry_drift_r"] if execution["median_entry_drift_r"] is not None else float("inf")) <= RETEST_EXECUTION_GATE["max_median_drift_r"], "MEDIAN_DRIFT_ABOVE_GATE"),
            ((execution["p95_entry_drift_r"] if execution["p95_entry_drift_r"] is not None else float("inf")) <= RETEST_EXECUTION_GATE["max_p95_drift_r"], "P95_DRIFT_ABOVE_GATE"),
        )
    else:
        execution_checks = (
            (execution["trigger_rate"] >= EXECUTION_GATE["min_trigger_rate"], "TRIGGER_RATE_BELOW_GATE"),
            (execution["trigger_fill_rate"] >= EXECUTION_GATE["min_fill_rate"], "FILL_RATE_BELOW_GATE"),
            (execution["expiry_rate"] <= EXECUTION_GATE["max_expiry_rate"], "EXPIRY_RATE_ABOVE_GATE"),
            (execution["crossed_rate"] <= EXECUTION_GATE["max_crossed_rate"], "CROSSED_RATE_ABOVE_GATE"),
            (execution["geometry_reject_rate"] <= EXECUTION_GATE["max_geometry_reject_rate"], "GEOMETRY_REJECT_RATE_ABOVE_GATE"),
            ((execution["median_entry_drift_r"] if execution["median_entry_drift_r"] is not None else float("inf")) <= EXECUTION_GATE["max_median_drift_r"], "MEDIAN_DRIFT_ABOVE_GATE"),
            ((execution["p95_entry_drift_r"] if execution["p95_entry_drift_r"] is not None else float("inf")) <= EXECUTION_GATE["max_p95_drift_r"], "P95_DRIFT_ABOVE_GATE"),
        )
    for passed, reason in execution_checks:
        if not passed:
            reasons.append(reason)
    return reasons


def _segments(rows: list[PostCloseReplayRow], field: str) -> dict[str, Any]:
    grouped: dict[str, list[PostCloseReplayRow]] = defaultdict(list)
    for row in rows:
        grouped[str(getattr(row, field))].append(row)
    return {
        name: summarize_post_close_rows(items)
        for name, items in sorted(grouped.items())
    }


def evaluate_post_close_result(
    result: PostCloseReplayResult,
    *,
    stage: str,
    candidate: str = "ONE_MINUTE_SYMMETRIC_POST_CLOSE_STATE_V1",
    fold_metrics: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    normalized_stage = str(stage).strip().upper()
    normalized_folds = [dict(item) for item in (fold_metrics or ())]
    if candidate == "ONE_MINUTE_SHOCK_RECLAIM_V6" and normalized_stage == "PROSPECTIVE":
        gate = SHOCK_RECLAIM_PROSPECTIVE_GATE
    elif candidate == "ONE_MINUTE_SHOCK_RECLAIM_V6":
        gate = SHOCK_RECLAIM_HELD_OUT_GATE
    elif normalized_stage == "PROSPECTIVE":
        gate = PROSPECTIVE_GATE
    elif candidate == "ONE_MINUTE_COMPRESSION_HOLD_V5_1":
        gate = HOLD_HELD_OUT_GATE
    else:
        gate = HELD_OUT_GATE
    metrics = summarize_post_close_rows(result.rows)
    execution = summarize_executability(result)
    reasons = _gate_reasons(metrics, execution, gate, candidate)
    rows = list(result.rows)
    segmentation = {
        "family": _segments(rows, "family"),
        "direction": _segments(rows, "direction"),
        "touch_count": _segments(rows, "touch_count"),
        "confirmation_type": _segments(rows, "confirmation_type"),
    }
    if candidate == "ONE_MINUTE_SHOCK_RECLAIM_V6":
        if sum(
            float(item["net_r"]) > 0
            for item in segmentation["direction"].values()
        ) < 2:
            reasons.append("NOT_POSITIVE_BOTH_DIRECTIONS")
        if sum(
            float(item["net_r"]) > 0
            for item in segmentation["family"].values()
        ) < 2:
            reasons.append("NOT_POSITIVE_BOTH_FAMILIES")
    evaluable = normalized_stage in {"HELD_OUT", "PROSPECTIVE"}
    decision = (
        "DISCOVERY_ONLY_NOT_APPROVAL"
        if not evaluable
        else "PASS"
        if not reasons
        else "FAIL"
    )
    report = {
        "schema_version": 1,
        "candidate": candidate,
        "stage": normalized_stage,
        "broker_mutation_enabled": False,
        "decision": decision,
        "evaluable": evaluable,
        "gate_reasons": reasons,
        "metrics": metrics,
        "executability": execution,
        "outcome_counts": dict(sorted(Counter(row.outcome for row in rows).items())),
        "reason_counts": dict(sorted(Counter(row.reason for row in rows).items())),
        "segmentation": segmentation,
        "fold_metrics": normalized_folds,
    }
    if candidate in {
        "ONE_MINUTE_RETEST_RECONFIRMATION_V3",
        "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4",
        "ONE_MINUTE_COMPRESSION_EXPANSION_V5",
        "ONE_MINUTE_COMPRESSION_HOLD_V5_1",
        "ONE_MINUTE_SHOCK_RECLAIM_V6",
    } and normalized_stage == "DISCOVERY":
        direction_metrics = report["segmentation"]["direction"]
        family_metrics = report["segmentation"]["family"]
        positive_directions = sum(
            float(item["net_r"]) > 0 for item in direction_metrics.values()
        )
        positive_families = sum(
            float(item["net_r"]) > 0 for item in family_metrics.values()
        )
        stop_reasons: list[str] = []
        if metrics["fills"] < 30:
            stop_reasons.append("DISCOVERY_FEWER_THAN_30_FILLS")
        if (metrics["profit_factor"] or 0.0) < 1.15:
            stop_reasons.append("DISCOVERY_PROFIT_FACTOR_BELOW_1_15")
        if metrics["expectancy_r"] < 0.05:
            stop_reasons.append("DISCOVERY_EXPECTANCY_BELOW_0_05R")
        if positive_directions < 2:
            stop_reasons.append("DISCOVERY_NOT_POSITIVE_BOTH_DIRECTIONS")
        if positive_families < 2:
            stop_reasons.append("DISCOVERY_FEWER_THAN_TWO_POSITIVE_FAMILIES")
        if candidate in {
            "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4",
            "ONE_MINUTE_COMPRESSION_EXPANSION_V5",
            "ONE_MINUTE_COMPRESSION_HOLD_V5_1",
            "ONE_MINUTE_SHOCK_RECLAIM_V6",
        }:
            minimum_sessions = (
                10
                if candidate
                in {
                    "ONE_MINUTE_COMPRESSION_HOLD_V5_1",
                    "ONE_MINUTE_SHOCK_RECLAIM_V6",
                }
                else 5
            )
            if metrics["session_count"] < minimum_sessions:
                stop_reasons.append(
                    "DISCOVERY_FEWER_THAN_TEN_SESSIONS"
                    if minimum_sessions == 10
                    else "DISCOVERY_FEWER_THAN_FIVE_SESSIONS"
                )
            if metrics["profitable_session_ratio"] < 0.50:
                stop_reasons.append("DISCOVERY_PROFITABLE_SESSION_RATIO_BELOW_0_50")
            if metrics["max_portfolio_drawdown_r"] > 8.0:
                stop_reasons.append("DISCOVERY_DRAWDOWN_ABOVE_8R")
            if metrics["max_loss_streak"] > 6:
                stop_reasons.append("DISCOVERY_LOSS_STREAK_ABOVE_6")
        if candidate in {
            "ONE_MINUTE_COMPRESSION_HOLD_V5_1",
            "ONE_MINUTE_SHOCK_RECLAIM_V6",
        }:
            execution_gate = (
                SHOCK_RECLAIM_EXECUTION_GATE
                if candidate == "ONE_MINUTE_SHOCK_RECLAIM_V6"
                else HOLD_EXECUTION_GATE
            )
            hold_checks = (
                (execution["trigger_rate"] >= execution_gate["min_trigger_rate"], "DISCOVERY_TRIGGER_RATE_BELOW_GATE"),
                (execution["placement_rate"] >= execution_gate["min_placement_rate"], "DISCOVERY_PLACEMENT_RATE_BELOW_GATE"),
                (execution["fill_rate"] >= execution_gate["min_stop_fill_rate"], "DISCOVERY_STOP_FILL_RATE_BELOW_GATE"),
                (execution["crossed_rate"] <= execution_gate["max_crossed_rate"], "DISCOVERY_CROSSED_RATE_ABOVE_GATE"),
                (execution["geometry_reject_rate"] <= execution_gate["max_geometry_reject_rate"], "DISCOVERY_GEOMETRY_REJECT_RATE_ABOVE_GATE"),
                ((execution["median_entry_drift_r"] if execution["median_entry_drift_r"] is not None else float("inf")) <= execution_gate["max_median_drift_r"], "DISCOVERY_MEDIAN_DRIFT_ABOVE_GATE"),
                ((execution["p95_entry_drift_r"] if execution["p95_entry_drift_r"] is not None else float("inf")) <= execution_gate["max_p95_drift_r"], "DISCOVERY_P95_DRIFT_ABOVE_GATE"),
            )
            stop_reasons.extend(reason for passed, reason in hold_checks if not passed)
            if candidate == "ONE_MINUTE_SHOCK_RECLAIM_V6":
                if execution["safety_failure_count"] > 0:
                    stop_reasons.append("DISCOVERY_SAFETY_FAILURES_ABOVE_GATE")
                positive_folds = sum(
                    float(item.get("net_r", 0.0)) > 0
                    for item in normalized_folds
                )
                if len(normalized_folds) != 3:
                    stop_reasons.append("DISCOVERY_REQUIRES_THREE_FOLDS")
                if positive_folds < 2:
                    stop_reasons.append(
                        "DISCOVERY_FEWER_THAN_TWO_POSITIVE_FOLDS"
                    )
        report["discovery_stop"] = {
            "passed": not stop_reasons,
            "reasons": stop_reasons,
            "positive_directions": positive_directions,
            "positive_families": positive_families,
            "positive_folds": (
                sum(
                    float(item.get("net_r", 0.0)) > 0
                    for item in normalized_folds
                )
                if candidate == "ONE_MINUTE_SHOCK_RECLAIM_V6"
                else None
            ),
        }
    return report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validated_manifest(manifest_file: Path) -> tuple[dict[str, Any], str]:
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    candidate = str(manifest.get("candidate") or "")
    if candidate not in {
        "ONE_MINUTE_SYMMETRIC_POST_CLOSE_STATE_V1",
        "ONE_MINUTE_POST_CLOSE_RETEST_V2",
        "ONE_MINUTE_RETEST_RECONFIRMATION_V3",
        "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4",
        "ONE_MINUTE_COMPRESSION_EXPANSION_V5",
        "ONE_MINUTE_COMPRESSION_HOLD_V5_1",
        "ONE_MINUTE_SHOCK_RECLAIM_V6",
    }:
        raise ValueError("unexpected post-close candidate manifest")
    if manifest.get("broker_mutation_enabled") is not False:
        raise ValueError("post-close evaluation manifest must disable broker mutation")
    if candidate == "ONE_MINUTE_SHOCK_RECLAIM_V6":
        frozen = {
            "baseline_window": 36,
            "reference_window": 12,
            "signal_model": "SHOCK_RECLAIM",
            "entry_policy": "POST_CLOSE_RECLAIM_STOP",
            "shock_range_baseline_minimum": 1.5,
            "shock_body_fraction_minimum": 0.6,
            "shock_close_extension_baseline_range_minimum": 0.1,
            "shock_close_location_minimum": 0.8,
            "reclaim_body_fraction_minimum": 0.5,
            "reclaim_close_depth_baseline_range_minimum": 0.1,
            "reclaim_close_location_minimum": 0.7,
            "hold_start_delay_seconds": 5.0,
            "hold_observation_seconds": 1.0,
            "placement_delay_after_hold_seconds": 5.0,
            "minimum_stop_distance": 0.35,
            "minimum_stop_spread_multiple": 1.2,
            "maximum_stop_distance": 1.5,
            "maximum_entry_drift_r": 0.75,
            "pending_stop_expiry_seconds": 20,
            "state_cap_seconds_after_confirmation_close": 90,
            "risk_reward": 1.5,
            "modeled_round_trip_cost_r": 0.05,
            "volume_policy": "CONSTANT_RESEARCH_VOLUME",
        }
        mismatches = [
            key for key, value in frozen.items() if manifest.get(key) != value
        ]
        if mismatches:
            raise ValueError(
                "V6 manifest differs from frozen preregistration: "
                + ", ".join(sorted(mismatches))
            )
    return manifest, candidate


def _load_research_fixture(fixture_file: Path) -> tuple[Any, Any, Any]:
    from tradingagents.agents.price_action.opening_state_screening import (
        OpeningResearchFixture,
    )
    from tradingagents.agents.price_action.models import Candle
    from tradingagents.agents.price_action.opening_tick_replay import MarketTick

    raw_fixture = json.loads(fixture_file.read_bytes())
    evidence_start = raw_fixture.get("evidence_start")
    evidence_end = raw_fixture.get("evidence_end")
    fixture = OpeningResearchFixture(
        schema_version=int(raw_fixture.get("schema_version", 1)),
        candles=tuple(
            Candle(
                timestamp=str(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row.get("volume", row.get("tick_volume", 0.0))),
            )
            for row in raw_fixture.get("candles", ())
        ),
        ticks=tuple(
            MarketTick(
                time=str(row["time"]),
                bid=float(row["bid"]),
                ask=float(row["ask"]),
            )
            for row in raw_fixture.get("ticks", ())
        ),
    )
    del raw_fixture
    return fixture, evidence_start, evidence_end


def _replay_config(
    manifest: dict[str, Any],
    candidate: str,
    *,
    evidence_start: Any,
    evidence_end: Any,
) -> PostCloseReplayConfig:
    return PostCloseReplayConfig(
        placement=PlacementConfig(
            minimum_stop_distance=float(manifest.get("minimum_stop_distance", 0.35)),
            minimum_stop_spread_multiple=float(
                manifest.get("minimum_stop_spread_multiple", 1.2)
            ),
            maximum_stop_distance=float(manifest.get("maximum_stop_distance", 1.0)),
            risk_reward=float(manifest.get("risk_reward", 1.5)),
        ),
        capture_events=False,
        cost_per_fill_r=float(manifest.get("modeled_round_trip_cost_r", 0.05)),
        entry_policy=(
            "SHOCK_RECLAIM_STOP_V6"
            if candidate == "ONE_MINUTE_SHOCK_RECLAIM_V6"
            else "HOLD_CONTINUATION_STOP_V5_1"
            if candidate == "ONE_MINUTE_COMPRESSION_HOLD_V5_1"
            else "RETEST_RECONFIRM_STOP_V3"
            if candidate
            in {
                "ONE_MINUTE_RETEST_RECONFIRMATION_V3",
                "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4",
                "ONE_MINUTE_COMPRESSION_EXPANSION_V5",
            }
            else "RETEST_LIMIT_V2"
            if candidate == "ONE_MINUTE_POST_CLOSE_RETEST_V2"
            else "MARKET_V1"
        ),
        pending_expiry_seconds=int(manifest.get("pending_expiry_seconds", 20)),
        reconfirmation_stop_expiry_seconds=int(
            manifest.get("reconfirmation_stop_expiry_seconds", 15)
        ),
        hold_stop_expiry_seconds=int(manifest.get("hold_stop_expiry_seconds", 20)),
        maximum_hold_entry_drift_r=float(
            manifest.get("maximum_hold_entry_drift_r", 0.75)
        ),
        reclaim_stop_expiry_seconds=int(
            manifest.get("pending_stop_expiry_seconds", 20)
        ),
        maximum_reclaim_entry_drift_r=float(
            manifest.get("maximum_entry_drift_r", 0.75)
        ),
        state_cap_seconds_after_confirmation_close=int(
            manifest.get("state_cap_seconds_after_confirmation_close", 90)
        ),
        clean_levels=(candidate == "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4"),
        candidate_name=candidate,
        signal_model=str(manifest.get("signal_model", "REPEATED_LEVEL")),
        evidence_start=str(evidence_start) if evidence_start else None,
        evidence_end=str(evidence_end) if evidence_end else None,
    )


def _evidence_summary(
    fixture: Any,
    *,
    evidence_start: Any,
    evidence_end: Any,
) -> dict[str, Any]:
    return {
        "candle_count": len(fixture.candles),
        "tick_count": len(fixture.ticks),
        "earliest_candle": min(
            (str(candle.timestamp) for candle in fixture.candles),
            default=None,
        ),
        "latest_candle": max(
            (str(candle.timestamp) for candle in fixture.candles),
            default=None,
        ),
        "evidence_start": evidence_start,
        "evidence_end": evidence_end,
    }


def screen_post_close_fixture_path(
    fixture_path: str | Path,
    *,
    manifest_path: str | Path,
    stage: str = "DISCOVERY",
) -> dict[str, Any]:
    """Load one sanitized fixture and emit a broker-free frozen report."""
    fixture_file = Path(fixture_path)
    manifest_file = Path(manifest_path)
    manifest, candidate = _validated_manifest(manifest_file)
    fixture, evidence_start, evidence_end = _load_research_fixture(fixture_file)
    replay = replay_post_close_fixture(
        fixture,
        config=_replay_config(
            manifest,
            candidate,
            evidence_start=evidence_start,
            evidence_end=evidence_end,
        ),
    )
    report = evaluate_post_close_result(replay, stage=stage, candidate=candidate)
    report.update(
        {
            "manifest": manifest,
            "manifest_sha256": _sha256(manifest_file),
            "source_fixture_sha256": _sha256(fixture_file),
            "evidence": _evidence_summary(
                fixture,
                evidence_start=evidence_start,
                evidence_end=evidence_end,
            ),
        }
    )
    return report


def screen_post_close_fixture_paths(
    fixture_paths: Iterable[str | Path],
    *,
    manifest_path: str | Path,
    stage: str = "DISCOVERY",
) -> dict[str, Any]:
    """Replay ordered non-overlapping fixture folds without co-loading them."""
    manifest_file = Path(manifest_path)
    manifest, candidate = _validated_manifest(manifest_file)
    paths = [Path(path) for path in fixture_paths]
    if not paths:
        raise ValueError("at least one post-close fixture is required")

    rows: list[PostCloseReplayRow] = []
    arms_detected = 0
    sources: list[dict[str, Any]] = []
    fold_metrics: list[dict[str, Any]] = []
    previous_end = None
    for fixture_file in paths:
        fixture, evidence_start, evidence_end = _load_research_fixture(fixture_file)
        if evidence_start is None or evidence_end is None:
            raise ValueError("multi-fixture screening requires explicit evidence bounds")
        start = parse_utc(str(evidence_start))
        end = parse_utc(str(evidence_end))
        if end <= start:
            raise ValueError("fixture evidence end must be after start")
        if previous_end is not None and start < previous_end:
            raise ValueError("multi-fixture evidence windows must not overlap")
        previous_end = end
        replay = replay_post_close_fixture(
            fixture,
            config=_replay_config(
                manifest,
                candidate,
                evidence_start=evidence_start,
                evidence_end=evidence_end,
            ),
        )
        rows.extend(replay.rows)
        arms_detected += replay.arms_detected
        current_fold_metrics = summarize_post_close_rows(replay.rows)
        fold_metrics.append(current_fold_metrics)
        source_hash = _sha256(fixture_file)
        sources.append(
            {
                "path": str(fixture_file),
                "sha256": source_hash,
                "metrics": current_fold_metrics,
                **_evidence_summary(
                    fixture,
                    evidence_start=evidence_start,
                    evidence_end=evidence_end,
                ),
            }
        )
        del replay
        del fixture
        gc.collect()

    rows.sort(key=lambda row: (parse_utc(row.armed_at), row.arm_id))
    combined = PostCloseReplayResult(
        rows=tuple(rows),
        events=(),
        arms_detected=arms_detected,
    )
    report = evaluate_post_close_result(
        combined,
        stage=stage,
        candidate=candidate,
        fold_metrics=fold_metrics,
    )
    source_hashes = "".join(str(source["sha256"]) for source in sources)
    report.update(
        {
            "manifest": manifest,
            "manifest_sha256": _sha256(manifest_file),
            "combined_source_sha256": hashlib.sha256(
                source_hashes.encode("ascii")
            ).hexdigest(),
            "evidence": {
                "fold_count": len(sources),
                "candle_count": sum(int(source["candle_count"]) for source in sources),
                "tick_count": sum(int(source["tick_count"]) for source in sources),
                "evidence_start": sources[0]["evidence_start"],
                "evidence_end": sources[-1]["evidence_end"],
                "sources": sources,
            },
        }
    )
    return report


__all__ = [
    "EXECUTION_GATE",
    "HELD_OUT_GATE",
    "HOLD_EXECUTION_GATE",
    "HOLD_HELD_OUT_GATE",
    "PROSPECTIVE_GATE",
    "RETEST_EXECUTION_GATE",
    "RECONFIRMATION_EXECUTION_GATE",
    "SHOCK_RECLAIM_EXECUTION_GATE",
    "SHOCK_RECLAIM_HELD_OUT_GATE",
    "SHOCK_RECLAIM_PROSPECTIVE_GATE",
    "evaluate_post_close_result",
    "screen_post_close_fixture_path",
    "screen_post_close_fixture_paths",
    "summarize_executability",
    "summarize_post_close_rows",
]
