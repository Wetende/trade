"""Deterministic M30/M15 price-action analysis engine."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from tradingagents.agents.price_action.candles import (
    candle_range,
    normalize_candles,
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


def _candidate_quality(candidate: dict[str, Any]) -> tuple[float, int, float]:
    setup = candidate["setup"]
    zone = setup.get("zone", {})
    return (
        float(_setup_grade_rank(candidate.get("setup_grade"))),
        _risk_reward_value(candidate.get("risk", {})),
        _timeframe_priority(zone.get("timeframe")),
        float(zone.get("score") or 0),
    )


def analyze_normal_entry(
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
    independent_direction = bool(profile_config.get("independent_direction", False))
    if "activation_window_minutes" in profile_config:
        activation_window_minutes = int(profile_config["activation_window_minutes"])
    else:
        activation_window_minutes = int(
            profile_config.get("normal_activation_window_minutes", 30)
        )
    control_label = "M30/M15 checklist"
    entry_label = _display_timeframe(entry_timeframe)
    confirmation_label = _display_timeframe(confirmation_timeframe)
    candles_by_tf = {
        timeframe: normalize_candles(candles)
        for timeframe, candles in timeframe_data.items()
    }
    entry_candles = candles_by_tf.get(entry_timeframe, [])
    confirmation_candles = candles_by_tf.get(confirmation_timeframe, [])
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
        zone_candles = candles_by_tf.get(tf, [])
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
    governing_context = _governing_context(
        candles_by_tf,
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
            candles_by_tf.get(tf, []),
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
    candidate_setups = _unique_setups(
        [
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
        candidate_checklist = dict(checklist)
        candidate_checklist["playbook_setup"] = PASS
        context_allows = confirmation_direction == setup.direction or (
            independent_direction
            and confirmation_direction is None
            and not require_clear_confirmation_context
        )
        timing_allows = (
            timing_direction is None or timing_direction == setup.direction
        )
        if context_allows and timing_allows:
            candidate_checklist["timeframe_correlation"] = PASS
        else:
            candidate_checklist["timeframe_correlation"] = FAIL
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
                confirmation_direction is not None
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
        candidate_checklist["fast_trigger_quality"] = PASS

        target_zone = nearest_target_zone(
            target_zones,
            setup.direction,
            setup.entry_price,
        )
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
        if setup_grade == "REJECTED":
            rejection_reason = _candidate_rejection_reason(
                candidate_checklist,
                risk,
                failed_rules,
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
