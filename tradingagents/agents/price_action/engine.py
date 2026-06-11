"""Deterministic M30/M15 price-action analysis engine."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from tradingagents.agents.price_action.candles import (
    candle_range,
    is_bearish,
    is_bullish,
    lower_wick,
    normalize_candles,
    upper_wick,
    wick_ratio,
)
from tradingagents.agents.price_action.models import Candle, Setup, Zone
from tradingagents.agents.price_action.risk import approve_risk
from tradingagents.agents.price_action.sessions import evaluate_time_filters
from tradingagents.agents.price_action.setups import (
    detect_break_and_retest,
    detect_breakouts,
    detect_sr_bounce,
)
from tradingagents.agents.price_action.structure import (
    classify_market_state,
    classify_timeframe_structure,
    determine_m30_bias,
    evaluate_higher_timeframe_permission,
)
from tradingagents.agents.price_action.zones import (
    calculate_support_resistance,
    classify_range,
    nearest_target_zone,
    zone_to_dict,
)


PASS = "passed"
FAIL = "failed"
UNKNOWN = "unknown"
FAST_MICRO_SETUP_NAMES = {"Aggressive Respect", "Confirmed Break"}
DEFAULT_FAST_HISTORY_WINDOW_CANDLES = 60
DEFAULT_FAST_MIN_TRIGGER_CANDLES = 3
DEFAULT_FAST_MAX_TRIGGER_CANDLES = 10


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _base_checklist(time_checks: dict[str, str]) -> dict[str, str]:
    return {
        "volume_time": time_checks.get("volume_time", UNKNOWN),
        "playbook_setup": FAIL,
        "timeframe_correlation": UNKNOWN,
        "entry_market_state_aligned": UNKNOWN,
        "confirmation_context_clear": UNKNOWN,
        "clean_range_to_fill": UNKNOWN,
        "candle_closed": UNKNOWN,
        "not_overextended": UNKNOWN,
        "not_last_15_of_4h": time_checks.get("not_last_15_of_4h", UNKNOWN),
        "not_15_min_before_open": time_checks.get("not_15_min_before_open", UNKNOWN),
        "not_sunday_asian_session": time_checks.get("not_sunday_asian_session", UNKNOWN),
        "confirmation_candle_wicks": UNKNOWN,
        "trading_candle_stop_wick": UNKNOWN,
        "fast_trigger_quality": PASS,
        "not_activated_last_5_min": PASS,
    }


def _payload(
    symbol: str,
    as_of: str,
    status: str,
    recommendation: str,
    checklist: dict[str, str],
    zones: list[Zone],
    market_context: dict[str, Any],
    setups: list[dict[str, Any]] | None = None,
    risk: dict[str, Any] | None = None,
    message: str = "",
    telemetry: dict[str, Any] | None = None,
    entry_profile: str | None = None,
    timeframe: str | None = None,
    confirmation_timeframe: str | None = None,
    activation_window_minutes: int | None = None,
) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "as_of": as_of,
        "entry_profile": entry_profile or market_context.get("entry_profile", "normal"),
        "timeframe": timeframe or market_context.get("timeframe", "15m"),
        "confirmation_timeframe": confirmation_timeframe
        or market_context.get("confirmation_timeframe", "30m"),
        "activation_window_minutes": activation_window_minutes
        if activation_window_minutes is not None
        else market_context.get("activation_window_minutes"),
        "status": status,
        "recommendation": recommendation,
        "setups": setups or [],
        "zones": [zone_to_dict(zone) for zone in zones],
        "market_context": market_context,
        "checklist": checklist,
        "risk": risk or {},
        "message": message,
        "telemetry": telemetry or {},
    }


_TIMEFRAME_ORDER = ("1d", "4h", "1h", "30m", "15m", "3m", "1m")


def _ordered_timeframes(keys) -> list[str]:
    available = {str(key) for key in keys}
    ordered = [tf for tf in _TIMEFRAME_ORDER if tf in available]
    ordered.extend(sorted(available - set(ordered)))
    return ordered


def _rows_by_timeframe(candles_by_tf: dict[str, list[Candle]]) -> dict[str, int]:
    return {tf: len(candles_by_tf.get(tf, [])) for tf in _ordered_timeframes(candles_by_tf)}


def _zone_counts(zones_by_tf: dict[str, list[Zone]]) -> dict[str, int]:
    return {tf: len(zones_by_tf.get(tf, [])) for tf in _ordered_timeframes(zones_by_tf)}


def _entry_reference_zones(
    zones_by_tf: dict[str, list[Zone]],
    zone_timeframes: tuple[str, ...],
) -> list[Zone]:
    zones: list[Zone] = []
    for timeframe in zone_timeframes:
        zones.extend(zones_by_tf.get(timeframe, []))
    return sorted(zones, key=lambda zone: zone.score, reverse=True)


def _direction_from_context(context: dict[str, Any]) -> str | None:
    bias = str(context.get("m30_bias") or "").strip().upper()
    if bias == "BULLISH":
        return "BUY"
    if bias == "BEARISH":
        return "SELL"
    return None


def _timeframe_context(
    timeframe: str,
    candles: list[Candle],
    zones: list[Zone],
) -> dict[str, Any]:
    breakouts = detect_breakouts(candles, zones)
    context = determine_m30_bias([_setup_to_dict(setup) for setup in breakouts])
    context["source_timeframe"] = timeframe
    if _direction_from_context(context) is not None:
        return context

    rejections = detect_sr_bounce(candles, zones)
    if not rejections:
        market_state = classify_market_state(candles, zones, timeframe)
        direction = _direction_from_bias(market_state.get("direction"))
        if direction is None:
            context["market_state"] = market_state
            return context
        return {
            "m30_bias": "BULLISH" if direction == "BUY" else "BEARISH",
            "m30_context": "STRUCTURE",
            "m30_structure": market_state,
            "source_timeframe": timeframe,
        }
    rejected = rejections[0]
    return {
        "m30_bias": "BULLISH" if rejected.direction == "BUY" else "BEARISH",
        "m30_context": "REJECTION",
        "m30_rejection": _setup_to_dict(rejected),
        "source_timeframe": timeframe,
    }


def _governing_context(
    candles_by_tf: dict[str, list[Candle]],
    zones_by_tf: dict[str, list[Zone]],
    governing_timeframes: tuple[str, ...],
) -> dict[str, Any]:
    contexts = [
        _timeframe_context(
            timeframe,
            candles_by_tf.get(timeframe, []),
            zones_by_tf.get(timeframe, []),
        )
        for timeframe in governing_timeframes
    ]
    clear = [
        (timeframe, context, _direction_from_context(context))
        for timeframe, context in zip(governing_timeframes, contexts)
        if _direction_from_context(context) is not None
    ]
    directions = {direction for _timeframe, _context, direction in clear}
    if not directions:
        return {
            "m30_bias": "UNCLEAR",
            "m30_context": "UNCLEAR",
            "governing_contexts": contexts,
        }
    if len(directions) > 1:
        return {
            "m30_bias": "UNCLEAR",
            "m30_context": "CONFLICT",
            "governing_contexts": contexts,
        }

    _timeframe, selected, _direction = clear[0]
    return {
        **selected,
        "governing_contexts": contexts,
    }


def _telemetry(
    *,
    decision_stage: str,
    primary_hold_reason: str,
    candles_by_tf: dict[str, list[Candle]],
    zones_by_tf: dict[str, list[Zone]],
    market_context: dict[str, Any],
    candidate_setups: list[Setup] | None = None,
    candidate_evaluations: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    evaluations = candidate_evaluations or []
    return {
        "entry_profile": market_context.get("entry_profile", "normal"),
        "timeframe": market_context.get("timeframe", "15m"),
        "confirmation_timeframe": market_context.get("confirmation_timeframe", "30m"),
        "decision_stage": decision_stage,
        "primary_hold_reason": primary_hold_reason,
        "timeframe_rows": _rows_by_timeframe(candles_by_tf),
        "zone_counts": _zone_counts(zones_by_tf),
        "permissions": {
            "daily": market_context.get("daily_permission"),
            "h4": market_context.get("h4_permission"),
            "h1": market_context.get("h1_permission"),
            "higher_timeframe": market_context.get("higher_timeframe_permission"),
        },
        "structures": {
            "daily": market_context.get("daily_structure"),
            "h4": market_context.get("h4_structure"),
            "h1": market_context.get("h1_structure"),
        },
        "m30_context": {
            "bias": market_context.get("m30_bias"),
            "context": market_context.get("m30_context"),
        },
        "market_state": market_context.get("market_state", {}),
        "candidate_setup_count": len(candidate_setups or []),
        "approved_candidate_count": sum(1 for item in evaluations if item.get("approved")),
        "candidate_evaluations": evaluations,
    }


def _is_overextended(candles: list[Candle], limit: int = 10) -> bool:
    if len(candles) < 2:
        return False
    previous = candles[-(limit + 1) : -1]
    if not previous:
        return False
    average = sum(candle_range(candle) for candle in previous) / len(previous)
    return average > 0 and candle_range(candles[-1]) > average * 1.5


def _has_top_and_bottom_wick(candle: Candle) -> bool:
    body_top = max(candle.open, candle.close)
    body_bottom = min(candle.open, candle.close)
    return candle.high > body_top and candle.low < body_bottom


def _has_stop_wick(candle: Candle, direction: str) -> bool:
    if direction == "BUY":
        return candle.low < min(candle.open, candle.close)
    return candle.high > max(candle.open, candle.close)


def _close_location(candle: Candle) -> float:
    span = candle_range(candle)
    if span <= 0:
        return 0.5
    return (float(candle.close) - float(candle.low)) / span


def _body_ratio(candle: Candle) -> float:
    span = candle_range(candle)
    if span <= 0:
        return 0.0
    return abs(float(candle.close) - float(candle.open)) / span


def _fast_micro_signal(setup: Setup) -> str:
    source = str(setup.zone.source or "").strip().lower()
    if source in {
        "fast_microstructure_respected_low",
        "fast_microstructure_confirmed_lows",
    }:
        return "TWO_LOWS_RESPECT_BUY"
    if source in {
        "fast_microstructure_respected_high",
        "fast_microstructure_confirmed_highs",
    }:
        return "TWO_HIGHS_RESPECT_SELL"
    if source == "fast_microstructure_failed_lows":
        return "TWO_LOWS_FAILED_SELL"
    if source == "fast_microstructure_failed_highs":
        return "TWO_HIGHS_FAILED_BUY"
    return f"ONE_MINUTE_{setup.direction}_SETUP"


def _fast_trigger_quality(setup: Setup) -> tuple[bool, str | None, dict[str, Any]]:
    candle = setup.confirmation_candle
    span = candle_range(candle)
    metrics = {
        "microstructure_signal": _fast_micro_signal(setup),
        "close_location": round(_close_location(candle), 4),
        "body_ratio": round(_body_ratio(candle), 4),
        "upper_wick_ratio": round(wick_ratio(candle, "upper"), 4),
        "lower_wick_ratio": round(wick_ratio(candle, "lower"), 4),
    }
    if span <= 0:
        return False, "1m trigger candle has no range. Default to HOLD.", metrics

    close_location = metrics["close_location"]
    body = metrics["body_ratio"]
    upper_rejection = metrics["upper_wick_ratio"]
    lower_rejection = metrics["lower_wick_ratio"]

    if setup.direction == "BUY":
        if not is_bullish(candle):
            return (
                False,
                "1m trigger candle rejected the BUY direction with a bearish close. Default to HOLD.",
                metrics,
            )
        if close_location < 0.6 or upper_rejection > 0.35:
            return (
                False,
                "1m trigger candle rejected the BUY direction near the candle high. Default to HOLD.",
                metrics,
            )
    else:
        if not is_bearish(candle):
            return (
                False,
                "1m trigger candle rejected the SELL direction with a bullish close. Default to HOLD.",
                metrics,
            )
        if close_location > 0.4 or lower_rejection > 0.35:
            return (
                False,
                "1m trigger candle rejected the SELL direction near the candle low. Default to HOLD.",
                metrics,
            )

    if body < 0.15:
        return (
            False,
            "1m trigger candle body is too weak for a fast entry. Default to HOLD.",
            metrics,
        )
    return True, None, metrics


def _fast_micro_confidence(setup: Setup, quality: dict[str, Any]) -> str:
    strong_buy_close = (
        setup.direction == "BUY" and quality.get("close_location", 0.0) >= 0.75
    )
    strong_sell_close = (
        setup.direction == "SELL" and quality.get("close_location", 1.0) <= 0.25
    )
    clean_rejection = (
        quality.get("upper_wick_ratio", 1.0) <= 0.25
        if setup.direction == "BUY"
        else quality.get("lower_wick_ratio", 1.0) <= 0.25
    )
    meaningful_body = quality.get("body_ratio", 0.0) >= 0.20
    repeated_level = int(setup.zone.touches or 0) >= 2
    if (
        repeated_level
        and meaningful_body
        and clean_rejection
        and (strong_buy_close or strong_sell_close)
    ):
        return "HIGH"
    return "NORMAL"


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
    setup: Setup,
    risk: dict[str, Any] | None = None,
    setup_grade: str | None = None,
) -> dict[str, Any]:
    result = asdict(setup)
    result["zone"] = zone_to_dict(setup.zone)
    if setup.confirmation_candle is not None:
        result["confirmation_candle"] = asdict(setup.confirmation_candle)
    if setup_grade:
        result["setup_grade"] = setup_grade
    if risk and risk.get("approved"):
        result.update(
            {
                "take_profit": risk["take_profit"],
                "risk_distance": risk["risk_distance"],
                "reward_distance": risk["reward_distance"],
                "risk_reward": risk["risk_reward"],
            }
        )
        for key in (
            "volume",
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
                result[key] = risk[key]
    return result


def _setup_identity(setup: Setup) -> tuple[Any, ...]:
    zone = setup.zone
    candle = setup.confirmation_candle
    return (
        setup.name,
        setup.direction,
        zone.type,
        zone.timeframe,
        round(float(zone.low), 4),
        round(float(zone.high), 4),
        round(float(setup.entry_price), 4),
        round(float(setup.stop_loss), 4),
        candle.timestamp if candle else None,
    )


def _unique_setups(setups: list[Setup]) -> list[Setup]:
    unique: list[Setup] = []
    seen: set[tuple[Any, ...]] = set()
    for setup in setups:
        identity = _setup_identity(setup)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(setup)
    return unique


def _candidate_rejection_reason(
    checklist: dict[str, str],
    risk: dict[str, Any],
    failed_rules: list[str],
) -> str | None:
    if not failed_rules:
        return None
    if "entry_market_state_aligned" in failed_rules:
        return "The entry market state opposes the setup direction. Default to HOLD."
    if "timeframe_correlation" in failed_rules and checklist.get(
        "timeframe_correlation_reason"
    ):
        return str(checklist["timeframe_correlation_reason"])
    if "confirmation_context_clear" in failed_rules:
        return "The confirmation context is unclear. Default to HOLD."
    if "fast_trigger_quality" in failed_rules and checklist.get(
        "fast_trigger_quality_reason"
    ):
        return str(checklist["fast_trigger_quality_reason"])
    if checklist.get("clean_range_to_fill") == FAIL and risk.get("reason"):
        return str(risk["reason"])
    return "Required checklist rules failed: " + ", ".join(failed_rules)


def _risk_reward_value(risk: dict[str, Any]) -> float:
    value = risk.get("available_risk_reward", risk.get("risk_reward", -1))
    try:
        return float(value)
    except (TypeError, ValueError):
        return -1.0


def _timeframe_priority(timeframe: str | None) -> int:
    normalized = str(timeframe or "").strip().lower()
    return {
        "1m": 7,
        "m1": 7,
        "3m": 6,
        "m3": 6,
        "15m": 5,
        "m15": 5,
        "30m": 4,
        "m30": 4,
        "1h": 3,
        "h1": 3,
        "4h": 2,
        "1d": 1,
        "daily": 1,
    }.get(normalized, 0)


def _normalize_setup_grade(value: Any) -> str:
    normalized = str(value or "").strip().upper()
    if normalized == "B_PLUS":
        return "B_PLUS"
    return "A_PLUS"


def _setup_grade_rank(value: Any) -> int:
    return {
        "REJECTED": 0,
        "B_PLUS": 1,
        "A_PLUS": 2,
    }.get(str(value or "").strip().upper(), 0)


def _display_timeframe(timeframe: str) -> str:
    normalized = str(timeframe or "").strip().lower()
    if normalized.endswith("m") and normalized[:-1].isdigit():
        return f"M{normalized[:-1]}"
    if normalized.endswith("h") and normalized[:-1].isdigit():
        return f"H{normalized[:-1]}"
    return str(timeframe or "").upper()


def _direction_from_bias(value: Any) -> str | None:
    normalized = str(value or "").strip().upper()
    if normalized in {"BUY", "BULLISH"}:
        return "BUY"
    if normalized in {"SELL", "BEARISH"}:
        return "SELL"
    return None


def _is_fast_profile(profile_name: str, entry_timeframe: str) -> bool:
    return (
        str(profile_name).strip().lower() == "fast"
        and str(entry_timeframe).strip().lower() in {"1m", "m1"}
    )


def _clear_fast_window_direction(market_state: dict[str, Any]) -> str | None:
    direction = _direction_from_bias(market_state.get("direction"))
    if direction is None:
        return None
    try:
        rows = int(market_state.get("rows") or 0)
    except (TypeError, ValueError):
        rows = 0
    trend_state = str(market_state.get("trend_state") or "").strip().upper()
    if rows < 4 or trend_state not in {"TRENDING", "EXPANDING"}:
        return None
    return direction


def _micro_tolerance(candles: list[Candle]) -> float:
    recent = candles[-12:] if len(candles) > 12 else candles
    ranges = [candle_range(candle) for candle in recent if candle_range(candle) > 0]
    if not ranges:
        return 0.2
    ranges = sorted(ranges)
    median = ranges[len(ranges) // 2]
    return max(0.2, median * 0.20)


def _micro_zone(
    *,
    direction: str,
    timeframe: str,
    low: float,
    high: float,
    touches: int,
    source: str,
    zone_type: str | None = None,
) -> Zone:
    resolved_zone_type = zone_type or (
        "support" if direction == "BUY" else "resistance"
    )
    return Zone(
        type=resolved_zone_type,
        timeframe=timeframe,
        low=round(float(low), 4),
        high=round(float(high), 4),
        midpoint=round((float(low) + float(high)) / 2, 4),
        touches=touches,
        score=18.0 + touches,
        source=source,
    )


def _micro_stop_buffer(candles: list[Candle]) -> float:
    recent = candles[-8:] if len(candles) > 8 else candles
    ranges = [candle_range(candle) for candle in recent if candle_range(candle) > 0]
    average_range = sum(ranges) / len(ranges) if ranges else 0.0
    return max(0.15, average_range * 0.15)


def _micro_setup(
    *,
    name: str,
    direction: str,
    zone: Zone,
    entry_price: float,
    stop_loss: float,
    confirmation_candle: Candle,
) -> Setup:
    return Setup(
        name=name,
        direction=direction,
        zone=zone,
        entry_price=round(float(entry_price), 4),
        stop_loss=round(float(stop_loss), 4),
        confirmation_candle=confirmation_candle,
    )


def _find_respected_low(
    previous_candles: list[Candle],
    latest: Candle,
    tolerance: float,
) -> tuple[int, Candle] | None:
    for index in range(len(previous_candles) - 1, -1, -1):
        candidate = previous_candles[index]
        if abs(float(candidate.low) - float(latest.low)) <= tolerance:
            return index, candidate
    return None


def _find_respected_high(
    previous_candles: list[Candle],
    latest: Candle,
    tolerance: float,
) -> tuple[int, Candle] | None:
    for index in range(len(previous_candles) - 1, -1, -1):
        candidate = previous_candles[index]
        if abs(float(candidate.high) - float(latest.high)) <= tolerance:
            return index, candidate
    return None


def _find_broken_respected_lows(
    candles: list[Candle],
    latest: Candle,
    tolerance: float,
) -> tuple[int, int, Candle, Candle, float] | None:
    prior = candles[:-1]
    for second_index in range(len(prior) - 1, 0, -1):
        second = prior[second_index]
        for first_index in range(second_index - 1, -1, -1):
            first = prior[first_index]
            if abs(float(first.low) - float(second.low)) > tolerance:
                continue
            level = min(float(first.low), float(second.low))
            if float(latest.close) < level:
                return first_index, second_index, first, second, level
    return None


def _find_broken_respected_highs(
    candles: list[Candle],
    latest: Candle,
    tolerance: float,
) -> tuple[int, int, Candle, Candle, float] | None:
    prior = candles[:-1]
    for second_index in range(len(prior) - 1, 0, -1):
        second = prior[second_index]
        for first_index in range(second_index - 1, -1, -1):
            first = prior[first_index]
            if abs(float(first.high) - float(second.high)) > tolerance:
                continue
            level = max(float(first.high), float(second.high))
            if float(latest.close) > level:
                return first_index, second_index, first, second, level
    return None


def _find_confirmed_respected_lows(
    candles: list[Candle],
    latest: Candle,
    tolerance: float,
) -> tuple[int, int, Candle, Candle, float] | None:
    if len(candles) < 4:
        return None
    prior = candles[:-1]
    for second_index in range(len(prior) - 1, 0, -1):
        second = prior[second_index]
        for first_index in range(second_index - 1, -1, -1):
            first = prior[first_index]
            if abs(float(first.low) - float(second.low)) > tolerance:
                continue
            between = prior[first_index + 1 : second_index]
            if not between:
                continue
            trigger = max(candle.high for candle in between)
            if float(latest.close) > trigger:
                return first_index, second_index, first, second, trigger
    return None


def _find_confirmed_respected_highs(
    candles: list[Candle],
    latest: Candle,
    tolerance: float,
) -> tuple[int, int, Candle, Candle, float] | None:
    if len(candles) < 4:
        return None
    prior = candles[:-1]
    for second_index in range(len(prior) - 1, 0, -1):
        second = prior[second_index]
        for first_index in range(second_index - 1, -1, -1):
            first = prior[first_index]
            if abs(float(first.high) - float(second.high)) > tolerance:
                continue
            between = prior[first_index + 1 : second_index]
            if not between:
                continue
            trigger = min(candle.low for candle in between)
            if float(latest.close) < trigger:
                return first_index, second_index, first, second, trigger
    return None


def _detect_fast_microstructure_setups(
    candles: list[Candle],
    *,
    timeframe: str,
    min_trigger_candles: int = DEFAULT_FAST_MIN_TRIGGER_CANDLES,
    max_trigger_candles: int = DEFAULT_FAST_MAX_TRIGGER_CANDLES,
) -> list[Setup]:
    min_trigger_candles = max(3, int(min_trigger_candles))
    max_trigger_candles = max(min_trigger_candles, int(max_trigger_candles))
    if len(candles) < min_trigger_candles:
        return []

    trigger_candles = candles[-max_trigger_candles:]
    latest = trigger_candles[-1]
    tolerance = _micro_tolerance(candles)
    buffer = _micro_stop_buffer(trigger_candles)
    setups: list[Setup] = []

    respected_low = _find_respected_low(trigger_candles[:-1], latest, tolerance)
    if (
        respected_low is not None
        and lower_wick(latest) > 0
        and wick_ratio(latest, "lower") >= 0.20
        and (
            is_bullish(latest)
            or latest.close >= latest.low + candle_range(latest) * 0.60
        )
    ):
        _index, first = respected_low
        low = min(float(first.low), float(latest.low))
        high = max(float(first.low), float(latest.low))
        zone = _micro_zone(
            direction="BUY",
            timeframe=timeframe,
            low=low,
            high=high,
            touches=2,
            source="fast_microstructure_respected_low",
        )
        setups.append(
            _micro_setup(
                name="Aggressive Respect",
                direction="BUY",
                zone=zone,
                entry_price=latest.high,
                stop_loss=low - buffer,
                confirmation_candle=latest,
            )
        )

    respected_high = _find_respected_high(trigger_candles[:-1], latest, tolerance)
    if (
        respected_high is not None
        and upper_wick(latest) > 0
        and wick_ratio(latest, "upper") >= 0.20
        and (
            is_bearish(latest)
            or latest.close <= latest.high - candle_range(latest) * 0.60
        )
    ):
        _index, first = respected_high
        low = min(float(first.high), float(latest.high))
        high = max(float(first.high), float(latest.high))
        zone = _micro_zone(
            direction="SELL",
            timeframe=timeframe,
            low=low,
            high=high,
            touches=2,
            source="fast_microstructure_respected_high",
        )
        setups.append(
            _micro_setup(
                name="Aggressive Respect",
                direction="SELL",
                zone=zone,
                entry_price=latest.low,
                stop_loss=high + buffer,
                confirmation_candle=latest,
            )
        )

    broken_lows = _find_broken_respected_lows(trigger_candles, latest, tolerance)
    if broken_lows is not None:
        _first_index, _second_index, first, second, level = broken_lows
        low = min(float(first.low), float(second.low))
        high = max(float(first.low), float(second.low))
        zone = _micro_zone(
            direction="SELL",
            timeframe=timeframe,
            low=low,
            high=high,
            touches=3,
            source="fast_microstructure_failed_lows",
            zone_type="support",
        )
        setups.append(
            _micro_setup(
                name="Confirmed Break",
                direction="SELL",
                zone=zone,
                entry_price=min(float(level), float(latest.close)),
                stop_loss=high + buffer,
                confirmation_candle=latest,
            )
        )

    broken_highs = _find_broken_respected_highs(trigger_candles, latest, tolerance)
    if broken_highs is not None:
        _first_index, _second_index, first, second, level = broken_highs
        low = min(float(first.high), float(second.high))
        high = max(float(first.high), float(second.high))
        zone = _micro_zone(
            direction="BUY",
            timeframe=timeframe,
            low=low,
            high=high,
            touches=3,
            source="fast_microstructure_failed_highs",
            zone_type="resistance",
        )
        setups.append(
            _micro_setup(
                name="Confirmed Break",
                direction="BUY",
                zone=zone,
                entry_price=max(float(level), float(latest.close)),
                stop_loss=low - buffer,
                confirmation_candle=latest,
            )
        )

    confirmed_lows = _find_confirmed_respected_lows(trigger_candles, latest, tolerance)
    if confirmed_lows is not None:
        _first_index, _second_index, first, second, trigger = confirmed_lows
        low = min(float(first.low), float(second.low))
        high = max(float(first.low), float(second.low))
        zone = _micro_zone(
            direction="BUY",
            timeframe=timeframe,
            low=low,
            high=high,
            touches=2,
            source="fast_microstructure_confirmed_lows",
        )
        setups.append(
            _micro_setup(
                name="Confirmed Break",
                direction="BUY",
                zone=zone,
                entry_price=max(float(trigger), float(latest.close)),
                stop_loss=low - buffer,
                confirmation_candle=latest,
            )
        )

    confirmed_highs = _find_confirmed_respected_highs(trigger_candles, latest, tolerance)
    if confirmed_highs is not None:
        _first_index, _second_index, first, second, trigger = confirmed_highs
        low = min(float(first.high), float(second.high))
        high = max(float(first.high), float(second.high))
        zone = _micro_zone(
            direction="SELL",
            timeframe=timeframe,
            low=low,
            high=high,
            touches=2,
            source="fast_microstructure_confirmed_highs",
        )
        setups.append(
            _micro_setup(
                name="Confirmed Break",
                direction="SELL",
                zone=zone,
                entry_price=min(float(trigger), float(latest.close)),
                stop_loss=high + buffer,
                confirmation_candle=latest,
            )
        )

    return sorted(
        _unique_setups(setups),
        key=lambda setup: 0 if setup.name == "Confirmed Break" else 1,
    )


def _approve_micro_scalp_risk(
    setup: Setup,
    *,
    minimum_rr: float,
    preferred_rr: float,
) -> dict[str, Any]:
    entry = float(setup.entry_price)
    stop = float(setup.stop_loss)
    risk = abs(entry - stop)
    if risk <= 0:
        return {"approved": False, "reason": "Invalid stop-loss distance"}
    reward = risk * float(preferred_rr)
    take_profit = entry + reward if setup.direction == "BUY" else entry - reward
    trigger_ok, _trigger_reason, trigger_quality = _fast_trigger_quality(setup)
    confidence = _fast_micro_confidence(setup, trigger_quality) if trigger_ok else "REJECTED"
    if preferred_rr < minimum_rr:
        return {
            "approved": False,
            "reason": "Micro scalp risk/reward is below minimum",
            "risk_reward": round(preferred_rr, 2),
        }
    result = {
        "approved": True,
        "entry_price": round(entry, 4),
        "stop_loss": round(stop, 4),
        "take_profit": round(take_profit, 4),
        "risk_distance": round(risk, 4),
        "reward_distance": round(reward, 4),
        "risk_reward": round(preferred_rr, 2),
        "available_risk_reward": round(preferred_rr, 2),
        "risk_model": "FAST_MICRO_SCALP",
        "microstructure_signal": _fast_micro_signal(setup),
        "microstructure_confidence": confidence,
        "fast_trigger_quality": trigger_quality,
    }
    if confidence == "HIGH":
        result.update(
            {
                "volume_multiplier": 1.5,
                "position_lifecycle": "FAST_PARTIAL_SCALE",
                **_dynamic_fast_exit_settings(risk),
            }
        )
    return result


def _candidate_quality(candidate: dict[str, Any]) -> tuple[float, int, float]:
    setup = candidate["setup"]
    zone = setup.get("zone", {})
    return (
        float(_setup_grade_rank(candidate.get("setup_grade"))),
        _risk_reward_value(candidate.get("risk", {})),
        _timeframe_priority(zone.get("timeframe")),
        float(zone.get("score") or 0),
    )


def analyze_playbook(
    symbol: str,
    as_of: str,
    timeframe_data: dict[str, Any],
    market_timezone: str = "America/New_York",
    session_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Analyze all available timeframes and return a structured decision payload."""
    profile_config = session_config or {}
    profile_name = str(profile_config.get("entry_profile", "normal"))
    entry_timeframe = str(profile_config.get("timeframe", "15m"))
    confirmation_timeframe = str(
        profile_config.get("confirmation_timeframe", "30m")
    )
    zone_timeframes = tuple(
        str(tf)
        for tf in profile_config.get(
            "zone_timeframes",
            (confirmation_timeframe,),
        )
    )
    context_timeframes = tuple(
        str(tf)
        for tf in profile_config.get(
            "context_timeframes",
            ("1d", "4h", "1h"),
        )
    )
    governing_timeframes = tuple(
        str(tf)
        for tf in profile_config.get(
            "governing_timeframes",
            (confirmation_timeframe,),
        )
    )
    independent_direction = bool(
        profile_config.get("independent_direction", profile_name == "fast")
    )
    if "activation_window_minutes" in profile_config:
        activation_window_minutes = int(profile_config["activation_window_minutes"])
    elif profile_name == "fast":
        activation_window_minutes = int(
            profile_config.get("fast_activation_window_minutes", 6)
        )
    else:
        activation_window_minutes = int(
            profile_config.get("normal_activation_window_minutes", 30)
        )
    control_label = (
        "1m candle reader"
        if profile_name == "fast"
        else "M30/M15 checklist"
    )
    entry_label = _display_timeframe(entry_timeframe)
    confirmation_label = _display_timeframe(confirmation_timeframe)
    candles_by_tf = {
        timeframe: normalize_candles(candles)
        for timeframe, candles in timeframe_data.items()
    }
    entry_candles = candles_by_tf.get(entry_timeframe, [])
    confirmation_candles = candles_by_tf.get(confirmation_timeframe, [])
    is_fast_micro_profile = _is_fast_profile(profile_name, entry_timeframe)
    fast_history_window_candles = _positive_int(
        profile_config.get("fast_history_window_candles"),
        DEFAULT_FAST_HISTORY_WINDOW_CANDLES,
    )
    fast_min_trigger_candles = _positive_int(
        profile_config.get("fast_min_trigger_candles"),
        DEFAULT_FAST_MIN_TRIGGER_CANDLES,
    )
    fast_max_trigger_candles = _positive_int(
        profile_config.get("fast_max_trigger_candles"),
        DEFAULT_FAST_MAX_TRIGGER_CANDLES,
    )
    fast_history_candles = (
        entry_candles[-fast_history_window_candles:]
        if is_fast_micro_profile
        else entry_candles
    )
    time_checks = evaluate_time_filters(as_of, market_timezone, config=session_config)
    checklist = _base_checklist(time_checks)
    checklist["candle_closed"] = PASS if entry_candles and confirmation_candles else FAIL
    time_filter_mode = str(
        (session_config or {}).get("time_filter_mode", "block")
    ).strip().lower()
    if time_filter_mode not in {"block", "observe", "allow"}:
        time_filter_mode = "block"
    minimum_setup_grade = _normalize_setup_grade(
        (session_config or {}).get("minimum_setup_grade", "A_PLUS")
    )
    try:
        b_plus_min_rr = float((session_config or {}).get("b_plus_min_rr", 1.2))
    except (TypeError, ValueError):
        b_plus_min_rr = 1.2
    require_clear_confirmation_context = bool(
        (session_config or {}).get("require_clear_confirmation_context", True)
    )

    zones: list[Zone] = []
    zones_by_tf: dict[str, list[Zone]] = {}
    zone_lookup_timeframes = tuple(
        dict.fromkeys(
            (
                *zone_timeframes,
                *governing_timeframes,
                *context_timeframes,
                confirmation_timeframe,
            )
        )
    )
    for tf in zone_lookup_timeframes:
        zone_candles = (
            fast_history_candles
            if is_fast_micro_profile and tf == entry_timeframe
            else candles_by_tf.get(tf, [])
        )
        tf_zones = calculate_support_resistance(zone_candles, timeframe=tf)
        zones_by_tf[tf] = tf_zones
        if tf in zone_timeframes:
            zones.extend(tf_zones)
    zones = sorted(zones, key=lambda zone: zone.score, reverse=True)
    target_zones = sorted(
        [
            zone
            for timeframe in zone_lookup_timeframes
            for zone in zones_by_tf.get(timeframe, [])
        ],
        key=lambda zone: zone.score,
        reverse=True,
    )

    timing_zones = zones_by_tf.get(confirmation_timeframe, [])
    timing_breakouts = detect_breakouts(confirmation_candles, timing_zones)
    timing_context = determine_m30_bias(
        [_setup_to_dict(setup) for setup in timing_breakouts]
    )
    context_candles_by_tf = dict(candles_by_tf)
    if is_fast_micro_profile:
        context_candles_by_tf[entry_timeframe] = fast_history_candles
    governing_context = _governing_context(
        context_candles_by_tf,
        zones_by_tf,
        governing_timeframes,
    )
    daily_structure = classify_timeframe_structure(
        candles_by_tf.get("1d", []),
        zones_by_tf.get("1d", []),
        "Daily",
    )
    h4_structure = classify_timeframe_structure(
        candles_by_tf.get("4h", []),
        zones_by_tf.get("4h", []),
        "4H",
    )
    h1_structure = classify_timeframe_structure(
        candles_by_tf.get("1h", []),
        zones_by_tf.get("1h", []),
        "1H",
    )
    market_state = {
        tf: classify_market_state(
            fast_history_candles
            if is_fast_micro_profile and tf == entry_timeframe
            else candles_by_tf.get(tf, []),
            zones_by_tf.get(tf, []),
            tf,
        )
        for tf in _ordered_timeframes(
            {*context_timeframes, *governing_timeframes, confirmation_timeframe, entry_timeframe}
        )
    }
    market_context = {
        **governing_context,
        "entry_profile": profile_name,
        "timeframe": entry_timeframe,
        "confirmation_timeframe": confirmation_timeframe,
        "context_timeframes": context_timeframes,
        "governing_timeframes": governing_timeframes,
        "target_zone_timeframes": zone_lookup_timeframes,
        "activation_window_minutes": activation_window_minutes,
        "independent_direction": independent_direction,
        "confirmation_bias": governing_context.get("m30_bias"),
        "confirmation_context": governing_context.get("m30_context"),
        "timing_context": timing_context,
        "daily_structure": daily_structure,
        "h4_structure": h4_structure,
        "h1_structure": h1_structure,
        "daily_permission": daily_structure["permission"],
        "h4_permission": h4_structure["permission"],
        "h1_permission": h1_structure["permission"],
        "range": classify_range(confirmation_candles, timing_zones),
        "market_state": market_state,
        "entry_market_state": market_state.get(entry_timeframe, {}),
        "confirmation_market_state": market_state.get(confirmation_timeframe, {}),
        "time_filter_mode": time_filter_mode,
        "minimum_setup_grade": minimum_setup_grade,
        "b_plus_min_rr": b_plus_min_rr,
        "require_clear_confirmation_context": require_clear_confirmation_context,
    }
    if is_fast_micro_profile:
        market_context["fast_microstructure"] = {
            "enabled": True,
            "entry_timeframe": entry_timeframe,
            "window_timeframe": entry_timeframe,
            "history_window_candles": fast_history_window_candles,
            "evaluated_history_candles": len(fast_history_candles),
            "trigger_window_min_candles": fast_min_trigger_candles,
            "trigger_window_max_candles": fast_max_trigger_candles,
            "trigger_window_evaluated_candles": min(
                len(fast_history_candles),
                fast_max_trigger_candles,
            ),
            "rules": ["AGGRESSIVE_RESPECT", "CONFIRMED_BREAK"],
        }

    def make_telemetry(
        decision_stage: str,
        primary_hold_reason: str,
        candidate_setups: list[Setup] | None = None,
        candidate_evaluations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return _telemetry(
            decision_stage=decision_stage,
            primary_hold_reason=primary_hold_reason,
            candles_by_tf=candles_by_tf,
            zones_by_tf=zones_by_tf,
            market_context=market_context,
            candidate_setups=candidate_setups,
            candidate_evaluations=candidate_evaluations,
        )

    hard_time_keys = (
        "volume_time",
        "not_last_15_of_4h",
        "not_15_min_before_open",
        "not_sunday_asian_session",
    )
    if time_filter_mode == "allow":
        for key in hard_time_keys:
            if checklist[key] == FAIL:
                checklist[key] = PASS
    if time_filter_mode == "block" and any(
        checklist[key] == FAIL for key in hard_time_keys
    ):
        return _payload(
            symbol,
            as_of,
            "NO_SETUP",
            "HOLD",
            checklist,
            zones,
            market_context,
            message="Time filter failed. Default to HOLD.",
            telemetry=make_telemetry("time_filter", "Time filter failed. Default to HOLD."),
        )

    if checklist["candle_closed"] == FAIL:
        return _payload(
            symbol,
            as_of,
            "NO_SETUP",
            "HOLD",
            checklist,
            zones,
            market_context,
            message=(
                f"Insufficient closed {entry_label}/{confirmation_label} candles. "
                "Default to HOLD."
            ),
            telemetry=make_telemetry(
                "data_insufficient",
                (
                    f"Insufficient closed {entry_label}/{confirmation_label} candles. "
                    "Default to HOLD."
                ),
            ),
        )

    confirmation_direction = None
    if market_context["m30_bias"] == "BULLISH":
        confirmation_direction = "BUY"
    elif market_context["m30_bias"] == "BEARISH":
        confirmation_direction = "SELL"
    timing_direction = _direction_from_context(timing_context)

    entry_reference_zones = _entry_reference_zones(zones_by_tf, zone_timeframes)
    micro_setups = (
        _detect_fast_microstructure_setups(
            fast_history_candles,
            timeframe=entry_timeframe,
            min_trigger_candles=fast_min_trigger_candles,
            max_trigger_candles=fast_max_trigger_candles,
        )
        if is_fast_micro_profile
        else []
    )
    candidate_setups = _unique_setups(
        [
            *micro_setups,
            *detect_breakouts(entry_candles, entry_reference_zones),
            *detect_break_and_retest(
                entry_candles,
                entry_reference_zones,
                direction=confirmation_direction,
            ),
            *detect_sr_bounce(entry_candles, entry_reference_zones),
        ]
    )

    if not candidate_setups:
        checklist["not_overextended"] = FAIL if _is_overextended(entry_candles) else PASS
        return _payload(
            symbol,
            as_of,
            "NO_SETUP",
            "HOLD",
            checklist,
            zones,
            market_context,
            message=f"No valid {entry_label} setup. Default to HOLD.",
            telemetry=make_telemetry(
                "no_m15_setup",
                f"No valid {entry_label} setup. Default to HOLD.",
                candidate_setups,
            ),
        )

    required = [
        "volume_time",
        "playbook_setup",
        "timeframe_correlation",
        "entry_market_state_aligned",
        "confirmation_context_clear",
        "clean_range_to_fill",
        "candle_closed",
        "not_overextended",
        "not_last_15_of_4h",
        "not_15_min_before_open",
        "not_sunday_asian_session",
        "confirmation_candle_wicks",
        "trading_candle_stop_wick",
        "fast_trigger_quality",
        "not_activated_last_5_min",
    ]

    candidate_evaluations: list[dict[str, Any]] = []
    for index, setup in enumerate(candidate_setups):
        is_micro_setup = is_fast_micro_profile and setup.name in FAST_MICRO_SETUP_NAMES
        candidate_checklist = dict(checklist)
        candidate_checklist["playbook_setup"] = PASS
        clear_window_direction = _clear_fast_window_direction(
            market_context.get("confirmation_market_state", {})
        )
        if is_micro_setup:
            context_allows = True
        else:
            context_allows = confirmation_direction == setup.direction or (
                independent_direction
                and confirmation_direction is None
                and not require_clear_confirmation_context
            )
        timing_allows = (
            True
            if is_micro_setup
            else timing_direction is None or timing_direction == setup.direction
        )
        if context_allows and timing_allows:
            candidate_checklist["timeframe_correlation"] = PASS
        else:
            candidate_checklist["timeframe_correlation"] = FAIL
            if is_micro_setup and clear_window_direction not in {None, setup.direction}:
                candidate_checklist["timeframe_correlation_reason"] = (
                    f"The {confirmation_timeframe} window opposes the fast "
                    "microstructure setup. Default to HOLD."
                )
        entry_state_direction = _direction_from_bias(
            market_context.get("entry_market_state", {}).get("direction")
        )
        candidate_checklist["entry_market_state_aligned"] = (
            PASS
            if entry_state_direction is None or entry_state_direction == setup.direction
            else FAIL
        )
        candidate_checklist["confirmation_context_clear"] = (
            PASS
            if (
                is_micro_setup
                or
                (not is_micro_setup and confirmation_direction is not None)
                or (
                    independent_direction
                    and not require_clear_confirmation_context
                )
            )
            else FAIL
        )
        candidate_checklist["not_overextended"] = (
            FAIL if _is_overextended(entry_candles) else PASS
        )
        candidate_checklist["confirmation_candle_wicks"] = (
            PASS if _has_top_and_bottom_wick(setup.confirmation_candle) else FAIL
        )
        candidate_checklist["trading_candle_stop_wick"] = (
            PASS if _has_stop_wick(setup.confirmation_candle, setup.direction) else FAIL
        )
        if is_micro_setup:
            trigger_ok, trigger_reason, trigger_metrics = _fast_trigger_quality(setup)
            candidate_checklist["fast_trigger_quality"] = PASS if trigger_ok else FAIL
            candidate_checklist["fast_trigger_quality_metrics"] = trigger_metrics
            if trigger_reason:
                candidate_checklist["fast_trigger_quality_reason"] = trigger_reason
        else:
            candidate_checklist["fast_trigger_quality"] = PASS

        target_zone = nearest_target_zone(
            target_zones,
            setup.direction,
            setup.entry_price,
        )
        if is_micro_setup:
            micro_preferred_rr = 1.5 if setup.name == "Confirmed Break" else 1.2
            b_plus_risk = _approve_micro_scalp_risk(
                setup,
                minimum_rr=b_plus_min_rr,
                preferred_rr=micro_preferred_rr,
            )
        else:
            b_plus_risk = approve_risk(
                setup,
                target_zone,
                minimum_rr=b_plus_min_rr,
                preferred_rr=3.0,
            )
        try:
            minimum_stop_distance = float(
                profile_config.get("minimum_stop_distance_price", 0.0)
            )
        except (TypeError, ValueError):
            minimum_stop_distance = 0.0
        stop_distance = abs(float(setup.entry_price) - float(setup.stop_loss))
        if minimum_stop_distance and stop_distance < minimum_stop_distance:
            b_plus_risk = {
                **b_plus_risk,
                "approved": False,
                "reason": (
                    "Stop distance is below minimum: "
                    f"distance={stop_distance:.2f}, minimum={minimum_stop_distance:.2f}"
                ),
            }
        candidate_checklist["clean_range_to_fill"] = PASS if b_plus_risk.get("approved") else FAIL
        failed_rules = [key for key in required if candidate_checklist[key] != PASS]
        risk = b_plus_risk
        setup_grade = "REJECTED"
        if not failed_rules:
            if is_micro_setup:
                micro_a_plus_rr = 1.5 if setup.name == "Confirmed Break" else 1.2
                a_plus_risk = _approve_micro_scalp_risk(
                    setup,
                    minimum_rr=1.5,
                    preferred_rr=micro_a_plus_rr,
                )
            else:
                a_plus_risk = approve_risk(
                    setup,
                    target_zone,
                    minimum_rr=1.5,
                    preferred_rr=3.0,
                )
            if a_plus_risk.get("approved"):
                risk = a_plus_risk
                setup_grade = "A_PLUS"
            elif b_plus_risk.get("approved"):
                setup_grade = "B_PLUS"
        meets_minimum_setup_grade = _setup_grade_rank(setup_grade) >= _setup_grade_rank(
            minimum_setup_grade
        )
        approved = meets_minimum_setup_grade
        permission = evaluate_higher_timeframe_permission(
            market_context["daily_structure"],
            market_context["h4_structure"],
            market_context["h1_structure"],
            setup.direction,
            control_label=control_label,
        )
        higher_timeframe_bias = _direction_from_bias(
            profile_config.get("higher_timeframe_bias")
        )
        counter_bias_minimum_grade = profile_config.get(
            "fast_counter_bias_minimum_grade",
            "A_PLUS",
        )
        counter_bias_rejected = (
            profile_name == "fast"
            and higher_timeframe_bias is not None
            and setup.direction != higher_timeframe_bias
            and _setup_grade_rank(setup_grade)
            < _setup_grade_rank(counter_bias_minimum_grade)
        )
        if counter_bias_rejected:
            approved = False
        if setup_grade == "REJECTED":
            rejection_reason = _candidate_rejection_reason(
                candidate_checklist,
                risk,
                failed_rules,
            )
        elif counter_bias_rejected:
            rejection_reason = (
                "Fast counter-bias setup requires "
                f"{str(counter_bias_minimum_grade).strip().upper()} grade."
            )
        elif not approved:
            rejection_reason = (
                f"Setup grade {setup_grade} is below minimum required {minimum_setup_grade}."
            )
        else:
            rejection_reason = None
        candidate_evaluations.append(
            {
                "index": index,
                "approved": approved,
                "setup_grade": setup_grade,
                "meets_minimum_setup_grade": meets_minimum_setup_grade,
                "counter_bias_rejected": counter_bias_rejected,
                "rejection_reason": rejection_reason,
                "failed_rules": failed_rules,
                "setup": _setup_to_dict(setup, risk, setup_grade if setup_grade != "REJECTED" else None),
                "risk": risk,
                "target_zone": target_zone,
                "checklist": candidate_checklist,
                "higher_timeframe_permission": permission,
                "_setup": setup,
            }
        )

    approved_candidates = [item for item in candidate_evaluations if item["approved"]]
    if approved_candidates:
        selected = max(approved_candidates, key=_candidate_quality)
        setup = selected["_setup"]
        risk = selected["risk"]
        checklist = selected["checklist"]
        setup_grade = selected["setup_grade"]
        market_context["higher_timeframe_permission"] = selected["higher_timeframe_permission"]
        telemetry_candidates = [
            {key: value for key, value in item.items() if key != "_setup"}
            for item in candidate_evaluations
        ]
        setup_grade_label = "A+" if setup_grade == "A_PLUS" else "B+"
        return _payload(
            symbol,
            as_of,
            "SETUP_FOUND",
            setup.direction,
            checklist,
            zones,
            market_context,
            setups=[_setup_to_dict(setup, risk, setup_grade)],
            risk=risk,
            message=f"A deterministic {setup_grade_label} price-action setup passed the checklist.",
            telemetry=make_telemetry(
                "setup_found",
                f"A deterministic {setup_grade_label} price-action setup passed the checklist.",
                candidate_setups,
                telemetry_candidates,
            ),
        )

    selected = max(candidate_evaluations, key=_candidate_quality)
    setup = selected["_setup"]
    risk = selected["risk"]
    checklist = selected["checklist"]
    setup_grade = selected["setup_grade"]
    market_context["higher_timeframe_permission"] = selected["higher_timeframe_permission"]
    telemetry_candidates = [
        {key: value for key, value in item.items() if key != "_setup"}
        for item in candidate_evaluations
    ]
    if selected.get("counter_bias_rejected"):
        minimum_grade = str(
            profile_config.get("fast_counter_bias_minimum_grade", "A_PLUS")
        ).strip().upper()
        return _payload(
            symbol,
            as_of,
            "NO_SETUP",
            "HOLD",
            checklist,
            zones,
            market_context,
            setups=[_setup_to_dict(setup, risk, setup_grade)],
            risk=risk,
            message=f"Fast counter-bias setup requires {minimum_grade} grade.",
            telemetry=make_telemetry(
                "counter_bias_grade_filter",
                f"Fast counter-bias setup requires {minimum_grade} grade.",
                candidate_setups,
                telemetry_candidates,
            ),
        )
    if setup_grade == "B_PLUS":
        return _payload(
            symbol,
            as_of,
            "NO_SETUP",
            "HOLD",
            checklist,
            zones,
            market_context,
            setups=[_setup_to_dict(setup, risk, setup_grade)],
            risk=risk,
            message=f"A B+ setup was found but the minimum required setup grade is {minimum_setup_grade}.",
            telemetry=make_telemetry(
                "setup_grade_filter",
                f"A B+ setup was found but the minimum required setup grade is {minimum_setup_grade}.",
                candidate_setups,
                telemetry_candidates,
            ),
        )
    if any(checklist[key] != PASS for key in required):
        hold_reason = selected.get("rejection_reason") or (
            "A required A+ checklist rule failed. Default to HOLD."
        )
        return _payload(
            symbol,
            as_of,
            "NO_SETUP",
            "HOLD",
            checklist,
            zones,
            market_context,
            setups=[_setup_to_dict(setup, risk)],
            risk=risk,
            message=hold_reason,
            telemetry=make_telemetry(
                "a_plus_checklist",
                hold_reason,
                candidate_setups,
                telemetry_candidates,
            ),
        )

    return _payload(
        symbol,
        as_of,
        "NO_SETUP",
        "HOLD",
        checklist,
        zones,
        market_context,
        setups=[_setup_to_dict(setup, risk)],
        risk=risk,
        message=selected.get("rejection_reason")
        or "A required A+ checklist rule failed. Default to HOLD.",
        telemetry=make_telemetry(
            "a_plus_checklist",
            selected.get("rejection_reason")
            or "A required A+ checklist rule failed. Default to HOLD.",
            candidate_setups,
            telemetry_candidates,
        ),
    )
