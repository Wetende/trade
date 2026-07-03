"""Shallow deterministic leave-one-session-out signal selector."""

from __future__ import annotations

import hashlib
from itertools import combinations
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from tradingagents.agents.price_action.evidence_gate import (
    EvidenceDecision,
    EvidenceSession,
    ScreeningRow,
)
from tradingagents.agents.price_action.evidence_metrics import (
    HistoricalGateResult,
    VariantMetrics,
    evaluate_historical_gate,
    summarize_variant,
)


CATEGORICAL_FEATURES = (
    "trigger",
    "reaction_type",
    "direction",
    "confirmation_type",
    "level_type",
    "pressure_relation",
    "pulse_relation",
)
NUMERIC_GRIDS = {
    "score": (8, 9, 10, 11, 12, 13, 14),
    "touch_count": (2, 3, 4, 5, 6, 7, 8),
    "touch_age": (1, 2, 3, 5, 8),
    "body_ratio": (0.50, 0.80, 1.00, 1.20, 1.50),
    "entry_distance": (0.80, 1.00, 1.20, 1.50),
    "opposing_wick_ratio": (0.05, 0.10, 0.20, 0.30),
    "stop_to_spread_ratio": (2.0, 2.5, 3.0),
    "utc_hour": (0, 6, 12, 18),
}


class RuleClause(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    feature: str
    operator: Literal["eq", "ne", "ge", "le"]
    value: str | float

    @model_validator(mode="after")
    def validate_grammar(self) -> "RuleClause":
        if self.feature in CATEGORICAL_FEATURES:
            if self.operator not in {"eq", "ne"} or not isinstance(
                self.value, str
            ):
                raise ValueError("categorical clause has invalid operator")
            return self
        grid = NUMERIC_GRIDS.get(self.feature)
        if grid is None:
            raise ValueError("feature is not in the pre-registered grammar")
        if self.operator not in {"ge", "le"}:
            raise ValueError("numeric clause has invalid operator")
        if float(self.value) not in grid:
            raise ValueError("numeric threshold is outside the fixed grid")
        return self

    @property
    def canonical(self) -> str:
        return f"{self.feature} {self.operator} {self.value}"

    def matches(self, decision: EvidenceDecision) -> bool:
        actual = getattr(decision, self.feature)
        if actual is None:
            return False
        if self.operator == "eq":
            return actual == self.value
        if self.operator == "ne":
            return actual != self.value
        if self.operator == "ge":
            return float(actual) >= float(self.value)
        return float(actual) <= float(self.value)


class SelectorRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    clauses: tuple[RuleClause, ...]

    @model_validator(mode="after")
    def validate_depth(self) -> "SelectorRule":
        if not 1 <= len(self.clauses) <= 2:
            raise ValueError("selector rules require one or two clauses")
        return self

    @property
    def canonical(self) -> str:
        return " AND ".join(
            sorted(clause.canonical for clause in self.clauses)
        )

    def matches(self, decision: EvidenceDecision) -> bool:
        return all(clause.matches(decision) for clause in self.clauses)


class WalkForwardFold(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    held_out_session: str
    rule: str | None
    training_metrics: VariantMetrics | None
    held_out_fills: int


class WalkForwardResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    folds: tuple[WalkForwardFold, ...]
    metrics: VariantMetrics
    gate: HistoricalGateResult


def generate_rules(
    sessions: tuple[EvidenceSession, ...],
) -> tuple[SelectorRule, ...]:
    decisions = [
        decision for session in sessions for decision in session.decisions
    ]
    clauses: list[RuleClause] = []
    for feature in CATEGORICAL_FEATURES:
        values = {getattr(decision, feature) for decision in decisions}
        if None in values:
            continue
        for value in sorted(values):
            clauses.extend(
                RuleClause(feature=feature, operator=operator, value=value)
                for operator in ("eq", "ne")
            )
    for feature, grid in NUMERIC_GRIDS.items():
        if any(getattr(decision, feature) is None for decision in decisions):
            continue
        for value in grid:
            clauses.extend(
                RuleClause(feature=feature, operator=operator, value=value)
                for operator in ("ge", "le")
            )
    rules = [SelectorRule(clauses=(clause,)) for clause in clauses]
    rules.extend(
        SelectorRule(clauses=pair) for pair in combinations(clauses, 2)
    )
    unique = {rule.canonical: rule for rule in rules}
    return tuple(unique[key] for key in sorted(unique))


def _observations(
    sessions: tuple[EvidenceSession, ...],
) -> list[tuple[EvidenceSession, int, float]]:
    observations = []
    for session in sessions:
        for trade in session.trades:
            if trade.filled and trade.profit is not None:
                observations.append(
                    (session, trade.decision_index, float(trade.profit))
                )
    return observations


def _rows_for_rule(
    observations: list[tuple[EvidenceSession, int, float]],
    rule: SelectorRule,
) -> tuple[ScreeningRow, ...]:
    return tuple(
        ScreeningRow(
            session_id=session.session_id,
            decision_index=index,
            accepted=True,
            filled=True,
            profit=profit,
        )
        for session, index, profit in observations
        if rule.matches(session.decisions[index])
    )


def run_walk_forward(
    sessions: tuple[EvidenceSession, ...],
) -> WalkForwardResult:
    if len(sessions) < 3:
        raise ValueError("walk-forward screening requires at least three sessions")
    rules = generate_rules(sessions)
    all_observations = _observations(sessions)
    baseline_rows = tuple(
        ScreeningRow(
            session_id=session.session_id,
            decision_index=index,
            accepted=True,
            filled=True,
            profit=profit,
        )
        for session, index, profit in all_observations
    )
    baseline = summarize_variant(
        "baseline",
        baseline_rows,
        baseline_fill_count=len(baseline_rows),
    )
    held_out_rows: list[ScreeningRow] = []
    folds: list[WalkForwardFold] = []
    no_rule = False
    for held_out in sessions:
        training = tuple(
            session for session in sessions if session is not held_out
        )
        training_observations = _observations(training)
        candidates: list[tuple[SelectorRule, VariantMetrics]] = []
        for rule in rules:
            rows = _rows_for_rule(training_observations, rule)
            metrics = summarize_variant(
                rule.canonical,
                rows,
                baseline_fill_count=len(training_observations),
            )
            if metrics.fill_retention >= 0.60 and metrics.expectancy > 0:
                candidates.append((rule, metrics))
        if not candidates:
            no_rule = True
            folds.append(
                WalkForwardFold(
                    held_out_session=held_out.session_id,
                    rule=None,
                    training_metrics=None,
                    held_out_fills=0,
                )
            )
            continue
        candidates.sort(
            key=lambda item: (
                -(
                    float("inf")
                    if item[1].profit_factor is None
                    else item[1].profit_factor
                ),
                -item[1].expectancy,
                -item[1].fills,
                len(item[0].clauses),
                item[0].canonical,
            )
        )
        rule, training_metrics = candidates[0]
        rows = _rows_for_rule(_observations((held_out,)), rule)
        held_out_rows.extend(rows)
        folds.append(
            WalkForwardFold(
                held_out_session=held_out.session_id,
                rule=rule.canonical,
                training_metrics=training_metrics,
                held_out_fills=len(rows),
            )
        )
    metrics = summarize_variant(
        "walk_forward",
        tuple(held_out_rows),
        baseline_fill_count=len(baseline_rows),
    )
    evaluated = evaluate_historical_gate(metrics, baseline)
    reasons = list(evaluated.reasons)
    if no_rule:
        reasons.append("NO_RULE_FOR_FOLD")
    return WalkForwardResult(
        folds=tuple(folds),
        metrics=metrics,
        gate=HistoricalGateResult(passed=not reasons, reasons=tuple(reasons)),
    )


def screen_walk_forward_dir(evidence_dir: str | Path) -> dict[str, Any]:
    root = Path(evidence_dir)
    files = sorted(root.glob("*.json"))
    sessions = tuple(
        EvidenceSession.model_validate_json(path.read_text(encoding="utf-8"))
        for path in files
    )
    result = run_walk_forward(sessions)
    return {
        "schema_version": 1,
        "broker_mutation_enabled": False,
        "threshold_grid_version": 1,
        "source_fixture_hashes": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in files
        },
        "rule_count": len(generate_rules(sessions)),
        "result": result.model_dump(mode="json"),
        "decision": (
            "FREEZE_WALK_FORWARD_CANDIDATE"
            if result.gate.passed
            else "NO_WALK_FORWARD_CANDIDATE"
        ),
    }
