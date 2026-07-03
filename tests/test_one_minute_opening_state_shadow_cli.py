import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.opening_state_shadow import (
    SHADOW_DEFAULT_CANDLE_COUNT,
    build_shadow_report,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
)


FIXTURE = "tests/fixtures/one_minute/opening_state/sample-openings.json"
MANIFEST = "docs/analysis/2026-07-03-one-minute-opening-state-target-grid-frozen-manifest.json"


def test_opening_shadow_cli_writes_deterministic_fixture_report(tmp_path):
    output = tmp_path / "shadow-report.json"
    prospective_start = "2026-07-01T00:00:00+00:00"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-opening-target-grid-shadow-step",
            "--manifest",
            MANIFEST,
            "--prospective-start",
            prospective_start,
            "--fixture",
            FIXTURE,
            "--output",
            str(output),
        ],
    )

    manifest = json.loads(open(MANIFEST, encoding="utf-8").read())
    fixture = OpeningResearchFixture.model_validate_json(
        open(FIXTURE, encoding="utf-8").read()
    )
    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == build_shadow_report(
        fixture,
        manifest=manifest,
        prospective_start=prospective_start,
    )


def test_opening_shadow_cli_default_candle_count_supports_three_sessions():
    result = CliRunner().invoke(
        app,
        ["one-minute-opening-target-grid-shadow-step", "--help"],
    )

    assert result.exit_code == 0
    assert f"[default: {SHADOW_DEFAULT_CANDLE_COUNT}]" in result.output
    assert SHADOW_DEFAULT_CANDLE_COUNT >= 3 * 24 * 60
