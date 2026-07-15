import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.one_minute_post_close_evaluation import (
    screen_post_close_fixture_path,
)


FIXTURE = Path("tests/fixtures/one_minute/opening_state/sample-openings.json")
MANIFEST = Path(
    "docs/analysis/2026-07-14-one-minute-symmetric-post-close-v1-manifest.json"
)
V2_MANIFEST = Path(
    "docs/analysis/2026-07-14-one-minute-post-close-retest-v2-manifest.json"
)
V3_MANIFEST = Path(
    "docs/analysis/2026-07-14-one-minute-retest-reconfirmation-v3-manifest.json"
)
V4_MANIFEST = Path(
    "docs/analysis/2026-07-14-one-minute-clean-level-reconfirmation-v4-manifest.json"
)
V5_MANIFEST = Path(
    "docs/analysis/2026-07-15-one-minute-compression-expansion-v5-manifest.json"
)
V5_1_MANIFEST = Path(
    "docs/analysis/2026-07-15-one-minute-compression-hold-v5-1-manifest.json"
)
V6_MANIFEST = Path(
    "docs/analysis/2026-07-15-one-minute-shock-reclaim-v6-manifest.json"
)
V7_MANIFEST = Path(
    "docs/analysis/2026-07-15-one-minute-impulse-inside-pullback-v7-manifest.json"
)


def test_post_close_cli_writes_deterministic_broker_free_discovery_report(tmp_path):
    output = tmp_path / "post-close-screen.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-screen",
            "--fixture",
            str(FIXTURE),
            "--manifest",
            str(MANIFEST),
            "--stage",
            "DISCOVERY",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == screen_post_close_fixture_path(
        FIXTURE,
        manifest_path=MANIFEST,
        stage="DISCOVERY",
    )
    assert payload["decision"] == "DISCOVERY_ONLY_NOT_APPROVAL"
    assert payload["broker_mutation_enabled"] is False


def test_post_close_cli_rejects_unknown_stage(tmp_path):
    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-screen",
            "--fixture",
            str(FIXTURE),
            "--manifest",
            str(MANIFEST),
            "--stage",
            "RETUNED_AFTER_RESULTS",
            "--output",
            str(tmp_path / "nope.json"),
        ],
    )

    assert result.exit_code != 0


def test_post_close_loader_ignores_non_strategy_mt5_candle_metadata(tmp_path):
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    source["candles"][0]["spread"] = 29.0
    source["candles"][0]["real_volume"] = 0.0
    fixture = tmp_path / "fixture-with-metadata.json"
    fixture.write_text(json.dumps(source), encoding="utf-8")

    report = screen_post_close_fixture_path(
        fixture,
        manifest_path=MANIFEST,
        stage="DISCOVERY",
    )

    assert report["decision"] == "DISCOVERY_ONLY_NOT_APPROVAL"
    assert report["evidence"]["candle_count"] == len(source["candles"])


def test_post_close_cli_accepts_frozen_v2_retest_manifest(tmp_path):
    output = tmp_path / "v2.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-screen",
            "--fixture",
            str(FIXTURE),
            "--manifest",
            str(V2_MANIFEST),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text(encoding="utf-8"))["candidate"] == (
        "ONE_MINUTE_POST_CLOSE_RETEST_V2"
    )


def test_post_close_cli_accepts_frozen_v3_reconfirmation_manifest(tmp_path):
    output = tmp_path / "v3.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-screen",
            "--fixture",
            str(FIXTURE),
            "--manifest",
            str(V3_MANIFEST),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate"] == "ONE_MINUTE_RETEST_RECONFIRMATION_V3"
    assert "discovery_stop" in payload


def test_post_close_cli_accepts_frozen_v4_clean_level_manifest(tmp_path):
    output = tmp_path / "v4.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-screen",
            "--fixture",
            str(FIXTURE),
            "--manifest",
            str(V4_MANIFEST),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate"] == "ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4"
    assert "discovery_stop" in payload


def test_post_close_cli_accepts_frozen_v5_compression_manifest(tmp_path):
    output = tmp_path / "v5.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-screen",
            "--fixture",
            str(FIXTURE),
            "--manifest",
            str(V5_MANIFEST),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate"] == "ONE_MINUTE_COMPRESSION_EXPANSION_V5"
    assert "discovery_stop" in payload
    assert payload["manifest"]["signal_model"] == "COMPRESSION_EXPANSION"


def test_post_close_cli_accepts_frozen_v5_1_hold_manifest(tmp_path):
    output = tmp_path / "v5-1.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-screen",
            "--fixture",
            str(FIXTURE),
            "--manifest",
            str(V5_1_MANIFEST),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate"] == "ONE_MINUTE_COMPRESSION_HOLD_V5_1"
    assert "discovery_stop" in payload
    assert payload["manifest"]["entry_policy"] == (
        "POST_CLOSE_HOLD_CONTINUATION_STOP"
    )


def test_post_close_cli_accepts_frozen_v6_shock_reclaim_manifest(tmp_path):
    output = tmp_path / "v6.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-screen",
            "--fixture",
            str(FIXTURE),
            "--manifest",
            str(V6_MANIFEST),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate"] == "ONE_MINUTE_SHOCK_RECLAIM_V6"
    assert payload["manifest"]["signal_model"] == "SHOCK_RECLAIM"
    assert payload["broker_mutation_enabled"] is False


def test_v6_loader_rejects_changed_frozen_threshold(tmp_path):
    manifest = json.loads(V6_MANIFEST.read_text(encoding="utf-8"))
    manifest["shock_range_baseline_minimum"] = 1.49
    changed = tmp_path / "changed-v6.json"
    changed.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="shock_range_baseline_minimum"):
        screen_post_close_fixture_path(
            FIXTURE,
            manifest_path=changed,
            stage="DISCOVERY",
        )


def test_post_close_cli_accepts_frozen_v7_inside_pullback_manifest(tmp_path):
    output = tmp_path / "v7.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-screen",
            "--fixture",
            str(FIXTURE),
            "--manifest",
            str(V7_MANIFEST),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["candidate"] == "ONE_MINUTE_IMPULSE_INSIDE_PULLBACK_V7"
    assert payload["manifest"]["signal_model"] == "IMPULSE_INSIDE_PULLBACK"
    assert payload["broker_mutation_enabled"] is False


def test_v7_loader_rejects_changed_frozen_threshold(tmp_path):
    manifest = json.loads(V7_MANIFEST.read_text(encoding="utf-8"))
    manifest["pullback_range_baseline_maximum"] = 0.8
    changed = tmp_path / "changed-v7.json"
    changed.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="pullback_range_baseline_maximum"):
        screen_post_close_fixture_path(
            FIXTURE,
            manifest_path=changed,
            stage="DISCOVERY",
        )


def test_post_close_multi_cli_aggregates_ordered_bounded_folds(tmp_path):
    source = json.loads(FIXTURE.read_text(encoding="utf-8"))
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text(
        json.dumps(
            {
                **source,
                "evidence_start": "2026-07-01T12:00:00+00:00",
                "evidence_end": "2026-07-01T13:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    second.write_text(
        json.dumps(
            {
                **source,
                "evidence_start": "2026-07-01T13:00:00+00:00",
                "evidence_end": "2026-07-01T14:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "multi.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-post-close-multi-screen",
            "--fixture",
            str(first),
            "--fixture",
            str(second),
            "--manifest",
            str(V5_1_MANIFEST),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["evidence"]["fold_count"] == 2
    assert len(payload["evidence"]["sources"]) == 2
    assert payload["candidate"] == "ONE_MINUTE_COMPRESSION_HOLD_V5_1"
