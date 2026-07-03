import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.opening_state_queue_fast_target import (
    screen_queue_fast_target_fixture,
)


FIXTURE = "tests/fixtures/one_minute/opening_state/sample-openings.json"


def test_opening_queue_fast_cli_writes_deterministic_report(tmp_path):
    output = tmp_path / "queue-fast-screen.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-opening-queue-fast-screen",
            "--fixture",
            FIXTURE,
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert json.loads(output.read_text(encoding="utf-8")) == (
        screen_queue_fast_target_fixture(FIXTURE)
    )
