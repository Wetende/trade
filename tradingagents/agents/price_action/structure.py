"""Higher-timeframe structure, permission, and M30 bias helpers."""

from __future__ import annotations

from typing import Any

from tradingagents.agents.price_action.models import Candle, Zone


STRUCTURE_CLASSIFICATIONS = {
    "BULLISH_STRUCTURE",
    "BEARISH_STRUCTURE",
    "RANGE",
    "NEAR_MAJOR_SUPPORT",
    "NEAR_MAJOR_RESISTANCE",
    "BREAK_OF_STRUCTURE_UP",
    "BREAK_OF_STRUCTURE_DOWN",
    "UNCLEAR",
}


def _allowed(direction: str) -> str:
    return f"{direction}_ALLOWED"


def _opposite(direction: str) -> str:
    return "SELL" if direction == "BUY" else "BUY"


def _permission_value(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("permission", "NEUTRAL")
    return str(value).strip().upper()


def _classification_value(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("classification", "UNCLEAR")
    return str(value).strip().upper()


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candle_value(candle: Candle | dict[str, Any], field: str) -> float:
    if isinstance(candle, dict):
        return _as_float(candle.get(field))
    return _as_float(getattr(candle, field, 0.0))


def _zone_value(zone: Zone | dict[str, Any], field: str) -> Any:
    if isinstance(zone, dict):
        return zone.get(field)
    return getattr(zone, field, None)


def _permission_for_classification(classification: str) -> str:
    if classification in {"BULLISH_STRUCTURE", "BREAK_OF_STRUCTURE_UP"}:
        return "BUY_ALLOWED"
    if classification in {"BEARISH_STRUCTURE", "BREAK_OF_STRUCTURE_DOWN"}:
        return "SELL_ALLOWED"
    return "NEUTRAL"


def _near_major_zone(
    latest: Candle | dict[str, Any],
    zones: list[Zone | dict[str, Any]],
    zone_type: str,
) -> bool:
    close = _candle_value(latest, "close")
    low = _candle_value(latest, "low")
    high = _candle_value(latest, "high")

    for zone in zones:
        if str(_zone_value(zone, "type")).strip().lower() != zone_type:
            continue
        zone_low = _as_float(_zone_value(zone, "low"))
        zone_high = _as_float(_zone_value(zone, "high"))
        width = max(zone_high - zone_low, 0.0)
        tolerance = max(width * 3, abs(close) * 0.002)
        if low <= zone_high + tolerance and high >= zone_low - tolerance:
            return True
    return False


def _recent_structure_direction(candles: list[Candle | dict[str, Any]]) -> str:
    if len(candles) < 3:
        return "UNCLEAR"

    recent = candles[-5:]
    highs = [_candle_value(candle, "high") for candle in recent]
    lows = [_candle_value(candle, "low") for candle in recent]
    closes = [_candle_value(candle, "close") for candle in recent]
    if len(recent) == 3:
        if highs[-1] > highs[0] and lows[-1] > lows[0] and closes[-1] > closes[0]:
            return "BULLISH_STRUCTURE"
        if highs[-1] < highs[0] and lows[-1] < lows[0] and closes[-1] < closes[0]:
            return "BEARISH_STRUCTURE"
        return "RANGE"

    first_high_zone = max(highs[:2])
    last_high_zone = max(highs[-2:])
    first_low_zone = min(lows[:2])
    last_low_zone = min(lows[-2:])
    close_change = closes[-1] - closes[0]

    higher_highs = highs[-1] > highs[0] and last_high_zone > first_high_zone
    higher_lows = lows[-1] > lows[0] and last_low_zone > first_low_zone
    lower_highs = highs[-1] < highs[0] and last_high_zone < first_high_zone
    lower_lows = lows[-1] < lows[0] and last_low_zone < first_low_zone

    if higher_highs and higher_lows:
        return "BULLISH_STRUCTURE"
    if lower_highs and lower_lows:
        return "BEARISH_STRUCTURE"
    if closes[-1] > first_high_zone and close_change > 0:
        return "BREAK_OF_STRUCTURE_UP"
    if closes[-1] < first_low_zone and close_change < 0:
        return "BREAK_OF_STRUCTURE_DOWN"

    total_range = max(highs) - min(lows)
    if total_range > 0 and abs(close_change) <= total_range * 0.25:
        return "RANGE"
    return "UNCLEAR"


def classify_timeframe_structure(
    candles: list[Candle | dict[str, Any]],
    zones: list[Zone | dict[str, Any]],
    timeframe: str,
) -> dict[str, Any]:
    """Classify a timeframe with structure labels closer to the playbook."""
    timeframe_label = str(timeframe).strip() or "unknown"
    if not candles:
        return {
            "timeframe": timeframe_label,
            "classification": "UNCLEAR",
            "permission": "NEUTRAL",
            "reason": f"{timeframe_label} has no closed candles",
            "latest_close": None,
        }

    latest = candles[-1]
    latest_close = _candle_value(latest, "close")
    if _near_major_zone(latest, zones, "support"):
        classification = "NEAR_MAJOR_SUPPORT"
    elif _near_major_zone(latest, zones, "resistance"):
        classification = "NEAR_MAJOR_RESISTANCE"
    else:
        classification = _recent_structure_direction(candles)

    permission = _permission_for_classification(classification)
    return {
        "timeframe": timeframe_label,
        "classification": classification,
        "permission": permission,
        "reason": f"{timeframe_label} structure is {classification}",
        "latest_close": latest_close,
    }


def _zone_blocks_direction(classification: str, direction: str) -> bool:
    return (direction == "BUY" and classification == "NEAR_MAJOR_RESISTANCE") or (
        direction == "SELL" and classification == "NEAR_MAJOR_SUPPORT"
    )


def evaluate_higher_timeframe_permission(
    daily: Any,
    h4: Any,
    h1: Any,
    planned_direction: str,
) -> dict[str, str]:
    """Evaluate whether daily, H4, and H1 structure permit a planned trade."""
    direction = str(planned_direction).strip().upper()
    daily_permission = _permission_value(daily)
    h4_permission = _permission_value(h4)
    h1_permission = _permission_value(h1)
    daily_classification = _classification_value(daily)
    h4_classification = _classification_value(h4)

    if daily_permission == _allowed(_opposite(direction)):
        return {"permission": "NO_TRADE", "reason": f"Daily blocks {direction}"}

    if _zone_blocks_direction(daily_classification, direction):
        return {"permission": "NO_TRADE", "reason": f"Daily danger zone blocks {direction}"}

    if h4_permission == _allowed(_opposite(direction)):
        return {"permission": "NO_TRADE", "reason": f"H4 blocks {direction}"}

    if _zone_blocks_direction(h4_classification, direction):
        return {"permission": "NO_TRADE", "reason": f"H4 danger zone blocks {direction}"}

    required_permission = _allowed(direction)
    if h1_permission != required_permission:
        return {"permission": "NO_TRADE", "reason": f"1H must agree with {direction}"}

    return {"permission": required_permission, "reason": f"Higher timeframes permit {direction}"}


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
