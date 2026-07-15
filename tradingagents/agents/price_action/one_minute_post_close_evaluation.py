"""Frozen metrics, gates, and segmentation for post-close V1 evidence."""

from __future__ import annotations

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
from tradingagents.agents.price_action.one_minute_post_close_state import PlacementConfig


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
    pending_expiries = [row for row in rows if row.reason == "PENDING_RETEST_EXPIRED"]
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
        }
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
        "geometry_reject_rate": round(len(geometry) / len(triggered), 6) if triggered else 0.0,
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
    checks = (
        (metrics["fills"] >= gate["min_fills"], "INSUFFICIENT_FILLS"),
        (metrics["session_count"] >= gate["min_sessions"], "INSUFFICIENT_SESSIONS"),
        ((metrics["profit_factor"] or 0.0) >= gate["min_profit_factor"], "PROFIT_FACTOR_BELOW_GATE"),
        (metrics["expectancy_r"] >= gate["min_expectancy_r"], "EXPECTANCY_BELOW_GATE"),
        (metrics["net_r"] > 0, "NON_POSITIVE_NET_R"),
        (metrics["profitable_session_ratio"] >= gate["min_profitable_session_ratio"], "PROFITABLE_SESSION_RATIO_BELOW_GATE"),
        (metrics["max_portfolio_drawdown_r"] <= gate["max_portfolio_drawdown_r"], "PORTFOLIO_DRAWDOWN_ABOVE_GATE"),
        (metrics["max_session_drawdown_r"] <= gate["max_session_drawdown_r"], "SESSION_DRAWDOWN_ABOVE_GATE"),
        (metrics["max_loss_streak"] <= gate["max_loss_streak"], "LOSS_STREAK_ABOVE_GATE"),
        ((metrics["best_session_profit_share"] or 1.0) <= gate["max_best_session_profit_share"], "SESSION_PROFIT_CONCENTRATION"),
        ((metrics["best_family_profit_share"] or 1.0) <= gate["max_best_family_profit_share"], "FAMILY_PROFIT_CONCENTRATION"),
        ((metrics["best_direction_profit_share"] or 1.0) <= gate["max_best_direction_profit_share"], "DIRECTION_PROFIT_CONCENTRATION"),
        (metrics["net_without_best_session_r"] > 0, "NOT_PROFITABLE_WITHOUT_BEST_SESSION"),
        (metrics["net_with_extra_0_05r_cost"] > 0, "FAILS_EXTRA_COST_STRESS"),
    )
    for passed, reason in checks:
        if not passed:
            reasons.append(reason)
    if candidate in {
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
) -> dict[str, Any]:
    normalized_stage = str(stage).strip().upper()
    gate = PROSPECTIVE_GATE if normalized_stage == "PROSPECTIVE" else HELD_OUT_GATE
    metrics = summarize_post_close_rows(result.rows)
    execution = summarize_executability(result)
    reasons = _gate_reasons(metrics, execution, gate, candidate)
    evaluable = normalized_stage in {"HELD_OUT", "PROSPECTIVE"}
    if not evaluable:
        decision = "DISCOVERY_ONLY_NOT_APPROVAL"
    else:
        decision = "PASS" if not reasons else "FAIL"
    rows = list(result.rows)
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
        "segmentation": {
            "family": _segments(rows, "family"),
            "direction": _segments(rows, "direction"),
            "touch_count": _segments(rows, "touch_count"),
            "confirmation_type": _segments(rows, "confirmation_type"),
        },
    }
    if candidate in {
        "ONE_MINUTE_RETEST_RECONFIRMATION_V3",
        "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4",
        "ONE_MINUTE_COMPRESSION_EXPANSION_V5",
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
        }:
            if metrics["session_count"] < 5:
                stop_reasons.append("DISCOVERY_FEWER_THAN_FIVE_SESSIONS")
            if metrics["profitable_session_ratio"] < 0.50:
                stop_reasons.append("DISCOVERY_PROFITABLE_SESSION_RATIO_BELOW_0_50")
            if metrics["max_portfolio_drawdown_r"] > 8.0:
                stop_reasons.append("DISCOVERY_DRAWDOWN_ABOVE_8R")
            if metrics["max_loss_streak"] > 6:
                stop_reasons.append("DISCOVERY_LOSS_STREAK_ABOVE_6")
        report["discovery_stop"] = {
            "passed": not stop_reasons,
            "reasons": stop_reasons,
            "positive_directions": positive_directions,
            "positive_families": positive_families,
        }
    return report


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def screen_post_close_fixture_path(
    fixture_path: str | Path,
    *,
    manifest_path: str | Path,
    stage: str = "DISCOVERY",
) -> dict[str, Any]:
    """Load one sanitized fixture and emit a broker-free frozen report."""
    from tradingagents.agents.price_action.opening_state_screening import (
        OpeningResearchFixture,
    )
    from tradingagents.agents.price_action.models import Candle
    from tradingagents.agents.price_action.opening_tick_replay import MarketTick

    fixture_file = Path(fixture_path)
    manifest_file = Path(manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    candidate = str(manifest.get("candidate") or "")
    if candidate not in {
        "ONE_MINUTE_SYMMETRIC_POST_CLOSE_STATE_V1",
        "ONE_MINUTE_POST_CLOSE_RETEST_V2",
        "ONE_MINUTE_RETEST_RECONFIRMATION_V3",
        "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4",
        "ONE_MINUTE_COMPRESSION_EXPANSION_V5",
    }:
        raise ValueError("unexpected post-close candidate manifest")
    if manifest.get("broker_mutation_enabled") is not False:
        raise ValueError("post-close evaluation manifest must disable broker mutation")
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
    replay = replay_post_close_fixture(
        fixture,
        config=PostCloseReplayConfig(
            placement=PlacementConfig(
                minimum_stop_distance=float(
                    manifest.get("minimum_stop_distance", 0.35)
                ),
                minimum_stop_spread_multiple=float(
                    manifest.get("minimum_stop_spread_multiple", 1.2)
                ),
                maximum_stop_distance=float(
                    manifest.get("maximum_stop_distance", 1.0)
                ),
                risk_reward=float(manifest.get("risk_reward", 1.5)),
            ),
            capture_events=False,
            cost_per_fill_r=float(manifest.get("modeled_round_trip_cost_r", 0.05)),
            entry_policy=(
                "RETEST_RECONFIRM_STOP_V3"
                if candidate in {
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
            state_cap_seconds_after_confirmation_close=int(
                manifest.get("state_cap_seconds_after_confirmation_close", 90)
            ),
            clean_levels=(candidate == "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4"),
            candidate_name=candidate,
            signal_model=str(manifest.get("signal_model", "REPEATED_LEVEL")),
            evidence_start=str(evidence_start) if evidence_start else None,
            evidence_end=str(evidence_end) if evidence_end else None,
        ),
    )
    report = evaluate_post_close_result(replay, stage=stage, candidate=candidate)
    report.update(
        {
            "manifest": manifest,
            "manifest_sha256": _sha256(manifest_file),
            "source_fixture_sha256": _sha256(fixture_file),
            "evidence": {
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
            },
        }
    )
    return report


__all__ = [
    "EXECUTION_GATE",
    "HELD_OUT_GATE",
    "PROSPECTIVE_GATE",
    "RETEST_EXECUTION_GATE",
    "RECONFIRMATION_EXECUTION_GATE",
    "evaluate_post_close_result",
    "screen_post_close_fixture_path",
    "summarize_executability",
    "summarize_post_close_rows",
]
