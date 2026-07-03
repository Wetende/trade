import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.opening_state_family import (
    screen_family_fixture,
)


FIXTURE = Path("tests/fixtures/one_minute/opening_state/sample-openings.json")


def test_opening_family_cli_writes_deterministic_report(tmp_path):
    output = tmp_path / "family-screen.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-opening-family-screen",
            "--fixture",
            str(FIXTURE),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == screen_family_fixture(FIXTURE)
    assert payload["broker_mutation_enabled"] is False
