import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app


def test_walk_forward_cli_is_deterministic_and_broker_free(tmp_path):
    fixtures = Path("tests/fixtures/one_minute/evidence_sessions")
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    runner = CliRunner()

    for output in (first, second):
        result = runner.invoke(
            app,
            [
                "one-minute-walk-forward",
                "--evidence-dir",
                str(fixtures),
                "--output",
                str(output),
            ],
        )
        assert result.exit_code == 0

    assert first.read_bytes() == second.read_bytes()
    payload = json.loads(first.read_text())
    assert payload["broker_mutation_enabled"] is False
    assert payload["decision"] == "NO_WALK_FORWARD_CANDIDATE"
