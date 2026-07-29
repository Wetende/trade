"""Explicit, hash-locked authorization for an unpromoted M1 DEMO experiment."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping


CANDIDATE_NAME = "ONE_MINUTE_SCALPER"
EXPERIMENTAL_VOLUME = 0.1
MAX_TOTAL_HOURS = 48.0
MAX_SESSION_HOURS = 3.0
MAX_SESSION_LOSS = 20.0
BLOCKED_STRATEGY_RULES: tuple[str, ...] = ()
MIN_CANDIDATE_SCORE = 8.0
MIN_STOP_SPREAD_MULTIPLE = 1.2
ARTIFACT_PATHS = (
    ".gitattributes",
    "cli/main.py",
    "docs/analysis/2026-07-15-one-minute-learning-sources.json",
    "docs/superpowers/specs/2026-07-28-one-minute-scalper-design.md",
    "reports/2026-07-27-one-minute-quote-pressure-24h-feasibility.json",
    "reports/2026-07-28-one-minute-execution-funnel-repair.json",
    "reports/2026-07-28-one-minute-live-funnel-diagnostic/artifact.json",
    "scripts/start-one-minute-experimental-demo.ps1",
    "scripts/start-one-minute-experimental-supervisor.ps1",
    "scripts/one-minute-experimental-supervisor-worker.ps1",
    "tradingagents/default_config.py",
    "tradingagents/agents/price_action/one_minute_entry_model.py",
    "tradingagents/agents/price_action/one_minute_scalper.py",
    "tradingagents/agents/price_action/decision.py",
    "tradingagents/agents/price_action/evidence_export.py",
    "tradingagents/agents/price_action/one_minute_experimental_demo.py",
    "tradingagents/brokers/mt5.py",
    "tradingagents/brokers/mt5_execution.py",
    "tradingagents/brokers/execution_state.py",
    "tradingagents/brokers/mt5_runner.py",
    "tests/test_mt5_broker.py",
    "tests/test_mt5_execution.py",
    "tests/test_mt5_runner.py",
    "tests/test_one_minute_evidence_export.py",
    "tests/test_one_minute_experimental_demo.py",
    "tests/test_one_minute_scalper.py",
)


class ExperimentalDemoAuthorizationError(RuntimeError):
    """Raised when the bounded DEMO learning exception cannot be proven."""


@dataclass(frozen=True)
class ExperimentalDemoValidation:
    candidate: str
    record_path: str
    record_sha256: str
    volume: float
    max_total_hours: float
    max_session_hours: float
    max_session_loss: float
    expires_at_utc: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def generate_experimental_demo_record(
    output_path: str | Path,
    *,
    repo_root: str | Path,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Freeze the exact code and constraints for the user-authorized experiment."""
    root = Path(repo_root).resolve()
    output = Path(output_path)
    preserved_generated_at = None
    if generated_at_utc is None and output.is_file():
        try:
            existing = _json_object(output)
            if (
                existing.get("schema_version") == 1
                and existing.get("candidate") == CANDIDATE_NAME
            ):
                preserved_generated_at = _parse_utc(
                    str(existing.get("generated_at_utc") or "")
                )
        except ExperimentalDemoAuthorizationError:
            preserved_generated_at = None
    generated_at = _parse_utc(
        generated_at_utc
        or (
            preserved_generated_at.isoformat()
            if preserved_generated_at is not None
            else datetime.now(timezone.utc).isoformat()
        )
    )
    artifacts: dict[str, str] = {}
    for relative in ARTIFACT_PATHS:
        path = _inside_root(root, relative)
        _require(path.is_file(), f"experimental artifact missing: {relative}")
        artifacts[relative] = sha256_file(path)
    record = {
        "schema_version": 1,
        "candidate": CANDIDATE_NAME,
        "status": "EXPERIMENTAL_DEMO_ONLY",
        "authorization_type": "EXPLICIT_USER_DEMO_RESEARCH_OVERRIDE",
        "account_mode": "DEMO_ONLY",
        "user_authorized": True,
        "promotion_eligible": False,
        "evidence_role": "HYPOTHESIS_GENERATION_ONLY",
        "generated_at_utc": generated_at.isoformat(),
        "expires_at_utc": (generated_at + timedelta(hours=MAX_TOTAL_HOURS)).isoformat(),
        "volume": EXPERIMENTAL_VOLUME,
        "max_total_hours": MAX_TOTAL_HOURS,
        "max_session_hours": MAX_SESSION_HOURS,
        "max_session_loss_account_currency": MAX_SESSION_LOSS,
        "shutdown_grace_seconds": 120,
        "flat_verification_count": 2,
        "loss_streak_cooldown_count": 2,
        "loss_streak_cooldown_seconds": 900,
        "volume_boost_enabled": False,
        "admission_firewall": {
            "blocked_strategy_rules": list(BLOCKED_STRATEGY_RULES),
            "minimum_candidate_score": MIN_CANDIDATE_SCORE,
            "minimum_stop_to_spread_multiple": MIN_STOP_SPREAD_MULTIPLE,
            "basis": [
                "all six families require a directionally aligned second fully closed M1 candle that retests and holds the frozen story",
                "the second candle confirms the frozen story and is not required to create a redundant independent signal",
                "crossed, moved-away, invalidated, and unsafe geometry are rejected",
                "continuation stops that exceed one unit may become risk-capped structural pullback limits only outside the spread and within the moved-away allowance",
                "effective stop risk is at least 1.2 spreads and no wider than one price unit",
                "session-risk pricing reconnects and retries one transient MT5 failure without consuming the approved candle",
                "quote counts are not represented as order flow",
                "the firewall is experimental and is not promotion evidence",
            ],
        },
        "artifact_hashes": dict(sorted(artifacts.items())),
        "prohibited_actions": [
            "REAL_ACCOUNT_ORDER",
            "AUTOMATIC_PROMOTION",
            "VOLUME_BOOST",
            "MARTINGALE",
            "GRID",
            "STRADDLE",
            "M15_OR_M30_CHANGE",
        ],
    }
    _atomic_json(output, record)
    return record


def validate_experimental_demo_record(
    record_path: str | Path,
    *,
    repo_root: str | Path,
    requested_volume: float,
    requested_session_hours: float,
    runtime_config: Mapping[str, Any],
    now_utc: str | datetime | None = None,
) -> ExperimentalDemoValidation:
    """Validate code hashes and every runtime constraint before order capability."""
    root = Path(repo_root).resolve()
    path = Path(record_path).resolve()
    record = _json_object(path)
    _require(record.get("schema_version") == 1, "unsupported experimental schema")
    _require(record.get("candidate") == CANDIDATE_NAME, "experimental candidate mismatch")
    _require(
        record.get("status") == "EXPERIMENTAL_DEMO_ONLY",
        "experimental record is not active",
    )
    _require(record.get("account_mode") == "DEMO_ONLY", "record is not DEMO-only")
    _require(record.get("user_authorized") is True, "user authorization is missing")
    _require(record.get("promotion_eligible") is False, "experiment cannot be promotable")
    _require(
        record.get("evidence_role") == "HYPOTHESIS_GENERATION_ONLY",
        "experimental evidence role mismatch",
    )
    volume = _finite_float(requested_volume, "requested volume")
    session_hours = _finite_float(requested_session_hours, "requested session hours")
    _require(abs(volume - EXPERIMENTAL_VOLUME) <= 1e-12, "experimental volume must be 0.1")
    _require(
        abs(float(record.get("volume")) - EXPERIMENTAL_VOLUME) <= 1e-12,
        "record volume mismatch",
    )
    _require(0 < session_hours <= MAX_SESSION_HOURS, "session must be at most 3 hours")
    _require(
        float(record.get("max_total_hours")) == MAX_TOTAL_HOURS,
        "record total duration mismatch",
    )
    _require(
        float(record.get("max_session_hours")) == MAX_SESSION_HOURS,
        "record session duration mismatch",
    )
    now = _parse_utc(now_utc or datetime.now(timezone.utc))
    generated_at = _parse_utc(str(record.get("generated_at_utc") or ""))
    expires_at = _parse_utc(str(record.get("expires_at_utc") or ""))
    _require(now >= generated_at, "experimental authorization is not active")
    authorization_hours = (
        expires_at - generated_at
    ).total_seconds() / 3600.0
    _require(
        abs(authorization_hours - MAX_TOTAL_HOURS) <= 1e-9,
        "experimental authorization duration mismatch",
    )
    _require(now < expires_at, "experimental authorization expired")

    expected_hashes = record.get("artifact_hashes")
    _require(isinstance(expected_hashes, dict), "experimental artifact hashes missing")
    _require(set(expected_hashes) == set(ARTIFACT_PATHS), "experimental artifact set mismatch")
    for relative, expected_hash in sorted(expected_hashes.items()):
        artifact = _inside_root(root, relative)
        _require(artifact.is_file(), f"experimental artifact missing: {relative}")
        _require(
            sha256_file(artifact) == expected_hash,
            f"experimental artifact hash mismatch: {relative}",
        )

    _require(runtime_config.get("require_demo_account") is True, "runtime must require DEMO")
    _require(runtime_config.get("allow_real_orders") is False, "REAL orders must be disabled")
    _require(
        str(runtime_config.get("signal_model") or "").strip().upper()
        == CANDIDATE_NAME,
        "runtime signal model mismatch",
    )
    _require(
        abs(
            _finite_float(
                runtime_config.get("max_session_loss"),
                "runtime max session loss",
            )
            - MAX_SESSION_LOSS
        )
        <= 1e-12,
        "runtime max session loss mismatch",
    )
    _require(runtime_config.get("volume_boost_enabled") is False, "volume boost must be off")
    _require(
        tuple(runtime_config.get("blocked_strategy_rules") or ())
        == BLOCKED_STRATEGY_RULES,
        "runtime blocked strategy rules mismatch",
    )
    _require(
        abs(
            _finite_float(
                runtime_config.get("minimum_candidate_score"),
                "runtime minimum candidate score",
            )
            - MIN_CANDIDATE_SCORE
        )
        <= 1e-12,
        "runtime minimum candidate score mismatch",
    )
    _require(
        abs(
            _finite_float(
                runtime_config.get("minimum_stop_spread_multiple"),
                "runtime minimum stop-spread multiple",
            )
            - MIN_STOP_SPREAD_MULTIPLE
        )
        <= 1e-12,
        "runtime minimum stop-spread multiple mismatch",
    )
    _require(
        abs(_finite_float(runtime_config.get("reaction_pending_seconds"), "reaction expiry") - 20.0)
        <= 1e-12,
        "runtime reaction expiry mismatch",
    )
    _require(
        abs(_finite_float(runtime_config.get("impulse_pending_seconds"), "impulse expiry") - 20.0)
        <= 1e-12,
        "runtime impulse expiry mismatch",
    )
    _require(
        int(runtime_config.get("loss_streak_cooldown_count") or 0) == 2,
        "runtime loss-streak count mismatch",
    )
    _require(
        int(runtime_config.get("loss_streak_cooldown_seconds") or 0) == 900,
        "runtime loss-streak cooldown mismatch",
    )
    return ExperimentalDemoValidation(
        candidate=CANDIDATE_NAME,
        record_path=str(path),
        record_sha256=sha256_file(path),
        volume=volume,
        max_total_hours=MAX_TOTAL_HOURS,
        max_session_hours=MAX_SESSION_HOURS,
        max_session_loss=MAX_SESSION_LOSS,
        expires_at_utc=expires_at.isoformat(),
    )


def _finite_float(value: Any, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ExperimentalDemoAuthorizationError(f"{label} must be numeric") from exc
    _require(math.isfinite(parsed), f"{label} must be finite")
    return parsed


def _parse_utc(value: str | datetime) -> datetime:
    try:
        parsed = (
            value
            if isinstance(value, datetime)
            else datetime.fromisoformat(value.replace("Z", "+00:00"))
        )
    except (TypeError, ValueError) as exc:
        raise ExperimentalDemoAuthorizationError("invalid experimental timestamp") from exc
    _require(parsed.tzinfo is not None, "experimental timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _inside_root(root: Path, value: str | Path) -> Path:
    candidate = Path(value)
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ExperimentalDemoAuthorizationError("experimental artifact escapes repository") from exc
    return resolved


def _json_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExperimentalDemoAuthorizationError(
            "experimental authorization record is unreadable"
        ) from exc
    _require(isinstance(payload, dict), "experimental record must be a JSON object")
    return payload


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ExperimentalDemoAuthorizationError(message)
