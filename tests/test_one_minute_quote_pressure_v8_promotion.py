import json

import pytest

from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import (
    CANDIDATE_NAME,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_promotion import (
    V8PromotionError,
    generate_v8_promotion_record,
    sha256_file,
    validate_v8_promotion,
)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _frozen_tree(tmp_path):
    code = tmp_path / "tradingagents" / "candidate.py"
    code.parent.mkdir(parents=True)
    code.write_text("CANDIDATE = 'V8'\n", encoding="utf-8")
    manifest = tmp_path / "docs" / "v8-manifest.json"
    _write_json(
        manifest,
        {
            "schema_version": 1,
            "candidate": CANDIDATE_NAME,
            "status": "FROZEN",
            "broker_mutation_enabled": False,
            "artifact_hashes": {
                "tradingagents/candidate.py": sha256_file(code),
            },
        },
    )
    manifest_hash = sha256_file(manifest)
    windows = {
        "DISCOVERY": [
            ("2026-06-22T00:00:00+00:00", "2026-06-29T00:00:00+00:00"),
            ("2026-06-29T00:00:00+00:00", "2026-07-06T00:00:00+00:00"),
            ("2026-07-06T00:00:00+00:00", "2026-07-13T00:00:00+00:00"),
        ],
        "HELD_OUT": [
            ("2026-07-13T00:00:00+00:00", "2026-07-20T00:00:00+00:00")
        ],
        "PROSPECTIVE": [
            ("2026-07-20T01:00:00+00:00", "2026-07-21T01:00:00+00:00")
        ],
    }
    reports = []
    for stage in ("DISCOVERY", "HELD_OUT"):
        report = tmp_path / "reports" / f"{stage.lower()}.json"
        _write_json(
            report,
            {
                "schema_version": 1,
                "candidate": CANDIDATE_NAME,
                "stage": stage,
                "status": "PASS",
                "retired": False,
                "broker_mutation_enabled": False,
                "manifest_sha256": manifest_hash,
                "sources": [
                    {"evidence_start": start, "evidence_end": end}
                    for start, end in windows[stage]
                ],
                "metrics": {},
            },
        )
        reports.append(report)
    registration = tmp_path / "reports" / "prospective-registration.json"
    _write_json(
        registration,
        {
            "schema_version": 1,
            "candidate": CANDIDATE_NAME,
            "status": "REGISTERED",
            "broker_mutation_enabled": False,
            "registered_at_utc": "2026-07-20T01:00:00+00:00",
            "manifest_sha256": manifest_hash,
            "held_out_report_path": str(reports[1]),
            "held_out_report_sha256": sha256_file(reports[1]),
        },
    )
    prospective = tmp_path / "reports" / "prospective.json"
    _write_json(
        prospective,
        {
            "schema_version": 1,
            "candidate": CANDIDATE_NAME,
            "stage": "PROSPECTIVE",
            "status": "PASS",
            "retired": False,
            "broker_mutation_enabled": False,
            "manifest_sha256": manifest_hash,
            "sources": [
                {"evidence_start": start, "evidence_end": end}
                for start, end in windows["PROSPECTIVE"]
            ],
            "prospective_registration": {
                "path": str(registration),
                "sha256": sha256_file(registration),
            },
            "metrics": {},
        },
    )
    reports.append(prospective)
    demo = tmp_path / "reports" / "demo_0_01.json"
    _write_json(
        demo,
        {
            "schema_version": 1,
            "candidate": CANDIDATE_NAME,
            "stage": "DEMO_0_01",
            "status": "PASS",
            "retired": False,
            "broker_mutation_enabled": True,
            "account_mode": "DEMO_ONLY",
            "real_account_mutations": 0,
            "complete_broker_reconciliation": True,
            "compliant_live_entry_drift": True,
            "manifest_sha256": manifest_hash,
            "sources": [{"session": "demo-session-1"}],
            "metrics": {},
        },
    )
    reports.append(demo)
    return code, manifest, reports


def test_initial_promotion_is_hash_locked_demo_only_and_volume_capped(tmp_path):
    _, manifest, reports = _frozen_tree(tmp_path)
    promotion = tmp_path / "promotion.json"
    generate_v8_promotion_record(
        manifest,
        reports[:3],
        promotion,
        approved_volume_cap=0.01,
        repo_root=tmp_path,
        generated_at_utc="2026-07-20T00:00:00+00:00",
    )

    validation = validate_v8_promotion(
        manifest,
        promotion,
        requested_volume=0.01,
        repo_root=tmp_path,
    )

    assert validation.promotion_kind == "INITIAL_DEMO"
    assert validation.approved_volume_cap == 0.01
    assert validation.evidence_stages == ("DISCOVERY", "HELD_OUT", "PROSPECTIVE")
    with pytest.raises(V8PromotionError, match="exceeds promotion cap"):
        validate_v8_promotion(
            manifest,
            promotion,
            requested_volume=1.0,
            repo_root=tmp_path,
        )


def test_volume_one_requires_passing_demo_evidence(tmp_path):
    _, manifest, reports = _frozen_tree(tmp_path)
    promotion = tmp_path / "promotion-volume-one.json"

    with pytest.raises(V8PromotionError, match="missing passing evidence stages"):
        generate_v8_promotion_record(
            manifest,
            reports[:3],
            promotion,
            approved_volume_cap=1.0,
            repo_root=tmp_path,
        )

    generate_v8_promotion_record(
        manifest,
        reports,
        promotion,
        approved_volume_cap=1.0,
        repo_root=tmp_path,
    )
    assert validate_v8_promotion(
        manifest,
        promotion,
        requested_volume=1.0,
        repo_root=tmp_path,
    ).promotion_kind == "VOLUME_1_DEMO"


def test_failed_or_retired_gate_cannot_generate_promotion(tmp_path):
    _, manifest, reports = _frozen_tree(tmp_path)
    payload = json.loads(reports[1].read_text(encoding="utf-8"))
    payload.update({"status": "FAIL", "retired": True})
    _write_json(reports[1], payload)

    with pytest.raises(V8PromotionError, match="evidence gate failed"):
        generate_v8_promotion_record(
            manifest,
            reports[:3],
            tmp_path / "promotion.json",
            approved_volume_cap=0.01,
            repo_root=tmp_path,
        )


def test_manifest_code_and_evidence_tampering_block_startup(tmp_path):
    code, manifest, reports = _frozen_tree(tmp_path)
    promotion = tmp_path / "promotion.json"
    generate_v8_promotion_record(
        manifest,
        reports[:3],
        promotion,
        approved_volume_cap=0.01,
        repo_root=tmp_path,
    )

    code.write_text("CANDIDATE = 'changed'\n", encoding="utf-8")
    with pytest.raises(V8PromotionError, match="artifact hash mismatch"):
        validate_v8_promotion(
            manifest,
            promotion,
            requested_volume=0.01,
            repo_root=tmp_path,
        )

    code.write_text("CANDIDATE = 'V8'\n", encoding="utf-8")
    reports[0].write_text(reports[0].read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(V8PromotionError, match="evidence report hash mismatch"):
        validate_v8_promotion(
            manifest,
            promotion,
            requested_volume=0.01,
            repo_root=tmp_path,
        )


def test_paths_outside_repository_are_rejected(tmp_path):
    _, manifest, reports = _frozen_tree(tmp_path)
    promotion = tmp_path / "promotion.json"
    generate_v8_promotion_record(
        manifest,
        reports[:3],
        promotion,
        approved_volume_cap=0.01,
        repo_root=tmp_path,
    )
    payload = json.loads(promotion.read_text(encoding="utf-8"))
    payload["evidence_reports"]["DISCOVERY"]["path"] = "../outside.json"
    # Keep the manifest link valid so the path guard is the first rejection.
    _write_json(promotion, payload)

    with pytest.raises(V8PromotionError, match="escapes repository"):
        validate_v8_promotion(
            manifest,
            promotion,
            requested_volume=0.01,
            repo_root=tmp_path,
        )
