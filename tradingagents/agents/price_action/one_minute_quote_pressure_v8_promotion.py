"""Hash-locked promotion records for the One Minute Scalper V8."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import (
    CANDIDATE_NAME,
)


INITIAL_STAGES = ("DISCOVERY", "HELD_OUT", "PROSPECTIVE")
VOLUME_ONE_STAGES = (*INITIAL_STAGES, "DEMO_0_01")


class V8PromotionError(RuntimeError):
    """Raised when V8 order-capable startup cannot prove promotion."""


@dataclass(frozen=True)
class V8PromotionValidation:
    candidate: str
    manifest_path: str
    manifest_sha256: str
    promotion_path: str
    promotion_sha256: str
    approved_volume_cap: float
    promotion_kind: str
    evidence_stages: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_v8_promotion(
    manifest_path: str | Path,
    promotion_path: str | Path,
    *,
    requested_volume: float,
    repo_root: str | Path,
) -> V8PromotionValidation:
    """Validate every startup hash and DEMO-only approval constraint."""
    root = Path(repo_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    promotion_file = Path(promotion_path).resolve()
    manifest = _json_object(manifest_file)
    promotion = _json_object(promotion_file)
    _require(manifest.get("schema_version") == 1, "unsupported candidate manifest schema")
    _require(manifest.get("candidate") == CANDIDATE_NAME, "candidate manifest mismatch")
    _require(manifest.get("status") == "FROZEN", "candidate manifest is not frozen")
    _require(
        manifest.get("broker_mutation_enabled") is False,
        "candidate manifest must be research-only",
    )
    manifest_hash = sha256_file(manifest_file)

    _require(promotion.get("schema_version") == 1, "unsupported promotion schema")
    _require(promotion.get("candidate") == CANDIDATE_NAME, "promotion candidate mismatch")
    _require(promotion.get("approved") is True, "candidate is not approved")
    _require(promotion.get("account_mode") == "DEMO_ONLY", "promotion is not DEMO-only")
    _require(
        promotion.get("manifest_sha256") == manifest_hash,
        "promotion manifest hash mismatch",
    )
    try:
        volume = float(requested_volume)
        cap = float(promotion.get("approved_volume_cap"))
    except (TypeError, ValueError) as exc:
        raise V8PromotionError("invalid requested or approved volume") from exc
    _require(volume > 0, "requested volume must be positive")
    _require(cap in {0.01, 1.0}, "approved volume cap must be 0.01 or 1.0")
    _require(volume <= cap + 1e-12, "requested volume exceeds promotion cap")
    kind = str(promotion.get("promotion_kind") or "")
    expected_kind = "VOLUME_1_DEMO" if cap == 1.0 else "INITIAL_DEMO"
    _require(kind == expected_kind, "promotion kind does not match volume cap")

    manifest_hashes = manifest.get("artifact_hashes")
    promotion_hashes = promotion.get("artifact_hashes")
    _require(isinstance(manifest_hashes, dict) and manifest_hashes, "manifest artifact hashes missing")
    _require(promotion_hashes == manifest_hashes, "promotion artifact hash set mismatch")
    for relative_path, expected_hash in sorted(manifest_hashes.items()):
        artifact = _inside_root(root, relative_path)
        _require(artifact.is_file(), f"promoted artifact missing: {relative_path}")
        _require(
            sha256_file(artifact) == expected_hash,
            f"promoted artifact hash mismatch: {relative_path}",
        )

    required_stages = VOLUME_ONE_STAGES if cap == 1.0 else INITIAL_STAGES
    reports = promotion.get("evidence_reports")
    _require(isinstance(reports, dict), "promotion evidence reports missing")
    for stage in required_stages:
        reference = reports.get(stage)
        _require(isinstance(reference, dict), f"promotion evidence missing: {stage}")
        report_file = _inside_root(root, reference.get("path"))
        _require(report_file.is_file(), f"evidence report missing: {stage}")
        _require(
            sha256_file(report_file) == reference.get("sha256"),
            f"evidence report hash mismatch: {stage}",
        )
        report = _json_object(report_file)
        _validate_evidence_report(
            report,
            stage=stage,
            root=root,
            manifest_hash=manifest_hash,
        )

    return V8PromotionValidation(
        candidate=CANDIDATE_NAME,
        manifest_path=str(manifest_file),
        manifest_sha256=manifest_hash,
        promotion_path=str(promotion_file),
        promotion_sha256=sha256_file(promotion_file),
        approved_volume_cap=cap,
        promotion_kind=kind,
        evidence_stages=tuple(required_stages),
    )


def generate_v8_promotion_record(
    manifest_path: str | Path,
    evidence_report_paths: Iterable[str | Path],
    output_path: str | Path,
    *,
    approved_volume_cap: float,
    repo_root: str | Path,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Generate a record only from frozen, passing, hash-addressed evidence."""
    root = Path(repo_root).resolve()
    manifest_file = Path(manifest_path).resolve()
    manifest = _json_object(manifest_file)
    _require(manifest.get("candidate") == CANDIDATE_NAME, "candidate manifest mismatch")
    _require(manifest.get("status") == "FROZEN", "candidate manifest is not frozen")
    _require(manifest.get("broker_mutation_enabled") is False, "manifest enables broker mutation")
    try:
        cap = float(approved_volume_cap)
    except (TypeError, ValueError) as exc:
        raise V8PromotionError("approved volume cap must be numeric") from exc
    _require(cap in {0.01, 1.0}, "approved volume cap must be 0.01 or 1.0")
    required = VOLUME_ONE_STAGES if cap == 1.0 else INITIAL_STAGES
    reports: dict[str, dict[str, str]] = {}
    for value in evidence_report_paths:
        report_file = Path(value).resolve()
        report = _json_object(report_file)
        stage = str(report.get("stage") or "")
        _require(stage in required, f"unexpected evidence stage: {stage}")
        _require(stage not in reports, f"duplicate evidence stage: {stage}")
        _validate_evidence_report(
            report,
            stage=stage,
            root=root,
            manifest_hash=sha256_file(manifest_file),
        )
        reports[stage] = {
            "path": _relative_inside(root, report_file),
            "sha256": sha256_file(report_file),
        }
    missing = tuple(stage for stage in required if stage not in reports)
    _require(not missing, "missing passing evidence stages: " + ", ".join(missing))
    artifact_hashes = manifest.get("artifact_hashes")
    _require(isinstance(artifact_hashes, dict) and artifact_hashes, "manifest artifact hashes missing")
    for relative_path, expected_hash in artifact_hashes.items():
        artifact = _inside_root(root, relative_path)
        _require(artifact.is_file(), f"promoted artifact missing: {relative_path}")
        _require(sha256_file(artifact) == expected_hash, f"manifest artifact changed: {relative_path}")
    generated = generated_at_utc or datetime.now(timezone.utc).isoformat()
    record = {
        "schema_version": 1,
        "candidate": CANDIDATE_NAME,
        "approved": True,
        "account_mode": "DEMO_ONLY",
        "promotion_kind": "VOLUME_1_DEMO" if cap == 1.0 else "INITIAL_DEMO",
        "approved_volume_cap": cap,
        "generated_at_utc": generated,
        "manifest_sha256": sha256_file(manifest_file),
        "artifact_hashes": dict(sorted(artifact_hashes.items())),
        "evidence_reports": {stage: reports[stage] for stage in required},
    }
    _atomic_json(Path(output_path), record)
    return record


def _json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise V8PromotionError(f"cannot read JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise V8PromotionError(f"JSON artifact must be an object: {path}")
    return payload


def _inside_root(root: Path, relative_path: Any) -> Path:
    _require(isinstance(relative_path, str) and relative_path, "artifact path missing")
    candidate = (root / relative_path).resolve()
    _require(candidate == root or root in candidate.parents, "artifact path escapes repository")
    return candidate


def _relative_inside(root: Path, path: Path) -> str:
    _require(path == root or root in path.parents, "evidence path escapes repository")
    return path.relative_to(root).as_posix()


def _validate_evidence_report(
    report: dict[str, Any],
    *,
    stage: str,
    root: Path,
    manifest_hash: str,
) -> None:
    _require(report.get("schema_version") == 1, f"evidence schema mismatch: {stage}")
    _require(report.get("candidate") == CANDIDATE_NAME, f"evidence candidate mismatch: {stage}")
    _require(report.get("stage") == stage, f"evidence stage mismatch: {stage}")
    _require(report.get("status") == "PASS", f"evidence gate failed: {stage}")
    _require(report.get("retired") is False, f"candidate retired at stage: {stage}")
    if stage == "DEMO_0_01":
        _require(
            report.get("broker_mutation_enabled") is True,
            "DEMO evidence must identify order-capable broker mutation",
        )
        _require(report.get("account_mode") == "DEMO_ONLY", "DEMO evidence account mode mismatch")
        _require(report.get("real_account_mutations") == 0, "REAL account mutation detected")
        _require(
            report.get("complete_broker_reconciliation") is True,
            "DEMO evidence reconciliation is incomplete",
        )
        _require(
            report.get("compliant_live_entry_drift") is True,
            "DEMO evidence entry drift is noncompliant",
        )
    else:
        _require(
            report.get("broker_mutation_enabled") is False,
            f"evidence report enables broker mutation: {stage}",
        )
    _require(
        report.get("manifest_sha256") == manifest_hash,
        f"evidence manifest hash mismatch: {stage}",
    )
    sources = report.get("sources")
    if stage in (*INITIAL_STAGES, "DEMO_0_01"):
        _require(isinstance(sources, list) and sources, f"evidence sources missing: {stage}")
    windows = tuple(
        (
            str(source.get("evidence_start")),
            str(source.get("evidence_end")),
        )
        for source in (sources or [])
    )
    if stage == "DISCOVERY":
        expected = (
            ("2026-06-22T00:00:00+00:00", "2026-06-29T00:00:00+00:00"),
            ("2026-06-29T00:00:00+00:00", "2026-07-06T00:00:00+00:00"),
            ("2026-07-06T00:00:00+00:00", "2026-07-13T00:00:00+00:00"),
        )
        _require(windows == expected, "discovery evidence windows mismatch")
    elif stage == "HELD_OUT":
        _require(
            windows
            == (("2026-07-13T00:00:00+00:00", "2026-07-20T00:00:00+00:00"),),
            "held-out evidence window mismatch",
        )
    elif stage == "PROSPECTIVE":
        registration = report.get("prospective_registration")
        _require(isinstance(registration, dict), "prospective registration missing")
        registration_file = _path_inside(root, registration.get("path"))
        _require(registration_file.is_file(), "prospective registration artifact missing")
        _require(
            sha256_file(registration_file) == registration.get("sha256"),
            "prospective registration hash mismatch",
        )
        registration_payload = _json_object(registration_file)
        _require(
            registration_payload.get("candidate") == CANDIDATE_NAME
            and registration_payload.get("status") == "REGISTERED"
            and registration_payload.get("broker_mutation_enabled") is False,
            "prospective registration is invalid",
        )
        _require(
            registration_payload.get("manifest_sha256") == manifest_hash,
            "prospective registration manifest hash mismatch",
        )
        registered_at = datetime.fromisoformat(
            str(registration_payload.get("registered_at_utc")).replace("Z", "+00:00")
        )
        first_start = datetime.fromisoformat(windows[0][0].replace("Z", "+00:00"))
        _require(first_start >= registered_at, "prospective evidence predates registration")


def _path_inside(root: Path, value: Any) -> Path:
    _require(isinstance(value, str) and value, "artifact path missing")
    raw = Path(value)
    candidate = raw.resolve() if raw.is_absolute() else (root / raw).resolve()
    _require(candidate == root or root in candidate.parents, "artifact path escapes repository")
    return candidate


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V8PromotionError(message)


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
    "INITIAL_STAGES",
    "V8PromotionError",
    "V8PromotionValidation",
    "VOLUME_ONE_STAGES",
    "generate_v8_promotion_record",
    "sha256_file",
    "validate_v8_promotion",
]
