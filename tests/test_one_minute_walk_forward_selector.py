from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.agents.price_action.evidence_gate import (
    EvidenceDecision,
    EvidenceSession,
    EvidenceTrade,
)
from tradingagents.agents.price_action.walk_forward_selector import (
    RuleClause,
    SelectorRule,
    run_walk_forward,
)


START = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _session(name, day):
    decisions = []
    trades = []
    for index in range(5):
        as_of = START + timedelta(days=day, minutes=index)
        sell = index < 3
        decisions.append(
            EvidenceDecision(
                as_of=as_of,
                trigger="HIGH_RESPECT_SELL" if sell else "LOW_RESPECT_BUY",
                direction="SELL" if sell else "BUY",
                reaction_type="respect",
                approved=True,
                touch_count=3,
                body_ratio=0.8,
                confirmation_type="rejection",
                score=10,
                level_type="three_touch",
                pressure_relation="neutral",
                pulse_relation="neutral",
                utc_hour=0,
            )
        )
        trades.append(
            EvidenceTrade(
                decision_index=index,
                filled=True,
                placed_at=as_of,
                filled_at=as_of,
                closed_at=as_of + timedelta(seconds=30),
                profit=50.0 if sell else -50.0,
                spread=0.3,
                mfe=0.5 if sell else 0,
                mae=-0.2 if sell else -0.5,
            )
        )
    return EvidenceSession(session_id=name, decisions=decisions, trades=trades)


def test_selector_rule_is_canonical_and_rejects_missing_evidence():
    first = RuleClause(feature="score", operator="ge", value=10)
    second = RuleClause(feature="direction", operator="eq", value="SELL")
    rule = SelectorRule(clauses=(first, second))
    reversed_rule = SelectorRule(clauses=(second, first))
    decision = _session("a", 0).decisions[0]

    assert rule.canonical == reversed_rule.canonical
    assert rule.matches(decision) is True
    assert rule.matches(decision.model_copy(update={"score": None})) is False


def test_selector_rejects_threshold_outside_preregistered_grid():
    with pytest.raises(ValueError, match="fixed grid"):
        RuleClause(feature="score", operator="ge", value=10.5)


def test_walk_forward_counts_only_held_out_trades():
    result = run_walk_forward(
        (_session("a", 0), _session("b", 1), _session("c", 2))
    )

    assert len(result.folds) == 3
    assert all(fold.rule is not None for fold in result.folds)
    assert result.metrics.fills == 9
    assert result.metrics.wins == 9
    assert result.metrics.losses == 0
    assert result.metrics.profitable_session_count == 3
    assert result.gate.passed is True


def test_walk_forward_reports_no_rule_when_training_has_no_edge():
    sessions = tuple(
        session.model_copy(
            update={
                "trades": tuple(
                    trade.model_copy(update={"profit": -50.0})
                    for trade in session.trades
                )
            }
        )
        for session in (_session("a", 0), _session("b", 1), _session("c", 2))
    )

    result = run_walk_forward(sessions)

    assert result.gate.passed is False
    assert all(fold.rule is None for fold in result.folds)
    assert "NO_RULE_FOR_FOLD" in result.gate.reasons
