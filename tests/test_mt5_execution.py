import json
import math
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.mt5 import MT5ConnectionConfig, MT5OrderRequestBuilder
from tradingagents.brokers.mt5_execution import (
    MT5ExitManagementConfig,
    MT5OneMinuteLifecycleConfig,
    MT5Executor,
    build_pending_order_policy,
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


def _one_minute_proposal(
    *,
    reaction_type: str,
    trigger_name: str,
) -> OrderProposal:
    return _proposal().model_copy(
        update={
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "reaction_type": reaction_type,
            "trigger_name": trigger_name,
            "position_lifecycle": "FAST_PARTIAL_SCALE",
            "activation_window_minutes": 1,
        }
    )


def _context_one_minute_proposal(**opening_updates) -> OrderProposal:
    context = {
        "model_name": "One Minute Scalper",
        "direction": "BUY",
        "trigger": "LOW_RESPECT_BUY",
        "reaction_type": "respect",
        "confirmation_type": "rejection",
        "level": 2450.0,
        "level_side": "low",
        "level_type": "three_touch",
        "tolerance": 0.2,
        "touch_count": 3,
        "first_touch_timestamp": "2026-07-01T13:30:00+00:00",
        "last_touch_timestamp": "2026-07-01T13:58:00+00:00",
        "confirmation_timestamp": "2026-07-01T14:00:00+00:00",
    }
    context.update(opening_updates)
    proposal = _one_minute_proposal(
        reaction_type=str(context["reaction_type"]),
        trigger_name=str(context["trigger"]),
    )
    side = TradeAction(str(context["direction"]))
    price_update = (
        {}
        if side == TradeAction.BUY
        else {
            "entry_price": 2450.123,
            "stop_loss": 2452.123,
            "take_profit": 2447.123,
        }
    )
    return proposal.model_copy(
        update={
            **price_update,
            "side": side,
            "opening_context": context,
            "decision_quote": {
                "observed_at_utc": "2026-07-01T14:00:01+00:00",
                "bid": 2449.80,
                "ask": 2450.00,
                "spread_price": 0.20,
            },
        }
    )


def test_one_minute_reaction_pending_policy_expires_after_twenty_seconds():
    placed_at = datetime(2026, 6, 30, 14, 0, 10, tzinfo=timezone.utc)

    policy = build_pending_order_policy(
        _one_minute_proposal(
            reaction_type="fakeout",
            trigger_name="FAILED_HIGH_BREAK_SELL",
        ),
        placed_at,
        MT5OneMinuteLifecycleConfig(),
    )

    assert policy["policy"] == "ONE_MINUTE_REACTION"
    assert policy["max_age_seconds"] == 20.0
    assert policy["cancel_after_utc"] == "2026-06-30T14:00:30+00:00"


def test_one_minute_impulse_pending_policy_expires_after_forty_five_seconds():
    placed_at = datetime(2026, 6, 30, 14, 0, 10, tzinfo=timezone.utc)

    policy = build_pending_order_policy(
        _one_minute_proposal(
            reaction_type="impulse_break",
            trigger_name="CLEAN_HIGH_IMPULSE_BUY",
        ),
        placed_at,
        MT5OneMinuteLifecycleConfig(),
    )

    assert policy["policy"] == "ONE_MINUTE_IMPULSE"
    assert policy["max_age_seconds"] == 45.0
    assert policy["cancel_after_utc"] == "2026-06-30T14:00:55+00:00"


def test_one_minute_pending_policy_expires_before_next_candle_boundary():
    placed_at = datetime(2026, 6, 30, 14, 0, 30, tzinfo=timezone.utc)

    policy = build_pending_order_policy(
        _one_minute_proposal(
            reaction_type="impulse_break",
            trigger_name="CLEAN_HIGH_IMPULSE_BUY",
        ),
        placed_at,
        MT5OneMinuteLifecycleConfig(),
    )

    assert policy["policy"] == "ONE_MINUTE_IMPULSE"
    assert policy["cancel_after_utc"] == "2026-06-30T14:00:59+00:00"
    assert policy["candle_boundary_utc"] == "2026-06-30T14:01:00+00:00"


def test_executor_skips_one_minute_order_without_usable_submission_window(
    tmp_path,
):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor._now_utc = lambda: datetime(
        2026,
        7,
        1,
        14,
        0,
        59,
        500000,
        tzinfo=timezone.utc,
    )

    result = executor.execute_proposal(
        _one_minute_proposal(
            reaction_type="respect",
            trigger_name="HIGH_RESPECT_SELL",
        )
    )

    assert result["status"] == "SKIPPED_PENDING_WINDOW_EXPIRED"
    assert result["reason"] == "ONE_MINUTE_PENDING_WINDOW_EXPIRED"
    assert broker.checked_requests == []
    assert broker.placed_requests == []


def test_executor_rechecks_one_minute_window_after_broker_validation(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    times = iter(
        (
            datetime(2026, 7, 1, 14, 0, 30, tzinfo=timezone.utc),
            datetime(2026, 7, 1, 14, 0, 49, 500000, tzinfo=timezone.utc),
        )
    )
    executor._now_utc = lambda: next(times)

    result = executor.execute_proposal(
        _one_minute_proposal(
            reaction_type="respect",
            trigger_name="HIGH_RESPECT_SELL",
        )
    )

    assert result["status"] == "SKIPPED_PENDING_WINDOW_EXPIRED"
    assert len(broker.checked_requests) == 1
    assert broker.placed_requests == []


def test_executor_applies_effective_m1_policy_as_broker_expiration(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    fixed_now = datetime(2026, 7, 1, 14, 0, 10, tzinfo=timezone.utc)
    executor._now_utc = lambda: fixed_now

    result = executor.execute_proposal(
        _one_minute_proposal(
            reaction_type="respect",
            trigger_name="HIGH_RESPECT_SELL",
        )
    )

    request = broker.checked_requests[0]
    assert result["status"] == "PLACED"
    assert request["type_time"] == "ORDER_TIME_SPECIFIED"
    assert request["expiration"] == int(
        datetime.fromisoformat(
            result["pending_policy"]["cancel_after_utc"]
        ).timestamp()
    )


def test_executor_falls_back_to_gtc_when_broker_rejects_short_expiration(tmp_path):
    broker = FakeBroker()
    broker.place_results = [
        {
            "ok": False,
            "order": 0,
            "retcode": 10022,
            "comment": "Invalid expiration",
        },
        {
            "ok": True,
            "order": 111223,
            "retcode": 10009,
            "comment": "ok",
        },
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    fixed_now = datetime(2026, 7, 1, 14, 0, 10, tzinfo=timezone.utc)
    executor._now_utc = lambda: fixed_now

    result = executor.execute_proposal(
        _one_minute_proposal(
            reaction_type="respect",
            trigger_name="HIGH_RESPECT_SELL",
        )
    )

    assert result["status"] == "PLACED"
    assert result["expiration_fallback"] is True
    assert broker.placed_requests[0]["type_time"] == "ORDER_TIME_SPECIFIED"
    assert broker.placed_requests[1]["type_time"] == "ORDER_TIME_GTC"
    assert "expiration" not in broker.placed_requests[1]
    assert len(broker.checked_requests) == 2

    second_result = executor.execute_proposal(
        _one_minute_proposal(
            reaction_type="respect",
            trigger_name="LOW_RESPECT_BUY",
        )
    )

    assert second_result["status"] == "PLACED"
    assert broker.placed_requests[2]["type_time"] == "ORDER_TIME_GTC"
    assert "expiration" not in broker.placed_requests[2]


def test_executor_keeps_normal_order_time_policy(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(_proposal())

    assert result["status"] == "PLACED"
    assert broker.checked_requests[0]["type_time"] == "ORDER_TIME_GTC"
    assert "expiration" not in broker.checked_requests[0]


def test_normal_pending_policy_keeps_activation_window():
    placed_at = datetime(2026, 6, 30, 14, 0, 10, tzinfo=timezone.utc)

    policy = build_pending_order_policy(
        _proposal(),
        placed_at,
        MT5OneMinuteLifecycleConfig(),
    )

    assert policy["policy"] == "ACTIVATION_WINDOW"
    assert policy["max_age_seconds"] == 600.0
    assert policy["cancel_after_utc"] == "2026-06-30T14:10:10+00:00"


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


def test_build_request_uses_proposal_volume_multiplier():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        volume=1.0,
        deviation=20,
        magic=150015,
    )
    builder = MT5OrderRequestBuilder(config)
    proposal = _proposal().model_copy(update={"volume_multiplier": 1.5})
    symbol = {
        "name": "XAUUSD",
        "digits": 2,
        "point": 0.01,
        "trade_tick_size": 0.01,
    }

    request = builder.build_pending_limit_request(proposal, symbol)

    assert request["volume"] == 1.5


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


@pytest.mark.parametrize(
    ("side", "entry", "stop", "target", "expected_type"),
    [
        (TradeAction.BUY, 4507.40, 4506.60, 4508.60, "BUY_STOP"),
        (TradeAction.SELL, 4506.90, 4507.70, 4505.70, "SELL_STOP"),
    ],
)
def test_confirmed_reaction_uses_near_quote_continuation_pending_order(
    side,
    entry,
    stop,
    target,
    expected_type,
):
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        min_stop_spread_multiple=1.2,
    )
    builder = MT5OrderRequestBuilder(config)
    proposal = _one_minute_proposal(
        reaction_type="respect",
        trigger_name=(
            "LOW_RESPECT_BUY"
            if side == TradeAction.BUY
            else "HIGH_RESPECT_SELL"
        ),
    ).model_copy(
        update={
            "side": side,
            "order_type": "AUTO",
            "entry_price": entry,
            "stop_loss": stop,
            "take_profit": target,
        }
    )

    request = builder.build_pending_order_request(
        proposal,
        {
            "name": "XAUUSD",
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
            "trade_stops_level": 1,
            "bid": 4506.99,
            "ask": 4507.32,
        },
    )

    assert request["type"] == expected_type


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


def test_build_auto_reprices_buy_entry_inside_broker_stop_level():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.entry_price = 4507.50
    proposal.stop_loss = 4506.00
    proposal.take_profit = 4512.00

    request = builder.build_pending_order_request(
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

    assert request["type"] == "BUY_STOP"
    assert request["price"] == 4507.83
    assert request["sl"] == 4506.00
    assert request["tp"] == 4512.00


def test_build_auto_reprices_entry_inside_broker_stop_level_by_one_tick():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
            min_stop_spread_multiple=0.0,
        )
    )
    proposal = _proposal(TradeAction.SELL)
    proposal.order_type = "AUTO"
    proposal.entry_price = 4506.99
    proposal.stop_loss = 4508.00
    proposal.take_profit = 4504.00

    request = builder.build_pending_order_request(
        proposal,
        {
            "name": "XAUUSD",
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
            "trade_stops_level": 1,
            "bid": 4506.99,
            "ask": 4507.32,
        },
    )

    assert request["type"] == "SELL_STOP"
    assert request["price"] == 4506.97
    assert request["sl"] == 4508.00
    assert request["tp"] == 4504.00


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
        self.closed_rates = []
        self.closed_rate_calls = []
        self.checked_requests = []
        self.check_result = {"ok": True, "retcode": 10009, "comment": "check ok"}
        self.place_result = {
            "ok": True,
            "order": 111222,
            "retcode": 10009,
            "comment": "ok",
        }
        self.place_results = []
        self.close_result = None
        self.modify_result = None
        self.symbol_snapshots = []
        self.remove_position_on_close_failure = False

    def connect(self):
        return {
            "connected": True,
            "symbol": self.symbol_info,
            "account": {"login": 123456789, "trade_mode_label": "DEMO"},
        }

    def current_symbol_snapshot(self):
        if self.symbol_snapshots:
            return dict(self.symbol_snapshots.pop(0))
        bid = self.symbol_info.get("bid", 2449.80)
        ask = self.symbol_info.get("ask", 2450.10)
        return {
            "symbol": {
                **self.symbol_info,
                "bid": bid,
                "ask": ask,
                "spread_price": ask - bid,
            },
            "tick": {"time_utc": "2026-07-01T14:00:02+00:00"},
        }

    def open_orders(self, symbol):
        return [order for order in self.pending_orders if order.get("symbol") == symbol]

    def open_positions(self, symbol):
        return [
            position for position in self.positions if position.get("symbol") == symbol
        ]

    def place_pending_order(self, request):
        self.placed_requests.append(dict(request))
        if self.place_results:
            return dict(self.place_results.pop(0))
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
        return dict(
            self.modify_result
            or {"ok": True, "position": position_ticket, "retcode": 10009}
        )

    def close_position(
        self,
        position,
        *,
        comment="TradingAgents close",
        volume=None,
    ):
        self.closed_positions.append((dict(position), comment, volume))
        result = dict(
            self.close_result
            or {"ok": True, "position": position.get("ticket"), "retcode": 10009}
        )
        if self.remove_position_on_close_failure and not result.get("ok"):
            self.positions = []
        return result

    def history_deals(self, symbol, start_utc, end_utc):
        self.history_deals_calls.append((symbol, start_utc, end_utc))
        return list(self.history_deals_result)

    def fetch_closed_rates(self, timeframe, count):
        self.closed_rate_calls.append((timeframe, count))
        return list(self.closed_rates)


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


def test_executor_skips_identical_consumed_opening_after_restart(tmp_path):
    stable_state = tmp_path / "stable-state"
    first_broker = FakeBroker()
    first = MT5Executor(
        _config(),
        tmp_path / "session-one",
        broker=first_broker,
        state_dir=stable_state,
    )
    proposal = _context_one_minute_proposal()

    placed = first.execute_proposal(proposal)
    first.state.clear_trade()

    restarted_broker = FakeBroker()
    restarted = MT5Executor(
        _config(),
        tmp_path / "session-two",
        broker=restarted_broker,
        state_dir=stable_state,
    )
    skipped = restarted.execute_proposal(proposal)

    assert placed["status"] == "PLACED"
    assert skipped["status"] == "SKIPPED_STALE_OPENING"
    assert skipped["reason"] == "STALE_CONSUMED_OPENING"
    assert restarted_broker.checked_requests == []
    assert restarted_broker.placed_requests == []


@pytest.mark.parametrize(
    "opening_updates",
    [
        {"confirmation_timestamp": "2026-07-01T14:01:00+00:00"},
        {"last_touch_timestamp": "2026-07-01T13:59:00+00:00"},
        {"touch_count": 4},
        {"reaction_type": "fakeout", "trigger": "FAILED_LOW_BREAK_BUY"},
        {"direction": "SELL", "level_side": "high"},
        {"level": 2450.5},
    ],
)
def test_executor_allows_fresh_structural_evidence_after_consumption(
    tmp_path,
    opening_updates,
):
    stable_state = tmp_path / "stable-state"
    first = MT5Executor(
        _config(),
        tmp_path / "session-one",
        broker=FakeBroker(),
        state_dir=stable_state,
    )
    assert first.execute_proposal(_context_one_minute_proposal())["status"] == "PLACED"
    first.state.clear_trade()
    restarted_broker = FakeBroker()
    restarted = MT5Executor(
        _config(),
        tmp_path / "session-two",
        broker=restarted_broker,
        state_dir=stable_state,
    )

    result = restarted.execute_proposal(
        _context_one_minute_proposal(**opening_updates)
    )

    assert result["status"] == "PLACED"
    assert len(restarted_broker.placed_requests) == 1


def test_rejected_order_does_not_consume_opening(tmp_path):
    broker = FakeBroker()
    broker.place_result = {
        "ok": False,
        "order": None,
        "retcode": 10030,
        "comment": "invalid stops",
    }
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(_context_one_minute_proposal())

    assert result["status"] == "REJECTED"
    assert executor.state.load().get("consumed_openings") in (None, [])


def test_expired_order_remains_consumed_after_cancellation(tmp_path):
    stable_state = tmp_path / "stable-state"
    broker = FakeBroker()
    executor = MT5Executor(
        _config(),
        tmp_path / "session-one",
        broker=broker,
        state_dir=stable_state,
    )
    executor._now_utc = lambda: datetime(
        2026,
        7,
        1,
        14,
        0,
        5,
        tzinfo=timezone.utc,
    )
    proposal = _context_one_minute_proposal()
    placed = executor.execute_proposal(proposal)
    broker.pending_orders = [{"ticket": placed["order"], "symbol": "XAUUSD"}]

    cancelled = executor.cancel_stale_pending_orders(
        now_utc="2026-07-01T14:00:30+00:00"
    )

    assert cancelled["status"] == "CANCELLED"
    assert len(executor.state.load()["consumed_openings"]) == 1
    restarted = MT5Executor(
        _config(),
        tmp_path / "session-two",
        broker=FakeBroker(),
        state_dir=stable_state,
    )
    assert restarted.execute_proposal(proposal)["status"] == "SKIPPED_STALE_OPENING"


def test_executor_records_decision_and_pre_send_timeline(tmp_path):
    broker = FakeBroker()
    broker.symbol_snapshots = [
        {
            "symbol": {
                "name": "XAUUSD",
                "bid": 2449.79,
                "ask": 2450.09,
                "spread_price": 0.30,
            },
            "tick": {"time_utc": "2026-07-01T14:00:02+00:00"},
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor._now_utc = lambda: datetime(
        2026,
        7,
        1,
        14,
        0,
        3,
        tzinfo=timezone.utc,
    )
    timeline_times = iter(
        [
            datetime(2026, 7, 1, 14, 0, 3, tzinfo=timezone.utc),
            datetime(2026, 7, 1, 14, 0, 4, tzinfo=timezone.utc),
        ]
    )
    executor._timeline_now_utc = lambda: next(timeline_times)

    result = executor.execute_proposal(_context_one_minute_proposal())

    assert result["execution_timeline"] == {
        "decision_quote": {
            "observed_at_utc": "2026-07-01T14:00:01+00:00",
            "bid": 2449.80,
            "ask": 2450.00,
            "spread_price": 0.20,
        },
        "pre_send_quote": {
            "observed_at_utc": "2026-07-01T14:00:03+00:00",
            "tick_time_utc": "2026-07-01T14:00:02+00:00",
            "bid": 2449.79,
            "ask": 2450.09,
            "spread_price": 0.30,
        },
        "submitted_at_utc": "2026-07-01T14:00:03+00:00",
        "acknowledged_at_utc": "2026-07-01T14:00:04+00:00",
        "attempt": 1,
    }
    assert executor.state.load()["execution_timeline"] == result[
        "execution_timeline"
    ]


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
        "ORDER_EXECUTION_TIMELINE",
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


def test_executor_cancels_one_minute_pending_buy_when_next_candle_rejects(tmp_path):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 111, "symbol": "XAUUSD"}]
    broker.closed_rates = [
        {
            "timestamp": "2026-05-27T14:01:00+00:00",
            "open": 2451.20,
            "high": 2451.40,
            "low": 2450.70,
            "close": 2450.82,
        }
    ]
    proposal = _proposal(TradeAction.BUY).model_copy(
        update={
            "timeframe": "1m",
            "confirmation_timeframe": "60 candles",
            "trigger_name": "CLEAN_HIGH_IMPULSE_BUY",
            "position_lifecycle": "FAST_PARTIAL_SCALE",
            "activation_window_minutes": 10,
        }
    )
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "placed_at_utc": "2026-05-27T14:00:00+00:00",
            "cancel_after_utc": "2026-05-27T14:10:00+00:00",
            "proposal": proposal.model_dump(mode="json"),
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:30+00:00"
    )

    assert result["status"] == "CANCELLED"
    assert result["reason"] == "OPENING_INVALIDATED_BEARISH_CANDLE"
    assert result["ticket"] == 111
    assert broker.cancelled == [111]
    assert broker.closed_rate_calls == [("1m", 3)]
    assert executor.state.load()["active_order_ticket"] is None


def test_executor_cancels_one_minute_pending_sell_when_next_candle_rejects(tmp_path):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 111, "symbol": "XAUUSD"}]
    broker.closed_rates = [
        {
            "timestamp": "2026-05-27T14:01:00+00:00",
            "open": 2450.10,
            "high": 2450.88,
            "low": 2449.95,
            "close": 2450.80,
        }
    ]
    proposal = _proposal(TradeAction.SELL).model_copy(
        update={
            "timeframe": "1m",
            "confirmation_timeframe": "60 candles",
            "trigger_name": "CLEAN_LOW_IMPULSE_SELL",
            "position_lifecycle": "FAST_PARTIAL_SCALE",
            "activation_window_minutes": 10,
        }
    )
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "placed_at_utc": "2026-05-27T14:00:00+00:00",
            "cancel_after_utc": "2026-05-27T14:10:00+00:00",
            "proposal": proposal.model_dump(mode="json"),
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:30+00:00"
    )

    assert result["status"] == "CANCELLED"
    assert result["reason"] == "OPENING_INVALIDATED_BULLISH_CANDLE"
    assert result["ticket"] == 111
    assert broker.cancelled == [111]
    assert broker.closed_rate_calls == [("1m", 3)]
    assert executor.state.load()["active_order_ticket"] is None


def test_executor_keeps_one_minute_pending_when_next_candle_continues(tmp_path):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 111, "symbol": "XAUUSD"}]
    broker.closed_rates = [
        {
            "timestamp": "2026-05-27T14:01:00+00:00",
            "open": 2450.10,
            "high": 2451.05,
            "low": 2450.00,
            "close": 2450.94,
        }
    ]
    proposal = _proposal(TradeAction.BUY).model_copy(
        update={
            "timeframe": "1m",
            "confirmation_timeframe": "60 candles",
            "trigger_name": "CLEAN_HIGH_IMPULSE_BUY",
            "position_lifecycle": "FAST_PARTIAL_SCALE",
            "activation_window_minutes": 10,
        }
    )
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "placed_at_utc": "2026-05-27T14:00:00+00:00",
            "cancel_after_utc": "2026-05-27T14:10:00+00:00",
            "proposal": proposal.model_dump(mode="json"),
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:30+00:00"
    )

    assert result["status"] == "ORDER_STILL_ACTIVE"
    assert broker.cancelled == []
    assert broker.closed_rate_calls == [("1m", 3)]
    assert executor.state.load()["active_order_ticket"] == 111


def test_executor_cancels_one_minute_pending_when_any_post_placement_candle_rejects(
    tmp_path,
):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 111, "symbol": "XAUUSD"}]
    broker.closed_rates = [
        {
            "timestamp": "2026-05-27T14:01:00+00:00",
            "open": 2451.20,
            "high": 2451.40,
            "low": 2450.70,
            "close": 2450.82,
        },
        {
            "timestamp": "2026-05-27T14:02:00+00:00",
            "open": 2450.82,
            "high": 2451.08,
            "low": 2450.76,
            "close": 2451.02,
        },
    ]
    proposal = _proposal(TradeAction.BUY).model_copy(
        update={
            "timeframe": "1m",
            "confirmation_timeframe": "60 candles",
            "trigger_name": "CLEAN_HIGH_IMPULSE_BUY",
            "position_lifecycle": "FAST_PARTIAL_SCALE",
            "activation_window_minutes": 10,
        }
    )
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "placed_at_utc": "2026-05-27T14:00:00+00:00",
            "cancel_after_utc": "2026-05-27T14:10:00+00:00",
            "proposal": proposal.model_dump(mode="json"),
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:02:30+00:00"
    )

    assert result["status"] == "CANCELLED"
    assert result["reason"] == "OPENING_INVALIDATED_BEARISH_CANDLE"
    assert result["candle"]["timestamp"] == "2026-05-27T14:01:00+00:00"
    assert broker.cancelled == [111]
    assert executor.state.load()["active_order_ticket"] is None


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
    assert broker.closed_positions[0][2] is None
    assert broker.modified_stops == []


def test_executor_partially_closes_boosted_position_and_moves_stop_to_break_even(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777010,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.5,
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
            partial_first_trigger_points=1.5,
            partial_first_target_volume=1.0,
        ),
    )
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "proposal": _one_minute_proposal(
                reaction_type="respect",
                trigger_name="LOW_RESPECT_BUY",
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_PARTIALLY_CLOSED"
    assert result["actions"][0]["reason"] == "PARTIAL_1_AND_BREAK_EVEN"
    assert broker.closed_positions[0] == (
        dict(broker.positions[0]),
        "TA partial 1",
        0.5,
    )
    assert broker.modified_stops[0]["position_ticket"] == 777010
    assert broker.modified_stops[0]["stop_loss"] == 2450.2


def test_executor_uses_proposal_dynamic_partial_thresholds(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777013,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.5,
            "entry_price": 2450.0,
            "stop_loss": 2452.0,
            "take_profit": 2447.0,
            "current_price": 2448.9,
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            break_even_trigger_points=5.0,
            break_even_lock_points=0.0,
            partial_first_trigger_points=5.0,
            partial_first_target_volume=1.0,
        ),
    )
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "proposal": _one_minute_proposal(
                reaction_type="respect",
                trigger_name="HIGH_RESPECT_SELL",
            ).model_copy(
                update={
                    "side": TradeAction.SELL,
                    "break_even_trigger_points": 0.8,
                    "break_even_lock_points": 0.1,
                    "partial_first_trigger_points": 1.0,
                    "partial_first_target_volume": 1.0,
                }
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_PARTIALLY_CLOSED"
    assert result["actions"][0]["reason"] == "PARTIAL_1_AND_BREAK_EVEN"
    assert broker.closed_positions[0] == (
        dict(broker.positions[0]),
        "TA partial 1",
        0.5,
    )
    assert broker.modified_stops[0]["position_ticket"] == 777013
    assert broker.modified_stops[0]["stop_loss"] == 2449.9


def test_executor_first_partial_reduces_base_volume_to_half(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777022,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
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
            partial_first_trigger_points=1.5,
            partial_first_target_volume=1.0,
        ),
    )
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "proposal": _one_minute_proposal(
                reaction_type="respect",
                trigger_name="LOW_RESPECT_BUY",
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_PARTIALLY_CLOSED"
    assert result["actions"][0]["reason"] == "PARTIAL_1_AND_BREAK_EVEN"
    assert result["actions"][0]["remaining_volume"] == 0.5
    assert broker.closed_positions[0] == (
        dict(broker.positions[0]),
        "TA partial 1",
        0.5,
    )


def test_executor_does_not_repeat_first_partial_on_next_monitor_cycle(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777026,
            "identifier": 777026,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
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
            partial_first_trigger_points=1.5,
            partial_first_target_volume=1.0,
        ),
    )
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "proposal": _one_minute_proposal(
                reaction_type="respect",
                trigger_name="LOW_RESPECT_BUY",
            ).model_dump(mode="json"),
        }
    )

    first_result = executor.manage_open_positions()
    broker.positions[0]["volume"] = 0.5
    second_result = executor.manage_open_positions()

    assert first_result["status"] == "POSITION_PARTIALLY_CLOSED"
    assert second_result["status"] == "NO_POSITION_ACTION"
    assert len(broker.closed_positions) == 1


def test_executor_failed_partial_remains_retryable_and_does_not_move_stop(tmp_path):
    broker = FakeBroker()
    broker.close_result = {"ok": False, "retcode": 10030, "comment": "rejected"}
    broker.positions = [
        {
            "ticket": 777027,
            "identifier": 777027,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.5,
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2451.6,
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            break_even_trigger_points=1.0,
            break_even_lock_points=0.2,
            partial_first_trigger_points=1.5,
            partial_first_target_volume=1.0,
        ),
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_MANAGEMENT_FAILED"
    assert result["actions"][0]["action"] == "PARTIAL_CLOSE_FAILED"
    assert broker.modified_stops == []
    assert executor.state.load().get("partial_close_state") is None


def test_executor_failed_rejection_close_remains_retryable(tmp_path):
    broker = FakeBroker()
    broker.close_result = {"ok": False, "retcode": 10030, "comment": "rejected"}
    broker.positions = [
        {
            "ticket": 777028,
            "identifier": 777028,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2453.0,
            "take_profit": 2445.0,
            "current_price": 2450.4,
            "opened_at_utc": "2026-07-01T12:00:05+00:00",
            "comment": "TA|M1|FAST",
        }
    ]
    broker.closed_rates = [
        {
            "timestamp": "2026-07-01T12:00:00+00:00",
            "open": 2449.8,
            "high": 2450.7,
            "low": 2449.5,
            "close": 2450.5,
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_MANAGEMENT_FAILED"
    assert result["actions"][0]["action"] == "CLOSE_POSITION_FAILED"
    assert executor.state.load().get("rejection_exit_state") is None


def test_executor_failed_stop_update_reports_management_failure(tmp_path):
    broker = FakeBroker()
    broker.modify_result = {
        "ok": False,
        "retcode": 10016,
        "comment": "invalid stops",
    }
    broker.positions = [
        {
            "ticket": 777031,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2451.5,
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            break_even_trigger_points=1.0,
            break_even_lock_points=0.2,
        ),
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_MANAGEMENT_FAILED"
    assert result["actions"][0]["action"] == "MODIFY_STOP_FAILED"
    assert result["actions"][0]["reason"] == "BREAK_EVEN_FAILED"


def test_executor_fully_closes_unprotected_sell_on_closed_bullish_rejection_candle(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777014,
            "identifier": 777014,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.5,
            "entry_price": 2450.0,
            "stop_loss": 2453.0,
            "take_profit": 2445.0,
            "current_price": 2450.4,
        }
    ]
    broker.closed_rates = [
        {
            "timestamp": "2026-06-11T12:01:00+00:00",
            "open": 2449.8,
            "high": 2450.7,
            "low": 2449.5,
            "close": 2450.5,
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "placed_at_utc": "2026-06-11T12:00:10+00:00",
            "proposal": _proposal(TradeAction.SELL).model_copy(
                update={"timeframe": "1m", "position_lifecycle": "FAST_PARTIAL_SCALE"}
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_CLOSED_REJECTION"
    assert result["actions"][0]["action"] == "FULL_CLOSE"
    assert result["actions"][0]["reason"] == "CANDLE_REJECTION_FULL_EXIT_UNPROTECTED"
    assert broker.closed_positions[0] == (
        dict(broker.positions[0]),
        "TA candle rejection full",
        None,
    )
    state = executor.state.load()
    assert state["rejection_exit_state"]["777014"]["stage"] == "CLOSED"
    assert state["rejection_exit_state"]["777014"]["last_candle_timestamp"] == (
        "2026-06-11T12:01:00+00:00"
    )


def test_executor_uses_candle_close_time_for_first_rejection_after_entry(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777023,
            "identifier": 777023,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2453.0,
            "take_profit": 2445.0,
            "current_price": 2450.4,
            "opened_at_utc": "2026-07-01T12:00:05+00:00",
        }
    ]
    broker.closed_rates = [
        {
            "timestamp": "2026-07-01T12:00:00+00:00",
            "open": 2449.8,
            "high": 2450.7,
            "low": 2449.5,
            "close": 2450.5,
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "placed_at_utc": "2026-07-01T12:00:01+00:00",
            "proposal": _proposal(TradeAction.SELL).model_copy(
                update={"timeframe": "1m", "position_lifecycle": "FAST_PARTIAL_SCALE"}
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_CLOSED_REJECTION"
    assert result["actions"][0]["candle"]["timestamp"] == (
        "2026-07-01T12:00:00+00:00"
    )


def test_executor_ignores_candle_that_closed_before_position_opened(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777024,
            "identifier": 777024,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2453.0,
            "take_profit": 2445.0,
            "current_price": 2450.4,
            "opened_at_utc": "2026-07-01T12:01:01+00:00",
        }
    ]
    broker.closed_rates = [
        {
            "timestamp": "2026-07-01T12:00:00+00:00",
            "open": 2449.8,
            "high": 2450.7,
            "low": 2449.5,
            "close": 2450.5,
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "placed_at_utc": "2026-07-01T11:59:00+00:00",
            "proposal": _proposal(TradeAction.SELL).model_copy(
                update={"timeframe": "1m", "position_lifecycle": "FAST_PARTIAL_SCALE"}
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "NO_POSITION_ACTION"
    assert broker.closed_positions == []


def test_executor_closes_remaining_sell_on_second_closed_bullish_rejection_candle(
    tmp_path,
):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777015,
            "identifier": 777015,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 0.75,
            "entry_price": 2450.0,
            "stop_loss": 2453.0,
            "take_profit": 2445.0,
            "current_price": 2451.0,
        }
    ]
    broker.closed_rates = [
        {
            "timestamp": "2026-06-11T12:02:00+00:00",
            "open": 2450.2,
            "high": 2451.2,
            "low": 2450.1,
            "close": 2451.0,
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "placed_at_utc": "2026-06-11T12:00:10+00:00",
            "rejection_exit_state": {
                "777015": {
                    "stage": "PARTIAL",
                    "last_candle_timestamp": "2026-06-11T12:01:00+00:00",
                }
            },
            "proposal": _proposal(TradeAction.SELL).model_copy(
                update={"timeframe": "1m", "position_lifecycle": "FAST_PARTIAL_SCALE"}
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_CLOSED_REJECTION"
    assert result["actions"][0]["reason"] == "CANDLE_REJECTION_FULL_EXIT"
    assert broker.closed_positions[0] == (
        dict(broker.positions[0]),
        "TA candle rejection exit",
        None,
    )


def test_executor_partially_closes_and_protects_buy_on_profitable_rejection_candle(
    tmp_path,
):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777016,
            "identifier": 777016,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2450.6,
        }
    ]
    broker.closed_rates = [
        {
            "timestamp": "2026-06-11T12:01:00+00:00",
            "open": 2450.1,
            "high": 2450.2,
            "low": 2449.3,
            "close": 2449.5,
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            candle_rejection_exit_enabled=True,
            candle_rejection_partial_fraction=0.5,
            break_even_lock_points=0.09,
        ),
    )
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "placed_at_utc": "2026-06-11T12:00:10+00:00",
            "proposal": _proposal(TradeAction.BUY).model_copy(
                update={"timeframe": "1m", "position_lifecycle": "FAST_PARTIAL_SCALE"}
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_PARTIALLY_CLOSED"
    assert result["actions"][0]["reason"] == "CANDLE_REJECTION_PARTIAL_EXIT"
    assert result["actions"][1]["action"] == "MODIFY_STOP"
    assert result["actions"][1]["reason"] == "CANDLE_REJECTION_PROTECT_REMAINDER"
    assert result["actions"][1]["stop_loss"] == 2450.09
    assert broker.closed_positions[0] == (
        dict(broker.positions[0]),
        "TA candle rejection partial",
        0.5,
    )
    assert broker.modified_stops[0]["position_ticket"] == 777016
    assert broker.modified_stops[0]["stop_loss"] == 2450.09


def test_executor_ignores_rejection_candle_before_fast_order_was_placed(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777017,
            "identifier": 777017,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.5,
            "entry_price": 2450.0,
            "stop_loss": 2453.0,
            "take_profit": 2445.0,
            "current_price": 2450.4,
        }
    ]
    broker.closed_rates = [
        {
            "timestamp": "2026-06-11T11:59:00+00:00",
            "open": 2449.8,
            "high": 2450.7,
            "low": 2449.5,
            "close": 2450.5,
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "placed_at_utc": "2026-06-11T12:00:10+00:00",
            "proposal": _proposal(TradeAction.SELL).model_copy(
                update={"timeframe": "1m", "position_lifecycle": "FAST_PARTIAL_SCALE"}
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "NO_POSITION_ACTION"
    assert broker.closed_positions == []


def test_executor_second_partial_closes_to_runner_volume_and_trails_stop(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777011,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2450.2,
            "take_profit": 2456.0,
            "current_price": 2452.7,
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            trailing_trigger_points=2.5,
            trailing_distance_points=0.8,
            min_stop_update_points=0.2,
            partial_second_trigger_points=2.5,
            partial_second_target_volume=0.4,
        ),
    )
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "proposal": _one_minute_proposal(
                reaction_type="respect",
                trigger_name="LOW_RESPECT_BUY",
            ).model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_PARTIALLY_CLOSED"
    assert result["actions"][0]["reason"] == "PARTIAL_2_AND_TRAIL"
    assert broker.closed_positions[0] == (
        dict(broker.positions[0]),
        "TA partial 2",
        0.6,
    )
    assert broker.modified_stops[0]["position_ticket"] == 777011
    assert broker.modified_stops[0]["stop_loss"] == 2451.9


def test_executor_does_not_partial_close_base_position_without_partial_lifecycle(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777012,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2452.7,
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            break_even_trigger_points=0.0,
            partial_second_trigger_points=2.5,
            partial_second_target_volume=0.4,
        ),
    )

    result = executor.manage_open_positions()

    assert result["status"] == "NO_POSITION_ACTION"
    assert broker.closed_positions == []


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


def test_executor_one_minute_ignores_price_only_early_loss(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777021,
            "symbol": "XAUUSD",
            "side": "SELL",
            "entry_price": 2450.0,
            "stop_loss": 2454.0,
            "take_profit": 2444.0,
            "current_price": 2451.7,
        }
    ]
    proposal = _one_minute_proposal(
        reaction_type="impulse_break",
        trigger_name="CLEAN_LOW_IMPULSE_SELL",
    )
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(early_loss_exit_points=1.5),
    )
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "proposal": proposal.model_dump(mode="json"),
        }
    )

    result = executor.manage_open_positions()

    assert result["status"] == "NO_POSITION_ACTION"
    assert broker.closed_positions == []


def test_executor_m1_intrabar_exit_requires_two_consecutive_observations(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777032,
            "identifier": 777032,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2451.0,
            "take_profit": 2448.5,
            "current_price": 2450.7,
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "active_position_ticket": 777032,
            "proposal": _one_minute_proposal(
                reaction_type="respect",
                trigger_name="HIGH_RESPECT_SELL",
            ).model_copy(
                update={
                    "side": TradeAction.SELL,
                    "entry_price": 2450.0,
                    "stop_loss": 2451.0,
                    "take_profit": 2448.5,
                }
            ).model_dump(mode="json"),
        }
    )

    first = executor.manage_open_positions()
    second = executor.manage_open_positions()

    assert first["status"] == "NO_POSITION_ACTION"
    assert first["monitoring"][0]["intrabar_adverse_observations"] == 1
    assert second["status"] == "POSITION_CLOSED_EARLY"
    assert second["actions"][0]["reason"] == "INTRABAR_ADVERSE_EXIT"
    assert len(broker.closed_positions) == 1


def test_executor_m1_intrabar_exit_resets_after_price_recovers(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777033,
            "identifier": 777033,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2451.0,
            "take_profit": 2448.5,
            "current_price": 2450.7,
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    first = executor.manage_open_positions()
    broker.positions[0]["current_price"] = 2450.2
    recovered = executor.manage_open_positions()
    broker.positions[0]["current_price"] = 2450.7
    third = executor.manage_open_positions()

    assert first["monitoring"][0]["intrabar_adverse_observations"] == 1
    assert recovered["monitoring"][0]["intrabar_adverse_observations"] == 0
    assert third["monitoring"][0]["intrabar_adverse_observations"] == 1
    assert broker.closed_positions == []


def test_executor_reconciles_intrabar_close_when_position_already_gone(tmp_path):
    broker = FakeBroker()
    broker.close_result = {
        "ok": False,
        "retcode": 10013,
        "comment": "Invalid request",
    }
    broker.remove_position_on_close_failure = True
    broker.positions = [
        {
            "ticket": 777037,
            "identifier": 777037,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2451.0,
            "take_profit": 2448.5,
            "current_price": 2450.7,
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    executor.manage_open_positions()
    result = executor.manage_open_positions()

    assert result["status"] == "NO_POSITION_ACTION"
    assert result["actions"][0]["action"] == "NO_ACTION"
    assert result["actions"][0]["reason"] == "POSITION_ALREADY_CLOSED"
    journal = tmp_path / "XAUUSD" / "execution_journal" / "mt5_events.jsonl"
    event_types = [
        json.loads(line)["event_type"]
        for line in journal.read_text(encoding="utf-8").splitlines()
    ]
    assert "POSITION_CLOSE_RECONCILED" in event_types
    assert "POSITION_CLOSE_FAILED" not in event_types


def test_executor_reconciles_partial_when_position_already_gone(tmp_path):
    broker = FakeBroker()
    broker.close_result = {
        "ok": False,
        "retcode": 10036,
        "comment": "Position doesn't exist",
    }
    broker.remove_position_on_close_failure = True
    broker.positions = [
        {
            "ticket": 777038,
            "identifier": 777038,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2449.0,
            "take_profit": 2453.0,
            "current_price": 2450.7,
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            break_even_trigger_points=1.0,
            partial_first_trigger_points=0.5,
            partial_first_target_volume=0.5,
            scalp_profit_points=2.0,
        ),
    )

    result = executor.manage_open_positions()

    assert result["status"] == "NO_POSITION_ACTION"
    assert result["actions"][0]["action"] == "NO_ACTION"
    assert result["actions"][0]["reason"] == "POSITION_ALREADY_CLOSED"
    assert executor.state.load().get("partial_close_state") is None


def test_executor_keeps_intrabar_failure_when_position_remains_open(tmp_path):
    broker = FakeBroker()
    broker.close_result = {
        "ok": False,
        "retcode": 10013,
        "comment": "Invalid request",
    }
    broker.positions = [
        {
            "ticket": 777039,
            "identifier": 777039,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2451.0,
            "take_profit": 2448.5,
            "current_price": 2450.7,
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    executor.manage_open_positions()
    result = executor.manage_open_positions()

    assert result["status"] == "POSITION_MANAGEMENT_FAILED"
    assert result["actions"][0]["action"] == "CLOSE_POSITION_FAILED"
    assert result["actions"][0]["reason"] == "INTRABAR_ADVERSE_EXIT_FAILED"


def test_executor_position_monitoring_persists_mfe_mae_and_thresholds(tmp_path):
    broker = FakeBroker()
    broker.symbol_info.update({"bid": 2450.4, "ask": 2450.7})
    broker.positions = [
        {
            "ticket": 777034,
            "identifier": 777034,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2448.0,
            "take_profit": 2453.0,
            "current_price": 2450.4,
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            break_even_trigger_points=0.5,
            partial_first_trigger_points=0.7,
            partial_first_target_volume=1.0,
            scalp_profit_points=1.0,
        ),
    )

    first = executor.manage_open_positions()
    broker.positions[0]["current_price"] = 2449.7
    second = executor.manage_open_positions()

    assert first["monitoring"][0]["mfe_points"] == 0.4
    assert second["monitoring"][0]["mfe_points"] == 0.4
    assert second["monitoring"][0]["mae_points"] == -0.3
    assert second["monitoring"][0]["spread_points"] == 0.3
    assert second["monitoring"][0]["break_even_trigger_points"] == 0.5
    assert second["monitoring"][0]["intrabar_adverse_threshold_points"] == 1.3
    state = executor.state.load()["position_excursion_state"]["777034"]
    assert state["mfe_points"] == 0.4
    assert state["mae_points"] == -0.3


def test_executor_records_first_position_observation_once(tmp_path):
    broker = FakeBroker()
    broker.symbol_info.update({"bid": 2450.1, "ask": 2450.4})
    broker.positions = [
        {
            "ticket": 777036,
            "identifier": 777036,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2448.0,
            "take_profit": 2453.0,
            "current_price": 2450.1,
            "opened_at_utc": "2026-07-01T14:00:00+00:00",
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor._timeline_now_utc = lambda: datetime(
        2026,
        7,
        1,
        14,
        0,
        3,
        tzinfo=timezone.utc,
    )

    executor.manage_open_positions()
    executor.manage_open_positions()

    observation = executor.state.load()["position_first_observation"]["777036"]
    assert observation == {
        "position_id": "777036",
        "opened_at_utc": "2026-07-01T14:00:00+00:00",
        "entry_price": 2450.0,
        "observed_at_utc": "2026-07-01T14:00:03+00:00",
        "quote": {
            "observed_at_utc": "2026-07-01T14:00:03+00:00",
            "tick_time_utc": None,
            "bid": 2450.1,
            "ask": 2450.4,
            "spread_price": 0.3,
        },
        "fill_to_observation_seconds": 3.0,
    }
    journal = tmp_path / "XAUUSD" / "execution_journal" / "mt5_events.jsonl"
    event_types = [
        json.loads(line)["event_type"]
        for line in journal.read_text(encoding="utf-8").splitlines()
    ]
    assert event_types.count("POSITION_FIRST_OBSERVED") == 1


def test_executor_archives_excursion_and_merges_exact_exit_movement(tmp_path):
    broker = FakeBroker()
    broker.symbol_info.update({"bid": 2450.4, "ask": 2450.7})
    broker.positions = [
        {
            "ticket": 111222,
            "identifier": 111222,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2448.0,
            "take_profit": 2453.0,
            "current_price": 2450.4,
            "opened_at_utc": "2026-07-01T14:00:05+00:00",
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    proposal = _context_one_minute_proposal()
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": None,
            "active_position_ticket": 111222,
            "placed_at_utc": "2026-07-01T14:00:01+00:00",
            "proposal": proposal.model_dump(mode="json"),
            "execution_timeline": {
                "submitted_at_utc": "2026-07-01T14:00:01+00:00",
                "acknowledged_at_utc": "2026-07-01T14:00:02+00:00",
            },
        }
    )
    executor._timeline_now_utc = lambda: datetime(
        2026,
        7,
        1,
        14,
        0,
        6,
        tzinfo=timezone.utc,
    )
    executor.manage_open_positions()
    broker.positions = []

    executor.manage_open_positions()

    archived = executor.state.load()["completed_position_telemetry"]["111222"]
    assert archived["position_excursion"]["mfe_points"] == 0.4
    assert archived["position_excursion"]["mae_points"] == 0.0
    assert archived["execution_timeline"]["submitted_at_utc"] == (
        "2026-07-01T14:00:01+00:00"
    )

    broker.history_deals_result = [
        {
            "ticket": 1001,
            "order": 111222,
            "position_id": 111222,
            "symbol": "XAUUSD",
            "time": 1,
            "time_utc": "2026-07-01T14:00:05+00:00",
            "type": 0,
            "entry": 0,
            "volume": 1.0,
            "price": 2450.0,
            "profit": 0.0,
            "commission": 0.0,
            "swap": 0.0,
            "magic": 150015,
            "comment": "TA|M1|FAST",
        },
        {
            "ticket": 1002,
            "order": 111333,
            "position_id": 111222,
            "symbol": "XAUUSD",
            "time": 2,
            "time_utc": "2026-07-01T14:00:09+00:00",
            "type": 1,
            "entry": 1,
            "volume": 1.0,
            "price": 2449.5,
            "profit": -50.0,
            "commission": 0.0,
            "swap": 0.0,
            "magic": 150015,
            "comment": "[sl 2449.5]",
        },
    ]

    result = executor.reconcile_trade_history(
        now_utc=datetime(2026, 7, 1, 14, 1, tzinfo=timezone.utc)
    )
    trade = result["closed_trades"][0]
    assert trade["mfe_points"] == 0.4
    assert trade["mae_points"] == -0.5
    assert trade["excursion_source"] == "one_second_samples_plus_exit"
    assert trade["entry_drift"] == pytest.approx(-0.123)
    assert trade["order_wait_seconds"] == 4.0


def test_executor_normal_position_does_not_use_m1_intrabar_exit(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777035,
            "identifier": 777035,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2451.0,
            "take_profit": 2448.5,
            "current_price": 2450.8,
            "comment": "TradingAgents",
        }
    ]
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    executor.manage_open_positions()
    result = executor.manage_open_positions()

    assert result["status"] == "NO_POSITION_ACTION"
    assert broker.closed_positions == []


def test_executor_recovers_one_minute_lifecycle_from_broker_comment(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777025,
            "symbol": "XAUUSD",
            "side": "SELL",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2454.0,
            "take_profit": 2444.0,
            "current_price": 2451.7,
            "comment": "TA|M1|FAST",
        }
    ]
    executor = MT5Executor(
        _config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(early_loss_exit_points=1.5),
    )

    result = executor.manage_open_positions()

    assert result["status"] == "NO_POSITION_ACTION"
    assert broker.closed_positions == []


def test_executor_recovers_dynamic_m1_thresholds_from_stable_state(tmp_path):
    stable_state_dir = tmp_path / "stable-state"
    first_executor = MT5Executor(
        _config(),
        tmp_path / "session-one",
        broker=FakeBroker(),
        state_dir=stable_state_dir,
    )
    proposal = _one_minute_proposal(
        reaction_type="respect",
        trigger_name="LOW_RESPECT_BUY",
    ).model_copy(
        update={
            "partial_first_trigger_points": 0.5,
            "partial_first_target_volume": 1.0,
            "break_even_trigger_points": 0.4,
        }
    )
    first_executor.state.record_pending_order(
        777029,
        proposal,
        placed_at_utc=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    first_executor.state.mark_position_active(777029)

    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 777029,
            "identifier": 777029,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2449.0,
            "take_profit": 2453.0,
            "current_price": 2450.6,
            "comment": "TA|M1|FAST",
        }
    ]
    fresh_executor = MT5Executor(
        _config(),
        tmp_path / "session-two",
        broker=broker,
        state_dir=stable_state_dir,
        exit_management=MT5ExitManagementConfig(
            partial_first_trigger_points=1.5,
            partial_first_target_volume=1.0,
            break_even_trigger_points=1.2,
        ),
    )

    result = fresh_executor.manage_open_positions()

    assert result["status"] == "POSITION_PARTIALLY_CLOSED"
    assert result["actions"][0]["remaining_volume"] == 0.5


def test_executor_does_not_apply_stale_m1_state_to_unrelated_position(tmp_path):
    executor = MT5Executor(
        _config(),
        tmp_path / "session",
        broker=FakeBroker(),
        state_dir=tmp_path / "stable-state",
    )
    proposal = _one_minute_proposal(
        reaction_type="respect",
        trigger_name="LOW_RESPECT_BUY",
    ).model_copy(
        update={
            "partial_first_trigger_points": 0.5,
            "partial_first_target_volume": 1.0,
        }
    )
    executor.state.record_pending_order(
        777030,
        proposal,
        placed_at_utc=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
    )
    executor.state.mark_position_active(777030)
    executor.broker.positions = [
        {
            "ticket": 888030,
            "identifier": 888030,
            "symbol": "XAUUSD",
            "side": "BUY",
            "volume": 1.0,
            "entry_price": 2450.0,
            "stop_loss": 2449.0,
            "take_profit": 2453.0,
            "current_price": 2450.6,
            "comment": "manual trade",
        }
    ]

    result = executor.manage_open_positions()

    assert result["status"] == "NO_POSITION_ACTION"
    assert executor.broker.closed_positions == []


def test_executor_namespaces_stable_state_by_mt5_account(tmp_path):
    first_config = _config()
    second_config = replace(
        first_config,
        login=987654321,
        expected_login=987654321,
        server="Other-Demo",
        expected_server="Other-Demo",
    )

    first = MT5Executor(
        first_config,
        tmp_path / "session-one",
        broker=FakeBroker(),
        state_dir=tmp_path / "stable-state",
    )
    second = MT5Executor(
        second_config,
        tmp_path / "session-two",
        broker=FakeBroker(),
        state_dir=tmp_path / "stable-state",
    )

    assert first.state.path != second.state.path
    assert str(first_config.login) in str(first.state.path)
    assert str(second_config.login) in str(second.state.path)


def test_executor_tags_one_minute_order_for_restart_safe_management(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor._now_utc = lambda: datetime(
        2026,
        7,
        1,
        14,
        0,
        10,
        tzinfo=timezone.utc,
    )

    result = executor.execute_proposal(
        _one_minute_proposal(
            reaction_type="impulse_break",
            trigger_name="CLEAN_LOW_IMPULSE_SELL",
        )
    )

    assert result["status"] == "PLACED"
    assert broker.placed_requests[0]["comment"] == "TA|M1|FAST"


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
