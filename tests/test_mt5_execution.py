import json
from pathlib import Path

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

    assert request["symbol"] == "XAUUSD"
    assert request["volume"] == 0.01
    assert request["price"] == 2450.12
    assert request["sl"] == 2447.99
    assert request["tp"] == 2456.79
    assert request["deviation"] == 20
    assert request["magic"] == 150015
    assert request["comment"] == "TradingAgents demo"


def test_build_request_rejects_no_trade_proposal():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
    )
    builder = MT5OrderRequestBuilder(config)
    proposal = _proposal()
    proposal.status = OrderStatus.NO_TRADE

    try:
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})
    except ValueError as exc:
        assert "PROPOSED" in str(exc)
    else:
        raise AssertionError("expected request builder to reject NO_TRADE")


def test_build_sell_limit_request_maps_side():
    builder = MT5OrderRequestBuilder(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
        )
    )

    request = builder.build_pending_limit_request(_proposal(TradeAction.SELL), {"digits": 2})

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

    try:
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})
    except ValueError as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("expected request builder to reject symbol mismatch")


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

    try:
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})
    except ValueError as exc:
        assert "entry_price, stop_loss, and take_profit" in str(exc)
    else:
        raise AssertionError("expected request builder to reject missing levels")

