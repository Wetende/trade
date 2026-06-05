from tradingagents.agents.schemas import OrderStatus, TradeAction
from tradingagents.agents.straddle_breakout import (
    StraddleBreakoutConfig,
    build_straddle_breakout_pair,
    simulate_straddle_pair_trigger,
)


def _candles():
    return [
        {
            "timestamp": "2026-06-04T12:00:00+00:00",
            "open": 4499.0,
            "high": 4500.0,
            "low": 4496.5,
            "close": 4498.0,
            "volume": 100,
        },
        {
            "timestamp": "2026-06-04T12:01:00+00:00",
            "open": 4498.0,
            "high": 4501.0,
            "low": 4497.0,
            "close": 4500.0,
            "volume": 100,
        },
        {
            "timestamp": "2026-06-04T12:02:00+00:00",
            "open": 4500.0,
            "high": 4502.0,
            "low": 4498.0,
            "close": 4501.0,
            "volume": 100,
        },
    ]


def _symbol_info():
    return {
        "name": "XAUUSD.vx",
        "digits": 2,
        "point": 0.01,
        "trade_tick_size": 0.01,
        "bid": 4499.80,
        "ask": 4500.10,
    }


def test_straddle_pair_uses_fixed_buy_and_sell_stop_geometry():
    config = StraddleBreakoutConfig(
        symbol="XAUUSD.vx",
        lookback_candles=3,
        entry_buffer_points=0.10,
        stop_distance_points=6.0,
        target_distance_points=9.0,
        activation_window_minutes=4,
        max_spread_points=0.50,
        min_box_points=1.0,
        max_box_points=8.0,
    )

    pair = build_straddle_breakout_pair(
        _candles(),
        _symbol_info(),
        config,
        now_utc="2026-06-04T12:03:00+00:00",
    )

    assert pair.status == "PROPOSED"
    assert pair.box["high"] == 4502.0
    assert pair.box["low"] == 4496.5
    assert pair.buy_stop is not None
    assert pair.sell_stop is not None
    assert pair.buy_stop.status == OrderStatus.PROPOSED
    assert pair.buy_stop.side == TradeAction.BUY
    assert pair.buy_stop.order_type == "BUY_STOP"
    assert pair.buy_stop.setup_name == "BuyStop Straddle"
    assert pair.buy_stop.strategy_type == "STRADDLE_BREAKOUT"
    assert pair.buy_stop.entry_price == 4502.10
    assert pair.buy_stop.stop_loss == 4496.10
    assert pair.buy_stop.take_profit == 4511.10
    assert pair.sell_stop.status == OrderStatus.PROPOSED
    assert pair.sell_stop.side == TradeAction.SELL
    assert pair.sell_stop.order_type == "SELL_STOP"
    assert pair.sell_stop.setup_name == "SellStop Straddle"
    assert pair.sell_stop.strategy_type == "STRADDLE_BREAKOUT"
    assert pair.sell_stop.entry_price == 4496.40
    assert pair.sell_stop.stop_loss == 4502.40
    assert pair.sell_stop.take_profit == 4487.40
    assert pair.buy_stop.cancel_if_not_triggered_after == "2026-06-04T12:07:00+00:00"


def test_straddle_pair_rejects_wide_spread():
    symbol_info = _symbol_info()
    symbol_info["ask"] = 4501.00
    config = StraddleBreakoutConfig(symbol="XAUUSD.vx", max_spread_points=0.25)

    pair = build_straddle_breakout_pair(_candles(), symbol_info, config)

    assert pair.status == "NO_TRADE"
    assert "spread" in pair.reason
    assert pair.buy_stop is None
    assert pair.sell_stop is None


def test_straddle_trigger_simulation_identifies_buy_sell_and_ambiguous_hits():
    pair = build_straddle_breakout_pair(
        _candles(),
        _symbol_info(),
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
    )

    buy = simulate_straddle_pair_trigger(pair, {"high": 4502.20, "low": 4499.0})
    sell = simulate_straddle_pair_trigger(pair, {"high": 4500.0, "low": 4496.20})
    ambiguous = simulate_straddle_pair_trigger(pair, {"high": 4502.20, "low": 4496.20})
    none = simulate_straddle_pair_trigger(pair, {"high": 4501.0, "low": 4497.0})

    assert buy["status"] == "BUY_TRIGGERED"
    assert sell["status"] == "SELL_TRIGGERED"
    assert ambiguous["status"] == "AMBIGUOUS_TRIGGER"
    assert none["status"] == "NO_TRIGGER"
