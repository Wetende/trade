import json
from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.agents.price_action.one_minute_experimental_demo import (
    ARTIFACT_PATHS,
    BLOCKED_STRATEGY_RULES,
    ExperimentalDemoAuthorizationError,
    generate_experimental_demo_record,
    validate_experimental_demo_record,
)


def _artifact_tree(tmp_path):
    for relative in ARTIFACT_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"artifact={relative}\n", encoding="utf-8")


def _runtime():
    return {
        "require_demo_account": True,
        "allow_real_orders": False,
        "max_session_loss": 20.0,
        "volume_boost_enabled": False,
        "blocked_strategy_rules": BLOCKED_STRATEGY_RULES,
        "minimum_candidate_score": 8.0,
        "minimum_stop_spread_multiple": 2.2,
    }


def test_experimental_record_is_hash_locked_demo_only_and_not_promotable(tmp_path):
    _artifact_tree(tmp_path)
    record = tmp_path / "authorization.json"
    generated = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)

    payload = generate_experimental_demo_record(
        record,
        repo_root=tmp_path,
        generated_at_utc=generated.isoformat(),
    )
    validation = validate_experimental_demo_record(
        record,
        repo_root=tmp_path,
        requested_volume=0.1,
        requested_session_hours=3.0,
        runtime_config=_runtime(),
        now_utc=generated + timedelta(hours=1),
    )

    assert payload["account_mode"] == "DEMO_ONLY"
    assert payload["promotion_eligible"] is False
    assert payload["evidence_role"] == "HYPOTHESIS_GENERATION_ONLY"
    assert validation.volume == 0.1
    assert validation.max_total_hours == 48.0
    assert validation.max_session_loss == 20.0


def test_experimental_record_rejects_wrong_volume_real_or_long_session(tmp_path):
    _artifact_tree(tmp_path)
    record = tmp_path / "authorization.json"
    generated = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    generate_experimental_demo_record(
        record,
        repo_root=tmp_path,
        generated_at_utc=generated.isoformat(),
    )

    with pytest.raises(
        ExperimentalDemoAuthorizationError,
        match="volume must be 0.1",
    ):
        validate_experimental_demo_record(
            record,
            repo_root=tmp_path,
            requested_volume=1.0,
            requested_session_hours=3.0,
            runtime_config=_runtime(),
            now_utc=generated,
        )
    with pytest.raises(
        ExperimentalDemoAuthorizationError,
        match="session must be at most 3 hours",
    ):
        validate_experimental_demo_record(
            record,
            repo_root=tmp_path,
            requested_volume=0.1,
            requested_session_hours=3.1,
            runtime_config=_runtime(),
            now_utc=generated,
        )
    real_runtime = _runtime()
    real_runtime["allow_real_orders"] = True
    with pytest.raises(
        ExperimentalDemoAuthorizationError,
        match="REAL orders must be disabled",
    ):
        validate_experimental_demo_record(
            record,
            repo_root=tmp_path,
            requested_volume=0.1,
            requested_session_hours=3.0,
            runtime_config=real_runtime,
            now_utc=generated,
        )


def test_experimental_record_rejects_expiry_and_artifact_tampering(tmp_path):
    _artifact_tree(tmp_path)
    record = tmp_path / "authorization.json"
    generated = datetime(2026, 7, 16, 8, 0, tzinfo=timezone.utc)
    generate_experimental_demo_record(
        record,
        repo_root=tmp_path,
        generated_at_utc=generated.isoformat(),
    )

    with pytest.raises(
        ExperimentalDemoAuthorizationError,
        match="authorization expired",
    ):
        validate_experimental_demo_record(
            record,
            repo_root=tmp_path,
            requested_volume=0.1,
            requested_session_hours=3.0,
            runtime_config=_runtime(),
            now_utc=generated + timedelta(hours=49),
        )

    payload = json.loads(record.read_text(encoding="utf-8"))
    artifact = tmp_path / next(iter(payload["artifact_hashes"]))
    artifact.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(
        ExperimentalDemoAuthorizationError,
        match="artifact hash mismatch",
    ):
        validate_experimental_demo_record(
            record,
            repo_root=tmp_path,
            requested_volume=0.1,
            requested_session_hours=3.0,
            runtime_config=_runtime(),
            now_utc=generated,
        )
