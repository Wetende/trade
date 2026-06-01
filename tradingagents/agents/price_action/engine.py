"""Deterministic M30/M15 price-action analysis engine."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from tradingagents.agents.price_action.candles import candle_range, normalize_candles
from tradingagents.agents.price_action.models import Candle, Setup, Zone
from tradingagents.agents.price_action.risk import approve_risk
from tradingagents.agents.price_action.sessions import evaluate_time_filters
from tradingagents.agents.price_action.setups import (
    detect_break_and_retest,
    detect_breakouts,
    detect_sr_bounce,
)
from tradingagents.agents.price_action.structure import (
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
        "clean_range_to_fill": UNKNOWN,
        "candle_closed": UNKNOWN,
        "not_overextended": UNKNOWN,
        "not_last_15_of_4h": time_checks.get("not_last_15_of_4h", UNKNOWN),
        "not_15_min_before_open": time_checks.get("not_15_min_before_open", UNKNOWN),
        "not_sunday_asian_session": time_checks.get("not_sunday_asian_session", UNKNOWN),
        "confirmation_candle_wicks": UNKNOWN,
        "trading_candle_stop_wick": UNKNOWN,
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
) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "as_of": as_of,
        "timeframe": "15m",
        "confirmation_timeframe": "30m",
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


def _rows_by_timeframe(candles_by_tf: dict[str, list[Candle]]) -> dict[str, int]:
    return {tf: len(candles_by_tf.get(tf, [])) for tf in ("1d", "4h", "1h", "30m", "15m")}


def _zone_counts(zones_by_tf: dict[str, list[Zone]]) -> dict[str, int]:
    return {tf: len(zones_by_tf.get(tf, [])) for tf in ("1d", "4h", "1h", "30m")}


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


def _setup_to_dict(setup: Setup, risk: dict[str, Any] | None = None) -> dict[str, Any]:
    result = asdict(setup)
    result["zone"] = zone_to_dict(setup.zone)
    if setup.confirmation_candle is not None:
        result["confirmation_candle"] = asdict(setup.confirmation_candle)
    if risk and risk.get("approved"):
        result.update(
            {
                "take_profit": risk["take_profit"],
                "risk_distance": risk["risk_distance"],
                "reward_distance": risk["reward_distance"],
                "risk_reward": risk["risk_reward"],
            }
        )
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


def _candidate_quality(candidate: dict[str, Any]) -> tuple[float, int, float]:
    setup = candidate["setup"]
    zone = setup.get("zone", {})
    return (
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
    candles_by_tf = {
        timeframe: normalize_candles(candles)
        for timeframe, candles in timeframe_data.items()
    }
    m15 = candles_by_tf.get("15m", [])
    m30 = candles_by_tf.get("30m", [])
    time_checks = evaluate_time_filters(as_of, market_timezone, config=session_config)
    checklist = _base_checklist(time_checks)
    checklist["candle_closed"] = PASS if m15 and m30 else FAIL
    time_filter_mode = str(
        (session_config or {}).get("time_filter_mode", "block")
    ).strip().lower()
    if time_filter_mode not in {"block", "observe", "allow"}:
        time_filter_mode = "block"

    zones: list[Zone] = []
    zones_by_tf: dict[str, list[Zone]] = {}
    for tf in ("1d", "4h", "1h", "30m"):
        tf_zones = calculate_support_resistance(candles_by_tf.get(tf, []), timeframe=tf)
        zones_by_tf[tf] = tf_zones
        zones.extend(tf_zones)
    zones = sorted(zones, key=lambda zone: zone.score, reverse=True)

    m30_zones = zones_by_tf.get("30m", [])
    m30_breakouts = detect_breakouts(m30, m30_zones)
    m30_breakout_dicts = [_setup_to_dict(setup) for setup in m30_breakouts]
    m30_context = determine_m30_bias(m30_breakout_dicts)
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
        [],
        "1H",
    )
    market_context = {
        **m30_context,
        "daily_structure": daily_structure,
        "h4_structure": h4_structure,
        "h1_structure": h1_structure,
        "daily_permission": daily_structure["permission"],
        "h4_permission": h4_structure["permission"],
        "h1_permission": h1_structure["permission"],
        "range": classify_range(m30, m30_zones),
        "time_filter_mode": time_filter_mode,
    }
    m30_rejections: list[Setup] = []
    if not m30_breakouts:
        m30_rejections = detect_sr_bounce(m30, m30_zones)
        if m30_rejections:
            rejected = m30_rejections[0]
            market_context["m30_bias"] = (
                "BULLISH" if rejected.direction == "BUY" else "BEARISH"
            )
            market_context["m30_context"] = "REJECTION"
            market_context["m30_rejection"] = _setup_to_dict(rejected)

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
            message="Insufficient closed M15/M30 candles. Default to HOLD.",
            telemetry=make_telemetry(
                "data_insufficient",
                "Insufficient closed M15/M30 candles. Default to HOLD.",
            ),
        )

    m30_direction = None
    if market_context["m30_bias"] == "BULLISH":
        m30_direction = "BUY"
    elif market_context["m30_bias"] == "BEARISH":
        m30_direction = "SELL"

    candidate_setups = _unique_setups(
        [
            *detect_breakouts(m15, m30_zones),
            *detect_break_and_retest(m15, m30_zones, direction=m30_direction),
            *detect_sr_bounce(m15, zones),
        ]
    )

    if not candidate_setups:
        checklist["not_overextended"] = FAIL if _is_overextended(m15) else PASS
        return _payload(
            symbol,
            as_of,
            "NO_SETUP",
            "HOLD",
            checklist,
            zones,
            market_context,
            message="No valid M15 setup. Default to HOLD.",
            telemetry=make_telemetry(
                "no_m15_setup",
                "No valid M15 setup. Default to HOLD.",
                candidate_setups,
            ),
        )

    required = [
        "volume_time",
        "playbook_setup",
        "timeframe_correlation",
        "clean_range_to_fill",
        "candle_closed",
        "not_overextended",
        "not_last_15_of_4h",
        "not_15_min_before_open",
        "not_sunday_asian_session",
        "confirmation_candle_wicks",
        "trading_candle_stop_wick",
        "not_activated_last_5_min",
    ]

    candidate_evaluations: list[dict[str, Any]] = []
    for index, setup in enumerate(candidate_setups):
        candidate_checklist = dict(checklist)
        candidate_checklist["playbook_setup"] = PASS
        candidate_checklist["timeframe_correlation"] = PASS if m30_direction == setup.direction else FAIL
        candidate_checklist["not_overextended"] = FAIL if _is_overextended(m15) else PASS
        candidate_checklist["confirmation_candle_wicks"] = (
            PASS if _has_top_and_bottom_wick(setup.confirmation_candle) else FAIL
        )
        candidate_checklist["trading_candle_stop_wick"] = (
            PASS if _has_stop_wick(setup.confirmation_candle, setup.direction) else FAIL
        )

        target_zone = nearest_target_zone(zones, setup.direction, setup.entry_price)
        risk = approve_risk(setup, target_zone, minimum_rr=1.5, preferred_rr=3.0)
        candidate_checklist["clean_range_to_fill"] = PASS if risk.get("approved") else FAIL
        failed_rules = [key for key in required if candidate_checklist[key] != PASS]
        approved = not failed_rules
        permission = evaluate_higher_timeframe_permission(
            market_context["daily_structure"],
            market_context["h4_structure"],
            market_context["h1_structure"],
            setup.direction,
        )
        candidate_evaluations.append(
            {
                "index": index,
                "approved": approved,
                "rejection_reason": _candidate_rejection_reason(
                    candidate_checklist,
                    risk,
                    failed_rules,
                ),
                "failed_rules": failed_rules,
                "setup": _setup_to_dict(setup, risk),
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
        market_context["higher_timeframe_permission"] = selected["higher_timeframe_permission"]
        telemetry_candidates = [
            {key: value for key, value in item.items() if key != "_setup"}
            for item in candidate_evaluations
        ]
        return _payload(
            symbol,
            as_of,
            "SETUP_FOUND",
            setup.direction,
            checklist,
            zones,
            market_context,
            setups=[_setup_to_dict(setup, risk)],
            risk=risk,
            message="A deterministic A+ price-action setup passed the checklist.",
            telemetry=make_telemetry(
                "setup_found",
                "A deterministic A+ price-action setup passed the checklist.",
                candidate_setups,
                telemetry_candidates,
            ),
        )

    selected = max(candidate_evaluations, key=_candidate_quality)
    setup = selected["_setup"]
    risk = selected["risk"]
    checklist = selected["checklist"]
    market_context["higher_timeframe_permission"] = selected["higher_timeframe_permission"]
    telemetry_candidates = [
        {key: value for key, value in item.items() if key != "_setup"}
        for item in candidate_evaluations
    ]
    if any(checklist[key] != PASS for key in required):
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
            message="A required A+ checklist rule failed. Default to HOLD.",
            telemetry=make_telemetry(
                "a_plus_checklist",
                "A required A+ checklist rule failed. Default to HOLD.",
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
        message="A required A+ checklist rule failed. Default to HOLD.",
        telemetry=make_telemetry(
            "a_plus_checklist",
            "A required A+ checklist rule failed. Default to HOLD.",
            candidate_setups,
            telemetry_candidates,
        ),
    )
