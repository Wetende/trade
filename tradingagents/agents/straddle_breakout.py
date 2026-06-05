"""Deterministic straddle breakout proposal builder."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction


@dataclass(frozen=True)
class StraddleBreakoutConfig:
    """Geometry and guardrails for a two-leg stop straddle."""

    symbol: str
    broker_symbol: str | None = None
    timeframe: str = "1m"
    confirmation_timeframe: str = "3m"
    lookback_candles: int = 3
    entry_buffer_points: float = 0.10
    stop_distance_points: float = 6.0
    target_distance_points: float = 9.0
    activation_window_minutes: int = 3
    max_spread_points: float = 0.50
    min_box_points: float = 0.50
    max_box_points: float = 8.0

    def __post_init__(self) -> None:
        if not self.symbol:
            raise ValueError("symbol is required")
        if int(self.lookback_candles) < 2:
            raise ValueError("lookback_candles must be at least 2")
        if int(self.activation_window_minutes) <= 0:
            raise ValueError("activation_window_minutes must be positive")
        object.__setattr__(self, "lookback_candles", int(self.lookback_candles))
        object.__setattr__(
            self, "activation_window_minutes", int(self.activation_window_minutes)
        )

        for name in (
            "entry_buffer_points",
            "stop_distance_points",
            "target_distance_points",
            "max_spread_points",
            "min_box_points",
            "max_box_points",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite non-negative number")
            if name in {"stop_distance_points", "target_distance_points"} and value <= 0:
                raise ValueError(f"{name} must be positive")
            object.__setattr__(self, name, value)
        if self.max_box_points and self.max_box_points < self.min_box_points:
            raise ValueError("max_box_points must be greater than min_box_points")


@dataclass(frozen=True)
class StraddlePairProposal:
    status: str
    reason: str
    symbol: str
    broker_symbol: str
    as_of: str
    box: dict[str, Any]
    buy_stop: OrderProposal | None = None
    sell_stop: OrderProposal | None = None

    def model_dump(self, mode: str = "python") -> dict[str, Any]:
        proposal_mode = "json" if mode == "json" else "python"
        return {
            "status": self.status,
            "reason": self.reason,
            "symbol": self.symbol,
            "broker_symbol": self.broker_symbol,
            "as_of": self.as_of,
            "box": dict(self.box),
            "buy_stop": (
                self.buy_stop.model_dump(mode=proposal_mode)
                if self.buy_stop is not None
                else None
            ),
            "sell_stop": (
                self.sell_stop.model_dump(mode=proposal_mode)
                if self.sell_stop is not None
                else None
            ),
        }


def build_straddle_breakout_pair(
    candles: list[dict[str, Any]],
    symbol_info: dict[str, Any],
    config: StraddleBreakoutConfig,
    now_utc: datetime | str | None = None,
) -> StraddlePairProposal:
    """Build a buy-stop/sell-stop breakout pair from recent candles."""

    current = _utc_datetime(now_utc)
    broker_symbol = config.broker_symbol or config.symbol
    ordered = sorted(candles, key=lambda candle: str(candle.get("timestamp") or ""))
    if len(ordered) < config.lookback_candles:
        return _no_trade(config, broker_symbol, current, "not enough candles")

    bid, ask = _quote(symbol_info)
    if bid is None or ask is None:
        return _no_trade(config, broker_symbol, current, "bid/ask quote is unavailable")
    spread = ask - bid
    if spread < 0:
        return _no_trade(config, broker_symbol, current, "invalid bid/ask quote")
    if spread > config.max_spread_points:
        return _no_trade(
            config,
            broker_symbol,
            current,
            f"spread {spread:.2f} exceeds max {config.max_spread_points:.2f}",
        )

    window = ordered[-config.lookback_candles :]
    try:
        box_high = max(_finite_price(candle["high"], "high") for candle in window)
        box_low = min(_finite_price(candle["low"], "low") for candle in window)
    except (KeyError, TypeError, ValueError) as exc:
        return _no_trade(config, broker_symbol, current, str(exc))

    box_range = box_high - box_low
    if box_range < config.min_box_points:
        return _no_trade(
            config,
            broker_symbol,
            current,
            f"box range {box_range:.2f} below minimum {config.min_box_points:.2f}",
            high=box_high,
            low=box_low,
            spread=spread,
        )
    if config.max_box_points and box_range > config.max_box_points:
        return _no_trade(
            config,
            broker_symbol,
            current,
            f"box range {box_range:.2f} exceeds maximum {config.max_box_points:.2f}",
            high=box_high,
            low=box_low,
            spread=spread,
        )

    buy_entry = _round_price(box_high + config.entry_buffer_points, symbol_info)
    sell_entry = _round_price(box_low - config.entry_buffer_points, symbol_info)
    if buy_entry <= ask:
        return _no_trade(
            config,
            broker_symbol,
            current,
            "buy stop entry is not above current ask",
            high=box_high,
            low=box_low,
            spread=spread,
        )
    if sell_entry >= bid:
        return _no_trade(
            config,
            broker_symbol,
            current,
            "sell stop entry is not below current bid",
            high=box_high,
            low=box_low,
            spread=spread,
        )

    cancel_after = current + timedelta(minutes=config.activation_window_minutes)
    valid_until = cancel_after.isoformat()
    box = {
        "high": _round_price(box_high, symbol_info),
        "low": _round_price(box_low, symbol_info),
        "range": _round_price(box_range, symbol_info),
        "lookback_candles": config.lookback_candles,
        "spread": _round_price(spread, symbol_info),
    }
    buy_stop = _proposal(
        config,
        broker_symbol,
        side=TradeAction.BUY,
        order_type="BUY_STOP",
        setup_name="BuyStop Straddle",
        entry=buy_entry,
        stop=buy_entry - config.stop_distance_points,
        target=buy_entry + config.target_distance_points,
        valid_until=valid_until,
    )
    sell_stop = _proposal(
        config,
        broker_symbol,
        side=TradeAction.SELL,
        order_type="SELL_STOP",
        setup_name="SellStop Straddle",
        entry=sell_entry,
        stop=sell_entry + config.stop_distance_points,
        target=sell_entry - config.target_distance_points,
        valid_until=valid_until,
    )

    return StraddlePairProposal(
        status="PROPOSED",
        reason=(
            f"{config.lookback_candles}-candle straddle breakout box: "
            f"high={box['high']}, low={box['low']}, range={box['range']}"
        ),
        symbol=config.symbol,
        broker_symbol=broker_symbol,
        as_of=current.isoformat(),
        box=box,
        buy_stop=buy_stop,
        sell_stop=sell_stop,
    )


def simulate_straddle_pair_trigger(
    pair: StraddlePairProposal,
    candle: dict[str, Any],
) -> dict[str, Any]:
    """Classify which pending leg would have triggered in one candle."""

    if pair.buy_stop is None or pair.sell_stop is None:
        return {"status": "NO_PAIR", "reason": pair.reason}
    high = _finite_price(candle.get("high"), "high")
    low = _finite_price(candle.get("low"), "low")
    buy_hit = high >= float(pair.buy_stop.entry_price)
    sell_hit = low <= float(pair.sell_stop.entry_price)
    if buy_hit and sell_hit:
        return {"status": "AMBIGUOUS_TRIGGER"}
    if buy_hit:
        return {"status": "BUY_TRIGGERED", "entry_price": pair.buy_stop.entry_price}
    if sell_hit:
        return {"status": "SELL_TRIGGERED", "entry_price": pair.sell_stop.entry_price}
    return {"status": "NO_TRIGGER"}


def _proposal(
    config: StraddleBreakoutConfig,
    broker_symbol: str,
    *,
    side: TradeAction,
    order_type: str,
    setup_name: str,
    entry: float,
    stop: float,
    target: float,
    valid_until: str,
) -> OrderProposal:
    return OrderProposal(
        symbol=config.symbol,
        broker_symbol=broker_symbol,
        side=side,
        order_type=order_type,
        setup_name=setup_name,
        strategy_type="STRADDLE_BREAKOUT",
        entry_price=round(float(entry), 2),
        stop_loss=round(float(stop), 2),
        take_profit=round(float(target), 2),
        timeframe=config.timeframe,
        confirmation_timeframe=config.confirmation_timeframe,
        valid_until=valid_until,
        activation_window_minutes=config.activation_window_minutes,
        cancel_if_not_triggered_after=valid_until,
        status=OrderStatus.PROPOSED,
        reason="Fixed-risk straddle breakout leg.",
    )


def _no_trade(
    config: StraddleBreakoutConfig,
    broker_symbol: str,
    current: datetime,
    reason: str,
    *,
    high: float | None = None,
    low: float | None = None,
    spread: float | None = None,
) -> StraddlePairProposal:
    box = {}
    if high is not None:
        box["high"] = high
    if low is not None:
        box["low"] = low
    if spread is not None:
        box["spread"] = spread
    return StraddlePairProposal(
        status="NO_TRADE",
        reason=reason,
        symbol=config.symbol,
        broker_symbol=broker_symbol,
        as_of=current.isoformat(),
        box=box,
    )


def _quote(symbol_info: dict[str, Any]) -> tuple[float | None, float | None]:
    try:
        bid = _finite_price(symbol_info.get("bid"), "bid")
        ask = _finite_price(symbol_info.get("ask"), "ask")
    except (TypeError, ValueError):
        return None, None
    return bid, ask


def _finite_price(value: Any, name: str) -> float:
    price = float(value)
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"{name} must be positive and finite")
    return price


def _round_price(value: float, symbol_info: dict[str, Any]) -> float:
    digits = int(symbol_info.get("digits") if symbol_info.get("digits") not in (None, "") else 2)
    tick_size = float(symbol_info.get("trade_tick_size") or 0)
    price = float(value)
    if tick_size > 0:
        price = round(price / tick_size) * tick_size
    return round(price, digits)


def _utc_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        current = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        current = value
    else:
        current = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)
