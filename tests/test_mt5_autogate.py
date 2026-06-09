from pathlib import Path

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.mt5_autogate import MT5AutoGateConfig, MT5AutoGateRunner


class FakeDirectionalExecutor:
    def __init__(self, active=False):
        self.active = active
        self.executed = []
        self.cancel_calls = 0
        self.manage_calls = 0
        self.history_calls = 0
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
        return {"status": "NO_POSITION_ACTION"}

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
        return dict(self.history_result)


class FakeStraddleExecutor:
    def __init__(self, candidate=None):
        self.candidate = candidate or {"status": "STRADDLE_NO_TRADE"}
        self.candidate_calls = 0
        self.executed = []
        self.executed_live = None
        self.monitor_calls = 0
        self.manage_calls = 0

    def monitor_pair(self):
        self.monitor_calls += 1
        return {"status": "NO_ACTIVE_PAIR"}

    def manage_open_positions(self, *_args, **_kwargs):
        self.manage_calls += 1
        return {"status": "NO_OPEN_POSITION"}

    def evaluate_entry_candidate(self, straddle_config, **_kwargs):
        self.candidate_calls += 1
        return dict(self.candidate)

    def execute_pair(self, pair, *, live=False):
        self.executed.append(pair)
        self.executed_live = live
        return {"status": "PAIR_PLACED", "order": 456}


def proposed_order(side=TradeAction.BUY):
    return OrderProposal(
        symbol="GC=F",
        broker_symbol="XAUUSD.vx",
        side=side,
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
        reason="Setup passed.",
    )


def no_trade_order():
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    proposal.reason = "No setup."
    return proposal


def test_autogate_selects_straddle_when_directional_holds(tmp_path):
    directional_executor = FakeDirectionalExecutor(active=False)
    pair = object()
    straddle_executor = FakeStraddleExecutor(
        candidate={"status": "PROPOSED", "pair": pair, "requests": []}
    )

    runner = MT5AutoGateRunner(
        MT5AutoGateConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        directional_executor=directional_executor,
        straddle_executor=straddle_executor,
        directional_analysis_func=lambda: [
            ("normal", "2026-06-03 08:15", no_trade_order(), {"entry_profile": "normal"}),
            ("fast", "2026-06-03 08:16", no_trade_order(), {"entry_profile": "fast"}),
        ],
        straddle_config=object(),
    )

    result = runner.run_once()

    assert result["status"] == "STRADDLE_ORDER_PLACED"
    assert result["trading_mode"] == "AUTO_GATED"
    assert result["selected_method"] == "STRADDLE"
    assert result["mode_decision"] == "STRADDLE_SELECTED"
    assert straddle_executor.candidate_calls == 1
    assert straddle_executor.executed == [pair]
    assert straddle_executor.executed_live is True
    assert directional_executor.executed == []
    assert Path(result["heartbeat_path"]).exists()


def test_autogate_active_trade_blocks_directional_and_straddle_scans(tmp_path):
    directional_executor = FakeDirectionalExecutor(active=True)
    straddle_executor = FakeStraddleExecutor()

    runner = MT5AutoGateRunner(
        MT5AutoGateConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        directional_executor=directional_executor,
        straddle_executor=straddle_executor,
        directional_analysis_func=lambda: (_ for _ in ()).throw(
            AssertionError("no analysis")
        ),
        straddle_config=object(),
    )

    result = runner.run_once()

    assert result["status"] == "ACTIVE_TRADE_MONITORED"
    assert result["selected_method"] == "HOLD"
    assert straddle_executor.candidate_calls == 0
    assert directional_executor.executed == []


def test_autogate_selects_directional_before_straddle(tmp_path):
    directional_executor = FakeDirectionalExecutor(active=False)
    pair = object()
    straddle_executor = FakeStraddleExecutor(
        candidate={"status": "PROPOSED", "pair": pair, "requests": []}
    )
    fast = proposed_order()
    fast.timeframe = "1m"
    fast.confirmation_timeframe = "3m"

    runner = MT5AutoGateRunner(
        MT5AutoGateConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        directional_executor=directional_executor,
        straddle_executor=straddle_executor,
        directional_analysis_func=lambda: [
            ("normal", "2026-06-03 08:15", no_trade_order(), {"entry_profile": "normal"}),
            ("fast", "2026-06-03 08:16", fast, {"entry_profile": "fast"}),
        ],
        straddle_config=object(),
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert result["selected_method"] == "ENTRY_FAST"
    assert result["mode_decision"] == "ENTRY_FAST_SELECTED"
    assert result["account_safety"]["trade_mode"] == "DEMO"
    assert len(directional_executor.executed) == 1
    assert straddle_executor.executed == []
