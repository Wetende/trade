from pathlib import Path

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.mt5_runner import MT5Runner, MT5RunnerConfig


class FakeExecutor:
    def __init__(self, active=False):
        self.active = active
        self.executed = []
        self.cancel_calls = 0
        self.manage_calls = 0

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
        return {"status": "NO_POSITION_ACTION"}

    def execute_proposal(self, proposal):
        self.executed.append(proposal)
        return {"status": "PLACED", "order": 123}


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
