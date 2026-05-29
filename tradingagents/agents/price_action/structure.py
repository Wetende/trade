"""Higher-timeframe permission and M30 structure bias helpers."""

from __future__ import annotations

from typing import Any


def _allowed(direction: str) -> str:
    return f"{direction}_ALLOWED"


def _opposite(direction: str) -> str:
    return "SELL" if direction == "BUY" else "BUY"


def evaluate_higher_timeframe_permission(
    daily: str,
    h4: str,
    h1: str,
    planned_direction: str,
) -> dict[str, str]:
    """Evaluate whether daily, H4, and H1 structure permit a planned trade."""
    direction = str(planned_direction).strip().upper()
    daily_permission = str(daily).strip().upper()
    h4_permission = str(h4).strip().upper()
    h1_permission = str(h1).strip().upper()

    if daily_permission == _allowed(_opposite(direction)):
        return {"permission": "NO_TRADE", "reason": f"Daily blocks {direction}"}

    if h4_permission == _allowed(_opposite(direction)):
        return {"permission": "NO_TRADE", "reason": f"H4 blocks {direction}"}

    required_permission = _allowed(direction)
    if h1_permission != required_permission:
        return {"permission": "NO_TRADE", "reason": f"H1 must agree with {direction}"}

    return {"permission": required_permission, "reason": "Higher timeframes permit trade"}


def determine_m30_bias(breakouts: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer M30 bias from the first recorded breakout direction."""
    if not breakouts:
        return {"m30_bias": "UNCLEAR", "m30_context": "UNCLEAR"}

    breakout = breakouts[0]
    if not isinstance(breakout, dict):
        return {"m30_bias": "UNCLEAR", "m30_context": "UNCLEAR"}

    direction = str(breakout.get("direction", "")).strip().upper()
    if direction == "BUY":
        bias = "BULLISH"
    elif direction == "SELL":
        bias = "BEARISH"
    else:
        bias = "UNCLEAR"

    return {
        "m30_bias": bias,
        "m30_context": "BREAKOUT" if bias != "UNCLEAR" else "UNCLEAR",
        "m30_breakout": breakout,
    }
