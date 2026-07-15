import json
from datetime import timedelta

import pytest

from tradingagents.agents.price_action.one_minute_post_close_state import parse_utc
from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import CANDIDATE_NAME
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_promotion import (
    sha256_file,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_screening import (
    register_v8_prospective,
    screen_v8_fixture_paths,
)


STRATEGY = {
    "history_candles": 60,
    "pressure_change_count": 20,
    "pressure_window_seconds": 3.0,
    "minimum_nonzero_moves": 10,
    "minimum_directional_pressure": 0.60,
    "minimum_displacement_r": 0.10,
    "maximum_adverse_r": 0.15,
    "maximum_spread_multiple": 1.10,
    "placement_delay_seconds": 5.0,
    "pending_expiry_seconds": 20,
    "minimum_stop_distance": 0.35,
    "minimum_stop_spread_multiple": 1.2,
    "maximum_stop_distance": 1.0,
    "risk_reward": 1.5,
    "tick_size": 0.01,
}


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _manifest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    artifact = tmp_path / "tradingagents" / "v8.py"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("CANDIDATE='V8'\n", encoding="utf-8")
    manifest = tmp_path / "docs" / "manifest.json"
    _write_json(
        manifest,
        {
            "schema_version": 1,
            "candidate": CANDIDATE_NAME,
            "status": "FROZEN",
            "broker_mutation_enabled": False,
            "modeled_round_trip_cost_r": 0.05,
            "two_loss_pause_minutes": 15,
            "strategy": STRATEGY,
            "artifact_hashes": {"tradingagents/v8.py": sha256_file(artifact)},
        },
    )
    return manifest, artifact


def _fixture(path, start, end):
    begin = parse_utc(start)
    candles = []
    for index in range(60):
        when = begin - timedelta(minutes=60 - index)
        candles.append(
            {
                "timestamp": when.isoformat(),
                "open": 100.0,
                "high": 100.1,
                "low": 99.9,
                "close": 100.0,
                "tick_volume": 100,
            }
        )
    _write_json(
        path,
        {
            "schema_version": 1,
            "evidence_start": start,
            "evidence_end": end,
            "broker_mutation_enabled": False,
            "collection": {"read_only": True},
            "candles": candles,
            "ticks": [{"time": begin.isoformat(), "bid": 99.98, "ask": 100.02}],
        },
    )
    return path


def _passing_discovery_report(tmp_path, manifest):
    report = tmp_path / "reports" / "discovery-pass.json"
    _write_json(
        report,
        {
            "candidate": CANDIDATE_NAME,
            "stage": "DISCOVERY",
            "status": "PASS",
            "retired": False,
            "broker_mutation_enabled": False,
            "manifest_sha256": sha256_file(manifest),
            "sources": [
                {
                    "evidence_start": "2026-06-22T00:00:00+00:00",
                    "evidence_end": "2026-06-29T00:00:00+00:00",
                },
                {
                    "evidence_start": "2026-06-29T00:00:00+00:00",
                    "evidence_end": "2026-07-06T00:00:00+00:00",
                },
                {
                    "evidence_start": "2026-07-06T00:00:00+00:00",
                    "evidence_end": "2026-07-13T00:00:00+00:00",
                },
            ],
        },
    )
    return report


def test_discovery_requires_and_reports_three_untouched_folds(tmp_path):
    manifest, _artifact = _manifest(tmp_path)
    paths = [
        _fixture(tmp_path / "fold1.json", "2026-06-22T00:00:00+00:00", "2026-06-29T00:00:00+00:00"),
        _fixture(tmp_path / "fold2.json", "2026-06-29T00:00:00+00:00", "2026-07-06T00:00:00+00:00"),
        _fixture(tmp_path / "fold3.json", "2026-07-06T00:00:00+00:00", "2026-07-13T00:00:00+00:00"),
    ]

    report = screen_v8_fixture_paths(
        paths,
        manifest_path=manifest,
        stage="DISCOVERY",
        as_of_utc="2026-07-15T00:00:00+00:00",
    )

    assert report["candidate"] == CANDIDATE_NAME
    assert report["status"] == "FAIL"
    assert report["retired"] is True
    assert report["failed_gate_action"] == "RETIRED_WITHOUT_TUNING"
    assert report["broker_mutation_enabled"] is False
    assert len(report["sources"]) == 3


def test_held_out_remains_sealed_until_july_twenty(tmp_path):
    manifest, _artifact = _manifest(tmp_path)
    discovery = _passing_discovery_report(tmp_path, manifest)
    heldout = _fixture(
        tmp_path / "heldout.json",
        "2026-07-13T00:00:00+00:00",
        "2026-07-20T00:00:00+00:00",
    )

    with pytest.raises(ValueError, match="remains sealed"):
        screen_v8_fixture_paths(
            [heldout],
            manifest_path=manifest,
            stage="HELD_OUT",
            as_of_utc="2026-07-19T23:59:59+00:00",
        )

    report = screen_v8_fixture_paths(
        [heldout],
        manifest_path=manifest,
        stage="HELD_OUT",
        as_of_utc="2026-07-20T00:00:00+00:00",
        discovery_report_path=discovery,
    )
    assert report["stage"] == "HELD_OUT"
    assert report["discovery_authorization"]["sha256"] == sha256_file(discovery)


def test_held_out_requires_passing_discovery_gate(tmp_path):
    manifest, _artifact = _manifest(tmp_path)
    heldout = _fixture(
        tmp_path / "heldout.json",
        "2026-07-13T00:00:00+00:00",
        "2026-07-20T00:00:00+00:00",
    )

    with pytest.raises(ValueError, match="requires a passing discovery report"):
        screen_v8_fixture_paths(
            [heldout],
            manifest_path=manifest,
            stage="HELD_OUT",
            as_of_utc="2026-07-20T00:00:00+00:00",
        )


def test_manifest_artifact_tampering_blocks_replay(tmp_path):
    manifest, artifact = _manifest(tmp_path)
    fold = _fixture(
        tmp_path / "fold.json",
        "2026-07-13T00:00:00+00:00",
        "2026-07-20T00:00:00+00:00",
    )
    artifact.write_text("CANDIDATE='changed'\n", encoding="utf-8")

    with pytest.raises(ValueError, match="artifact hash mismatch"):
        screen_v8_fixture_paths(
            [fold],
            manifest_path=manifest,
            stage="HELD_OUT",
            as_of_utc="2026-07-20T00:00:00+00:00",
        )


def test_prospective_requires_registration_after_passing_heldout(tmp_path):
    manifest, _artifact = _manifest(tmp_path)
    heldout = tmp_path / "reports" / "heldout.json"
    _write_json(
        heldout,
        {
            "candidate": CANDIDATE_NAME,
            "stage": "HELD_OUT",
            "status": "PASS",
            "retired": False,
            "manifest_sha256": sha256_file(manifest),
        },
    )
    registration_path = tmp_path / "reports" / "prospective-registration.json"
    registration = register_v8_prospective(
        manifest_path=manifest,
        held_out_report_path=heldout,
        output_path=registration_path,
        registered_at_utc="2026-07-20T01:00:00+00:00",
    )
    prospective = _fixture(
        tmp_path / "prospective.json",
        "2026-07-20T01:00:00+00:00",
        "2026-07-21T00:00:00+00:00",
    )

    with pytest.raises(ValueError, match="requires a fresh registration"):
        screen_v8_fixture_paths(
            [prospective],
            manifest_path=manifest,
            stage="PROSPECTIVE",
            as_of_utc="2026-07-21T00:00:00+00:00",
        )

    report = screen_v8_fixture_paths(
        [prospective],
        manifest_path=manifest,
        stage="PROSPECTIVE",
        as_of_utc="2026-07-21T00:00:00+00:00",
        prospective_registration_path=registration_path,
    )
    assert report["prospective_registration"]["sha256"] == sha256_file(
        registration_path
    )
    assert registration["held_out_report_sha256"] == sha256_file(heldout)
