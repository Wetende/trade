"""Frozen evidence gates for ``ONE_MINUTE_QUOTE_PRESSURE_V8``.

The evaluator is intentionally policy-only: it does not replay data, tune a
threshold, or write a promotion record.  A failed frozen stage retires the
candidate for that evidence window.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Iterable, Literal

from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
    HIGH_BREAK_BUY,
    HIGH_RESPECT_SELL,
    LOW_BREAK_SELL,
    LOW_RESPECT_BUY,
)
from tradingagents.agents.price_action.one_minute_post_close_state import parse_utc
from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import (
    CANDIDATE_NAME,
)


EvidenceStage = Literal["DISCOVERY", "HELD_OUT", "PROSPECTIVE", "DEMO_0_01"]

DISCOVERY_FOLDS = (
    ("2026-06-22T00:00:00+00:00", "2026-06-29T00:00:00+00:00"),
    ("2026-06-29T00:00:00+00:00", "2026-07-06T00:00:00+00:00"),
    ("2026-07-06T00:00:00+00:00", "2026-07-13T00:00:00+00:00"),
)
HELD_OUT_WINDOW = (
    "2026-07-13T00:00:00+00:00",
    "2026-07-20T00:00:00+00:00",
)


@dataclass(frozen=True)
class V8EvidenceRow:
    arm_id: str
    session_id: str
    family: str
    direction: str
    armed_at: str
    triggered_at: str | None = None
    placed_at: str | None = None
    filled_at: str | None = None
    closed_at: str | None = None
    outcome: str = "SKIPPED"
    reason: str = ""
    profit_r: float | None = None

    @property
    def filled(self) -> bool:
        return self.filled_at is not None

    @property
    def placed(self) -> bool:
        return self.placed_at is not None

    @property
    def triggered(self) -> bool:
        return self.triggered_at is not None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class V8EvidenceCounters:
    arms_detected: int
    valid_triggers: int
    placements: int
    fills: int
    crossed_rejections: int = 0
    geometry_rejections: int = 0
    safety_failures: int = 0
    lifecycle_failures: int = 0
    restart_failures: int = 0
    telemetry_failures: int = 0
    lookahead_failures: int = 0
    mutation_failures: int = 0
    reconciliation_failures: int = 0
    entry_drift_failures: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class V8GateReport:
    candidate: str
    stage: EvidenceStage
    status: str
    retired: bool
    reasons: tuple[str, ...]
    metrics: dict[str, Any]
    counters: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status == "PASS"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_v8_evidence(
    stage: EvidenceStage,
    rows: Iterable[V8EvidenceRow | dict[str, Any]],
    counters: V8EvidenceCounters | dict[str, Any],
) -> V8GateReport:
    """Apply one frozen stage without making tuning suggestions."""
    normalized_rows = tuple(_row(row) for row in rows)
    normalized_counters = (
        counters
        if isinstance(counters, V8EvidenceCounters)
        else V8EvidenceCounters(**dict(counters))
    )
    metrics = summarize_v8_evidence(normalized_rows, normalized_counters)
    if stage == "DISCOVERY":
        reasons = _discovery_reasons(metrics)
    elif stage == "HELD_OUT":
        reasons = _held_out_reasons(metrics)
    elif stage == "PROSPECTIVE":
        reasons = _prospective_reasons(metrics, normalized_counters)
    elif stage == "DEMO_0_01":
        reasons = _demo_reasons(metrics, normalized_counters)
    else:  # pragma: no cover - protected by Literal for typed callers
        raise ValueError(f"unsupported V8 evidence stage: {stage}")
    return V8GateReport(
        candidate=CANDIDATE_NAME,
        stage=stage,
        status="PASS" if not reasons else "FAIL",
        retired=bool(reasons),
        reasons=tuple(reasons),
        metrics=metrics,
        counters=normalized_counters.as_dict(),
    )


def summarize_v8_evidence(
    rows: Iterable[V8EvidenceRow],
    counters: V8EvidenceCounters,
) -> dict[str, Any]:
    ordered = tuple(sorted(rows, key=_row_time))
    trades = tuple(
        row for row in ordered if row.filled and row.profit_r is not None
    )
    profits = tuple(float(row.profit_r) for row in trades)
    wins = sum(value > 0 for value in profits)
    losses = sum(value < 0 for value in profits)
    gross_profit = sum(max(0.0, value) for value in profits)
    gross_loss = abs(sum(min(0.0, value) for value in profits))
    net = sum(profits)
    profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else (math.inf if gross_profit > 0 else 0.0)
    )
    sessions: dict[str, list[float]] = defaultdict(list)
    directions: dict[str, list[float]] = defaultdict(list)
    families: dict[str, list[float]] = defaultdict(list)
    for row in trades:
        value = float(row.profit_r)
        sessions[row.session_id].append(value)
        directions[row.direction.upper()].append(value)
        families[row.family].append(value)
    session_net = {key: round(sum(values), 10) for key, values in sessions.items()}
    direction_net = {key: round(sum(values), 10) for key, values in directions.items()}
    family_net = {key: round(sum(values), 10) for key, values in families.items()}
    category_net = {
        "BREAK": round(
            family_net.get(HIGH_BREAK_BUY, 0.0)
            + family_net.get(LOW_BREAK_SELL, 0.0),
            10,
        ),
        "RESPECT": round(
            family_net.get(HIGH_RESPECT_SELL, 0.0)
            + family_net.get(LOW_RESPECT_BUY, 0.0),
            10,
        ),
        "FAILED_BREAK": round(
            family_net.get(FAILED_HIGH_BREAK_SELL, 0.0)
            + family_net.get(FAILED_LOW_BREAK_BUY, 0.0),
            10,
        ),
    }
    profitable_sessions = sum(value > 0 for value in session_net.values())
    session_count = len(session_net)
    fold_net = _fold_net(trades)
    best_session = max(session_net.values(), default=0.0)
    net_without_best = net - best_session if session_net else net
    extra_cost_net = net - 0.05 * len(trades)
    arms = max(0, counters.arms_detected)
    triggers = max(0, counters.valid_triggers)
    placements = max(0, counters.placements)
    return {
        "fills": len(trades),
        "wins": wins,
        "losses": losses,
        "break_even": len(trades) - wins - losses,
        "net_r": round(net, 10),
        "gross_profit_r": round(gross_profit, 10),
        "gross_loss_r": round(gross_loss, 10),
        "profit_factor": profit_factor,
        "expectancy_r": round(net / len(trades), 10) if trades else 0.0,
        "maximum_loss_streak": _maximum_loss_streak(profits),
        "portfolio_drawdown_r": round(_maximum_drawdown(profits), 10),
        "maximum_session_drawdown_r": round(
            max((_maximum_drawdown(values) for values in sessions.values()), default=0.0),
            10,
        ),
        "sessions": session_count,
        "profitable_sessions": profitable_sessions,
        "profitable_session_rate": (
            profitable_sessions / session_count if session_count else 0.0
        ),
        "session_net_r": session_net,
        "direction_net_r": direction_net,
        "family_net_r": family_net,
        "mirrored_category_net_r": category_net,
        "positive_mirrored_categories": sum(
            value > 0 for value in category_net.values()
        ),
        "fold_net_r": fold_net,
        "profitable_folds": sum(value > 0 for value in fold_net.values()),
        "trigger_rate": counters.valid_triggers / arms if arms else 0.0,
        "placement_success_rate": placements / triggers if triggers else 0.0,
        "fill_success_rate": counters.fills / placements if placements else 0.0,
        "valid_trigger_placement_fill_rate": (
            counters.fills / triggers if triggers else 0.0
        ),
        "crossed_rate": counters.crossed_rejections / triggers if triggers else 0.0,
        "geometry_rejection_rate": (
            counters.geometry_rejections / triggers if triggers else 0.0
        ),
        "net_without_best_session_r": round(net_without_best, 10),
        "net_with_extra_0_05r_cost_r": round(extra_cost_net, 10),
    }


def _discovery_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    _minimum(reasons, metrics, "fills", 30)
    _minimum(reasons, metrics, "sessions", 10)
    _positive(reasons, metrics, "net_r")
    _minimum(reasons, metrics, "profit_factor", 1.15)
    _minimum(reasons, metrics, "expectancy_r", 0.05)
    for direction in ("BUY", "SELL"):
        if metrics["direction_net_r"].get(direction, 0.0) <= 0:
            reasons.append(f"{direction.lower()}_net_not_positive")
    _minimum(reasons, metrics, "positive_mirrored_categories", 2)
    if metrics["profitable_sessions"] * 2 < metrics["sessions"]:
        reasons.append("fewer_than_half_sessions_profitable")
    _minimum(reasons, metrics, "profitable_folds", 2)
    _maximum(reasons, metrics, "maximum_loss_streak", 6)
    _maximum(reasons, metrics, "portfolio_drawdown_r", 8.0)
    _maximum(reasons, metrics, "maximum_session_drawdown_r", 3.0)
    _minimum(reasons, metrics, "trigger_rate", 0.15)
    _minimum(reasons, metrics, "valid_trigger_placement_fill_rate", 0.85)
    _maximum(reasons, metrics, "crossed_rate", 0.15)
    _maximum(reasons, metrics, "geometry_rejection_rate", 0.05)
    return reasons


def _held_out_reasons(metrics: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    _minimum(reasons, metrics, "fills", 15)
    _minimum(reasons, metrics, "sessions", 5)
    _positive(reasons, metrics, "net_r")
    _minimum(reasons, metrics, "profit_factor", 1.25)
    _minimum(reasons, metrics, "expectancy_r", 0.10)
    _positive(reasons, metrics, "net_without_best_session_r")
    _positive(reasons, metrics, "net_with_extra_0_05r_cost_r")
    return reasons


def _prospective_reasons(
    metrics: dict[str, Any], counters: V8EvidenceCounters
) -> list[str]:
    reasons: list[str] = []
    _minimum(reasons, metrics, "fills", 60)
    _minimum(reasons, metrics, "sessions", 10)
    _positive(reasons, metrics, "net_r")
    _minimum(reasons, metrics, "profit_factor", 1.20)
    _minimum(reasons, metrics, "expectancy_r", 0.08)
    _minimum(reasons, metrics, "profitable_session_rate", 0.60)
    _zero_failure_reasons(reasons, counters)
    return reasons


def _demo_reasons(
    metrics: dict[str, Any], counters: V8EvidenceCounters
) -> list[str]:
    reasons: list[str] = []
    _minimum(reasons, metrics, "fills", 30)
    _minimum(reasons, metrics, "sessions", 5)
    _positive(reasons, metrics, "net_r")
    _positive(reasons, metrics, "expectancy_r")
    _minimum(reasons, metrics, "profit_factor", 1.10)
    _maximum(reasons, metrics, "portfolio_drawdown_r", 3.0)
    _zero_failure_reasons(reasons, counters)
    if counters.reconciliation_failures:
        reasons.append("broker_reconciliation_incomplete")
    if counters.entry_drift_failures:
        reasons.append("live_entry_drift_noncompliant")
    return reasons


def _zero_failure_reasons(
    reasons: list[str], counters: V8EvidenceCounters
) -> None:
    for field_name in (
        "lookahead_failures",
        "mutation_failures",
        "lifecycle_failures",
        "restart_failures",
        "safety_failures",
        "telemetry_failures",
    ):
        if getattr(counters, field_name):
            reasons.append(f"{field_name}_nonzero")


def _fold_net(trades: Iterable[V8EvidenceRow]) -> dict[str, float]:
    totals = {f"fold_{index + 1}": 0.0 for index in range(len(DISCOVERY_FOLDS))}
    for row in trades:
        when = parse_utc(row.closed_at or row.filled_at or row.armed_at)
        for index, (start, end) in enumerate(DISCOVERY_FOLDS):
            if parse_utc(start) <= when < parse_utc(end):
                totals[f"fold_{index + 1}"] += float(row.profit_r or 0.0)
                break
    return {key: round(value, 10) for key, value in totals.items()}


def _maximum_loss_streak(profits: Iterable[float]) -> int:
    current = maximum = 0
    for value in profits:
        if value < 0:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 0
    return maximum


def _maximum_drawdown(profits: Iterable[float]) -> float:
    equity = peak = drawdown = 0.0
    for value in profits:
        equity += float(value)
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def _row(value: V8EvidenceRow | dict[str, Any]) -> V8EvidenceRow:
    return value if isinstance(value, V8EvidenceRow) else V8EvidenceRow(**dict(value))


def _row_time(row: V8EvidenceRow) -> datetime:
    return parse_utc(row.closed_at or row.filled_at or row.placed_at or row.armed_at)


def _minimum(
    reasons: list[str], metrics: dict[str, Any], field_name: str, threshold: float
) -> None:
    if float(metrics[field_name]) < threshold:
        reasons.append(f"{field_name}_below_{threshold:g}")


def _maximum(
    reasons: list[str], metrics: dict[str, Any], field_name: str, threshold: float
) -> None:
    if float(metrics[field_name]) > threshold:
        reasons.append(f"{field_name}_above_{threshold:g}")


def _positive(reasons: list[str], metrics: dict[str, Any], field_name: str) -> None:
    if float(metrics[field_name]) <= 0:
        reasons.append(f"{field_name}_not_positive")


__all__ = [
    "DISCOVERY_FOLDS",
    "HELD_OUT_WINDOW",
    "V8EvidenceCounters",
    "V8EvidenceRow",
    "V8GateReport",
    "evaluate_v8_evidence",
    "summarize_v8_evidence",
]
