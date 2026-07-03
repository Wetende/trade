import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.historical_screening import (
    screen_evidence_dir,
)


FIXTURES = Path("tests/fixtures/one_minute/evidence_sessions")


def test_screening_evaluates_every_registered_variant_deterministically():
    first = screen_evidence_dir(FIXTURES)
    second = screen_evidence_dir(FIXTURES)

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert set(first["variants"]) == {
        "baseline",
        "h1_touch_maturity",
        "h2_exhaustion",
        "h3_post_loss_cluster",
        "h1_touch_maturity+h2_exhaustion",
        "h1_touch_maturity+h3_post_loss_cluster",
        "h2_exhaustion+h3_post_loss_cluster",
    }
    assert first["variants"]["baseline"]["metrics"]["fills"] == 71
    assert first["broker_mutation_enabled"] is False


def test_no_registered_variant_qualifies_on_all_three_sessions():
    report = screen_evidence_dir(FIXTURES)

    assert report["qualifying_candidates"] == []
    assert all(
        not row["gate"]["passed"]
        for name, row in report["variants"].items()
        if name != "baseline"
    )
    assert "INSUFFICIENT_HISTORICAL_EVIDENCE" in report["variants"][
        "h2_exhaustion"
    ]["gate"]["reasons"]


def test_screening_cli_writes_the_same_read_only_report(tmp_path):
    output = tmp_path / "screen.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-screen",
            "--evidence-dir",
            str(FIXTURES),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == screen_evidence_dir(FIXTURES)
    assert payload["broker_mutation_enabled"] is False
