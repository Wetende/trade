"""Dedicated deterministic entry model for closed one-minute candles."""

from __future__ import annotations

from dataclasses import asdict
from statistics import median
from typing import Any

from tradingagents.agents.price_action.candles import (
    candle_range,
    is_bearish,
    is_bullish,
    lower_wick,
    normalize_candles,
    upper_wick,
)
from tradingagents.agents.price_action.models import Candle, Zone
from tradingagents.agents.price_action.zones import zone_to_dict


PASS = "passed"
FAIL = "failed"
UNKNOWN = "unknown"

DEFAULT_FAST_HISTORY_WINDOW_CANDLES = 60
DEFAULT_FAST_MIN_TRIGGER_CANDLES = 3
DEFAULT_MAX_STOP_DISTANCE = 2.0
DEFAULT_BOOST_MAX_STOP_DISTANCE = 1.2
DEFAULT_RISK_REWARD = 1.5
MINIMUM_STOP_DISTANCE_BUFFER = 0.05

LOW_RESPECT_BUY = "LOW_RESPECT_BUY"
HIGH_RESPECT_SELL = "HIGH_RESPECT_SELL"
LOW_BREAK_SELL = "LOW_BREAK_SELL"
HIGH_BREAK_BUY = "HIGH_BREAK_BUY"
FAILED_LOW_BREAK_BUY = "FAILED_LOW_BREAK_BUY"
FAILED_HIGH_BREAK_SELL = "FAILED_HIGH_BREAK_SELL"

HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS = {
    LOW_RESPECT_BUY,
    HIGH_RESPECT_SELL,
    FAILED_LOW_BREAK_BUY,
    FAILED_HIGH_BREAK_SELL,
}


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _recent_tolerance(candles: list[Candle]) -> float:
    ranges = [candle_range(candle) for candle in candles if candle_range(candle) > 0]
    if not ranges:
        return 0.2
    return max(0.2, median(ranges) * 0.2)


def _cluster_levels_with_recency(
    prices: list[float],
    tolerance: float,
    *,
    minimum_touches: int = 2,
) -> list[dict[str, Any]]:
    levels: list[dict[str, Any]] = []
    for index, price in enumerate(prices):
        touches = [
            (touch_index, candidate)
            for touch_index, candidate in enumerate(prices)
            if abs(candidate - price) <= tolerance
        ]
        if len(touches) < minimum_touches:
            continue
        level = sum(candidate for _touch_index, candidate in touches) / len(touches)
        if any(abs(float(item["level"]) - level) <= tolerance for item in levels):
            continue
        touch_prices = [candidate for _touch_index, candidate in touches]
        levels.append(
            {
                "level": level,
                "touches": len(touches),
                "spread": max(touch_prices) - min(touch_prices),
                "first_touch_index": min(touch_index for touch_index, _price in touches),
                "last_touch_index": max(touch_index for touch_index, _price in touches),
                "seed_index": index,
            }
        )
    return levels


def _closest_prior_touch_level(
    prices: list[float],
    anchor: float,
    tolerance: float,
) -> dict[str, Any] | None:
    matches = [
        (index, price)
        for index, price in enumerate(prices)
        if abs(price - anchor) <= tolerance
    ]
    if not matches:
        return None
    level = sum(price for _index, price in matches) / len(matches)
    return {
        "level": level,
        "touches": len(matches) + 1,
        "spread": max(price for _index, price in matches + [(-1, anchor)])
        - min(price for _index, price in matches + [(-1, anchor)]),
        "first_touch_index": min(index for index, _price in matches),
        "last_touch_index": max(index for index, _price in matches),
    }


def _trigger(
    name: str,
    direction: str,
    level_type: str,
    level_info: dict[str, Any],
) -> dict[str, Any]:
    return {
        "name": name,
        "direction": direction,
        "level": float(level_info["level"]),
        "level_type": level_type,
        "touches": int(level_info["touches"]),
    }


def _select_break_level(
    levels: list[dict[str, Any]],
    *,
    anchor: float,
    predicate,
) -> dict[str, Any] | None:
    matches = [level for level in levels if predicate(float(level["level"]))]
    if not matches:
        return None
    return min(
        matches,
        key=lambda level: (
            abs(float(level["level"]) - anchor),
            -int(level["last_touch_index"]),
            float(level["spread"]),
        ),
    )


def _level_zone(
    *,
    level_type: str,
    level: float,
    tolerance: float,
    touches: int,
) -> Zone:
    half_width = max(0.01, min(tolerance, 0.25))
    low = round(level - half_width, 4)
    high = round(level + half_width, 4)
    return Zone(
        type=level_type,
        timeframe="1m",
        low=low,
        high=high,
        midpoint=round(level, 4),
        touches=touches,
        score=float(touches),
        source="one_minute_equal_level",
    )


def _bullish_rejection(candle: Candle) -> bool:
    total = candle_range(candle)
    if total <= 0 or not is_bullish(candle):
        return False
    close_position = (float(candle.close) - float(candle.low)) / total
    return close_position >= 0.65 and upper_wick(candle) <= max(total * 0.40, 0.05)


def _bearish_rejection(candle: Candle) -> bool:
    total = candle_range(candle)
    if total <= 0 or not is_bearish(candle):
        return False
    close_position = (float(candle.close) - float(candle.low)) / total
    return close_position <= 0.35 and lower_wick(candle) <= max(total * 0.40, 0.05)


def _detect_trigger(
    history: list[Candle],
    tolerance: float,
) -> dict[str, Any] | None:
    latest = history[-1]
    prior = history[:-1]
    prior_lows = [float(candle.low) for candle in prior]
    prior_highs = [float(candle.high) for candle in prior]
    equal_lows = _cluster_levels_with_recency(prior_lows, tolerance)
    equal_highs = _cluster_levels_with_recency(prior_highs, tolerance)
    touched_low = _closest_prior_touch_level(prior_lows, float(latest.low), tolerance)
    touched_high = _closest_prior_touch_level(prior_highs, float(latest.high), tolerance)
    break_margin = max(0.05, tolerance * 0.25)

    if touched_low is not None:
        level = float(touched_low["level"])
        if (
            float(latest.close) > level
            and _bullish_rejection(latest)
        ):
            return _trigger(LOW_RESPECT_BUY, "BUY", "support", touched_low)

    if touched_high is not None:
        level = float(touched_high["level"])
        if (
            float(latest.close) < level
            and _bearish_rejection(latest)
        ):
            return _trigger(HIGH_RESPECT_SELL, "SELL", "resistance", touched_high)

    failed_low = _select_break_level(
        equal_lows,
        anchor=float(latest.low),
        predicate=lambda level: float(latest.low) < level - break_margin
        and float(latest.close) > level,
    )
    if failed_low is not None and _bullish_rejection(latest):
        return _trigger(FAILED_LOW_BREAK_BUY, "BUY", "support", failed_low)

    failed_high = _select_break_level(
        equal_highs,
        anchor=float(latest.high),
        predicate=lambda level: float(latest.high) > level + break_margin
        and float(latest.close) < level,
    )
    if failed_high is not None and _bearish_rejection(latest):
        return _trigger(FAILED_HIGH_BREAK_SELL, "SELL", "resistance", failed_high)

    broken_low = _select_break_level(
        equal_lows,
        anchor=float(latest.close),
        predicate=lambda level: float(latest.close) < level - break_margin,
    )
    if broken_low is not None:
        return _trigger(LOW_BREAK_SELL, "SELL", "support", broken_low)

    broken_high = _select_break_level(
        equal_highs,
        anchor=float(latest.close),
        predicate=lambda level: float(latest.close) > level + break_margin,
    )
    if broken_high is not None:
        return _trigger(HIGH_BREAK_BUY, "BUY", "resistance", broken_high)

    return None


def _entry_price(trigger: dict[str, Any], latest: Candle) -> float:
    name = trigger["name"]
    level = float(trigger["level"])
    if name in {LOW_BREAK_SELL, HIGH_BREAK_BUY}:
        return float(latest.close)
    return level


def _risk_for_trigger(
    trigger: dict[str, Any],
    latest: Candle,
    *,
    tolerance: float,
    minimum_stop_distance: float,
    max_stop_distance: float,
    boost_max_stop_distance: float,
    risk_reward: float,
) -> dict[str, Any]:
    direction = trigger["direction"]
    level = float(trigger["level"])
    name = trigger["name"]
    entry = _entry_price(trigger, latest)
    stop_buffer = max(0.05, min(tolerance * 0.5, 0.25))
    if direction == "BUY":
        stop = level - stop_buffer
        if name == HIGH_BREAK_BUY:
            stop = level - stop_buffer
        reward_sign = 1
    else:
        stop = level + stop_buffer
        if name == LOW_BREAK_SELL:
            stop = level + stop_buffer
        reward_sign = -1

    risk_distance = abs(entry - stop)
    if minimum_stop_distance > 0 and risk_distance < minimum_stop_distance:
        risk_distance = minimum_stop_distance + MINIMUM_STOP_DISTANCE_BUFFER
        stop = entry - risk_distance if direction == "BUY" else entry + risk_distance
    if risk_distance <= 0:
        return {"approved": False, "reason": "Invalid stop distance"}
    if risk_distance > max_stop_distance:
        return {
            "approved": False,
            "reason": (
                "Stop distance exceeds one-minute maximum: "
                f"distance={risk_distance:.2f}, maximum={max_stop_distance:.2f}"
            ),
        }

    reward_distance = risk_distance * risk_reward
    take_profit = entry + (reward_distance * reward_sign)
    risk = {
        "approved": True,
        "entry_price": round(entry, 4),
        "stop_loss": round(stop, 4),
        "take_profit": round(take_profit, 4),
        "risk_distance": round(risk_distance, 4),
        "reward_distance": round(reward_distance, 4),
        "risk_reward": round(risk_reward, 2),
        "available_risk_reward": round(risk_reward, 2),
        "risk_model": "ONE_MINUTE_FAST_ENTRY",
        "microstructure_signal": name,
        "microstructure_confidence": (
            "HIGH" if name in HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS else "NORMAL"
        ),
        "fast_trigger_quality": {
            "trigger": name,
            "level": round(level, 4),
            "tolerance": round(tolerance, 4),
            "minimum_stop_distance": round(minimum_stop_distance, 4),
        },
        "position_lifecycle": "FAST_PARTIAL_SCALE",
        **_dynamic_fast_exit_settings(risk_distance),
    }
    if (
        name in HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS
        and risk_distance <= boost_max_stop_distance
    ):
        risk["volume_multiplier"] = 1.5
    return risk


def _dynamic_fast_exit_settings(risk_distance: float) -> dict[str, float]:
    break_even_trigger = max(0.4, min(1.2, risk_distance * 0.60))
    partial_first = max(break_even_trigger, min(1.5, risk_distance * 0.75))
    partial_second = max(partial_first + 0.1, min(2.5, risk_distance * 1.25))
    return {
        "break_even_trigger_points": round(break_even_trigger, 2),
        "break_even_lock_points": round(max(0.05, min(0.25, risk_distance * 0.12)), 2),
        "partial_first_trigger_points": round(partial_first, 2),
        "partial_first_target_volume": 1.0,
        "partial_second_trigger_points": round(partial_second, 2),
        "partial_second_target_volume": 0.4,
        "trailing_trigger_points": round(partial_second, 2),
        "trailing_distance_points": round(max(0.3, min(1.2, risk_distance * 0.40)), 2),
    }


def _setup_to_dict(
    trigger: dict[str, Any],
    latest: Candle,
    zone: Zone,
    risk: dict[str, Any],
) -> dict[str, Any]:
    setup = {
        "name": trigger["name"],
        "direction": trigger["direction"],
        "zone": zone_to_dict(zone),
        "entry_price": risk["entry_price"],
        "stop_loss": risk["stop_loss"],
        "confirmation_candle": asdict(latest),
        "setup_grade": "A_PLUS",
        "take_profit": risk["take_profit"],
        "risk_distance": risk["risk_distance"],
        "reward_distance": risk["reward_distance"],
        "risk_reward": risk["risk_reward"],
    }
    for key in (
        "volume_multiplier",
        "position_lifecycle",
        "microstructure_signal",
        "microstructure_confidence",
        "fast_trigger_quality",
        "break_even_trigger_points",
        "break_even_lock_points",
        "partial_first_trigger_points",
        "partial_first_target_volume",
        "partial_second_trigger_points",
        "partial_second_target_volume",
        "trailing_trigger_points",
        "trailing_distance_points",
    ):
        if key in risk:
            setup[key] = risk[key]
    return setup


def _base_checklist() -> dict[str, str]:
    return {
        "volume_time": UNKNOWN,
        "playbook_setup": FAIL,
        "timeframe_correlation": PASS,
        "entry_market_state_aligned": PASS,
        "confirmation_context_clear": PASS,
        "clean_range_to_fill": UNKNOWN,
        "candle_closed": PASS,
        "not_overextended": PASS,
        "not_last_15_of_4h": UNKNOWN,
        "not_15_min_before_open": UNKNOWN,
        "not_sunday_asian_session": UNKNOWN,
        "confirmation_candle_wicks": PASS,
        "trading_candle_stop_wick": PASS,
        "fast_trigger_quality": UNKNOWN,
        "not_activated_last_5_min": PASS,
    }


def _payload(
    symbol: str,
    as_of: str,
    *,
    status: str,
    recommendation: str,
    history: list[Candle],
    checklist: dict[str, str],
    market_context: dict[str, Any],
    setups: list[dict[str, Any]] | None = None,
    zones: list[Zone] | None = None,
    risk: dict[str, Any] | None = None,
    message: str = "",
) -> dict[str, Any]:
    if status == "SETUP_FOUND":
        decision_stage = "one_minute_setup_found"
    elif risk and risk.get("approved") is False:
        decision_stage = "one_minute_risk_rejected"
    else:
        decision_stage = "one_minute_no_trigger"
    return {
        "symbol": symbol.upper(),
        "as_of": as_of,
        "entry_profile": "fast",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "activation_window_minutes": market_context.get("activation_window_minutes"),
        "status": status,
        "recommendation": recommendation,
        "setups": setups or [],
        "zones": [zone_to_dict(zone) for zone in zones or []],
        "market_context": market_context,
        "checklist": checklist,
        "risk": risk or {},
        "message": message,
        "telemetry": {
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "decision_stage": decision_stage,
            "primary_hold_reason": message,
            "timeframe_rows": {"1m": len(history)},
            "zone_counts": {"1m": len(zones or [])},
            "market_state": {},
            "candidate_setup_count": len(setups or []),
            "approved_candidate_count": 1 if status == "SETUP_FOUND" else 0,
        },
    }


def analyze_one_minute_entry(
    symbol: str,
    as_of: str,
    timeframe_data: dict[str, Any],
    market_timezone: str = "America/New_York",
    session_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze the latest closed one-minute candle against recent equal levels."""
    del market_timezone
    config = session_config or {}
    history_window = _positive_int(
        config.get("fast_history_window_candles"),
        DEFAULT_FAST_HISTORY_WINDOW_CANDLES,
    )
    min_candles = _positive_int(
        config.get("fast_min_trigger_candles"),
        DEFAULT_FAST_MIN_TRIGGER_CANDLES,
    )
    max_stop_distance = _positive_float(
        config.get("fast_max_stop_distance_price"),
        DEFAULT_MAX_STOP_DISTANCE,
    )
    minimum_stop_distance = _positive_float(
        config.get("minimum_stop_distance_price"),
        0.0,
    )
    boost_max_stop_distance = _positive_float(
        config.get("fast_boost_max_stop_distance_price"),
        DEFAULT_BOOST_MAX_STOP_DISTANCE,
    )
    risk_reward = _positive_float(
        config.get("fast_risk_reward"),
        DEFAULT_RISK_REWARD,
    )
    activation_window_minutes = _positive_int(
        config.get("fast_activation_window_minutes"),
        6,
    )

    all_candles = normalize_candles(timeframe_data.get("1m"))
    history = all_candles[-history_window:]
    tolerance = _recent_tolerance(history)
    story = {
        "classification": "UNCLEAR",
        "history_candles": len(history),
        "history_window_candles": history_window,
        "min_trigger_candles": min_candles,
        "tolerance": round(tolerance, 4),
    }
    market_context = {
        "entry_profile": "fast",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "activation_window_minutes": activation_window_minutes,
        "one_minute_story": story,
        "fast_microstructure": {
            "enabled": True,
            "entry_timeframe": "1m",
            "window_timeframe": "1m",
            "history_window_candles": history_window,
            "evaluated_history_candles": len(history),
            "trigger_window_min_candles": min_candles,
            "trigger_selection": "cleanest_recent_story",
            "trigger_window_evaluated_candles": len(history),
            "rules": [
                LOW_RESPECT_BUY,
                HIGH_RESPECT_SELL,
                LOW_BREAK_SELL,
                HIGH_BREAK_BUY,
                FAILED_LOW_BREAK_BUY,
                FAILED_HIGH_BREAK_SELL,
            ],
        },
    }
    checklist = _base_checklist()

    if len(history) < min_candles:
        return _payload(
            symbol,
            as_of,
            status="NO_SETUP",
            recommendation="HOLD",
            history=history,
            checklist=checklist,
            market_context=market_context,
            message="Not enough closed 1m candles for the fast entry model.",
        )

    trigger = _detect_trigger(history, tolerance)
    if trigger is None:
        return _payload(
            symbol,
            as_of,
            status="NO_SETUP",
            recommendation="HOLD",
            history=history,
            checklist=checklist,
            market_context=market_context,
            message="No explicit one-minute trigger from the latest closed candle.",
        )

    latest = history[-1]
    risk = _risk_for_trigger(
        trigger,
        latest,
        tolerance=tolerance,
        minimum_stop_distance=minimum_stop_distance,
        max_stop_distance=max_stop_distance,
        boost_max_stop_distance=boost_max_stop_distance,
        risk_reward=risk_reward,
    )
    story.update(
        {
            "classification": trigger["name"],
            "direction": trigger["direction"],
            "level": round(float(trigger["level"]), 4),
            "trigger_candle": latest.timestamp,
        }
    )
    checklist["playbook_setup"] = PASS
    checklist["fast_trigger_quality"] = PASS
    checklist["clean_range_to_fill"] = PASS if risk.get("approved") else FAIL

    if not risk.get("approved"):
        return _payload(
            symbol,
            as_of,
            status="NO_SETUP",
            recommendation="HOLD",
            history=history,
            checklist=checklist,
            market_context=market_context,
            risk=risk,
            message=str(risk.get("reason") or "One-minute risk rejected."),
        )

    zone = _level_zone(
        level_type=trigger["level_type"],
        level=float(trigger["level"]),
        tolerance=tolerance,
        touches=int(trigger["touches"]),
    )
    setup = _setup_to_dict(trigger, latest, zone, risk)
    return _payload(
        symbol,
        as_of,
        status="SETUP_FOUND",
        recommendation=trigger["direction"],
        history=history,
        checklist=checklist,
        market_context=market_context,
        setups=[setup],
        zones=[zone],
        risk=risk,
        message=f"Explicit 1m trigger {trigger['name']} passed using the latest closed candle.",
    )


__all__ = [
    "HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS",
    "analyze_one_minute_entry",
]
