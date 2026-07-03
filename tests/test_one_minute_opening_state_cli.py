import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.opening_state_screening import (
    screen_opening_fixture_path,
)


FIXTURE = Path("tests/fixtures/one_minute/opening_state/sample-openings.json")


def test_opening_state_cli_writes_deterministic_broker_free_report(tmp_path):
    output = tmp_path / "opening-screen.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-opening-state-screen",
            "--fixture",
            str(FIXTURE),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == screen_opening_fixture_path(FIXTURE)
    assert payload["broker_mutation_enabled"] is False
