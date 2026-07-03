from tradingagents.agents.price_action.evidence_gate import ScreeningRow
from tradingagents.agents.price_action.evidence_metrics import (
    evaluate_historical_gate,
    summarize_variant,
)


def _row(session, index, profit):
    return ScreeningRow(
        session_id=session,
        decision_index=index,
        accepted=True,
        filled=True,
        profit=profit,
    )


def test_summarize_variant_calculates_core_risk_metrics():
    rows = (
        _row("a", 0, 60.0),
        _row("a", 1, -40.0),
        _row("a", 2, -30.0),
        _row("b", 0, 50.0),
    )

    result = summarize_variant("candidate", rows, baseline_fill_count=5)

    assert result.fills == 4
    assert result.wins == 2
    assert result.losses == 2
    assert result.net_profit == 40.0
    assert result.profit_factor == 1.5714
    assert result.expectancy == 10.0
    assert result.fill_retention == 0.8
    assert result.max_loss_streak == 2
    assert result.max_session_drawdown == 70.0
    assert result.profitable_session_count == 1


def test_no_loss_profit_factor_is_explicit_not_infinite():
    result = summarize_variant(
        "no-loss",
        (_row("a", 0, 20.0),),
        baseline_fill_count=1,
    )

    assert result.profit_factor is None
    assert result.no_gross_loss is True


def test_historical_gate_reports_every_failed_requirement():
    baseline = summarize_variant(
        "baseline",
        (_row("a", 0, 100.0), _row("a", 1, -100.0)),
        baseline_fill_count=2,
    )
    candidate = summarize_variant(
        "candidate",
        (_row("a", 0, 10.0), _row("a", 1, -20.0)),
        baseline_fill_count=4,
    )

    gate = evaluate_historical_gate(candidate, baseline)

    assert gate.passed is False
    assert set(gate.reasons) >= {
        "NON_POSITIVE_EXPECTANCY",
        "PROFIT_FACTOR_BELOW_1_15",
        "FEWER_THAN_TWO_PROFITABLE_SESSIONS",
        "FILL_RETENTION_BELOW_0_60",
    }


def test_positive_no_loss_candidate_can_pass_numeric_profit_factor_gate():
    baseline = summarize_variant(
        "baseline",
        (_row("a", 0, 10.0), _row("b", 0, 10.0)),
        baseline_fill_count=2,
    )
    candidate = summarize_variant(
        "candidate",
        (_row("a", 0, 20.0), _row("b", 0, 20.0)),
        baseline_fill_count=2,
    )

    assert evaluate_historical_gate(candidate, baseline).passed is True
