import json
import math
from datetime import datetime, timezone

import pytest

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.mt5 import MT5ConnectionConfig, MT5OrderRequestBuilder
from tradingagents.brokers.mt5_execution import (
    MT5ExitManagementConfig,
    MT5Executor,
    load_order_proposal,
)


def _proposal(side: TradeAction = TradeAction.BUY) -> OrderProposal:
    return OrderProposal(
        symbol="XAUUSD",
        side=side,
        order_type="LIMIT",
        entry_price=2450.123,
        stop_loss=2447.987,
        take_profit=2456.789,
        timeframe="15m",
        confirmation_timeframe="30m",
        valid_until="2026-05-27 10:15 EDT",
        activation_window_minutes=10,
        cancel_if_not_triggered_after="2026-05-27 10:10 EDT",
        status=OrderStatus.PROPOSED,
        reason="A+ setup passed.",
    )


def test_package_exports_only_generic_mt5_executor():
    import tradingagents.brokers as brokers
    from tradingagents.brokers import MT5Executor as PackageMT5Executor

    assert PackageMT5Executor is MT5Executor
    retired_alias = "MT5" + "Demo" + "Executor"
    assert not hasattr(brokers, retired_alias)


def test_build_buy_limit_request_rounds_prices():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        volume=0.01,
        deviation=20,
        magic=150015,
    )
    builder = MT5OrderRequestBuilder(config)
    symbol = {
        "name": "XAUUSD",
        "digits": 2,
        "point": 0.01,
        "trade_tick_size": 0.01,
    }

    request = builder.build_pending_limit_request(_proposal(), symbol)

    assert request == {
        "action": "TRADE_ACTION_PENDING",
        "symbol": "XAUUSD",
        "volume": 0.01,
        "type": "BUY_LIMIT",
        "price": 2450.12,
        "sl": 2447.99,
        "tp": 2456.79,
        "deviation": 20,
        "magic": 150015,
        "comment": "TradingAgents",
        "type_time": "ORDER_TIME_GTC",
        "type_filling": "ORDER_FILLING_RETURN",
    }


def test_build_request_uses_broker_symbol_when_analysis_symbol_differs():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD.vx",
    )
    builder = MT5OrderRequestBuilder(config)
    proposal = _proposal()
    proposal.symbol = "GC=F"
    proposal.broker_symbol = "XAUUSD.vx"

    request = builder.build_pending_limit_request(
        proposal,
        {
            "name": "XAUUSD.vx",
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
        },
    )

    assert request["symbol"] == "XAUUSD.vx"


def test_build_request_rejects_no_trade_proposal():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
    )
    builder = MT5OrderRequestBuilder(config)
    proposal = _proposal()
    proposal.status = OrderStatus.NO_TRADE

    with pytest.raises(ValueError, match="PROPOSED"):
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})


def test_build_request_rejects_market_order_proposal():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )
    proposal = _proposal()
    proposal.order_type = "MARKET"

    with pytest.raises(ValueError, match="unsupported MT5 pending order type: MARKET"):
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})


def test_build_sell_limit_request_maps_side():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )

    proposal = _proposal(TradeAction.SELL)
    proposal.stop_loss = 2456.789
    proposal.take_profit = 2447.987

    request = builder.build_pending_limit_request(proposal, {"digits": 2})

    assert request["type"] == "SELL_LIMIT"


def test_build_breakout_buy_above_ask_as_buy_stop():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.setup_name = "Breakout"
    proposal.strategy_type = "BREAKOUT"
    proposal.entry_price = 4508.00
    proposal.stop_loss = 4506.00
    proposal.take_profit = 4512.00

    request = builder.build_pending_order_request(
        proposal,
        {
            "name": "XAUUSD",
            "digits": 2,
            "trade_tick_size": 0.01,
            "bid": 4506.99,
            "ask": 4507.32,
        },
    )

    assert request["type"] == "BUY_STOP"


def test_build_breakout_sell_below_bid_as_sell_stop():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.SELL)
    proposal.order_type = "AUTO"
    proposal.setup_name = "Breakout"
    proposal.strategy_type = "BREAKOUT"
    proposal.entry_price = 4506.00
    proposal.stop_loss = 4508.00
    proposal.take_profit = 4502.00

    request = builder.build_pending_order_request(
        proposal,
        {
            "name": "XAUUSD",
            "digits": 2,
            "trade_tick_size": 0.01,
            "bid": 4506.99,
            "ask": 4507.32,
        },
    )

    assert request["type"] == "SELL_STOP"


def test_build_retest_buy_below_ask_as_buy_limit():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.setup_name = "Break and Retest"
    proposal.strategy_type = "BREAK_AND_RETEST"
    proposal.entry_price = 4506.50
    proposal.stop_loss = 4505.00
    proposal.take_profit = 4510.00

    request = builder.build_pending_order_request(
        proposal,
        {
            "name": "XAUUSD",
            "digits": 2,
            "trade_tick_size": 0.01,
            "bid": 4506.99,
            "ask": 4507.32,
        },
    )

    assert request["type"] == "BUY_LIMIT"


def test_build_retest_sell_above_bid_as_sell_limit():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.SELL)
    proposal.order_type = "AUTO"
    proposal.setup_name = "Break and Retest"
    proposal.strategy_type = "BREAK_AND_RETEST"
    proposal.entry_price = 4507.50
    proposal.stop_loss = 4509.00
    proposal.take_profit = 4504.00

    request = builder.build_pending_order_request(
        proposal,
        {
            "name": "XAUUSD",
            "digits": 2,
            "trade_tick_size": 0.01,
            "bid": 4506.99,
            "ask": 4507.32,
        },
    )

    assert request["type"] == "SELL_LIMIT"


def test_build_auto_rejects_stale_buy_entry_between_bid_and_ask():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.entry_price = 4507.10
    proposal.stop_loss = 4505.00
    proposal.take_profit = 4511.00

    with pytest.raises(ValueError, match="entry price is stale or inside spread"):
        builder.build_pending_order_request(
            proposal,
            {
                "name": "XAUUSD",
                "digits": 2,
                "trade_tick_size": 0.01,
                "bid": 4506.99,
                "ask": 4507.32,
            },
        )


def test_build_auto_rejects_entry_inside_broker_stop_level():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.entry_price = 4507.50
    proposal.stop_loss = 4506.00
    proposal.take_profit = 4512.00

    with pytest.raises(ValueError, match="entry price is inside broker stop level"):
        builder.build_pending_order_request(
            proposal,
            {
                "name": "XAUUSD",
                "digits": 2,
                "point": 0.01,
                "trade_tick_size": 0.01,
                "trade_stops_level": 50,
                "bid": 4506.99,
                "ask": 4507.32,
            },
        )


def test_build_request_rejects_broker_symbol_mismatch():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        )
    )
    proposal = _proposal()
    proposal.symbol = "GC=F"
    proposal.broker_symbol = "EURUSD"

    with pytest.raises(ValueError, match="proposal broker symbol EURUSD does not match"):
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})


def test_build_request_rejects_symbol_info_name_mismatch():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        )
    )

    with pytest.raises(
        ValueError,
        match="symbol info EURUSD does not match MT5 symbol XAUUSD",
    ):
        builder.build_pending_limit_request(_proposal(), {"name": "EURUSD", "digits": 2})


def test_build_request_rejects_missing_levels():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )
    proposal = _proposal()
    proposal.take_profit = None

    with pytest.raises(
        ValueError,
        match="entry_price, stop_loss, and take_profit",
    ):
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})


def test_build_request_rejects_invalid_buy_levels():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )
    proposal = _proposal()
    proposal.stop_loss = 2451.00

    with pytest.raises(ValueError, match="invalid BUY levels"):
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})


def test_build_request_rejects_invalid_sell_levels():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )
    proposal = _proposal(TradeAction.SELL)

    with pytest.raises(ValueError, match="invalid SELL levels"):
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})


def test_build_request_snaps_prices_to_trade_tick_size():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )

    request = builder.build_pending_limit_request(
        _proposal(),
        {"name": "XAUUSD", "digits": 2, "trade_tick_size": 0.05},
    )

    assert request["price"] == 2450.10
    assert request["sl"] == 2448.00
    assert request["tp"] == 2456.80


def test_build_request_preserves_digits_zero():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )

    request = builder.build_pending_limit_request(_proposal(), {"digits": 0})

    assert request["price"] == 2450
    assert request["sl"] == 2448
    assert request["tp"] == 2457


@pytest.mark.parametrize("price_field", ["entry_price", "stop_loss", "take_profit"])
@pytest.mark.parametrize("bad_price", [math.nan, math.inf, -math.inf, 0, -1])
def test_build_request_rejects_non_positive_or_non_finite_prices(
    price_field,
    bad_price,
):
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )
    proposal = _proposal()
    setattr(proposal, price_field, bad_price)

    with pytest.raises(ValueError, match="price must be positive"):
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})


class FakeBroker:
    def __init__(self):
        self.symbol_info = {
            "name": "XAUUSD",
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
        }
        self.pending_orders = []
        self.positions = []
        self.placed_requests = []
        self.cancelled = []
        self.modified_stops = []
        self.closed_positions = []
        self.history_deals_result = []
        self.history_deals_calls = []
        self.checked_requests = []
        self.check_result = {"ok": True, "retcode": 10009, "comment": "check ok"}
        self.place_result = {
            "ok": True,
            "order": 111222,
            "retcode": 10009,
            "comment": "ok",
        }

    def connect(self):
        return {
            "connected": True,
            "symbol": self.symbol_info,
            "account": {"login": 123456789, "trade_mode_label": "DEMO"},
        }

    def open_orders(self, symbol):
        return [order for order in self.pending_orders if order.get("symbol") == symbol]

    def open_positions(self, symbol):
        return [
            position for position in self.positions if position.get("symbol") == symbol
        ]

    def place_pending_order(self, request):
        self.placed_requests.append(request)
        return dict(self.place_result)

    def check_order(self, request):
        self.checked_requests.append(dict(request))
        return dict(self.check_result)

    def cancel_order(self, ticket):
        self.cancelled.append(ticket)
        return {"ok": True, "order": ticket, "retcode": 10009}

    def modify_position_stops(self, position_ticket, stop_loss, take_profit):
        self.modified_stops.append(
            {
                "position_ticket": position_ticket,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            }
        )
        return {"ok": True, "position": position_ticket, "retcode": 10009}

    def close_position(self, position, *, comment="TradingAgents close"):
        self.closed_positions.append((dict(position), comment))
        return {"ok": True, "position": position.get("ticket"), "retcode": 10009}

    def history_deals(self, symbol, start_utc, end_utc):
        self.history_deals_calls.append((symbol, start_utc, end_utc))
        return list(self.history_deals_result)


def _config() -> MT5ConnectionConfig:
    return MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        volume=0.01,
        deviation=20,
        magic=150015,
    )


def test_load_order_proposal_reads_json_artifact(tmp_path):
    proposal_path = tmp_path / "proposal.json"
    proposal_path.write_text(
        json.dumps(_proposal().model_dump(mode="json")),
        encoding="utf-8",
    )

    proposal = load_order_proposal(proposal_path)

    assert proposal.symbol == "XAUUSD"
    assert proposal.status == OrderStatus.PROPOSED
    assert proposal.side == TradeAction.BUY


def test_executor_places_pending_order_when_no_active_trade(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(_proposal())

    assert result["status"] == "PLACED"
    assert result["order"] == 111222
    assert len(broker.checked_requests) == 1
    assert len(broker.placed_requests) == 1
    assert broker.placed_requests[0]["type"] == "BUY_LIMIT"
    assert result["order_check_result"]["ok"] is True


def test_executor_skips_when_order_check_fails(tmp_path):
    broker = FakeBroker()
    broker.check_result = {
        "ok": False,
        "retcode": 10030,
        "comment": "invalid stops",
    }
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(_proposal())

    assert result["status"] == "SKIPPED_ORDER_CHECK"
    assert result["reason"] == "ORDER_CHECK_FAILED"
    assert result["order_check_result"]["retcode"] == 10030
    assert broker.checked_requests
    assert broker.placed_requests == []


def test_executor_result_and_journal_include_account_safety(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(_proposal())

    assert result["account_safety"] == {
        "require_demo": True,
        "trade_mode": "DEMO",
        "passed": True,
        "reason": None,
    }
    journal_path = tmp_path / "XAUUSD" / "execution_journal" / "mt5_events.jsonl"
    events = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
    ]
    connected = events[0]
    assert connected["event_type"] == "CONNECTED"
    assert connected["payload"]["account_safety"]["trade_mode"] == "DEMO"


def test_executor_refuses_when_active_order_exists(tmp_path):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 999, "symbol": "XAUUSD"}]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(_proposal())

    assert result["status"] == "SKIPPED_ACTIVE_TRADE"
    assert broker.placed_requests == []


def test_executor_refuses_when_active_position_exists(tmp_path):
    broker = FakeBroker()
    broker.positions = [{"ticket": 888, "symbol": "XAUUSD"}]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(_proposal())

    assert result["status"] == "SKIPPED_ACTIVE_TRADE"
    assert broker.placed_requests == []


def test_executor_returns_rejected_when_broker_rejects_order(tmp_path):
    broker = FakeBroker()
    broker.place_result = {
        "ok": False,
        "order": None,
        "retcode": 10030,
        "comment": "invalid stops",
    }
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(_proposal())

    assert result["status"] == "REJECTED"
    assert result["order"] is None
    assert result["broker_result"]["retcode"] == 10030


def test_executor_skips_stale_auto_entry_without_broker_send(tmp_path):
    broker = FakeBroker()
    broker.symbol_info = {
        "name": "XAUUSD",
        "digits": 2,
        "point": 0.01,
        "trade_tick_size": 0.01,
        "bid": 4506.99,
        "ask": 4507.32,
    }
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.entry_price = 4507.10
    proposal.stop_loss = 4505.00
    proposal.take_profit = 4511.00
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(proposal)

    assert result["status"] == "SKIPPED_INVALID_ENTRY"
    assert result["reason"] == "ENTRY_PRICE_STALE_OR_INVALID"
    assert "inside spread" in result["error"]
    assert broker.placed_requests == []


def test_executor_skips_entry_far_from_live_quote(tmp_path):
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        max_entry_distance_points=10.0,
    )
    broker = FakeBroker()
    broker.symbol_info = {
        "name": "XAUUSD",
        "bid": 4476.39,
        "ask": 4476.72,
        "digits": 2,
        "point": 0.01,
        "trade_tick_size": 0.01,
        "trade_stops_level": 50,
    }
    proposal = _proposal(TradeAction.SELL)
    proposal.entry_price = 4517.47
    proposal.stop_loss = 4520.47
    proposal.take_profit = 4510.47
    proposal.broker_symbol = "XAUUSD"
    executor = MT5Executor(config, tmp_path, broker=broker)

    result = executor.execute_proposal(proposal)

    assert result["status"] == "SKIPPED_INVALID_ENTRY"
    assert "too far from live MT5 quote" in result["error"]
    assert broker.placed_requests == []


def test_executor_journals_connection_request_and_order_result(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    executor.execute_proposal(_proposal())

    journal_path = (
        tmp_path / "XAUUSD" / "execution_journal" / "mt5_events.jsonl"
    )
    event_types = [
        json.loads(line)["event_type"]
        for line in journal_path.read_text(encoding="utf-8").splitlines()
    ]
    assert event_types == [
        "CONNECTED",
        "ORDER_REQUEST_BUILT",
        "ORDER_CHECKED",
        "ORDER_PLACED",
    ]


def test_executor_records_active_order_state(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    executor.execute_proposal(_proposal())

    state = executor.state.load()
    assert state["active_order_ticket"] == 111222
    assert state["symbol"] == "XAUUSD"
    assert state["proposal"]["symbol"] == "XAUUSD"


def test_executor_does_not_record_state_when_order_rejected(tmp_path):
    broker = FakeBroker()
    broker.place_result = {
        "ok": False,
        "order": None,
        "retcode": 10030,
        "comment": "invalid stops",
    }
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    executor.execute_proposal(_proposal())

    assert executor.state.load()["active_order_ticket"] is None


def test_executor_cancels_stale_active_pending_order(tmp_path):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 111, "symbol": "XAUUSD"}]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "cancel_after_utc": "2026-05-27T14:00:00+00:00",
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:00+00:00"
    )

    assert result["status"] == "CANCELLED"
    assert result["ticket"] == 111
    assert broker.cancelled == [111]
    assert executor.state.load()["active_order_ticket"] is None


def test_executor_clears_state_when_tracked_ticket_is_open_position(tmp_path):
    broker = FakeBroker()
    broker.positions = [{"ticket": 111, "symbol": "XAUUSD"}]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "cancel_after_utc": "2026-05-27T14:00:00+00:00",
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:00+00:00"
    )

    assert result["status"] == "ORDER_ALREADY_FILLED"
    assert result["ticket"] == 111
    assert broker.cancelled == []
    assert executor.state.load()["active_order_ticket"] is None


def test_executor_clears_state_when_tracked_ticket_is_not_open_anymore(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "cancel_after_utc": "2026-05-27T14:00:00+00:00",
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:00+00:00"
    )

    assert result["status"] == "ORDER_NOT_OPEN"
    assert result["ticket"] == 111
    assert broker.cancelled == []
    assert executor.state.load()["active_order_ticket"] is None


def test_executor_reconciles_closed_bot_trade_history(tmp_path):
    broker = FakeBroker()
    broker.history_deals_result = [
        {
            "ticket": 1001,
            "order": 111222,
            "position_id": 111222,
            "symbol": "XAUUSD",
            "time": 1779610000,
            "type": 0,
            "entry": 0,
            "volume": 0.01,
            "price": 2450.12,
            "profit": 0.0,
            "commission": 0.0,
            "swap": 0.0,
            "magic": 150015,
            "comment": "TradingAgents",
        },
        {
            "ticket": 1002,
            "order": 111333,
            "position_id": 111222,
            "symbol": "XAUUSD",
            "time": 1779610300,
            "type": 1,
            "entry": 1,
            "volume": 0.01,
            "price": 2456.79,
            "profit": 6.67,
            "commission": 0.0,
            "swap": 0.0,
            "magic": 150015,
            "comment": "[tp 2456.79]",
        },
        {
            "ticket": 2001,
            "order": 222222,
            "position_id": 222222,
            "symbol": "XAUUSD",
            "time": 1779610300,
            "type": 0,
            "entry": 0,
            "volume": 0.01,
            "price": 2451.00,
            "profit": 0.0,
            "magic": 0,
            "comment": "manual trade",
        },
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.reconcile_trade_history(
        now_utc=datetime.fromtimestamp(1779610400, tz=timezone.utc),
    )

    assert broker.history_deals_calls
    assert result["status"] == "RECONCILED"
    assert result["filled_trade_count"] == 1
    assert result["closed_trade_count"] == 1
    assert result["net_profit"] == 6.67
    assert result["wins"] == 1
    assert result["losses"] == 0
    assert result["closed_trades"][0]["position_id"] == 111222
    assert result["closed_trades"][0]["outcome"] == "TP"
    assert result["closed_trades"][0]["exit_deal_ticket"] == 1002


def test_executor_reconcile_trade_history_accepts_explicit_start(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    start = datetime.fromtimestamp(1779610100, tz=timezone.utc)
    now = datetime.fromtimestamp(1779610400, tz=timezone.utc)

    result = executor.reconcile_trade_history(since_utc=start, now_utc=now)

    assert result["status"] == "RECONCILED"
    assert broker.history_deals_calls[0][1] == start
    assert broker.history_deals_calls[0][2] == now


def test_executor_leaves_non_stale_active_pending_order(tmp_path):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 111, "symbol": "XAUUSD"}]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "cancel_after_utc": "2026-05-27T14:10:00+00:00",
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:00+00:00"
    )

    assert result["status"] == "ORDER_STILL_ACTIVE"
    assert broker.cancelled == []
    assert executor.state.load()["active_order_ticket"] == 111


def test_executor_cancel_stale_handles_no_active_order(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:00+00:00"
    )

    assert result["status"] == "NO_ACTIVE_ORDER"
    assert broker.cancelled == []


def test_executor_keeps_state_when_stale_cancel_fails(tmp_path):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 111, "symbol": "XAUUSD"}]
    broker.cancel_result = {"ok": False, "retcode": 10030, "comment": "not found"}

    def cancel_order(ticket):
        broker.cancelled.append(ticket)
        return broker.cancel_result

    broker.cancel_order = cancel_order
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "cancel_after_utc": "2026-05-27T14:00:00+00:00",
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:00+00:00"
    )

    assert result["status"] == "CANCEL_FAILED"
    assert broker.cancelled == [111]
    assert executor.state.load()["active_order_ticket"] == 111


def test_executor_moves_stop_to_break_even(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2453.0,
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.manage_open_positions(break_even_threshold_pips=20)

    assert result["status"] == "MANAGED"
    assert result["actions"][0]["action"] == "MOVE_TO_BREAK_EVEN"
    assert broker.modified_stops[0]["position_ticket"] == 333444
    assert broker.modified_stops[0]["stop_loss"] == 2450.0
    assert broker.modified_stops[0]["take_profit"] == 2456.0


def test_executor_does_not_move_stop_before_break_even_threshold(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2451.0,
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.manage_open_positions(break_even_threshold_pips=20)

    assert result["status"] == "NO_POSITION_ACTION"
    assert broker.modified_stops == []


def test_executor_moves_sell_stop_to_break_even(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 333445,
            "symbol": "XAUUSD",
            "side": "SELL",
            "entry_price": 2450.0,
            "stop_loss": 2456.0,
            "take_profit": 2444.0,
            "current_price": 2447.0,
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.manage_open_positions(break_even_threshold_pips=20)

    assert result["status"] == "MANAGED"
    assert broker.modified_stops[0]["position_ticket"] == 333445
    assert broker.modified_stops[0]["stop_loss"] == 2450.0


def test_executor_closes_scalp_profit_before_break_even(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777001,
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2451.6,
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            scalp_profit_points=1.5,
            break_even_trigger_points=1.0,
            break_even_lock_points=0.2,
        ),
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_CLOSED_SCALP"
    assert result["actions"][0]["reason"] == "SCALP_PROFIT_EXIT"
    assert broker.closed_positions[0][0]["ticket"] == 777001
    assert broker.closed_positions[0][1] == "TA scalp exit"
    assert broker.modified_stops == []


def test_executor_closes_early_adverse_position(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777002,
            "symbol": "XAUUSD",
            "side": "SELL",
            "entry_price": 2450.0,
            "stop_loss": 2454.0,
            "take_profit": 2444.0,
            "current_price": 2451.7,
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(early_loss_exit_points=1.5),
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_CLOSED_EARLY"
    assert result["actions"][0]["reason"] == "EARLY_LOSS_EXIT"
    assert broker.closed_positions[0][0]["ticket"] == 777002
    assert broker.closed_positions[0][1] == "TA early loss"
    assert broker.modified_stops == []


def test_executor_trails_stop_after_favorable_move(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777003,
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 2450.0,
            "stop_loss": 2450.2,
            "take_profit": 2458.0,
            "current_price": 2454.0,
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            break_even_trigger_points=1.0,
            break_even_lock_points=0.2,
            trailing_trigger_points=3.0,
            trailing_distance_points=1.2,
            min_stop_update_points=0.3,
        ),
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_STOP_MOVED"
    assert result["actions"][0]["reason"] == "TRAILING_STOP"
    assert broker.modified_stops[0]["position_ticket"] == 777003
    assert broker.modified_stops[0]["stop_loss"] == 2452.8
    assert broker.closed_positions == []


def test_full_fake_mt5_flow_places_cancels_and_manages(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    placed = executor.execute_proposal(_proposal())
    broker.pending_orders = [{"ticket": placed["order"], "symbol": "XAUUSD"}]
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": placed["order"],
            "cancel_after_utc": "2026-05-27T14:00:00+00:00",
        }
    )

    cancelled = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:00+00:00"
    )
    broker.pending_orders = []
    broker.positions = [
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2453.0,
        }
    ]
    managed = executor.manage_open_positions(break_even_threshold_pips=20)

    assert placed["status"] == "PLACED"
    assert cancelled["status"] == "CANCELLED"
    assert managed["status"] == "MANAGED"
    journal = tmp_path / "XAUUSD" / "execution_journal" / "mt5_events.jsonl"
    journal_text = journal.read_text(encoding="utf-8")
    assert "ORDER_PLACED" in journal_text
    assert "ORDER_CANCELLED" in journal_text
    assert "POSITION_STOP_MOVED" in journal_text
