from datetime import datetime, timedelta, timezone
from pathlib import Path

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.mt5_runner import MT5Runner, MT5RunnerConfig


class FakeExecutor:
    def __init__(self, active=False):
        self.active = active
        self.executed = []
        self.cancel_calls = 0
        self.manage_calls = 0
        self.manage_result = {
            "status": "NO_POSITION_ACTION",
            "account_safety": {
                "require_demo": True,
                "trade_mode": "DEMO",
                "passed": True,
                "reason": None,
            },
        }
        self.history_calls = 0
        self.history_kwargs = []
        self.history_result = {"status": "RECONCILED", "closed_trade_count": 0}

    def snapshot_state(self):
        return {
            "orders": [{"ticket": 1}] if self.active else [],
            "positions": [],
        }

    def cancel_stale_pending_orders(self):
        self.cancel_calls += 1
        return {"status": "NO_ACTIVE_ORDER"}

    def manage_open_positions(self):
        self.manage_calls += 1
        return dict(self.manage_result)

    def execute_proposal(self, proposal):
        self.executed.append(proposal)
        return {
            "status": "PLACED",
            "order": 123,
            "account_safety": {
                "require_demo": True,
                "trade_mode": "DEMO",
                "passed": True,
                "reason": None,
            },
        }

    def reconcile_trade_history(self, **kwargs):
        self.history_calls += 1
        self.history_kwargs.append(kwargs)
        return dict(self.history_result)


class MonotonicClock:
    def __init__(self, times):
        self._times = list(times)
        self._index = 0

    def __call__(self):
        if self._index >= len(self._times):
            return self._times[-1]
        value = self._times[self._index]
        self._index += 1
        return value


def proposed_order():
    return OrderProposal(
        symbol="GC=F",
        broker_symbol="XAUUSD.vx",
        side=TradeAction.BUY,
        order_type="LIMIT",
        entry_price=2450.0,
        stop_loss=2447.0,
        take_profit=2459.0,
        timeframe="15m",
        confirmation_timeframe="30m",
        valid_until="2026-05-28 10:30 EDT",
        activation_window_minutes=10,
        cancel_if_not_triggered_after="2026-05-28 10:25 EDT",
        status=OrderStatus.PROPOSED,
        reason="A+ setup passed.",
    )


def test_runner_executes_proposed_order_once(tmp_path):
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposed_order()),
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert len(executor.executed) == 1
    assert Path(result["heartbeat_path"]).exists()


def test_runner_skips_new_analysis_when_active_trade_exists(tmp_path):
    executor = FakeExecutor(active=True)
    called = False

    def analysis_func():
        nonlocal called
        called = True
        return "2026-05-28 10:15", proposed_order()

    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=analysis_func,
    )

    result = runner.run_once()

    assert result["status"] == "ACTIVE_TRADE_MONITORED"
    assert called is False
    assert executor.cancel_calls == 1
    assert executor.manage_calls == 1
    assert executor.history_calls == 1


def test_runner_records_position_management_in_active_trade_heartbeat(tmp_path):
    executor = FakeExecutor(active=True)
    executor.manage_result = {
        "status": "POSITION_STOP_MOVED",
        "actions": [{"ticket": 123, "reason": "TRAILING_STOP"}],
        "account_safety": {
            "require_demo": True,
            "trade_mode": "DEMO",
            "passed": True,
            "reason": None,
        },
    }

    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposed_order()),
    )

    result = runner.run_once()

    assert result["status"] == "ACTIVE_TRADE_MONITORED"
    assert result["position_management"] == executor.manage_result
    assert result["account_safety"]["trade_mode"] == "DEMO"


def test_runner_records_trade_history_reconciliation_in_summary(tmp_path):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    executor.history_result = {
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
    }
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_once()

    assert result["history_reconciliation"]["closed_trade_count"] == 1
    assert result["summary"]["trade_history"]["closed_trade_count"] == 1
    assert result["summary"]["trade_history"]["net_profit"] == 6.67


def test_runner_stops_before_analysis_when_session_loss_limit_is_reached(tmp_path):
    executor = FakeExecutor(active=False)
    executor.history_result = {
        "status": "RECONCILED",
        "closed_trade_count": 4,
        "net_profit": -350.0,
        "wins": 1,
        "losses": 3,
    }

    def analysis_func():
        raise AssertionError("analysis should not run after risk limit is reached")

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_cycles=1,
            max_session_loss=300.0,
        ),
        executor=executor,
        analysis_func=analysis_func,
    )

    result = runner.run_once()

    assert result["status"] == "RISK_LIMIT_REACHED"
    assert result["risk_limit"]["max_session_loss"] == 300.0
    assert result["risk_limit"]["net_profit"] == -350.0
    assert executor.executed == []
    assert result["summary"]["latest_cycle"]["status"] == "RISK_LIMIT_REACHED"


def test_runner_starts_post_close_cooldown_before_new_analysis(tmp_path):
    closed_at = datetime.now(timezone.utc)
    executor = FakeExecutor(active=False)
    executor.history_result = {
        "status": "RECONCILED",
        "closed_trade_count": 1,
        "net_profit": 42.0,
        "latest_closed_trade": {
            "position_id": 111222,
            "exit_deal_ticket": 1002,
            "profit": 42.0,
            "closed_at_utc": closed_at.isoformat(),
        },
    }

    def analysis_func():
        raise AssertionError("analysis should not run during entry cooldown")

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_cycles=1,
            post_close_cooldown_seconds=300,
        ),
        executor=executor,
        analysis_func=analysis_func,
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["mode_decision"] == "ENTRY_COOLDOWN_ACTIVE"
    assert result["mode_rejection_reason"] == "POST_CLOSE_COOLDOWN"
    assert result["health_gate"] == {"passed": False, "reasons": ["entry_cooldown"]}
    assert result["entry_cooldown"]["exit_ticket"] == 1002
    assert result["entry_cooldown"]["reason"] == "POST_CLOSE_COOLDOWN"
    assert executor.executed == []
    assert runner._load_state()["entry_cooldown_exit_ticket"] == 1002


def test_runner_uses_longer_loss_cooldown_after_losing_trade(tmp_path):
    closed_at = datetime.now(timezone.utc)
    executor = FakeExecutor(active=False)
    executor.history_result = {
        "status": "RECONCILED",
        "closed_trade_count": 1,
        "net_profit": -30.0,
        "latest_closed_trade": {
            "position_id": 111223,
            "exit_deal_ticket": 1003,
            "profit": -30.0,
            "closed_at_utc": closed_at.isoformat(),
        },
    }

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_cycles=1,
            post_close_cooldown_seconds=60,
            loss_cooldown_seconds=600,
        ),
        executor=executor,
        analysis_func=lambda: (_ for _ in ()).throw(
            AssertionError("analysis should not run during loss cooldown")
        ),
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["mode_rejection_reason"] == "LOSS_COOLDOWN"
    assert result["entry_cooldown"]["seconds"] == 600
    assert result["entry_cooldown"]["profit"] == -30.0
    assert executor.executed == []


def test_runner_starts_loss_streak_cooldown_before_new_analysis(tmp_path):
    closed_at = datetime.now(timezone.utc)
    executor = FakeExecutor(active=False)
    executor.history_result = {
        "status": "RECONCILED",
        "closed_trade_count": 2,
        "net_profit": -185.0,
        "losses": 2,
        "closed_trades": [
            {
                "position_id": 111225,
                "exit_deal_ticket": 1005,
                "profit": -75.0,
                "closed_at_utc": (closed_at - timedelta(seconds=20)).isoformat(),
            },
            {
                "position_id": 111226,
                "exit_deal_ticket": 1006,
                "profit": -110.0,
                "closed_at_utc": closed_at.isoformat(),
            },
        ],
        "latest_closed_trade": {
            "position_id": 111226,
            "exit_deal_ticket": 1006,
            "profit": -110.0,
            "closed_at_utc": closed_at.isoformat(),
        },
    }

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_cycles=1,
            loss_streak_cooldown_count=2,
            loss_streak_cooldown_seconds=600,
        ),
        executor=executor,
        analysis_func=lambda: (_ for _ in ()).throw(
            AssertionError("analysis should not run during loss streak cooldown")
        ),
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["mode_rejection_reason"] == "LOSS_STREAK_COOLDOWN"
    assert result["health_gate"] == {"passed": False, "reasons": ["entry_cooldown"]}
    assert result["entry_cooldown"]["seconds"] == 600
    assert result["entry_cooldown"]["loss_streak"] == 2
    assert result["entry_cooldown"]["exit_ticket"] == 1006
    assert executor.executed == []


def test_runner_allows_analysis_after_entry_cooldown_expires(tmp_path):
    proposal = proposed_order()
    executor = FakeExecutor(active=False)
    closed_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    executor.history_result = {
        "status": "RECONCILED",
        "closed_trade_count": 1,
        "net_profit": 8.0,
        "latest_closed_trade": {
            "position_id": 111224,
            "exit_deal_ticket": 1004,
            "profit": 8.0,
            "closed_at_utc": closed_at.isoformat(),
        },
    }
    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_cycles=1,
            post_close_cooldown_seconds=60,
        ),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert len(executor.executed) == 1
    assert runner._load_state()["entry_cooldown_exit_ticket"] == 1004


def test_runner_reconciles_history_from_session_start(tmp_path):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    runner.run_once()

    assert executor.history_kwargs
    assert "since_utc" in executor.history_kwargs[0]
    assert executor.history_kwargs[0]["since_utc"] <= executor.history_kwargs[0]["now_utc"]


def test_runner_records_no_trade_without_execution(tmp_path):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert executor.executed == []


def test_runner_keeps_fast_profile_label_for_single_analysis_result(tmp_path):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    proposal.timeframe = "1m"
    proposal.confirmation_timeframe = "1m"
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: (
            "2026-06-03 08:16",
            proposal,
            {"entry_profile": "fast", "telemetry": {"entry_profile": "fast"}},
        ),
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["candidate_methods"]["ENTRY_FAST"]["selected_profile"] == "fast"


def test_runner_executes_first_proposed_profile_and_marks_each_profile(tmp_path):
    normal_no_trade = proposed_order()
    normal_no_trade.status = OrderStatus.NO_TRADE
    fast_order = proposed_order()
    fast_order.timeframe = "1m"
    fast_order.confirmation_timeframe = "3m"

    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: [
            (
                "normal",
                "2026-06-03 08:15",
                normal_no_trade,
                {"entry_profile": "normal"},
            ),
            (
                "fast",
                "2026-06-03 08:16",
                fast_order,
                {"entry_profile": "fast"},
            ),
        ],
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert result["entry_profile"] == "fast"
    assert len(executor.executed) == 1
    assert runner._load_state()["last_processed_by_profile"]["normal"] == "2026-06-03 08:15"
    assert runner._load_state()["last_processed_by_profile"]["fast"] == "2026-06-03 08:16"


def test_autogate_selects_fast_when_only_fast_qualifies(tmp_path):
    normal_no_trade = proposed_order()
    normal_no_trade.status = OrderStatus.NO_TRADE
    fast_order = proposed_order()
    fast_order.timeframe = "1m"
    fast_order.confirmation_timeframe = "3m"

    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_cycles=1,
            trading_mode="AUTO_GATED",
        ),
        executor=executor,
        analysis_func=lambda: [
            (
                "normal",
                "2026-06-03 08:15",
                normal_no_trade,
                {"entry_profile": "normal"},
            ),
            (
                "fast",
                "2026-06-03 08:16",
                fast_order,
                {"entry_profile": "fast"},
            ),
        ],
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert result["trading_mode"] == "AUTO_GATED"
    assert result["selected_method"] == "ENTRY_FAST"
    assert result["selected_profile"] == "fast"
    assert result["mode_decision"] == "ENTRY_FAST_SELECTED"
    assert result["health_gate"] == {"passed": True, "reasons": []}
    assert result["account_safety"]["trade_mode"] == "DEMO"
    assert len(executor.executed) == 1


def test_autogate_holds_when_fast_and_normal_conflict(tmp_path):
    normal = proposed_order()
    normal.side = TradeAction.BUY
    fast = proposed_order()
    fast.side = TradeAction.SELL
    fast.timeframe = "1m"
    fast.confirmation_timeframe = "3m"

    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_cycles=1,
            trading_mode="AUTO_GATED",
        ),
        executor=executor,
        analysis_func=lambda: [
            ("normal", "2026-06-03 08:15", normal, {"entry_profile": "normal"}),
            ("fast", "2026-06-03 08:16", fast, {"entry_profile": "fast"}),
        ],
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["trading_mode"] == "AUTO_GATED"
    assert result["selected_method"] == "HOLD"
    assert result["selected_profile"] is None
    assert result["mode_decision"] == "DIRECTIONAL_CONFLICT_HOLD"
    assert result["mode_rejection_reason"] == "FAST_NORMAL_DIRECTION_CONFLICT"
    assert executor.executed == []


def test_runner_marks_no_trade_candle_as_processed(tmp_path):
    no_trade = proposed_order()
    no_trade.status = OrderStatus.NO_TRADE
    proposed = proposed_order()
    responses = iter(
        [
            ("2026-05-28 10:15", no_trade),
            ("2026-05-28 10:15", proposed),
        ]
    )
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: next(responses),
    )

    first = runner.run_once()
    second = runner.run_once()

    assert first["status"] == "NO_TRADE"
    assert second["status"] == "CANDLE_ALREADY_PROCESSED"
    assert executor.executed == []


def test_runner_skips_analysis_for_already_processed_current_candle(tmp_path):
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: (_ for _ in ()).throw(RuntimeError("analysis should not run")),
        current_as_of_func=lambda: "2026-05-28 10:15",
    )

    runner._save_state({"last_processed_as_of": "2026-05-28 10:15"})
    result = runner.run_once()

    assert result["status"] == "CANDLE_ALREADY_PROCESSED"
    assert executor.executed == []


def test_runner_stops_after_max_runtime_seconds(tmp_path, monkeypatch):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    clock = MonotonicClock([0.0, 0.0, 2.0])
    sleeps = []

    monkeypatch.setattr(
        "tradingagents.brokers.mt5_runner.time.monotonic",
        clock,
    )
    monkeypatch.setattr(
        "tradingagents.brokers.mt5_runner.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_runtime_seconds=1,
        ),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_forever()

    assert result["status"] == "STOPPED_MAX_RUNTIME_SECONDS"
    assert result["last_result"]["status"] == "NO_TRADE"
    assert sleeps == []


def test_runner_forever_stops_when_session_loss_limit_is_reached(tmp_path, monkeypatch):
    executor = FakeExecutor(active=False)
    executor.history_result = {
        "status": "RECONCILED",
        "closed_trade_count": 3,
        "net_profit": -300.0,
        "wins": 0,
        "losses": 3,
    }
    sleeps = []
    monkeypatch.setattr(
        "tradingagents.brokers.mt5_runner.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_session_loss=300.0,
        ),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposed_order()),
    )

    result = runner.run_forever()

    assert result["status"] == "STOPPED_RISK_LIMIT"
    assert result["last_result"]["status"] == "RISK_LIMIT_REACHED"
    assert sleeps == []


def test_runner_maintains_active_trade_each_second_between_full_cycles(
    tmp_path,
    monkeypatch,
):
    executor = FakeExecutor(active=True)
    sleeps = []
    monkeypatch.setattr(
        "tradingagents.brokers.mt5_runner.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            maintenance_poll_seconds=1,
            max_cycles=2,
        ),
        executor=executor,
        analysis_func=lambda: (_ for _ in ()).throw(
            AssertionError("analysis should not run while a trade is active")
        ),
    )

    result = runner.run_forever()

    assert result["status"] == "STOPPED_MAX_CYCLES"
    assert sleeps == [1.0, 1.0, 1.0, 1.0, 1.0]
    assert executor.cancel_calls == 6
    assert executor.manage_calls == 2


def test_runner_runtime_deadline_takes_precedence_over_max_cycles(tmp_path, monkeypatch):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    clock = MonotonicClock([0.0, 2.0])

    monkeypatch.setattr(
        "tradingagents.brokers.mt5_runner.time.monotonic",
        clock,
    )
    monkeypatch.setattr(
        "tradingagents.brokers.mt5_runner.time.sleep",
        lambda seconds: None,
    )

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_cycles=1,
            max_runtime_seconds=1,
        ),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_forever()

    assert result["status"] == "STOPPED_MAX_RUNTIME_SECONDS"
    assert result["last_result"]["status"] == "NO_TRADE"


def test_runner_clamps_sleep_to_remaining_runtime(tmp_path, monkeypatch):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    clock = MonotonicClock([0.0, 2.0, 2.0, 5.0])
    sleeps = []

    monkeypatch.setattr(
        "tradingagents.brokers.mt5_runner.time.monotonic",
        clock,
    )
    monkeypatch.setattr(
        "tradingagents.brokers.mt5_runner.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=10,
            max_runtime_seconds=5,
        ),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_forever()

    assert result["status"] == "STOPPED_MAX_RUNTIME_SECONDS"
    assert sleeps == [3.0]


def test_runner_skips_already_processed_candle(tmp_path):
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposed_order()),
    )

    first = runner.run_once()
    second = runner.run_once()

    assert first["status"] == "ORDER_PLACED"
    assert second["status"] == "CANDLE_ALREADY_PROCESSED"
    assert len(executor.executed) == 1


def test_runner_records_invalid_entry_skip_as_order_not_placed(tmp_path):
    proposal = proposed_order()

    class InvalidEntryExecutor(FakeExecutor):
        def execute_proposal(self, proposal):
            self.executed.append(proposal)
            return {
                "status": "SKIPPED_INVALID_ENTRY",
                "reason": "ENTRY_PRICE_STALE_OR_INVALID",
                "proposal": proposal.model_dump(mode="json"),
            }

    executor = InvalidEntryExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal, {"telemetry": {}}),
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_NOT_PLACED"
    assert result["execution"]["status"] == "SKIPPED_INVALID_ENTRY"
    assert (
        result["summary"]["execution_skip_counts"]["ENTRY_PRICE_STALE_OR_INVALID"]
        == 1
    )


def test_runner_blocks_configured_strategy_rule_before_execution(tmp_path):
    proposal = proposed_order()
    proposal.side = TradeAction.SELL
    proposal.setup_name = "Support/Resistance Bounce"
    proposal.strategy_type = "SUPPORT_RESISTANCE_BOUNCE"
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_cycles=1,
            blocked_strategy_rules=("SUPPORT_RESISTANCE_BOUNCE:SELL",),
        ),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_BLOCKED_STRATEGY"
    assert result["execution"]["status"] == "SKIPPED_BLOCKED_STRATEGY"
    assert result["execution"]["reason"] == "BLOCKED_STRATEGY_RULE"
    assert result["execution"]["matched_rule"] == "SUPPORT_RESISTANCE_BOUNCE:SELL"
    assert executor.executed == []
    assert (
        result["summary"]["execution_skip_counts"]["BLOCKED_STRATEGY_RULE"]
        == 1
    )


def test_runner_records_summary_for_no_trade_with_analysis_metadata(tmp_path):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: (
            "2026-05-28 10:15",
            proposal,
            {
                "telemetry": {
                    "decision_stage": "higher_timeframe_permission",
                    "primary_hold_reason": "H4 blocks BUY",
                },
                "data_status": {"healthy": True, "timeframes": {}},
            },
        ),
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["analysis"]["telemetry"]["decision_stage"] == "higher_timeframe_permission"
    assert Path(result["summary_path"]).exists()
    summary = Path(result["summary_path"]).read_text(encoding="utf-8")
    assert "higher_timeframe" in summary


def test_runner_keeps_two_tuple_analysis_func_backward_compatible(tmp_path):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["analysis"] == {}


def test_runner_records_analysis_error_without_stopping(tmp_path):
    executor = FakeExecutor(active=False)

    def analysis_func():
        raise RuntimeError("OpenRouter connection error")

    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=analysis_func,
    )

    result = runner.run_once()

    assert result["status"] == "RUNNER_ERROR"
    assert result["analysis"]["error_type"] == "RuntimeError"
    assert result["analysis"]["error"] == "OpenRouter connection error"
    assert Path(result["heartbeat_path"]).exists()
    assert Path(result["summary_path"]).exists()
