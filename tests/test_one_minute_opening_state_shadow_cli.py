import json

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.opening_state_shadow import (
    SHADOW_DEFAULT_CANDLE_COUNT,
    SHADOW_DEFAULT_CANDLE_CLOSE_DELAY_SECONDS,
    SHADOW_DEFAULT_PLACEMENT_DELAY_SECONDS,
    build_shadow_report,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
)
from tradingagents.agents.price_action.opening_tick_replay import ReplayConfig


FIXTURE = "tests/fixtures/one_minute/opening_state/sample-openings.json"
MANIFEST = "docs/analysis/2026-07-03-one-minute-opening-state-target-grid-frozen-manifest.json"


def test_opening_shadow_cli_writes_deterministic_fixture_report(tmp_path):
    output = tmp_path / "shadow-report.json"
    heartbeat = tmp_path / "shadow-heartbeat.json"
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
        replay_config=ReplayConfig(
            risk_reward=float(manifest["final_target"]),
            candle_close_delay_seconds=SHADOW_DEFAULT_CANDLE_CLOSE_DELAY_SECONDS,
            placement_delay_seconds=SHADOW_DEFAULT_PLACEMENT_DELAY_SECONDS,
            absolute_pending_expiry=True,
            skip_if_entry_crossed_at_placement=True,
        ),
    )
    heartbeat_payload = json.loads(heartbeat.read_text(encoding="utf-8"))
    assert heartbeat_payload["schema_version"] == 1
    assert heartbeat_payload["report_path"] == str(output)
    assert heartbeat_payload["candidate"] == heartbeat_payload["report"]["candidate"]
    assert heartbeat_payload["decision"] == heartbeat_payload["report"]["decision"]
    assert heartbeat_payload["broker_mutation_enabled"] is False
    assert heartbeat_payload["open_order_count"] == 0
    assert heartbeat_payload["open_position_count"] == 0
    assert "heartbeat_utc" in heartbeat_payload
    rendered = json.dumps(heartbeat_payload)
    assert "password" not in rendered.lower()
    assert "login" not in rendered.lower()


def test_opening_shadow_cli_default_candle_count_supports_three_sessions():
    result = CliRunner().invoke(
        app,
        ["one-minute-opening-target-grid-shadow-step", "--help"],
    )

    assert result.exit_code == 0
    assert f"[default: {SHADOW_DEFAULT_CANDLE_COUNT}]" in result.output
    assert f"[default: {SHADOW_DEFAULT_CANDLE_CLOSE_DELAY_SECONDS:.1f}]" in result.output
    assert f"[default: {SHADOW_DEFAULT_PLACEMENT_DELAY_SECONDS:.1f}]" in result.output
    assert SHADOW_DEFAULT_CANDLE_COUNT >= 3 * 24 * 60
