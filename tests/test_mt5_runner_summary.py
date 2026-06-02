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


def test_categorize_hold_reason_uses_data_health_before_text():
    assert (
        categorize_hold_reason(
            "No valid M15 setup. Default to HOLD.",
            {"decision_stage": "no_m15_setup"},
            {"healthy": False},
        )
        == "data_health"
    )


def test_categorize_hold_reason_uses_stage_before_misleading_text():
    telemetry = {
        "decision_stage": "no_m15_setup",
        "primary_hold_reason": "No valid M15 setup. Default to HOLD.",
    }

    assert (
        categorize_hold_reason(
            "No price data was provided by the analyst report.",
            telemetry,
            {"healthy": True},
        )
        == "no_m15_setup"
    )


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


def test_runner_summary_hold_reason_prefers_telemetry_over_proposal_text(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    summary = store.record_cycle(
        {
            "status": "NO_TRADE",
            "as_of": "2026-06-01 01:45",
            "proposal": {
                "status": "NO_TRADE",
                "reason": "No price data was provided by the analyst report.",
            },
            "analysis": {
                "telemetry": {
                    "decision_stage": "no_m15_setup",
                    "primary_hold_reason": "No valid M15 setup. Default to HOLD.",
                },
                "data_status": {"healthy": True},
            },
        }
    )

    assert summary["hold_reason_counts"] == {"no_m15_setup": 1}
    assert summary["latest_cycle"]["hold_reason"] == "no_m15_setup"


def test_runner_summary_counts_execution_skips_and_latest_order_context(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    summary = store.record_cycle(
        {
            "status": "ORDER_NOT_PLACED",
            "as_of": "2026-06-01 10:15",
            "execution": {
                "status": "SKIPPED_INVALID_ENTRY",
                "reason": "ENTRY_PRICE_STALE_OR_INVALID",
                "proposal": {
                    "setup_name": "Breakout",
                    "strategy_type": "BREAKOUT",
                    "order_type": "AUTO",
                    "side": "SELL",
                },
            },
            "analysis": {
                "telemetry": {
                    "candidate_evaluations": [
                        {"setup": {"name": "Breakout"}, "approved": True},
                        {
                            "setup": {"name": "Support/Resistance Bounce"},
                            "approved": False,
                        },
                    ]
                },
                "data_status": {"healthy": True},
            },
        }
    )

    assert summary["orders_skipped"] == 1
    assert summary["execution_skip_counts"]["ENTRY_PRICE_STALE_OR_INVALID"] == 1
    assert summary["candidate_strategy_counts"]["Breakout"] == 1
    assert summary["candidate_strategy_counts"]["Support/Resistance Bounce"] == 1
    assert summary["approved_candidate_strategy_counts"]["Breakout"] == 1
    assert summary["latest_execution"]["status"] == "SKIPPED_INVALID_ENTRY"
    assert summary["latest_execution"]["setup_name"] == "Breakout"


def test_runner_summary_records_rejection_retcode_comment(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    summary = store.record_cycle(
        {
            "status": "ORDER_NOT_PLACED",
            "as_of": "2026-06-01 10:15",
            "heartbeat_utc": "2026-06-01T14:15:00+00:00",
            "proposal": {
                "setup_name": "Breakout",
                "strategy_type": "BREAKOUT",
                "order_type": "BUY_STOP",
                "side": "BUY",
            },
            "execution": {
                "status": "REJECTED",
                "broker_result": {
                    "retcode": 10015,
                    "comment": "Invalid price",
                    "request": {"type": "SELL_LIMIT"},
                },
            },
            "analysis": {"data_status": {"healthy": True}},
        }
    )

    assert summary["broker_rejections"] == 1
    assert summary["latest_execution"]["retcode"] == 10015
    assert summary["latest_execution"]["comment"] == "Invalid price"
    assert summary["latest_execution"]["request_type"] == "SELL_LIMIT"
    assert summary["latest_execution"]["setup_name"] == "Breakout"
    assert summary["latest_execution"]["side"] == "BUY"
    assert summary["latest_execution"]["as_of"] == "2026-06-01 10:15"
    assert summary["latest_execution"]["heartbeat_utc"] == "2026-06-01T14:15:00+00:00"
