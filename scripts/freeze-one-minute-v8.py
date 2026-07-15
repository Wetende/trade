"""Create or verify the hash-locked One Minute Quote Pressure V8 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


CANDIDATE = "ONE_MINUTE_QUOTE_PRESSURE_V8"
ARTIFACTS = (
    "cli/main.py",
    "docs/superpowers/specs/2026-07-15-one-minute-quote-pressure-v8-design.md",
    "docs/one-minute-quote-pressure-v8-runbook.md",
    "scripts/freeze-one-minute-v8.py",
    "scripts/start-one-minute-demo.ps1",
    "tradingagents/agents/schemas.py",
    "tradingagents/agents/price_action/models.py",
    "tradingagents/agents/price_action/opening_state.py",
    "tradingagents/agents/price_action/one_minute_entry_model.py",
    "tradingagents/agents/price_action/one_minute_post_close_state.py",
    "tradingagents/agents/price_action/one_minute_post_close_replay.py",
    "tradingagents/agents/price_action/one_minute_quote_pressure_v8.py",
    "tradingagents/agents/price_action/one_minute_quote_pressure_v8_replay.py",
    "tradingagents/agents/price_action/one_minute_quote_pressure_v8_evidence.py",
    "tradingagents/agents/price_action/one_minute_quote_pressure_v8_demo_audit.py",
    "tradingagents/agents/price_action/one_minute_quote_pressure_v8_screening.py",
    "tradingagents/agents/price_action/one_minute_quote_pressure_v8_promotion.py",
    "tradingagents/brokers/mode_gate.py",
    "tradingagents/brokers/mt5.py",
    "tradingagents/brokers/mt5_execution.py",
    "tradingagents/brokers/mt5_one_minute_v8_risk.py",
    "tradingagents/brokers/mt5_one_minute_v8_runner.py",
    "tests/test_one_minute_quote_pressure_v8.py",
    "tests/test_one_minute_opening_state.py",
    "tests/test_one_minute_quote_pressure_v8_replay.py",
    "tests/test_one_minute_quote_pressure_v8_evidence.py",
    "tests/test_one_minute_quote_pressure_v8_demo_audit.py",
    "tests/test_one_minute_quote_pressure_v8_screening.py",
    "tests/test_one_minute_quote_pressure_v8_promotion.py",
    "tests/test_mt5_one_minute_v8_risk.py",
    "tests/test_mt5_one_minute_v8_runner.py",
    "tests/test_mt5_broker.py",
    "tests/test_mt5_execution.py",
    "tests/test_cli_mt5_execution.py",
    "tests/test_portability_artifacts.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path, frozen_at_utc: str) -> dict:
    missing = [relative for relative in ARTIFACTS if not (root / relative).is_file()]
    if missing:
        raise ValueError("missing V8 artifacts: " + ", ".join(missing))
    return {
        "schema_version": 1,
        "candidate": CANDIDATE,
        "status": "FROZEN",
        "broker_mutation_enabled": False,
        "frozen_at_utc": frozen_at_utc,
        "interpretation": {
            "signal": "BEST_QUOTE_PRESSURE_PROXY",
            "not_true_order_flow_imbalance": True,
            "depth_available": False,
            "reliable_traded_volume_available": False,
        },
        "strategy": {
            "families": [
                "HIGH_BREAK_BUY",
                "LOW_BREAK_SELL",
                "HIGH_RESPECT_SELL",
                "LOW_RESPECT_BUY",
                "FAILED_HIGH_BREAK_SELL",
                "FAILED_LOW_BREAK_BUY",
            ],
            "history_candles": 60,
            "closed_candle_can_enter": False,
            "pressure_change_count": 20,
            "pressure_window_seconds": 3.0,
            "minimum_nonzero_moves": 10,
            "minimum_directional_pressure": 0.60,
            "minimum_displacement_r": 0.10,
            "maximum_adverse_r": 0.15,
            "maximum_spread_multiple": 1.10,
            "maximum_live_entry_drift_spread_multiple": 1.0,
            "placement_delay_seconds": 5.0,
            "pending_expiry_seconds": 20,
            "minimum_stop_distance": 0.35,
            "minimum_stop_spread_multiple": 1.2,
            "maximum_stop_distance": 1.0,
            "risk_reward": 1.5,
            "tick_size": 0.01,
            "order_kind": "DIRECTION_SAFE_STOP",
            "one_active_lifecycle": True,
        },
        "modeled_round_trip_cost_r": 0.05,
        "max_session_r": 2.0,
        "two_loss_pause_minutes": 15,
        "shutdown_grace_seconds": 120,
        "flat_verification_count": 3,
        "volume_boost_enabled": False,
        "discovery_folds": [
            ["2026-06-22T00:00:00+00:00", "2026-06-29T00:00:00+00:00"],
            ["2026-06-29T00:00:00+00:00", "2026-07-06T00:00:00+00:00"],
            ["2026-07-06T00:00:00+00:00", "2026-07-13T00:00:00+00:00"],
        ],
        "held_out_window": [
            "2026-07-13T00:00:00+00:00",
            "2026-07-20T00:00:00+00:00",
        ],
        "gates": {
            "discovery": {
                "minimum_fills": 30,
                "minimum_sessions": 10,
                "minimum_profit_factor": 1.15,
                "minimum_expectancy_r": 0.05,
                "positive_net": True,
                "buy_and_sell_positive": True,
                "minimum_positive_mirrored_categories": 2,
                "minimum_profitable_session_rate": 0.50,
                "minimum_profitable_folds": 2,
                "maximum_loss_streak": 6,
                "maximum_portfolio_drawdown_r": 8.0,
                "maximum_session_drawdown_r": 3.0,
                "minimum_trigger_rate": 0.15,
                "minimum_valid_trigger_placement_fill_rate": 0.85,
                "maximum_crossed_rate": 0.15,
                "maximum_geometry_rejection_rate": 0.05,
            },
            "held_out": {
                "minimum_fills": 15,
                "minimum_sessions": 5,
                "minimum_profit_factor": 1.25,
                "minimum_expectancy_r": 0.10,
                "positive_net": True,
                "positive_without_best_session": True,
                "positive_with_extra_cost_r_per_fill": 0.05,
            },
            "prospective": {
                "minimum_fills": 60,
                "minimum_sessions": 10,
                "minimum_profit_factor": 1.20,
                "minimum_expectancy_r": 0.08,
                "positive_net": True,
                "minimum_profitable_session_rate": 0.60,
                "maximum_safety_failure_count": 0,
            },
            "demo_0_01_to_1_0": {
                "minimum_closed_trades": 30,
                "minimum_sessions": 5,
                "minimum_profit_factor": 1.10,
                "positive_net": True,
                "positive_expectancy": True,
                "maximum_drawdown_r": 3.0,
                "maximum_safety_failure_count": 0,
                "complete_reconciliation": True,
                "compliant_entry_drift": True,
            },
        },
        "failed_gate_action": "RETIRE_WITHOUT_TUNING_OR_PROMOTION",
        "artifact_hashes": {
            relative: sha256_file(root / relative) for relative in sorted(ARTIFACTS)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen-at-utc")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    if args.verify:
        current = json.loads(output.read_text(encoding="utf-8"))
        expected = build_manifest(root, str(current["frozen_at_utc"]))
        if current != expected:
            raise SystemExit("V8 manifest verification failed")
        print(json.dumps({"status": "VERIFIED", "manifest": str(output)}, indent=2))
        return 0
    frozen_at = args.frozen_at_utc or datetime.now(timezone.utc).isoformat()
    payload = build_manifest(root, frozen_at)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(json.dumps({"status": "FROZEN", "manifest": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
