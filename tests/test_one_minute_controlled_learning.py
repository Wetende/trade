import json
from datetime import datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.controlled_learning import (
    build_controlled_learning_ledger,
    validate_evaluation_source_isolation,
)


def _write_session(root: Path, *, order: int, profit: float, minute: int) -> None:
    runner = root / "mt5_runner"
    runner.mkdir(parents=True)
    placed = f"2026-07-15T17:{minute:02d}:00+00:00"
    closed = f"2026-07-15T17:{minute:02d}:30+00:00"
    cycle = {
        "status": "ORDER_PLACED",
        "heartbeat_utc": placed,
        "execution": {
            "order": order,
            "execution_timeline": {"submitted_at_utc": placed},
        },
        "proposal": {
            "trigger_name": "CLEAN_HIGH_IMPULSE_BUY",
            "side": "BUY",
            "reaction_type": "impulse_break",
            "touch_count": 3,
            "decision_quote": {"spread_price": 0.3},
        },
        "analysis": {
            "telemetry": {
                "selected_candidate": {
                    "approved": True,
                    "trigger": "CLEAN_HIGH_IMPULSE_BUY",
                    "direction": "BUY",
                    "reaction_type": "impulse_break",
                    "confirmation_type": "strong_close",
                    "score": 11.0,
                    "level_type": "three_touch",
                    "touch_count": 3,
                    "pressure": {"direction": "bullish"},
                    "active_pulse": {"direction": "bullish"},
                    "signal_quality": {
                        "body_to_recent_median_range": 0.75,
                        "touch_age_closed_bars": 1,
                        "entry_distance_from_level": 0.4,
                        "opposing_wick_to_range": 0.1,
                        "stop_to_spread_ratio": 2.5,
                    },
                }
            }
        },
    }
    (runner / "cycles.jsonl").write_text(
        json.dumps(cycle) + "\n", encoding="utf-8"
    )
    summary = {
        "trade_history": {
            "closed_trades": [
                {
                    "entry_order": order,
                    "opened_at_utc": placed,
                    "closed_at_utc": closed,
                    "profit": profit,
                    "mfe_points": 0.0 if profit < 0 else 0.8,
                    "mae_points": -0.8 if profit < 0 else -0.1,
                }
            ]
        }
    }
    (runner / "summary.json").write_text(
        json.dumps(summary), encoding="utf-8"
    )


def _write_retired_report(path: Path, *, demo_start_allowed: bool = False) -> None:
    payload = {
        "candidate": "ONE_MINUTE_QUOTE_PRESSURE_V8",
        "candidate_status": "RETIRED_READ_ONLY",
        "order_capability": False,
        "promotion_record_generated": False,
        "manifest": {
            "sha256": "a" * 64,
            "frozen_at_utc": "2026-07-15T19:10:20+00:00",
        },
        "discovery": {
            "report_sha256": "b" * 64,
            "source_candles": 20571,
            "source_quotes": 12708961,
            "arms_detected": 10936,
            "valid_triggers": 0,
            "placements": 0,
            "fills": 0,
            "top_skip_rejection_counts": {
                "ARM_EXPIRED": 5865,
                "PRESSURE_STOP_DISTANCE_ABOVE_MAXIMUM": 2393,
            },
        },
        "broker_final_proof": {
            "checked_at_utc": "2026-07-15T19:16:26+00:00"
        },
        "policy_result": {
            "held_out_must_remain_unopened": True,
            "demo_start_allowed": demo_start_allowed,
            "tuning_on_failed_window_allowed": False,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _sources(tmp_path: Path) -> tuple[list[Path], Path]:
    first = tmp_path / "session-a"
    second = tmp_path / "session-b"
    _write_session(first, order=101, profit=-80.0, minute=1)
    _write_session(second, order=102, profit=40.0, minute=2)
    retired = tmp_path / "retired.json"
    _write_retired_report(retired)
    return [first, second], retired


def test_controlled_learning_is_deterministic_and_cannot_promote(tmp_path):
    sessions, retired = _sources(tmp_path)

    first = build_controlled_learning_ledger(sessions, [retired], min_samples=1)
    second = build_controlled_learning_ledger(
        reversed(sessions), [retired], min_samples=1
    )

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["broker_mutation_enabled"] is False
    assert first["live_rule_mutation_enabled"] is False
    assert first["automatic_promotion_enabled"] is False
    assert first["operational_permissions"]["place_or_modify_orders"] is False
    assert first["operational_permissions"]["authorize_demo_start"] is False
    assert first["diagnostics"]["summary"]["fills"] == 2
    assert first["verified_patterns"][0]["zero_mfe_share_of_all_losses"] == 1.0
    assert (
        first["verified_patterns"][0]["zero_mfe_share_of_losses_with_mfe"]
        == 1.0
    )
    assert first["verified_patterns"][-1]["valid_triggers"] == 0
    candidate_keys = {
        item["key"]
        for item in first["diagnostics"]["candidate_rule_hypotheses"]
    }
    assert "FILTER_FEATURE:ZERO_MFE_REVERSAL" not in candidate_keys


def test_controlled_learning_preserves_completed_no_decision_session(tmp_path):
    sessions, retired = _sources(tmp_path)
    empty = tmp_path / "session-empty"
    runner = empty / "mt5_runner"
    runner.mkdir(parents=True)
    (runner / "cycles.jsonl").write_text("", encoding="utf-8")
    (runner / "summary.json").write_text(
        json.dumps(
            {
                "started_at_utc": "2026-07-15T18:00:00+00:00",
                "updated_at_utc": "2026-07-15T18:30:00+00:00",
                "trade_history": {"closed_trades": []},
            }
        ),
        encoding="utf-8",
    )

    ledger = build_controlled_learning_ledger(
        [*sessions, empty],
        [retired],
        min_samples=1,
    )

    source = next(
        item
        for item in ledger["source_registry"]["sessions"]
        if item["session_id"] == "session-empty"
    )
    assert source["filled_trades"] == 0
    assert source["observed_through_utc"] == "2026-07-15T18:30:00Z"


def test_controlled_learning_owns_repeated_close_by_placing_session(tmp_path):
    sessions, retired = _sources(tmp_path)
    first_summary_path = sessions[0] / "mt5_runner" / "summary.json"
    second_summary_path = sessions[1] / "mt5_runner" / "summary.json"
    first_trade = json.loads(first_summary_path.read_text(encoding="utf-8"))[
        "trade_history"
    ]["closed_trades"][0]
    repeated = dict(first_trade)
    repeated["opened_at_utc"] = "2026-07-15T18:01:00+00:00"
    repeated["closed_at_utc"] = "2026-07-15T18:01:30+00:00"
    second_summary = json.loads(second_summary_path.read_text(encoding="utf-8"))
    second_summary["trade_history"]["closed_trades"].append(repeated)
    second_summary_path.write_text(json.dumps(second_summary), encoding="utf-8")

    ledger = build_controlled_learning_ledger(sessions, [retired], min_samples=1)

    assert ledger["diagnostics"]["summary"]["fills"] == 2
    sources = ledger["source_registry"]["sessions"]
    assert [source["filled_trades"] for source in sources] == [1, 1]
    assert all(source["unmatched_closed_trade_count"] == 0 for source in sources)


def test_controlled_learning_rejects_trade_without_owning_placement(tmp_path):
    sessions, retired = _sources(tmp_path)
    summary_path = sessions[1] / "mt5_runner" / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    foreign = dict(summary["trade_history"]["closed_trades"][0])
    foreign["entry_order"] = 999999
    summary["trade_history"]["closed_trades"].append(foreign)
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(ValueError, match="without an owning placement"):
        build_controlled_learning_ledger(sessions, [retired], min_samples=1)


def test_evaluation_isolation_rejects_reused_or_old_sources(tmp_path):
    sessions, retired = _sources(tmp_path)
    ledger = build_controlled_learning_ledger(sessions, [retired], min_samples=1)
    forbidden = ledger["source_registry"]["hypothesis_source_hashes"][0]

    rejected = validate_evaluation_source_isolation(
        ledger,
        evaluation_source_hashes=[forbidden],
        evaluation_start_utc="2026-07-15T19:00:00+00:00",
    )
    passed = validate_evaluation_source_isolation(
        ledger,
        evaluation_source_hashes=["c" * 64],
        evaluation_start_utc="2026-07-15T20:00:00+00:00",
    )

    assert rejected["passed"] is False
    assert rejected["reasons"] == [
        "HYPOTHESIS_SOURCE_HASH_REUSED_FOR_EVALUATION",
        "EVALUATION_WINDOW_NOT_CHRONOLOGICALLY_NEW",
    ]
    assert passed["passed"] is True


def test_learning_cli_uses_explicit_m1_source_manifest(tmp_path):
    sessions, retired = _sources(tmp_path)
    manifest = tmp_path / "sources.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "strategy_scope": "one_minute_scalper",
                "min_samples": 1,
                "sessions": [str(path) for path in sessions],
                "retired_candidate_reports": [str(retired)],
            }
        ),
        encoding="utf-8",
    )
    output = tmp_path / "ledger.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-learn",
            "--source-manifest",
            str(manifest),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["learning_mode"] == "OFFLINE_HYPOTHESIS_GENERATION_ONLY"
    assert payload["source_registry"]["manifest"]["sha256"]


def test_learning_rejects_retired_report_that_authorizes_demo(tmp_path):
    sessions, retired = _sources(tmp_path)
    _write_retired_report(retired, demo_start_allowed=True)

    with pytest.raises(ValueError, match="cannot authorize DEMO start"):
        build_controlled_learning_ledger(sessions, [retired], min_samples=1)
