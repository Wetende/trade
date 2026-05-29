"""Local backtest metrics for price-action simulation runs."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from typing import Any

from tradingagents.agents.price_action.candles import normalize_candles
from tradingagents.agents.price_action.engine import analyze_playbook


def _average(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0.0


def _counter(values: list[str]) -> dict[str, int]:
    return dict(Counter(value for value in values if value))


def summarize_backtest(trades: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [trade for trade in trades if float(trade["result_r"]) > 0]
    losses = [trade for trade in trades if float(trade["result_r"]) <= 0]
    trade_count = len(trades)
    win_rate = round((len(wins) / trade_count) * 100, 2) if trade_count else 0.0
    win_r = [float(trade["result_r"]) for trade in wins]
    loss_r = [float(trade["result_r"]) for trade in losses]
    all_r = [float(trade["result_r"]) for trade in trades]

    return {
        "trade_count": trade_count,
        "win_rate": win_rate,
        "average_win_r": _average(win_r),
        "average_loss_r": _average(loss_r),
        "net_r": round(sum(all_r), 2),
        "max_win_r": round(max(all_r), 2) if all_r else 0.0,
        "max_loss_r": round(min(all_r), 2) if all_r else 0.0,
        "by_setup": _counter([str(trade.get("setup", "")) for trade in trades]),
        "by_session": _counter([str(trade.get("session", "")) for trade in trades]),
        "by_zone_timeframe": _counter(
            [str(trade.get("zone_timeframe", "")) for trade in trades]
        ),
    }


def _trade_outcome(setup: dict[str, Any], future_candles: Any) -> dict[str, Any]:
    candles = normalize_candles(future_candles)
    if not candles:
        return {"status": "CANCELLED", "result_r": None}

    side = str(setup["direction"]).strip().upper()
    entry = float(setup["entry_price"])
    stop = float(setup["stop_loss"])
    take_profit = float(setup["take_profit"])
    risk = abs(entry - stop)
    if side not in {"BUY", "SELL"} or risk <= 0:
        return {"status": "INVALID", "result_r": None}

    first = candles[0]
    if not (first.low <= entry <= first.high):
        return {"status": "CANCELLED", "result_r": None}

    for candle in candles:
        if side == "BUY":
            hit_stop = candle.low <= stop
            hit_target = candle.high >= take_profit
        else:
            hit_stop = candle.high >= stop
            hit_target = candle.low <= take_profit

        # Conservative OHLC replay: if both are touched inside the same candle,
        # count the stop first because intrabar sequence is unknown.
        if hit_stop:
            return {"status": "STOP_LOSS", "result_r": -1.0}
        if hit_target:
            return {
                "status": "TAKE_PROFIT",
                "result_r": round(abs(take_profit - entry) / risk, 2),
            }

    return {"status": "OPEN", "result_r": 0.0}


def replay_backtest(
    symbol: str,
    snapshots: list[dict[str, Any]],
    *,
    analyzer: Callable[..., dict[str, Any]] = analyze_playbook,
    market_timezone: str = "America/New_York",
    session_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Replay saved historical snapshots through the deterministic engine.

    Each snapshot should contain `as_of`, `timeframe_data`, and future M15
    candles under `future_15m` or `future_candles`. The first future candle is
    used as the 10-minute limit-order activation proxy; if the entry is not
    touched there, the local order is treated as cancelled.
    """
    trades: list[dict[str, Any]] = []
    signals = 0
    cancelled_orders = 0

    for snapshot in snapshots:
        payload = analyzer(
            symbol,
            snapshot["as_of"],
            snapshot.get("timeframe_data", {}),
            market_timezone=market_timezone,
            session_config=session_config,
        )
        if payload.get("status") != "SETUP_FOUND" or not payload.get("setups"):
            continue

        signals += 1
        setup = payload["setups"][0]
        outcome = _trade_outcome(
            setup,
            snapshot.get("future_15m", snapshot.get("future_candles", [])),
        )
        if outcome["status"] == "CANCELLED":
            cancelled_orders += 1
            continue
        if outcome["result_r"] is None:
            continue

        zone = setup.get("zone", {})
        trades.append(
            {
                "symbol": symbol.upper(),
                "as_of": snapshot["as_of"],
                "setup": setup.get("name", "Unknown Setup"),
                "direction": setup.get("direction"),
                "session": snapshot.get("session", "unknown"),
                "zone_timeframe": zone.get("timeframe", "unknown"),
                "status": outcome["status"],
                "result_r": outcome["result_r"],
            }
        )

    return {
        "symbol": symbol.upper(),
        "evaluated_snapshots": len(snapshots),
        "signals": signals,
        "cancelled_orders": cancelled_orders,
        "trades": trades,
        "summary": summarize_backtest(trades),
    }
