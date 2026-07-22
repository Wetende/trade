"""Frozen chronological evidence screening for Causal Reclaim V10."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tradingagents.agents.price_action.one_minute_causal_reclaim_v10 import (
    CANDIDATE_NAME,
)
from tradingagents.agents.price_action.one_minute_causal_microburst_v9_screening import (
    _atomic_json,
    _gate_reasons,
    _load_fixture,
    _repository_root,
    _tick_stream,
)
from tradingagents.agents.price_action.one_minute_post_close_state import parse_utc
from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import V8Config
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_evidence import (
    V8EvidenceCounters,
    summarize_v8_evidence,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_promotion import (
    sha256_file,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_replay import (
    V8ReplayConfig,
    replay_v8,
)


DISCOVERY_FOLDS = (
    ("2026-07-22T20:00:00+00:00", "2026-07-23T12:00:00+00:00"),
    ("2026-07-23T12:00:00+00:00", "2026-07-24T04:00:00+00:00"),
    ("2026-07-24T04:00:00+00:00", "2026-07-24T20:00:00+00:00"),
)
HELD_OUT_WINDOW = (
    "2026-07-26T22:00:00+00:00",
    "2026-07-28T00:00:00+00:00",
)


def screen_v10_fixture_paths(
    fixture_paths: Iterable[str | Path],
    *,
    manifest_path: str | Path,
    stage: str,
    as_of_utc: str | datetime | None = None,
    discovery_report_path: str | Path | None = None,
    prospective_registration_path: str | Path | None = None,
) -> dict[str, Any]:
    normalized_stage = str(stage).strip().upper()
    if normalized_stage not in {"DISCOVERY", "HELD_OUT", "PROSPECTIVE"}:
        raise ValueError("V10 stage must be DISCOVERY, HELD_OUT, or PROSPECTIVE")
    manifest_file = Path(manifest_path).resolve()
    manifest = validate_v10_manifest(manifest_file)
    paths = tuple(Path(value).resolve() for value in fixture_paths)
    if not paths:
        raise ValueError("at least one V10 fixture is required")
    as_of = parse_utc(as_of_utc) if as_of_utc else datetime.now(timezone.utc)
    loaded = tuple(_load_fixture(path) for path in paths)
    _validate_windows(normalized_stage, loaded, as_of)

    discovery_authorization = None
    if normalized_stage == "HELD_OUT":
        if discovery_report_path is None:
            raise ValueError("V10 held-out screening requires a discovery report")
        discovery_authorization = _validate_passing_report(
            Path(discovery_report_path).resolve(), manifest_file, "DISCOVERY"
        )
    registration = None
    if normalized_stage == "PROSPECTIVE":
        if prospective_registration_path is None:
            raise ValueError("V10 prospective screening requires a registration")
        registration = _validate_registration(
            Path(prospective_registration_path).resolve(), manifest_file, loaded[0][2]
        )

    rows = []
    sources = []
    totals = {field: 0 for field in V8EvidenceCounters.__dataclass_fields__}
    strategy = _strategy(manifest)
    for path, candles, start, end, collection in loaded:
        count = [0]
        replay = replay_v8(
            candles,
            _tick_stream(path, count),
            config=V8ReplayConfig(
                strategy=strategy,
                cost_per_fill_r=float(manifest["modeled_round_trip_cost_r"]),
                two_loss_pause_minutes=int(manifest["two_loss_pause_minutes"]),
                evidence_start=start.isoformat(),
                evidence_end=end.isoformat(),
                capture_events=False,
                ordered_ticks=True,
                candidate_name=CANDIDATE_NAME,
                signal_model="CAUSAL_RECLAIM",
                session_bucket_hours=3,
            ),
        )
        if count[0] == 0:
            raise ValueError(f"fixture has no V10 ticks: {path}")
        rows.extend(replay.rows)
        for field, value in replay.counters.as_dict().items():
            totals[field] += int(value)
        source_metrics = summarize_v8_evidence(replay.rows, replay.counters)
        sources.append(
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "evidence_start": start.isoformat(),
                "evidence_end": end.isoformat(),
                "candle_count": len(candles),
                "tick_count": count[0],
                "broker_mutation_enabled": False,
                "metrics": source_metrics,
                "collection": collection,
            }
        )

    counters = V8EvidenceCounters(**totals)
    metrics = summarize_v8_evidence(rows, counters)
    metrics["fold_net_r"] = {
        str(index + 1): source["metrics"]["net_r"]
        for index, source in enumerate(sources)
    }
    metrics["profitable_folds"] = sum(
        source["metrics"]["net_r"] > 0 for source in sources
    )
    reasons = _gate_reasons(normalized_stage, metrics, counters)
    return {
        "schema_version": 1,
        "candidate": CANDIDATE_NAME,
        "stage": normalized_stage,
        "status": "PASS" if not reasons else "FAIL",
        "retired": bool(reasons),
        "reasons": reasons,
        "metrics": metrics,
        "counters": counters.as_dict(),
        "manifest_path": str(manifest_file),
        "manifest_sha256": sha256_file(manifest_file),
        "as_of_utc": as_of.isoformat(),
        "sources": sources,
        "rows": [row.as_dict() for row in rows],
        "broker_mutation_enabled": False,
        "failed_gate_action": "RETIRED_WITHOUT_TUNING" if reasons else None,
        "discovery_authorization": discovery_authorization,
        "prospective_registration": registration,
    }


def register_v10_prospective(
    *,
    manifest_path: str | Path,
    held_out_report_path: str | Path,
    output_path: str | Path,
    registered_at_utc: str | datetime | None = None,
) -> dict[str, Any]:
    manifest_file = Path(manifest_path).resolve()
    validate_v10_manifest(manifest_file)
    heldout_file = Path(held_out_report_path).resolve()
    _validate_passing_report(heldout_file, manifest_file, "HELD_OUT")
    registered = (
        parse_utc(registered_at_utc)
        if registered_at_utc
        else datetime.now(timezone.utc)
    )
    if registered < parse_utc(HELD_OUT_WINDOW[1]):
        raise ValueError("V10 prospective registration predates held-out completion")
    payload = {
        "schema_version": 1,
        "candidate": CANDIDATE_NAME,
        "status": "REGISTERED",
        "registered_at_utc": registered.isoformat(),
        "broker_mutation_enabled": False,
        "manifest_sha256": sha256_file(manifest_file),
        "held_out_report_path": str(heldout_file),
        "held_out_report_sha256": sha256_file(heldout_file),
    }
    _atomic_json(Path(output_path), payload)
    return payload


def validate_v10_manifest(path: str | Path) -> dict[str, Any]:
    manifest_file = Path(path).resolve()
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("V10 manifest must be an object")
    if payload.get("candidate") != CANDIDATE_NAME:
        raise ValueError("unexpected V10 candidate manifest")
    if payload.get("status") != "FROZEN":
        raise ValueError("V10 manifest is not frozen")
    if payload.get("broker_mutation_enabled") is not False:
        raise ValueError("V10 manifest enables broker mutation")
    _strategy(payload)
    root = _repository_root(manifest_file)
    hashes = payload.get("artifact_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("V10 manifest artifact hashes are missing")
    for relative, expected in hashes.items():
        artifact = (root / relative).resolve()
        if root not in artifact.parents or not artifact.is_file():
            raise ValueError(f"V10 frozen artifact missing: {relative}")
        if sha256_file(artifact) != expected:
            raise ValueError(f"V10 frozen artifact hash mismatch: {relative}")
    return payload


def _strategy(manifest: dict[str, Any]) -> V8Config:
    value = manifest.get("strategy") or {}
    frozen = {
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
    mismatch = [key for key, expected in frozen.items() if value.get(key) != expected]
    if mismatch:
        raise ValueError("V10 manifest differs from frozen design: " + ", ".join(mismatch))
    return V8Config(candidate_name=CANDIDATE_NAME, **frozen)


def _validate_windows(stage: str, loaded: tuple[Any, ...], as_of: datetime) -> None:
    windows = tuple((row[2], row[3]) for row in loaded)
    if tuple(sorted(windows)) != windows:
        raise ValueError("V10 fixtures must be chronological")
    for previous, current in zip(windows, windows[1:]):
        if current[0] < previous[1]:
            raise ValueError("V10 fixture windows overlap")
    if stage == "DISCOVERY":
        expected = tuple((parse_utc(a), parse_utc(b)) for a, b in DISCOVERY_FOLDS)
        if windows != expected:
            raise ValueError("V10 discovery windows mismatch")
        if as_of < expected[-1][1]:
            raise ValueError("V10 discovery window remains incomplete")
    elif stage == "HELD_OUT":
        expected = ((parse_utc(HELD_OUT_WINDOW[0]), parse_utc(HELD_OUT_WINDOW[1])),)
        if windows != expected:
            raise ValueError("V10 held-out window mismatch")
        if as_of < expected[0][1]:
            raise ValueError("V10 held-out window remains incomplete")
    elif windows[-1][1] > as_of:
        raise ValueError("V10 prospective evidence exceeds as-of")


def _validate_passing_report(path: Path, manifest: Path, stage: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("candidate") != CANDIDATE_NAME
        or payload.get("stage") != stage
        or payload.get("status") != "PASS"
        or payload.get("retired") is not False
        or payload.get("broker_mutation_enabled") is not False
        or payload.get("manifest_sha256") != sha256_file(manifest)
    ):
        raise ValueError(f"V10 {stage.lower()} authorization is invalid")
    return {"path": str(path), "sha256": sha256_file(path)}


def _validate_registration(path: Path, manifest: Path, evidence_start: datetime) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("candidate") != CANDIDATE_NAME
        or payload.get("status") != "REGISTERED"
        or payload.get("broker_mutation_enabled") is not False
        or payload.get("manifest_sha256") != sha256_file(manifest)
    ):
        raise ValueError("V10 prospective registration is invalid")
    if evidence_start < parse_utc(payload["registered_at_utc"]):
        raise ValueError("V10 prospective evidence predates registration")
    return {"path": str(path), "sha256": sha256_file(path)}


__all__ = [
    "DISCOVERY_FOLDS",
    "HELD_OUT_WINDOW",
    "register_v10_prospective",
    "screen_v10_fixture_paths",
    "validate_v10_manifest",
]
