"""Broker-agnostic local order lifecycle rules for the playbook."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from tradingagents.agents.price_action.models import PendingOrder
from tradingagents.agents.price_action.risk import gold_points_to_pips


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace(" ", "T"))


def _format(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def build_pending_order(
    symbol: str,
    side: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    candle_open: str,
    activation_window_minutes: int = 10,
) -> PendingOrder:
    opened = _parse(candle_open)
    expires = opened + timedelta(minutes=activation_window_minutes)
    return PendingOrder(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        candle_open=_format(opened),
        expires_at=_format(expires),
        status="PENDING",
    )


def trigger_pending_order(
    order: PendingOrder,
    current_time: str,
    high: float,
    low: float,
) -> PendingOrder:
    if order.status != "PENDING":
        return order
    if _parse(current_time) >= _parse(order.expires_at):
        return replace(order, status="CANCELLED")
    hit = low <= order.entry_price <= high
    return replace(order, status="TRIGGERED") if hit else order


def cancel_stale_order(order: PendingOrder, current_time: str) -> PendingOrder:
    if order.status == "PENDING" and _parse(current_time) >= _parse(order.expires_at):
        return replace(order, status="CANCELLED")
    return order


def move_stop_to_break_even(position: dict, threshold_pips: float) -> dict:
    side = str(position["side"]).strip().upper()
    if side not in {"BUY", "SELL"}:
        return {**position, "management_action": "HOLD_STOP"}
    entry = float(position["entry_price"])
    current_stop = float(position["stop_loss"])
    current = float(position["current_price"])
    moved_points = current - entry if side == "BUY" else entry - current
    if gold_points_to_pips(moved_points) < float(threshold_pips):
        return {**position, "management_action": "HOLD_STOP"}
    if side == "BUY" and current_stop >= entry:
        return {**position, "management_action": "HOLD_STOP"}
    if side == "SELL" and current_stop <= entry:
        return {**position, "management_action": "HOLD_STOP"}
    return {**position, "stop_loss": entry, "management_action": "MOVE_TO_BREAK_EVEN"}


def trail_stop_from_m15_structure(
    position: dict,
    m15_structure: list[dict],
    buffer_points: float,
) -> dict:
    side = str(position["side"]).strip().upper()
    if side not in {"BUY", "SELL"}:
        return {**position, "management_action": "HOLD_STOP"}
    current_stop = float(position["stop_loss"])
    if side == "BUY":
        higher_lows = [
            float(item["higher_low"]) for item in m15_structure if "higher_low" in item
        ]
        if not higher_lows:
            return {**position, "management_action": "HOLD_STOP"}
        new_stop = max(higher_lows) - float(buffer_points)
        if new_stop <= current_stop:
            return {**position, "management_action": "HOLD_STOP"}
        return {
            **position,
            "stop_loss": round(new_stop, 4),
            "management_action": "TRAIL_STOP",
        }

    lower_highs = [
        float(item["lower_high"]) for item in m15_structure if "lower_high" in item
    ]
    if not lower_highs:
        return {**position, "management_action": "HOLD_STOP"}
    new_stop = min(lower_highs) + float(buffer_points)
    if new_stop >= current_stop:
        return {**position, "management_action": "HOLD_STOP"}
    return {
        **position,
        "stop_loss": round(new_stop, 4),
        "management_action": "TRAIL_STOP",
    }


def should_exit_on_change_of_character(
    position: dict,
    m15_structure: list[dict],
    current_price: float,
) -> dict:
    side = str(position["side"]).strip().upper()
    if side not in {"BUY", "SELL"}:
        return {**position, "management_action": "HOLD_POSITION"}
    price = float(current_price)

    if side == "BUY":
        higher_lows = [
            float(item["higher_low"]) for item in m15_structure if "higher_low" in item
        ]
        if higher_lows and price < max(higher_lows):
            return {**position, "management_action": "EXIT_CHANGE_OF_CHARACTER"}
        return {**position, "management_action": "HOLD_POSITION"}

    lower_highs = [
        float(item["lower_high"]) for item in m15_structure if "lower_high" in item
    ]
    if lower_highs and price > min(lower_highs):
        return {**position, "management_action": "EXIT_CHANGE_OF_CHARACTER"}
    return {**position, "management_action": "HOLD_POSITION"}
