"""Frozen V8 fixture screening with chronological-window locks."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_post_close_state import (
    QuoteObservation,
    parse_utc,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import (
    CANDIDATE_NAME,
    V8Config,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_evidence import (
    DISCOVERY_FOLDS,
    HELD_OUT_WINDOW,
    V8EvidenceCounters,
    evaluate_v8_evidence,
    summarize_v8_evidence,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_promotion import (
    sha256_file,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_replay import (
    V8ReplayConfig,
    replay_v8,
)


def screen_v8_fixture_paths(
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
        raise ValueError("V8 stage must be DISCOVERY, HELD_OUT, or PROSPECTIVE")
    manifest_file = Path(manifest_path).resolve()
    manifest = _manifest(manifest_file)
    paths = tuple(Path(value).resolve() for value in fixture_paths)
    if not paths:
        raise ValueError("at least one V8 fixture is required")
    as_of = (
        parse_utc(as_of_utc)
        if as_of_utc is not None
        else datetime.now(timezone.utc)
    )
    loaded = tuple(_load_fixture(path) for path in paths)
    _validate_windows(normalized_stage, loaded, as_of)
    discovery_authorization = None
    if normalized_stage == "HELD_OUT":
        if discovery_report_path is None:
            raise ValueError("V8 held-out screening requires a passing discovery report")
        discovery_authorization = _validate_discovery_report(
            Path(discovery_report_path).resolve(),
            manifest_file,
        )
    registration = None
    if normalized_stage == "PROSPECTIVE":
        if prospective_registration_path is None:
            raise ValueError("V8 prospective screening requires a fresh registration")
        registration = _validate_registration(
            Path(prospective_registration_path).resolve(),
            manifest_file,
            loaded[0][2],
        )

    all_rows = []
    events = []
    sources = []
    total = {
        field: 0
        for field in V8EvidenceCounters.__dataclass_fields__
    }
    for path, candles, start, end, collection in loaded:
        tick_count = [0]
        replay_policy = V8ReplayConfig(
            strategy=_strategy(manifest),
            cost_per_fill_r=float(manifest["modeled_round_trip_cost_r"]),
            two_loss_pause_minutes=int(manifest["two_loss_pause_minutes"]),
            evidence_start=start.isoformat(),
            evidence_end=end.isoformat(),
            capture_events=False,
            ordered_ticks=True,
        )
        replay = replay_v8(
            candles,
            _tick_stream(path, tick_count),
            config=replay_policy,
        )
        if tick_count[0] == 0:
            raise ValueError(f"fixture has no post-close ticks: {path}")
        all_rows.extend(replay.rows)
        events.extend(replay.events)
        for field, value in replay.counters.as_dict().items():
            total[field] += int(value)
        sources.append(
            {
                "path": str(path),
                "sha256": sha256_file(path),
                "evidence_start": start.isoformat(),
                "evidence_end": end.isoformat(),
                "candle_count": len(candles),
                "tick_count": tick_count[0],
                "broker_mutation_enabled": False,
                "metrics": summarize_v8_evidence(
                    replay.rows,
                    replay.counters,
                ),
                "collection": collection,
            }
        )
    all_rows.sort(
        key=lambda row: (
            parse_utc(row.closed_at or row.filled_at or row.armed_at),
            row.arm_id,
        )
    )
    counters = V8EvidenceCounters(**total)
    report = evaluate_v8_evidence(normalized_stage, all_rows, counters).as_dict()
    report.update(
        {
            "schema_version": 1,
            "manifest_path": str(manifest_file),
            "manifest_sha256": sha256_file(manifest_file),
            "as_of_utc": as_of.isoformat(),
            "sources": sources,
            "rows": [row.as_dict() for row in all_rows],
            "broker_mutation_enabled": False,
            "frozen_thresholds": manifest["strategy"],
            "failed_gate_action": (
                "RETIRED_WITHOUT_TUNING" if report["retired"] else None
            ),
            "discovery_authorization": discovery_authorization,
            "prospective_registration": registration,
        }
    )
    return report


def register_v8_prospective(
    *,
    manifest_path: str | Path,
    held_out_report_path: str | Path,
    output_path: str | Path,
    registered_at_utc: str | datetime | None = None,
) -> dict[str, Any]:
    """Open a fresh prospective clock only after a passing held-out report."""
    manifest_file = Path(manifest_path).resolve()
    _manifest(manifest_file)
    heldout_file = Path(held_out_report_path).resolve()
    heldout = json.loads(heldout_file.read_text(encoding="utf-8"))
    if not isinstance(heldout, dict):
        raise ValueError("held-out report must be an object")
    if heldout.get("candidate") != CANDIDATE_NAME:
        raise ValueError("held-out candidate mismatch")
    if heldout.get("stage") != "HELD_OUT":
        raise ValueError("prospective registration requires a held-out report")
    if heldout.get("status") != "PASS" or heldout.get("retired") is not False:
        raise ValueError("prospective registration requires a passing held-out gate")
    if heldout.get("manifest_sha256") != sha256_file(manifest_file):
        raise ValueError("held-out report manifest hash mismatch")
    registered = (
        parse_utc(registered_at_utc)
        if registered_at_utc is not None
        else datetime.now(timezone.utc)
    )
    if registered < parse_utc(HELD_OUT_WINDOW[1]):
        raise ValueError("prospective registration cannot predate held-out completion")
    record = {
        "schema_version": 1,
        "candidate": CANDIDATE_NAME,
        "status": "REGISTERED",
        "broker_mutation_enabled": False,
        "registered_at_utc": registered.isoformat(),
        "manifest_sha256": sha256_file(manifest_file),
        "held_out_report_path": str(heldout_file),
        "held_out_report_sha256": sha256_file(heldout_file),
    }
    _atomic_json(Path(output_path), record)
    return record


def _manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read V8 manifest") from exc
    if not isinstance(payload, dict):
        raise ValueError("V8 manifest must be an object")
    if payload.get("candidate") != CANDIDATE_NAME:
        raise ValueError("unexpected V8 candidate manifest")
    if payload.get("status") != "FROZEN":
        raise ValueError("V8 manifest is not frozen")
    if payload.get("broker_mutation_enabled") is not False:
        raise ValueError("V8 screening manifest must disable broker mutation")
    hashes = payload.get("artifact_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError("V8 manifest artifact hashes are missing")
    root = _repository_root(path)
    for relative, expected in hashes.items():
        artifact = (root / relative).resolve()
        if root not in artifact.parents:
            raise ValueError("V8 manifest artifact path escapes repository")
        if not artifact.is_file() or sha256_file(artifact) != expected:
            raise ValueError(f"V8 frozen artifact hash mismatch: {relative}")
    return payload


def validate_v8_manifest(path: str | Path) -> dict[str, Any]:
    """Validate the frozen candidate and every hash-addressed artifact."""
    return _manifest(Path(path).resolve())


def _repository_root(manifest_path: Path) -> Path:
    for parent in manifest_path.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise ValueError("V8 manifest is not inside a repository")


def _load_fixture(
    path: Path,
) -> tuple[Path, tuple[Candle, ...], datetime, datetime, dict[str, Any]]:
    if _read_json_value(path, "broker_mutation_enabled") is not False:
        raise ValueError(f"fixture is not read-only: {path}")
    start = parse_utc(str(_read_json_value(path, "evidence_start")))
    end = parse_utc(str(_read_json_value(path, "evidence_end")))
    if end <= start:
        raise ValueError(f"fixture evidence window is invalid: {path}")
    candles = tuple(
            Candle(
                timestamp=str(row["timestamp"]),
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(
                    row.get("real_volume")
                    or row.get("tick_volume")
                    or row.get("volume")
                    or 0.0
                ),
            )
            for row in _iter_json_array(path, "candles")
    )
    if len(candles) < 60:
        raise ValueError(f"fixture has fewer than 60 closed-context candles: {path}")
    collection = _read_json_value(path, "collection")
    if not isinstance(collection, dict):
        collection = {}
    return path, candles, start, end, collection


def _tick_stream(path: Path, count: list[int]) -> Iterable[QuoteObservation]:
    for row in _iter_json_array(path, "ticks"):
        count[0] += 1
        yield QuoteObservation(
            time=str(row["time"]),
            bid=float(row["bid"]),
            ask=float(row["ask"]),
        )


def _read_json_value(path: Path, key: str) -> Any:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as handle:
        buffer = _seek_json_key(handle, key)
        while True:
            stripped = buffer.lstrip()
            try:
                value, _end = decoder.raw_decode(stripped)
                return value
            except json.JSONDecodeError as exc:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    raise ValueError(f"cannot decode fixture field {key}: {path}") from exc
                buffer += chunk


def _iter_json_array(path: Path, key: str) -> Iterable[dict[str, Any]]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as handle:
        buffer = _seek_json_key(handle, key)
        position = 0
        while True:
            while position < len(buffer) and buffer[position].isspace():
                position += 1
            if position < len(buffer):
                if buffer[position] != "[":
                    raise ValueError(f"fixture field is not an array: {key}")
                position += 1
                break
            chunk = handle.read(1024 * 1024)
            if not chunk:
                raise ValueError(f"fixture array is missing: {key}")
            buffer += chunk
        while True:
            while position < len(buffer) and (
                buffer[position].isspace() or buffer[position] == ","
            ):
                position += 1
            if position < len(buffer) and buffer[position] == "]":
                return
            try:
                value, end = decoder.raw_decode(buffer, position)
            except json.JSONDecodeError as exc:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    raise ValueError(f"cannot decode fixture array {key}: {path}") from exc
                if position:
                    buffer = buffer[position:]
                    position = 0
                buffer += chunk
                continue
            if not isinstance(value, dict):
                raise ValueError(f"fixture array {key} contains a non-object")
            yield value
            position = end
            if position >= 1024 * 1024:
                buffer = buffer[position:]
                position = 0


def _seek_json_key(handle: Any, key: str) -> str:
    marker = json.dumps(key)
    buffer = ""
    while True:
        chunk = handle.read(1024 * 1024)
        if not chunk:
            raise ValueError(f"fixture field is missing: {key}")
        buffer += chunk
        position = buffer.find(marker)
        if position >= 0:
            colon = buffer.find(":", position + len(marker))
            if colon >= 0:
                return buffer[colon + 1 :]
        buffer = buffer[-(len(marker) + 2) :]


def _validate_windows(
    stage: str,
    loaded: tuple[
        tuple[Path, tuple[Candle, ...], datetime, datetime, dict[str, Any]],
        ...,
    ],
    as_of: datetime,
) -> None:
    windows = tuple((start, end) for _path, _candles, start, end, _collection in loaded)
    if tuple(sorted(windows)) != windows:
        raise ValueError("V8 fixtures must be supplied chronologically")
    for previous, current in zip(windows, windows[1:]):
        if current[0] < previous[1]:
            raise ValueError("V8 fixture evidence windows must not overlap")
    if stage == "DISCOVERY":
        expected = tuple((parse_utc(start), parse_utc(end)) for start, end in DISCOVERY_FOLDS)
        if windows != expected:
            raise ValueError("V8 discovery requires the three untouched frozen folds")
    elif stage == "HELD_OUT":
        expected = ((parse_utc(HELD_OUT_WINDOW[0]), parse_utc(HELD_OUT_WINDOW[1])),)
        if windows != expected:
            raise ValueError("V8 held-out requires exactly July 13-20")
        if as_of < expected[0][1]:
            raise ValueError("V8 held-out window is not complete and remains sealed")
    else:
        if windows[0][0] < parse_utc(HELD_OUT_WINDOW[1]):
            raise ValueError("V8 prospective evidence cannot predate held-out completion")
        if windows[-1][1] > as_of:
            raise ValueError("V8 prospective evidence cannot extend beyond as-of")


def _strategy(manifest: dict[str, Any]) -> V8Config:
    value = manifest.get("strategy") or {}
    required = {
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
        "maximum_stop_distance": 1.0,
        "risk_reward": 1.5,
    }
    mismatch = [key for key, expected in required.items() if value.get(key) != expected]
    if mismatch:
        raise ValueError("V8 manifest differs from frozen design: " + ", ".join(mismatch))
    return V8Config(
        history_candles=int(value["history_candles"]),
        pressure_change_count=int(value["pressure_change_count"]),
        pressure_window_seconds=float(value["pressure_window_seconds"]),
        minimum_nonzero_moves=int(value["minimum_nonzero_moves"]),
        minimum_directional_pressure=float(value["minimum_directional_pressure"]),
        minimum_displacement_r=float(value["minimum_displacement_r"]),
        maximum_adverse_r=float(value["maximum_adverse_r"]),
        maximum_spread_multiple=float(value["maximum_spread_multiple"]),
        placement_delay_seconds=float(value["placement_delay_seconds"]),
        pending_expiry_seconds=int(value["pending_expiry_seconds"]),
        minimum_stop_distance=float(value["minimum_stop_distance"]),
        minimum_stop_spread_multiple=float(value["minimum_stop_spread_multiple"]),
        maximum_stop_distance=float(value["maximum_stop_distance"]),
        risk_reward=float(value["risk_reward"]),
        tick_size=float(value.get("tick_size", 0.01)),
    )


def _validate_registration(
    path: Path,
    manifest_file: Path,
    prospective_start: datetime,
) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("V8 prospective registration must be an object")
    if payload.get("candidate") != CANDIDATE_NAME or payload.get("status") != "REGISTERED":
        raise ValueError("invalid V8 prospective registration")
    if payload.get("broker_mutation_enabled") is not False:
        raise ValueError("V8 prospective registration enables mutation")
    if payload.get("manifest_sha256") != sha256_file(manifest_file):
        raise ValueError("V8 prospective registration manifest hash mismatch")
    heldout = Path(str(payload.get("held_out_report_path"))).resolve()
    if not heldout.is_file() or sha256_file(heldout) != payload.get(
        "held_out_report_sha256"
    ):
        raise ValueError("V8 held-out report changed after prospective registration")
    heldout_payload = json.loads(heldout.read_text(encoding="utf-8"))
    if (
        heldout_payload.get("stage") != "HELD_OUT"
        or heldout_payload.get("status") != "PASS"
        or heldout_payload.get("retired") is not False
    ):
        raise ValueError("V8 prospective registration held-out gate is invalid")
    registered = parse_utc(str(payload.get("registered_at_utc")))
    if prospective_start < registered:
        raise ValueError("V8 prospective evidence predates its registration")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "registered_at_utc": registered.isoformat(),
        "held_out_report_sha256": payload["held_out_report_sha256"],
    }


def _validate_discovery_report(
    path: Path,
    manifest_file: Path,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("cannot read V8 discovery report") from exc
    if not isinstance(payload, dict):
        raise ValueError("V8 discovery report must be an object")
    if payload.get("candidate") != CANDIDATE_NAME or payload.get("stage") != "DISCOVERY":
        raise ValueError("V8 held-out authorization requires a discovery report")
    if payload.get("status") != "PASS" or payload.get("retired") is not False:
        raise ValueError("V8 held-out authorization requires a passing discovery gate")
    if payload.get("broker_mutation_enabled") is not False:
        raise ValueError("V8 discovery report enables broker mutation")
    if payload.get("manifest_sha256") != sha256_file(manifest_file):
        raise ValueError("V8 discovery report manifest hash mismatch")
    sources = payload.get("sources")
    if not isinstance(sources, list):
        raise ValueError("V8 discovery report sources are missing")
    windows = tuple(
        (
            str(source.get("evidence_start")),
            str(source.get("evidence_end")),
        )
        for source in sources
        if isinstance(source, dict)
    )
    if windows != DISCOVERY_FOLDS:
        raise ValueError("V8 discovery report does not cover the frozen folds")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "manifest_sha256": payload["manifest_sha256"],
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


__all__ = [
    "register_v8_prospective",
    "screen_v8_fixture_paths",
    "validate_v8_manifest",
]
