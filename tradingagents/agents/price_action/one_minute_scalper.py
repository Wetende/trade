"""Causal two-closed-candle implementation of the One Minute Scalper.

The first closed candle creates an immutable clean-level story.  Only the next
fully closed M1 candle may reconfirm it.  A fresh quote is then used solely to
prove that a direction-safe pending entry has not already been crossed, moved
away, or invalidated; quote counts are deliberately not treated as order flow.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import timedelta
from typing import Any, Iterable

from tradingagents.agents.price_action.candles import is_bearish, is_bullish, normalize_candles
from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
    HIGH_BREAK_BUY,
    HIGH_RESPECT_SELL,
    LOW_BREAK_SELL,
    LOW_RESPECT_BUY,
    _base_checklist,
    _confirmation_type,
    _dynamic_fast_exit_settings,
    _level_zone,
    _payload,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PostCloseArm,
    detect_post_close_arms,
    parse_utc,
)


CANDIDATE_NAME = "ONE_MINUTE_SCALPER"
HISTORY_CANDLES = 60
MINIMUM_STOP_SPREAD_MULTIPLE = 1.2
MAXIMUM_STOP_DISTANCE = 1.0
RISK_REWARD = 1.5
DEFAULT_TICK_SIZE = 0.01
MAX_RECONFIRMATION_GAP = timedelta(minutes=3)

BUY_FAMILIES = {
    LOW_RESPECT_BUY,
    HIGH_BREAK_BUY,
    FAILED_LOW_BREAK_BUY,
}
SELL_FAMILIES = {
    HIGH_RESPECT_SELL,
    LOW_BREAK_SELL,
    FAILED_HIGH_BREAK_SELL,
}
@dataclass(frozen=True)
class Reconfirmation:
    accepted: bool
    reason: str
    confirmation_type: str


@dataclass(frozen=True)
class OrderGeometry:
    accepted: bool
    reason: str
    direction: str
    entry_mode: str | None = None
    entry_price: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_distance: float | None = None
    reward_distance: float | None = None


def _positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) and parsed > 0 else default


def _snap_above(value: float, tick_size: float) -> float:
    size = max(float(tick_size), 1e-9)
    return round((math.floor(float(value) / size + 1e-9) + 1) * size, 10)


def _snap_below(value: float, tick_size: float) -> float:
    size = max(float(tick_size), 1e-9)
    return round((math.ceil(float(value) / size - 1e-9) - 1) * size, 10)


def _snap_down(value: float, tick_size: float) -> float:
    size = max(float(tick_size), 1e-9)
    return round(math.floor(float(value) / size + 1e-9) * size, 10)


def _snap_up(value: float, tick_size: float) -> float:
    size = max(float(tick_size), 1e-9)
    return round(math.ceil(float(value) / size - 1e-9) * size, 10)


def _consecutive_closed_candles(arm: PostCloseArm, confirmation: Candle) -> bool:
    arm_time = parse_utc(arm.confirmation_time)
    confirmation_time = parse_utc(confirmation.timestamp)
    gap = confirmation_time - arm_time
    return timedelta(0) < gap <= MAX_RECONFIRMATION_GAP


def reconfirm_arm(arm: PostCloseArm, confirmation: Candle) -> Reconfirmation:
    """Apply the symmetric second-closed-candle gate to an immutable arm."""
    if not _consecutive_closed_candles(arm, confirmation):
        return Reconfirmation(False, "RECONFIRMATION_TIME_INVALID", "mixed")

    family = arm.family
    direction = arm.direction
    confirmation_type = _confirmation_type(family, _arm_candle(arm), confirmation)
    direction_aligned = (
        (direction == "BUY" and is_bullish(confirmation))
        or (direction == "SELL" and is_bearish(confirmation))
    )
    if direction not in {"BUY", "SELL"}:
        return Reconfirmation(False, "UNKNOWN_SCALPER_DIRECTION", "mixed")
    if not direction_aligned:
        return Reconfirmation(False, "RECONFIRMATION_CANDLE_WEAK", confirmation_type)
    if confirmation_type == "mixed":
        # The first candle already created the fully classified signal.  The
        # second candle only has to prove that the frozen story still holds;
        # requiring it to create another legacy rejection/engulfing signal
        # makes two independent triggers a prerequisite for one entry.
        confirmation_type = "directional_hold"

    if family in {LOW_RESPECT_BUY, FAILED_LOW_BREAK_BUY}:
        zone_tested = float(confirmation.low) <= float(arm.zone_high)
        story_held = (
            direction_aligned and float(confirmation.close) >= float(arm.zone_high)
        )
    elif family in {HIGH_RESPECT_SELL, FAILED_HIGH_BREAK_SELL}:
        zone_tested = float(confirmation.high) >= float(arm.zone_low)
        story_held = (
            direction_aligned and float(confirmation.close) <= float(arm.zone_low)
        )
    elif family == HIGH_BREAK_BUY:
        zone_tested = float(confirmation.low) <= (
            float(arm.zone_high) + float(arm.break_margin)
        )
        story_held = (
            direction_aligned
            and float(confirmation.close)
            >= float(arm.zone_high) + float(arm.break_margin)
        )
    elif family == LOW_BREAK_SELL:
        zone_tested = float(confirmation.high) >= (
            float(arm.zone_low) - float(arm.break_margin)
        )
        story_held = (
            direction_aligned
            and float(confirmation.close)
            <= float(arm.zone_low) - float(arm.break_margin)
        )
    else:
        return Reconfirmation(False, "UNKNOWN_SCALPER_FAMILY", confirmation_type)

    if not zone_tested:
        return Reconfirmation(False, "FROZEN_ZONE_NOT_RETESTED", confirmation_type)
    if not story_held:
        return Reconfirmation(False, "FROZEN_STORY_NOT_RECONFIRMED", confirmation_type)
    return Reconfirmation(True, "RECONFIRMATION_ACCEPTED", confirmation_type)


def _arm_candle(arm: PostCloseArm) -> Candle:
    return Candle(
        timestamp=arm.confirmation_time,
        open=float(arm.confirmation_open),
        high=float(arm.confirmation_high),
        low=float(arm.confirmation_low),
        close=float(arm.confirmation_close),
    )


def build_order_geometry(
    arm: PostCloseArm,
    confirmation: Candle,
    *,
    bid: float,
    ask: float,
    spread: float,
    minimum_stop_distance: float,
    minimum_stop_spread_multiple: float = MINIMUM_STOP_SPREAD_MULTIPLE,
    maximum_stop_distance: float = MAXIMUM_STOP_DISTANCE,
    risk_reward: float = RISK_REWARD,
    tick_size: float = DEFAULT_TICK_SIZE,
) -> OrderGeometry:
    """Build a direction-safe pending entry, failing closed on unsafe geometry."""
    direction = arm.direction
    if (
        not all(math.isfinite(float(value)) for value in (bid, ask, spread))
        or float(bid) <= 0
        or float(ask) <= 0
        or float(ask) < float(bid)
        or float(spread) <= 0
    ):
        return OrderGeometry(False, "INVALID_DECISION_QUOTE", direction)

    tick = max(float(tick_size), 1e-9)
    minimum_risk = max(
        float(minimum_stop_distance),
        float(spread) * float(minimum_stop_spread_multiple),
        tick,
    )
    maximum_risk = float(maximum_stop_distance)
    if minimum_risk > maximum_risk + 1e-12:
        return OrderGeometry(False, "MINIMUM_STOP_EXCEEDS_MAXIMUM", direction)

    moved_away_limit = max(float(spread) * 3.0, 0.60)
    if direction == "BUY":
        entry = _snap_above(float(confirmation.high), tick)
        if float(ask) >= entry - 1e-12:
            return OrderGeometry(False, "BUY_STOP_ALREADY_CROSSED", direction)
        if entry - float(ask) > moved_away_limit + 1e-12:
            return OrderGeometry(False, "BUY_STORY_MOVED_AWAY", direction)
        if float(bid) <= float(arm.invalidation) + 1e-12:
            return OrderGeometry(False, "BUY_STORY_INVALIDATED", direction)
        structural_stop = min(
            float(arm.invalidation),
            float(confirmation.low) - tick,
        )
        stop = _snap_down(min(structural_stop, entry - minimum_risk), tick)
        risk = entry - stop
        if risk > maximum_risk + 1e-12:
            continuation_entry = entry
            continuation_risk = risk
            entry = _snap_down(stop + maximum_risk, tick)
            risk = entry - stop
            if entry > float(bid) - tick + 1e-12:
                return OrderGeometry(
                    False,
                    "RISK_CAPPED_PULLBACK_INSIDE_SPREAD",
                    direction,
                    entry_mode="RISK_CAPPED_PULLBACK",
                    entry_price=round(continuation_entry, 10),
                    stop_loss=round(stop, 10),
                    risk_distance=round(continuation_risk, 10),
                )
            if float(ask) - entry > moved_away_limit + 1e-12:
                return OrderGeometry(
                    False,
                    "RISK_CAPPED_PULLBACK_TOO_FAR",
                    direction,
                    entry_mode="RISK_CAPPED_PULLBACK",
                    entry_price=round(continuation_entry, 10),
                    stop_loss=round(stop, 10),
                    risk_distance=round(continuation_risk, 10),
                )
            if risk < minimum_risk - 1e-12:
                return OrderGeometry(
                    False,
                    "RISK_CAPPED_PULLBACK_BELOW_MINIMUM",
                    direction,
                    entry_mode="RISK_CAPPED_PULLBACK",
                    entry_price=round(entry, 10),
                    stop_loss=round(stop, 10),
                    risk_distance=round(risk, 10),
                )
            target = _snap_up(entry + risk * float(risk_reward), tick)
            return OrderGeometry(
                True,
                "ORDER_GEOMETRY_ACCEPTED",
                direction,
                entry_mode="RISK_CAPPED_PULLBACK",
                entry_price=round(entry, 10),
                stop_loss=round(stop, 10),
                take_profit=round(target, 10),
                risk_distance=round(risk, 10),
                reward_distance=round(abs(target - entry), 10),
            )
        target = _snap_up(entry + risk * float(risk_reward), tick)
    elif direction == "SELL":
        entry = _snap_below(float(confirmation.low), tick)
        if float(bid) <= entry + 1e-12:
            return OrderGeometry(False, "SELL_STOP_ALREADY_CROSSED", direction)
        if float(bid) - entry > moved_away_limit + 1e-12:
            return OrderGeometry(False, "SELL_STORY_MOVED_AWAY", direction)
        if float(ask) >= float(arm.invalidation) - 1e-12:
            return OrderGeometry(False, "SELL_STORY_INVALIDATED", direction)
        structural_stop = max(
            float(arm.invalidation),
            float(confirmation.high) + tick,
        )
        stop = _snap_up(max(structural_stop, entry + minimum_risk), tick)
        risk = stop - entry
        if risk > maximum_risk + 1e-12:
            continuation_entry = entry
            continuation_risk = risk
            entry = _snap_up(stop - maximum_risk, tick)
            risk = stop - entry
            if entry < float(ask) + tick - 1e-12:
                return OrderGeometry(
                    False,
                    "RISK_CAPPED_PULLBACK_INSIDE_SPREAD",
                    direction,
                    entry_mode="RISK_CAPPED_PULLBACK",
                    entry_price=round(continuation_entry, 10),
                    stop_loss=round(stop, 10),
                    risk_distance=round(continuation_risk, 10),
                )
            if entry - float(bid) > moved_away_limit + 1e-12:
                return OrderGeometry(
                    False,
                    "RISK_CAPPED_PULLBACK_TOO_FAR",
                    direction,
                    entry_mode="RISK_CAPPED_PULLBACK",
                    entry_price=round(continuation_entry, 10),
                    stop_loss=round(stop, 10),
                    risk_distance=round(continuation_risk, 10),
                )
            if risk < minimum_risk - 1e-12:
                return OrderGeometry(
                    False,
                    "RISK_CAPPED_PULLBACK_BELOW_MINIMUM",
                    direction,
                    entry_mode="RISK_CAPPED_PULLBACK",
                    entry_price=round(entry, 10),
                    stop_loss=round(stop, 10),
                    risk_distance=round(risk, 10),
                )
            target = _snap_down(entry - risk * float(risk_reward), tick)
            return OrderGeometry(
                True,
                "ORDER_GEOMETRY_ACCEPTED",
                direction,
                entry_mode="RISK_CAPPED_PULLBACK",
                entry_price=round(entry, 10),
                stop_loss=round(stop, 10),
                take_profit=round(target, 10),
                risk_distance=round(risk, 10),
                reward_distance=round(abs(target - entry), 10),
            )
        target = _snap_down(entry - risk * float(risk_reward), tick)
    else:
        return OrderGeometry(False, "INVALID_DIRECTION", direction)

    if risk <= 0 or not math.isfinite(risk):
        return OrderGeometry(False, "INVALID_RISK_GEOMETRY", direction)
    reward = abs(target - entry)
    return OrderGeometry(
        True,
        "ORDER_GEOMETRY_ACCEPTED",
        direction,
        entry_mode="CONTINUATION_STOP",
        entry_price=round(entry, 10),
        stop_loss=round(stop, 10),
        take_profit=round(target, 10),
        risk_distance=round(risk, 10),
        reward_distance=round(reward, 10),
    )


def _candidate_row(
    arm: PostCloseArm,
    confirmation: Candle,
    reconfirmation: Reconfirmation,
    geometry: OrderGeometry | None,
    spread: float,
) -> dict[str, Any]:
    accepted = reconfirmation.accepted and bool(geometry and geometry.accepted)
    reason = (
        geometry.reason
        if reconfirmation.accepted and geometry is not None
        else reconfirmation.reason
    )
    risk_distance = geometry.risk_distance if geometry else None
    return {
        "model_name": CANDIDATE_NAME,
        "trigger": arm.family,
        "direction": arm.direction,
        "reaction_type": "closed_candle_reconfirmation",
        "confirmation_type": reconfirmation.confirmation_type,
        "level": arm.level,
        "level_side": arm.level_side,
        "level_type": "three_touch" if arm.touch_count >= 3 else "two_touch",
        "touch_count": arm.touch_count,
        "score": 10.0 if accepted else 0.0,
        "minimum_required_score": 8.0,
        "approved": accepted,
        "entry_mode": geometry.entry_mode if geometry else None,
        "score_reasons": (
            ["CLEAN_LEVEL_ARM", "SECOND_CLOSED_CANDLE_RECONFIRMED", "QUOTE_SAFE"]
            if accepted
            else []
        ),
        "rejection_reasons": [] if accepted else [reason],
        "entry_price": geometry.entry_price if geometry else None,
        "stop_loss": geometry.stop_loss if geometry else None,
        "take_profit": geometry.take_profit if geometry else None,
        "risk_distance": risk_distance,
        "reward_distance": geometry.reward_distance if geometry else None,
        "volume_decision": "STANDARD_FIXED_VOLUME" if accepted else "REJECTED",
        "volume_multiplier": 1.0 if accepted else None,
        "opening_context": {
            "model_name": CANDIDATE_NAME,
            "arm_id": arm.arm_id,
            "arm_timestamp": arm.confirmation_time,
            "confirmation_timestamp": confirmation.timestamp,
            "family": arm.family,
            "direction": arm.direction,
            "level": arm.level,
            "zone_low": arm.zone_low,
            "zone_high": arm.zone_high,
            "tolerance": arm.tolerance,
            "touch_count": arm.touch_count,
            "entry_mode": geometry.entry_mode if geometry else None,
        },
        "signal_quality": {
            "quote_pressure_used": False,
            "true_order_flow_claimed": False,
            "second_closed_candle_required": True,
            "current_spread_price": round(float(spread), 4),
            "stop_to_spread_ratio": round(
                float(risk_distance) / float(spread)
                if risk_distance and spread > 0
                else 0.0,
                4,
            ),
        },
    }


def _hold_payload(
    symbol: str,
    as_of: str,
    history: list[Candle],
    market_context: dict[str, Any],
    message: str,
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    checklist = _base_checklist()
    checklist["playbook_setup"] = "failed"
    checklist["fast_trigger_quality"] = "failed"
    return _payload(
        symbol,
        as_of,
        status="NO_SETUP",
        recommendation="HOLD",
        history=history,
        checklist=checklist,
        market_context=market_context,
        candidate_evaluations=rows or [],
        selected_candidate=(rows or [None])[0],
        decision_stage="one_minute_closed_candle_gate",
        message=message,
    )


def analyze_one_minute_scalper(
    symbol: str,
    as_of: str,
    timeframe_data: dict[str, Any],
    *,
    session_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a proposal only after arm, reconfirmation, quote, and geometry pass."""
    config = session_config or {}
    all_candles = normalize_candles(timeframe_data.get("1m"))
    history = all_candles[-HISTORY_CANDLES:]
    bid = _positive_float(config.get("current_bid_price"), 0.0)
    ask = _positive_float(config.get("current_ask_price"), 0.0)
    spread = _positive_float(
        config.get("current_spread_price", config.get("spread_price")),
        max(0.0, ask - bid),
    )
    minimum_stop_distance = _positive_float(
        config.get("minimum_stop_distance_price"),
        0.35,
    )
    minimum_stop_spread_multiple = max(
        _positive_float(config.get("minimum_stop_spread_multiple"), 1.2),
        _positive_float(config.get("fast_min_stop_spread_multiple"), 1.2),
    )
    maximum_stop_distance = _positive_float(
        config.get("fast_max_stop_distance_price"),
        MAXIMUM_STOP_DISTANCE,
    )
    risk_reward = _positive_float(config.get("fast_risk_reward"), RISK_REWARD)
    tick_size = _positive_float(
        config.get("trade_tick_size", config.get("tick_size")),
        DEFAULT_TICK_SIZE,
    )
    story = {
        "model_name": CANDIDATE_NAME,
        "classification": "WAITING_FOR_TWO_CLOSED_CANDLES",
        "history_candles": len(history),
        "history_window_candles": HISTORY_CANDLES,
        "current_spread_price": round(spread, 4),
        "current_bid_price": round(bid, 4),
        "current_ask_price": round(ask, 4),
        "minimum_stop_spread_multiple": round(minimum_stop_spread_multiple, 4),
        "quote_pressure_used": False,
        "true_order_flow_claimed": False,
    }
    market_context = {
        "entry_profile": "fast",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "activation_window_minutes": 1,
        "one_minute_story": story,
        "fast_microstructure": {
            "enabled": True,
            "candidate": CANDIDATE_NAME,
            "history_window_candles": HISTORY_CANDLES,
            "trigger_selection": "clean_level_two_closed_candle_reconfirmation",
            "quote_pressure_used": False,
            "rules": sorted(BUY_FAMILIES | SELL_FAMILIES),
        },
    }

    if len(history) < HISTORY_CANDLES:
        return _hold_payload(
            symbol,
            as_of,
            history,
            market_context,
            "Exactly 60 fully closed M1 candles are required.",
        )
    if bid <= 0 or ask <= 0 or spread <= 0:
        return _hold_payload(
            symbol,
            as_of,
            history,
            market_context,
            "A valid fresh bid/ask quote is required after reconfirmation.",
        )

    confirmation = history[-1]
    arms = detect_post_close_arms(
        history[:-1],
        history_candles=HISTORY_CANDLES,
        clean_levels=True,
        candidate_name=CANDIDATE_NAME,
    )
    if not arms:
        return _hold_payload(
            symbol,
            as_of,
            history,
            market_context,
            "The preceding closed candle did not arm a clean symmetric story.",
        )

    rows: list[dict[str, Any]] = []
    selected: tuple[PostCloseArm, Reconfirmation, OrderGeometry, dict[str, Any]] | None = None
    for arm in arms:
        reconfirmation = reconfirm_arm(arm, confirmation)
        geometry = (
            build_order_geometry(
                arm,
                confirmation,
                bid=bid,
                ask=ask,
                spread=spread,
                minimum_stop_distance=minimum_stop_distance,
                minimum_stop_spread_multiple=minimum_stop_spread_multiple,
                maximum_stop_distance=maximum_stop_distance,
                risk_reward=risk_reward,
                tick_size=tick_size,
            )
            if reconfirmation.accepted
            else None
        )
        row = _candidate_row(arm, confirmation, reconfirmation, geometry, spread)
        rows.append(row)
        if reconfirmation.accepted and geometry and geometry.accepted and selected is None:
            selected = (arm, reconfirmation, geometry, row)

    if selected is None:
        return _hold_payload(
            symbol,
            as_of,
            history,
            market_context,
            "Armed stories failed reconfirmation, quote safety, or stop geometry.",
            rows,
        )

    arm, reconfirmation, geometry, selected_row = selected
    risk_distance = float(geometry.risk_distance or 0.0)
    risk = {
        "approved": True,
        "reason": "Causal closed-candle reconfirmation and quote-safe stop geometry passed.",
        "entry_price": geometry.entry_price,
        "entry_mode": geometry.entry_mode,
        "stop_loss": geometry.stop_loss,
        "take_profit": geometry.take_profit,
        "risk_distance": risk_distance,
        "reward_distance": geometry.reward_distance,
        "risk_reward": round(
            float(geometry.reward_distance or 0.0) / risk_distance
            if risk_distance > 0
            else 0.0,
            4,
        ),
        "volume_multiplier": 1.0,
        "position_lifecycle": "FAST_PARTIAL_SCALE",
        **_dynamic_fast_exit_settings(risk_distance, spread),
    }
    zone = _level_zone(
        level_type="support" if arm.level_side == "low" else "resistance",
        level=float(arm.level),
        tolerance=float(arm.tolerance),
        touches=int(arm.touch_count),
    )
    setup = {
        "name": CANDIDATE_NAME,
        "strategy_type": CANDIDATE_NAME,
        "direction": arm.direction,
        "zone": asdict(zone),
        "entry_price": geometry.entry_price,
        "entry_mode": geometry.entry_mode,
        "stop_loss": geometry.stop_loss,
        "take_profit": geometry.take_profit,
        "confirmation_candle": asdict(confirmation),
        "setup_grade": "A_PLUS",
        "risk_distance": risk_distance,
        "reward_distance": geometry.reward_distance,
        "risk_reward": risk["risk_reward"],
        "volume_multiplier": 1.0,
        "position_lifecycle": "FAST_PARTIAL_SCALE",
    }
    story.update(
        {
            "classification": arm.family,
            "direction": arm.direction,
            "arm_id": arm.arm_id,
            "arm_timestamp": arm.confirmation_time,
            "confirmation_timestamp": confirmation.timestamp,
            "confirmation_type": reconfirmation.confirmation_type,
            "level": arm.level,
            "touch_count": arm.touch_count,
        }
    )
    checklist = _base_checklist()
    checklist["playbook_setup"] = "passed"
    checklist["fast_trigger_quality"] = "passed"
    checklist["clean_range_to_fill"] = "passed"
    return _payload(
        symbol,
        as_of,
        status="SETUP_FOUND",
        recommendation=arm.direction,
        history=history,
        checklist=checklist,
        market_context=market_context,
        setups=[setup],
        zones=[zone],
        risk=risk,
        candidate_evaluations=rows,
        selected_candidate=selected_row,
        decision_stage="one_minute_closed_candle_proposal",
        message=(
            f"{CANDIDATE_NAME} selected {arm.family} after a second fully "
            "closed M1 candle reconfirmed the frozen story."
        ),
    )


def detect_reconfirmed_arms(
    candles: Iterable[Candle],
) -> tuple[tuple[PostCloseArm, Reconfirmation], ...]:
    """Broker-free helper used by deterministic tests and evidence tooling."""
    history = list(candles)[-HISTORY_CANDLES:]
    if len(history) < HISTORY_CANDLES:
        return ()
    confirmation = history[-1]
    return tuple(
        (arm, reconfirm_arm(arm, confirmation))
        for arm in detect_post_close_arms(
            history[:-1],
            history_candles=HISTORY_CANDLES,
            clean_levels=True,
            candidate_name=CANDIDATE_NAME,
        )
    )


__all__ = [
    "BUY_FAMILIES",
    "CANDIDATE_NAME",
    "HISTORY_CANDLES",
    "MAXIMUM_STOP_DISTANCE",
    "MINIMUM_STOP_SPREAD_MULTIPLE",
    "OrderGeometry",
    "RISK_REWARD",
    "Reconfirmation",
    "SELL_FAMILIES",
    "analyze_one_minute_scalper",
    "build_order_geometry",
    "detect_reconfirmed_arms",
    "reconfirm_arm",
]
