import math

import pytest

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.mt5 import MT5ConnectionConfig, MT5OrderRequestBuilder


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
        "comment": "TradingAgents demo",
        "type_time": "ORDER_TIME_GTC",
        "type_filling": "ORDER_FILLING_RETURN",
    }


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


def test_build_request_rejects_non_limit_proposal():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )
    proposal = _proposal()
    proposal.order_type = "MARKET"

    with pytest.raises(ValueError, match="LIMIT order proposals"):
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


def test_build_request_rejects_symbol_mismatch():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        )
    )
    proposal = _proposal()
    proposal.symbol = "EURUSD"

    with pytest.raises(ValueError, match="does not match"):
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
