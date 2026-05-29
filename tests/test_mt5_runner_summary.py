import json

from tradingagents.brokers.runner_summary import (
    RunnerSummaryStore,
    categorize_hold_reason,
)


def test_categorize_hold_reason_prefers_structured_stage():
    telemetry = {
        "decision_stage": "higher_timeframe_permission",
        "primary_hold_reason": "H4 blocks BUY",
    }

    assert categorize_hold_reason("The text can be noisy.", telemetry) == "higher_timeframe"


def test_categorize_hold_reason_falls_back_to_text():
    assert categorize_hold_reason("Time filter failed. Default to HOLD.", {}) == "time_filter"
    assert categorize_hold_reason("No valid M15 setup. Default to HOLD.", {}) == "no_m15_setup"
    assert categorize_hold_reason("Insufficient closed OHLCV data.", {}) == "data_health"


def test_runner_summary_records_cycle_and_writes_files(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    result = {
        "status": "NO_TRADE",
        "as_of": "2026-05-29 08:15",
        "proposal": {
            "status": "NO_TRADE",
            "reason": "Time filter failed. Default to HOLD.",
        },
        "analysis": {
            "telemetry": {
                "decision_stage": "time_filter",
                "primary_hold_reason": "Time filter failed. Default to HOLD.",
            },
            "data_status": {
                "healthy": True,
                "timeframes": {
                    "15m": {"available": True, "fresh": True, "rows": 745},
                    "30m": {"available": True, "fresh": True, "rows": 373},
                },
            },
        },
    }

    summary = store.record_cycle(result)

    assert summary["total_checks"] == 1
    assert summary["status_counts"]["NO_TRADE"] == 1
    assert summary["hold_reason_counts"]["time_filter"] == 1
    assert summary["data_health"]["healthy_checks"] == 1
    assert summary["data_health"]["unhealthy_checks"] == 0
    assert store.summary_path.exists()
    assert store.cycles_path.exists()

    written = json.loads(store.summary_path.read_text(encoding="utf-8"))
    assert written["total_checks"] == 1
