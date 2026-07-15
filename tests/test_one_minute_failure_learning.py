import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.evidence_gate import (
    EvidenceDecision,
    EvidenceSession,
    EvidenceTrade,
)
from tradingagents.agents.price_action.failure_learning import (
    build_evidence_dir_learning_report,
    build_learning_report,
)


FIXTURES = Path("tests/fixtures/one_minute/evidence_sessions")


def _at(minutes: int, seconds: int = 0) -> datetime:
    return datetime(2026, 7, 6, 12, minutes, seconds, tzinfo=timezone.utc)


def _decision(trigger: str, *, score: float, reaction_type: str) -> EvidenceDecision:
    return EvidenceDecision(
        as_of=_at(0),
        trigger=trigger,
        direction="SELL",
        reaction_type=reaction_type,
        approved=True,
        touch_count=3,
        body_ratio=0.55 if reaction_type == "impulse_break" else None,
        confirmation_type="strong_close",
        score=score,
        level_type="three_touch",
        touch_age=1,
        entry_distance=0.8,
        opposing_wick_ratio=0.1,
        stop_to_spread_ratio=2.0,
        pressure_relation="opposed",
        pulse_relation="neutral",
        utc_hour=12,
    )


def _trade(index: int, profit: float, *, minute: int, mfe: float) -> EvidenceTrade:
    placed = _at(minute)
    return EvidenceTrade(
        decision_index=index,
        filled=True,
        placed_at=placed,
        filled_at=placed + timedelta(seconds=6 if profit < 0 else 1),
        closed_at=placed + timedelta(seconds=30),
        profit=profit,
        spread=0.3,
        mfe=mfe,
        mae=-0.8 if profit < 0 else -0.1,
    )


def test_failure_learning_tags_losses_and_proposes_shadow_only_rule():
    session = EvidenceSession(
        session_id="synthetic-scalper",
        decisions=(
            _decision("HIGH_RESPECT_SELL", score=6, reaction_type="respect"),
            _decision("HIGH_RESPECT_SELL", score=7, reaction_type="respect"),
            _decision("CLEAN_LOW_IMPULSE_SELL", score=13, reaction_type="impulse_break"),
        ),
        trades=(
            _trade(0, -90, minute=0, mfe=0.0),
            _trade(1, -50, minute=1, mfe=0.1),
            _trade(2, 80, minute=2, mfe=0.9),
        ),
    )

    report = build_learning_report((session,), min_samples=2)

    assert report["broker_mutation_enabled"] is False
    assert report["summary"]["fills"] == 3
    assert report["summary"]["net_profit"] == -60.0
    assert report["failure_taxonomy_counts"]["ZERO_MFE_REVERSAL"] == 1
    assert report["failure_taxonomy_counts"]["LOW_APPROVAL_SCORE"] == 2
    assert report["by_trigger"]["HIGH_RESPECT_SELL"]["losses"] == 2
    assert report["candidate_rule_hypotheses"][0]["key"] == (
        "BLOCK_TRIGGER:HIGH_RESPECT_SELL:*"
    )
    assert report["candidate_rule_hypotheses"][0]["status"] == (
        "SHADOW_ONLY_NOT_AUTOPROMOTED"
    )
    candidate_keys = {
        item["key"] for item in report["candidate_rule_hypotheses"]
    }
    assert "FILTER_FEATURE:ZERO_MFE_REVERSAL" not in candidate_keys
    assert "FILTER_FEATURE:LATE_FILL_AFTER_SIGNAL" not in candidate_keys
    assert report["by_outcome_diagnostic_tag"]["ZERO_MFE_REVERSAL"]["losses"] == 1
    assert report["leakage_controls"] == {
        "candidate_rules_use_decision_time_features_only": True,
        "fill_latency_is_diagnostic_only": True,
        "mfe_and_mae_are_outcome_diagnostics_only": True,
        "descriptive_exclusion_is_not_causal_evidence": True,
    }


def test_failure_learning_report_is_deterministic_for_fixture_dir():
    first = build_evidence_dir_learning_report(FIXTURES)
    second = build_evidence_dir_learning_report(FIXTURES)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["broker_mutation_enabled"] is False
    assert first["strategy_scope"] == "one_minute_scalper"
    assert first["summary"]["fills"] == 71
    assert first["source_fixture_hashes"]


def test_failure_learning_cli_writes_report(tmp_path):
    output = tmp_path / "learning.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-failure-report",
            "--evidence-dir",
            str(FIXTURES),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == build_evidence_dir_learning_report(FIXTURES)
