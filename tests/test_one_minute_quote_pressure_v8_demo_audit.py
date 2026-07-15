import json
from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import CANDIDATE_NAME
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_demo_audit import (
    audit_v8_demo_sessions,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_promotion import (
    sha256_file,
)


START = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def _write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _manifest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    artifact = tmp_path / "candidate.py"
    artifact.write_text("V8 = True\n", encoding="utf-8")
    manifest = tmp_path / "docs" / "manifest.json"
    _write_json(
        manifest,
        {
            "schema_version": 1,
            "candidate": CANDIDATE_NAME,
            "status": "FROZEN",
            "broker_mutation_enabled": False,
            "artifact_hashes": {"candidate.py": sha256_file(artifact)},
        },
    )
    return manifest


def _session(tmp_path, manifest, index, *, drift_failure=False):
    session = tmp_path / "results" / f"demo-{index}"
    runner = session / "mt5_one_minute_v8"
    manifest_hash = sha256_file(manifest)
    rows = []
    submissions = {}
    trades = []
    events = []
    for trade_index in range(6):
        number = index * 100 + trade_index
        opened = START + timedelta(days=index, minutes=trade_index)
        closed = opened + timedelta(seconds=30)
        arm_id = f"arm-{number}"
        rows.append(
            {
                "arm_id": arm_id,
                "session_id": session.name,
                "family": "LOW_RESPECT_BUY",
                "direction": "BUY",
                "armed_at": opened.isoformat(),
                "triggered_at": opened.isoformat(),
                "placed_at": opened.isoformat(),
                "filled_at": opened.isoformat(),
                "closed_at": closed.isoformat(),
                "outcome": "WIN",
                "reason": "TA target",
                "profit_r": 0.1,
            }
        )
        submissions[str(number)] = {
            "filled_at": opened.isoformat(),
            "entry_drift_compliant": not drift_failure,
        }
        trades.append(
            {
                "entry_order": number,
                "closed_at_utc": closed.isoformat(),
                "profit": 1.0,
            }
        )
        events.append({"event": "ARMED", "arm_id": arm_id, "time_utc": opened.isoformat()})
    _write_json(
        runner / "state.json",
        {
            "schema_version": 1,
            "candidate": CANDIDATE_NAME,
            "phase": "COMPLETE",
            "started_at_utc": (START + timedelta(days=index)).isoformat(),
            "completed_at_utc": (START + timedelta(days=index, hours=1)).isoformat(),
            "volume": 0.01,
            "manifest_sha256": manifest_hash,
            "last_history": {
                "status": "RECONCILED",
                "closed_trade_count": 6,
                "closed_trades": trades,
            },
            "submissions": submissions,
            "evidence_rows": rows,
            "safety_failures": 0,
            "telemetry_failures": 0,
            "reconciliation_failures": 0,
            "entry_drift_failures": int(drift_failure),
            "lifecycle_failures": 0,
            "restart_failures": 0,
        },
    )
    _write_json(
        runner / "promotion_receipt.json",
        {
            "manifest_sha256": manifest_hash,
            "approved_volume_cap": 0.01,
            "account_safety": {"passed": True, "trade_mode": "DEMO"},
            "zero_initial_orders": True,
            "zero_initial_positions": True,
        },
    )
    (runner / "events.jsonl").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    return session


def test_demo_audit_passes_only_complete_reconciled_0_01_sessions(tmp_path):
    manifest = _manifest(tmp_path)
    sessions = [_session(tmp_path, manifest, index) for index in range(5)]

    report = audit_v8_demo_sessions(sessions, manifest_path=manifest)

    assert report["status"] == "PASS"
    assert report["metrics"]["fills"] == 30
    assert report["metrics"]["sessions"] == 5
    assert report["broker_mutation_enabled"] is True
    assert report["account_mode"] == "DEMO_ONLY"
    assert report["real_account_mutations"] == 0
    assert report["complete_broker_reconciliation"] is True
    assert report["compliant_live_entry_drift"] is True


def test_demo_audit_fails_noncompliant_live_entry_drift(tmp_path):
    manifest = _manifest(tmp_path)
    sessions = [
        _session(tmp_path, manifest, index, drift_failure=index == 0)
        for index in range(5)
    ]

    report = audit_v8_demo_sessions(sessions, manifest_path=manifest)

    assert report["status"] == "FAIL"
    assert report["retired"] is True
    assert report["compliant_live_entry_drift"] is False
    assert "live_entry_drift_noncompliant" in report["reasons"]
