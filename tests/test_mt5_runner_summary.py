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


def test_runner_summary_counts_statuses_by_entry_profile(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    store.record_cycle(
        {
            "status": "ORDER_PLACED",
            "entry_profile": "fast",
            "as_of": "2026-06-03 08:16",
            "execution": {"status": "PLACED", "order": 1},
            "analysis": {"telemetry": {"decision_stage": "setup_found"}},
        }
    )
    summary = store.record_cycle(
        {
            "status": "NO_TRADE",
            "profiles": [
                {
                    "entry_profile": "normal",
                    "as_of": "2026-06-03 08:15",
                    "status": "NO_TRADE",
                    "analysis": {
                        "telemetry": {
                            "decision_stage": "no_m15_setup",
                            "primary_hold_reason": "No valid M15 setup.",
                        }
                    },
                },
                {
                    "entry_profile": "fast",
                    "as_of": "2026-06-03 08:16",
                    "status": "NO_TRADE",
                    "analysis": {
                        "telemetry": {
                            "decision_stage": "counter_bias_grade_filter",
                            "primary_hold_reason": "Fast counter-bias setup requires A_PLUS.",
                        }
                    },
                },
            ],
        }
    )

    assert summary["profile_status_counts"]["fast"]["ORDER_PLACED"] == 1
    assert summary["profile_status_counts"]["fast"]["NO_TRADE"] == 1
    assert summary["profile_status_counts"]["normal"]["NO_TRADE"] == 1


def test_runner_summary_deduplicates_history_reconciliation(tmp_path):
    store = RunnerSummaryStore(tmp_path)
    result = {
        "status": "NO_TRADE",
        "history_reconciliation": {
            "status": "RECONCILED",
            "filled_trade_count": 1,
            "closed_trade_count": 1,
            "net_profit": 6.67,
            "wins": 1,
            "losses": 0,
            "closed_trades": [
                {
                    "position_id": 111222,
                    "entry_deal_ticket": 1001,
                    "exit_deal_ticket": 1002,
                    "side": "BUY",
                    "entry_price": 2450.12,
                    "exit_price": 2456.79,
                    "volume": 0.01,
                    "profit": 6.67,
                    "outcome": "TP",
                    "closed_at_utc": "2026-05-24T10:00:00+00:00",
                }
            ],
        },
    }

    first = store.record_cycle(result)
    second = store.record_cycle(result)

    assert first["trade_history"]["closed_trade_count"] == 1
    assert second["trade_history"]["closed_trade_count"] == 1
    assert second["trade_history"]["filled_trade_count"] == 1
    assert second["trade_history"]["wins"] == 1
    assert second["trade_history"]["losses"] == 0
    assert second["trade_history"]["net_profit"] == 6.67
    assert second["trade_history"]["latest_closed_trade"]["position_id"] == 111222


def test_runner_summary_counts_filled_trade_before_close(tmp_path):
    store = RunnerSummaryStore(tmp_path)
    result = {
        "status": "ACTIVE_TRADE_MONITORED",
        "history_reconciliation": {
            "status": "RECONCILED",
            "filled_trade_count": 1,
            "closed_trade_count": 0,
            "filled_trades": [
                {
                    "position_id": 111222,
                    "entry_deal_ticket": 1001,
                    "side": "BUY",
                    "entry_price": 2450.12,
                    "volume": 0.01,
                    "opened_at_utc": "2026-05-24T09:55:00+00:00",
                }
            ],
            "closed_trades": [],
        },
    }

    first = store.record_cycle(result)
    second = store.record_cycle(result)

    assert first["trade_history"]["filled_trade_count"] == 1
    assert second["trade_history"]["filled_trade_count"] == 1
    assert second["trade_history"]["closed_trade_count"] == 0
    assert second["trade_history"]["latest_filled_trade"]["position_id"] == 111222


def test_runner_summary_excludes_duplicate_processed_candles_from_check_counts(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    first = store.record_cycle(
        {
            "status": "NO_TRADE",
            "as_of": "2026-06-01 10:15",
            "proposal": {
                "status": "NO_TRADE",
                "reason": "Time filter failed. Default to HOLD.",
            },
            "analysis": {
                "telemetry": {
                    "decision_stage": "time_filter",
                    "primary_hold_reason": "Time filter failed. Default to HOLD.",
                },
                "data_status": {"healthy": True},
            },
        }
    )
    second = store.record_cycle(
        {
            "status": "CANDLE_ALREADY_PROCESSED",
            "as_of": "2026-06-01 10:15",
            "proposal": {
                "status": "NO_TRADE",
                "reason": "Current candle already processed.",
            },
        }
    )

    assert first["total_checks"] == 1
    assert second["total_checks"] == 1
    assert second["status_counts"] == {"NO_TRADE": 1}
    assert second["latest_cycle"]["status"] == "CANDLE_ALREADY_PROCESSED"
