"""Dedicated deterministic entry model for closed one-minute candles."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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
MODEL_NAME = "One Minute Scalper"
TWO_TOUCH = "two_touch"
THREE_TOUCH = "three_touch"

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


@dataclass(frozen=True)
class OneMinuteLevel:
    side: str
    level: float
    touch_count: int
    first_touch_index: int
    last_touch_index: int
    spread: float
    tolerance: float

    @property
    def level_type(self) -> str:
        return THREE_TOUCH if self.touch_count >= 3 else TWO_TOUCH


@dataclass
class OneMinuteCandidate:
    trigger: str
    direction: str
    reaction_type: str
    confirmation_type: str
    level: OneMinuteLevel
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_distance: float
    reward_distance: float
    risk: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    approved: bool = False
    score_reasons: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    volume_decision: str = "REJECTED"
    volume_multiplier: float | None = None


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


def _detect_equal_levels(
    candles: list[Candle],
    tolerance: float,
    *,
    side: str,
) -> list[OneMinuteLevel]:
    prices = [
        float(candle.high if side == "high" else candle.low)
        for candle in candles
    ]
    levels: list[OneMinuteLevel] = []
    for _index, price in enumerate(prices):
        touches = [
            (touch_index, candidate)
            for touch_index, candidate in enumerate(prices)
            if abs(candidate - price) <= tolerance
        ]
        if len(touches) < 2:
            continue
        level = sum(candidate for _touch_index, candidate in touches) / len(touches)
        if any(abs(existing.level - level) <= tolerance for existing in levels):
            continue
        touch_prices = [candidate for _touch_index, candidate in touches]
        levels.append(
            OneMinuteLevel(
                side=side,
                level=level,
                touch_count=len(touches),
                first_touch_index=min(touch_index for touch_index, _price in touches),
                last_touch_index=max(touch_index for touch_index, _price in touches),
                spread=max(touch_prices) - min(touch_prices),
                tolerance=tolerance,
            )
        )
    return sorted(
        levels,
        key=lambda item: (-item.touch_count, -item.last_touch_index, item.spread),
    )


def _body_size(candle: Candle) -> float:
    return abs(float(candle.close) - float(candle.open))


def _body_top(candle: Candle) -> float:
    return max(float(candle.open), float(candle.close))


def _body_bottom(candle: Candle) -> float:
    return min(float(candle.open), float(candle.close))


def _close_position(candle: Candle) -> float:
    total = candle_range(candle)
    if total <= 0:
        return 0.5
    return (float(candle.close) - float(candle.low)) / total


def _bullish_engulfing(previous: Candle, latest: Candle) -> bool:
    return (
        is_bearish(previous)
        and is_bullish(latest)
        and _body_bottom(latest) <= _body_bottom(previous)
        and _body_top(latest) >= _body_top(previous)
        and _close_position(latest) >= 0.65
    )


def _bearish_engulfing(previous: Candle, latest: Candle) -> bool:
    return (
        is_bullish(previous)
        and is_bearish(latest)
        and _body_top(latest) >= _body_top(previous)
        and _body_bottom(latest) <= _body_bottom(previous)
        and _close_position(latest) <= 0.35
    )


def _strong_bullish_close(candle: Candle) -> bool:
    total = candle_range(candle)
    return (
        total > 0
        and is_bullish(candle)
        and _body_size(candle) >= total * 0.45
        and _close_position(candle) >= 0.70
    )


def _strong_bearish_close(candle: Candle) -> bool:
    total = candle_range(candle)
    return (
        total > 0
        and is_bearish(candle)
        and _body_size(candle) >= total * 0.45
        and _close_position(candle) <= 0.30
    )


def _decisive_directional_close(direction: str, candle: Candle) -> bool:
    position = _close_position(candle)
    if direction == "BUY":
        return position >= 0.82 and _strong_bullish_close(candle)
    if direction == "SELL":
        return position <= 0.18 and _strong_bearish_close(candle)
    return False


def _confirmation_type(trigger: str, previous: Candle, latest: Candle) -> str:
    if trigger in {LOW_RESPECT_BUY, FAILED_LOW_BREAK_BUY}:
        if _bullish_engulfing(previous, latest):
            return "engulfing"
        if _bullish_rejection(latest):
            return "rejection"
        if _strong_bullish_close(latest):
            return "strong_close"
        return "mixed"
    if trigger in {HIGH_RESPECT_SELL, FAILED_HIGH_BREAK_SELL}:
        if _bearish_engulfing(previous, latest):
            return "engulfing"
        if _bearish_rejection(latest):
            return "rejection"
        if _strong_bearish_close(latest):
            return "strong_close"
        return "mixed"
    if trigger == HIGH_BREAK_BUY and _strong_bullish_close(latest):
        return "strong_close"
    if trigger == LOW_BREAK_SELL and _strong_bearish_close(latest):
        return "strong_close"
    return "mixed"


def _is_overlapping_chop(candles: list[Candle]) -> bool:
    if len(candles) < 8:
        return False
    recent = candles[-8:]
    ranges = [candle_range(candle) for candle in recent if candle_range(candle) > 0]
    if not ranges:
        return True
    highs = [float(candle.high) for candle in recent]
    lows = [float(candle.low) for candle in recent]
    closes = [float(candle.close) for candle in recent]
    median_range = median(ranges)
    total_range = max(highs) - min(lows)
    close_range = max(closes) - min(closes)
    alternating = sum(
        1
        for left, right in zip(recent, recent[1:])
        if (is_bullish(left) and is_bearish(right))
        or (is_bearish(left) and is_bullish(right))
    )
    return (
        alternating >= 5
        and total_range <= median_range * 2.2
        and close_range <= median_range * 0.8
    )


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
        "microstructure_confidence": "NORMAL",
        "fast_trigger_quality": {
            "trigger": name,
            "level": round(level, 4),
            "tolerance": round(tolerance, 4),
            "minimum_stop_distance": round(minimum_stop_distance, 4),
        },
        "position_lifecycle": "FAST_PARTIAL_SCALE",
        **_dynamic_fast_exit_settings(risk_distance),
    }
    return risk


def _candidate_from_level(
    level: OneMinuteLevel,
    previous: Candle,
    latest: Candle,
    *,
    tolerance: float,
    minimum_stop_distance: float,
    max_stop_distance: float,
    boost_max_stop_distance: float,
    risk_reward: float,
) -> OneMinuteCandidate | None:
    break_margin = max(0.05, tolerance * 0.25)
    level_kind = "support" if level.side == "low" else "resistance"
    if level.side == "low":
        if (
            float(latest.low) < level.level - break_margin
            and float(latest.close) > level.level
        ):
            trigger_name = FAILED_LOW_BREAK_BUY
            direction = "BUY"
            reaction_type = "fakeout"
        elif float(latest.close) < level.level - break_margin:
            trigger_name = LOW_BREAK_SELL
            direction = "SELL"
            reaction_type = "break"
        elif (
            abs(float(latest.low) - level.level) <= tolerance
            and float(latest.close) > level.level
        ):
            trigger_name = LOW_RESPECT_BUY
            direction = "BUY"
            reaction_type = "respect"
        else:
            return None
    else:
        if (
            float(latest.high) > level.level + break_margin
            and float(latest.close) < level.level
        ):
            trigger_name = FAILED_HIGH_BREAK_SELL
            direction = "SELL"
            reaction_type = "fakeout"
        elif float(latest.close) > level.level + break_margin:
            trigger_name = HIGH_BREAK_BUY
            direction = "BUY"
            reaction_type = "break"
        elif (
            abs(float(latest.high) - level.level) <= tolerance
            and float(latest.close) < level.level
        ):
            trigger_name = HIGH_RESPECT_SELL
            direction = "SELL"
            reaction_type = "respect"
        else:
            return None

    trigger = _trigger(trigger_name, direction, level_kind, {
        "level": level.level,
        "touches": level.touch_count,
    })
    risk = _risk_for_trigger(
        trigger,
        latest,
        tolerance=tolerance,
        minimum_stop_distance=minimum_stop_distance,
        max_stop_distance=max_stop_distance,
        boost_max_stop_distance=boost_max_stop_distance,
        risk_reward=risk_reward,
    )
    confirmation = _confirmation_type(trigger_name, previous, latest)
    if not risk.get("approved"):
        candidate = OneMinuteCandidate(
            trigger=trigger_name,
            direction=direction,
            reaction_type=reaction_type,
            confirmation_type=confirmation,
            level=level,
            entry_price=float(latest.close),
            stop_loss=float(latest.close),
            take_profit=float(latest.close),
            risk_distance=0.0,
            reward_distance=0.0,
            risk=risk,
        )
        candidate.rejection_reasons.append(str(risk.get("reason") or "RISK_REJECTED"))
        return candidate

    return OneMinuteCandidate(
        trigger=trigger_name,
        direction=direction,
        reaction_type=reaction_type,
        confirmation_type=confirmation,
        level=level,
        entry_price=float(risk["entry_price"]),
        stop_loss=float(risk["stop_loss"]),
        take_profit=float(risk["take_profit"]),
        risk_distance=float(risk["risk_distance"]),
        reward_distance=float(risk["reward_distance"]),
        risk=risk,
    )


def _score_candidate(
    candidate: OneMinuteCandidate,
    latest: Candle,
    *,
    is_chop: bool,
    boost_max_stop_distance: float,
) -> OneMinuteCandidate:
    initial_rejections = list(candidate.rejection_reasons)
    candidate.score = 0.0
    candidate.score_reasons = []
    candidate.rejection_reasons = initial_rejections

    candidate.score += 2
    candidate.score_reasons.append("TWO_TOUCH_LEVEL")
    if candidate.level.touch_count >= 3:
        candidate.score += 2
        candidate.score_reasons.append("THIRD_TOUCH_PRIORITY")
    if candidate.confirmation_type == "rejection":
        candidate.score += 2
        candidate.score_reasons.append("CLEAN_REJECTION")
    elif candidate.confirmation_type == "engulfing":
        candidate.score += 2
        candidate.score_reasons.append("ENGULFING_CONFIRMATION")
    elif candidate.confirmation_type == "strong_close":
        candidate.score += 2
        candidate.score_reasons.append("STRONG_CLOSE")
    if _decisive_directional_close(candidate.direction, latest):
        candidate.score += 2
        candidate.score_reasons.append("DECISIVE_CLOSE")
    if candidate.risk_distance > 0 and candidate.risk_distance <= boost_max_stop_distance:
        candidate.score += 2
        candidate.score_reasons.append("CLOSE_INVALIDATION")

    if candidate.confirmation_type == "mixed":
        candidate.score -= 3
        candidate.rejection_reasons.append("LATEST_CANDLE_NOT_CONFIRMING")
        candidate.rejection_reasons.append("MIXED_CONFIRMATION")
    if is_chop:
        candidate.score -= 3
        candidate.rejection_reasons.append("OVERLAPPING_CHOP")
    if candidate.risk_distance <= 0:
        candidate.rejection_reasons.append("INVALID_STOP_DISTANCE")

    candidate.rejection_reasons = list(dict.fromkeys(candidate.rejection_reasons))
    candidate.approved = candidate.score >= 6 and not candidate.rejection_reasons
    if not candidate.approved:
        candidate.volume_decision = "REJECTED"
        candidate.volume_multiplier = None
        return candidate

    high_confidence = (
        candidate.score >= 8
        and candidate.confirmation_type in {"engulfing", "rejection"}
        and candidate.risk_distance <= boost_max_stop_distance
        and candidate.trigger in HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS
    )
    if high_confidence:
        candidate.volume_decision = "BOOST_1_5"
        candidate.volume_multiplier = 1.5
        candidate.risk["volume_multiplier"] = 1.5
        candidate.risk["microstructure_confidence"] = "HIGH"
    else:
        candidate.volume_decision = "BASE_1_0"
        candidate.volume_multiplier = None
        candidate.risk.pop("volume_multiplier", None)
        candidate.risk["microstructure_confidence"] = "NORMAL"
    candidate.risk["fast_trigger_quality"] = {
        **candidate.risk.get("fast_trigger_quality", {}),
        "score": round(candidate.score, 2),
        "score_reasons": list(candidate.score_reasons),
        "volume_decision": candidate.volume_decision,
    }
    return candidate


def _build_candidates(
    history: list[Candle],
    *,
    tolerance: float,
    minimum_stop_distance: float,
    max_stop_distance: float,
    boost_max_stop_distance: float,
    risk_reward: float,
) -> list[OneMinuteCandidate]:
    latest = history[-1]
    previous = history[-2]
    prior = history[:-1]
    levels = [
        *_detect_equal_levels(prior, tolerance, side="low"),
        *_detect_equal_levels(prior, tolerance, side="high"),
    ]
    touched_low_level = any(
        level.side == "low" and abs(float(latest.low) - level.level) <= tolerance
        for level in levels
    )
    touched_high_level = any(
        level.side == "high" and abs(float(latest.high) - level.level) <= tolerance
        for level in levels
    )
    is_chop = _is_overlapping_chop(history)
    candidates: list[OneMinuteCandidate] = []
    seen: set[tuple[str, str, int]] = set()
    for level in levels:
        if (
            level.side == "low"
            and touched_low_level
            and abs(float(latest.low) - level.level) > tolerance
            and float(latest.close) > level.level
        ):
            continue
        if (
            level.side == "high"
            and touched_high_level
            and abs(float(latest.high) - level.level) > tolerance
            and float(latest.close) < level.level
        ):
            continue
        candidate = _candidate_from_level(
            level,
            previous,
            latest,
            tolerance=tolerance,
            minimum_stop_distance=minimum_stop_distance,
            max_stop_distance=max_stop_distance,
            boost_max_stop_distance=boost_max_stop_distance,
            risk_reward=risk_reward,
        )
        if candidate is None:
            continue
        key = (
            candidate.trigger,
            candidate.level.side,
            round(candidate.level.level / max(tolerance, 0.0001)),
        )
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            _score_candidate(
                candidate,
                latest,
                is_chop=is_chop,
                boost_max_stop_distance=boost_max_stop_distance,
            )
        )
    return sorted(
        candidates,
        key=lambda item: (
            item.approved,
            item.score,
            item.level.touch_count,
            item.level.last_touch_index,
            -item.risk_distance,
        ),
        reverse=True,
    )


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


def _candidate_to_trigger(candidate: OneMinuteCandidate) -> dict[str, Any]:
    return _trigger(
        candidate.trigger,
        candidate.direction,
        "support" if candidate.level.side == "low" else "resistance",
        {
            "level": candidate.level.level,
            "touches": candidate.level.touch_count,
        },
    )


def _candidate_to_setup(
    candidate: OneMinuteCandidate,
    latest: Candle,
    zone: Zone,
) -> dict[str, Any]:
    return _setup_to_dict(
        _candidate_to_trigger(candidate),
        latest,
        zone,
        candidate.risk,
    )


def _candidate_to_telemetry(candidate: OneMinuteCandidate) -> dict[str, Any]:
    return {
        "model_name": MODEL_NAME,
        "trigger": candidate.trigger,
        "direction": candidate.direction,
        "reaction_type": candidate.reaction_type,
        "confirmation_type": candidate.confirmation_type,
        "level": round(candidate.level.level, 4),
        "level_side": candidate.level.side,
        "level_type": candidate.level.level_type,
        "touch_count": candidate.level.touch_count,
        "score": round(candidate.score, 2),
        "approved": candidate.approved,
        "score_reasons": list(candidate.score_reasons),
        "rejection_reasons": list(candidate.rejection_reasons),
        "entry_price": round(candidate.entry_price, 4),
        "stop_loss": round(candidate.stop_loss, 4),
        "take_profit": round(candidate.take_profit, 4),
        "risk_distance": round(candidate.risk_distance, 4),
        "reward_distance": round(candidate.reward_distance, 4),
        "volume_decision": candidate.volume_decision,
        "volume_multiplier": candidate.volume_multiplier,
    }


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
    candidate_evaluations: list[dict[str, Any]] | None = None,
    selected_candidate: dict[str, Any] | None = None,
    decision_stage: str | None = None,
) -> dict[str, Any]:
    if decision_stage is None:
        if status == "SETUP_FOUND":
            decision_stage = "one_minute_setup_found"
        elif risk and risk.get("approved") is False:
            decision_stage = "one_minute_risk_rejected"
        else:
            decision_stage = "one_minute_no_trigger"
    candidate_rows = candidate_evaluations or []
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
            "model_name": MODEL_NAME,
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "decision_stage": decision_stage,
            "primary_hold_reason": message,
            "timeframe_rows": {"1m": len(history)},
            "zone_counts": {"1m": len(zones or [])},
            "market_state": {},
            "candidate_setup_count": (
                len(candidate_rows)
                if candidate_evaluations is not None
                else len(setups or [])
            ),
            "approved_candidate_count": (
                sum(1 for item in candidate_rows if item.get("approved"))
                if candidate_evaluations is not None
                else 1 if status == "SETUP_FOUND" else 0
            ),
            "candidate_evaluations": candidate_rows,
            "selected_candidate": selected_candidate,
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
        "model_name": MODEL_NAME,
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
    candidate_evaluations: list[dict[str, Any]] = []

    if len(history) < min_candles:
        return _payload(
            symbol,
            as_of,
            status="NO_SETUP",
            recommendation="HOLD",
            history=history,
            checklist=checklist,
            market_context=market_context,
            candidate_evaluations=candidate_evaluations,
            message="Not enough closed 1m candles for the fast entry model.",
        )

    if len(history) < 2:
        return _payload(
            symbol,
            as_of,
            status="NO_SETUP",
            recommendation="HOLD",
            history=history,
            checklist=checklist,
            market_context=market_context,
            candidate_evaluations=candidate_evaluations,
            message="Not enough closed 1m candles for candidate comparison.",
        )

    latest = history[-1]
    candidates = _build_candidates(
        history,
        tolerance=tolerance,
        minimum_stop_distance=minimum_stop_distance,
        max_stop_distance=max_stop_distance,
        boost_max_stop_distance=boost_max_stop_distance,
        risk_reward=risk_reward,
    )
    candidate_evaluations = [_candidate_to_telemetry(candidate) for candidate in candidates]
    approved_candidates = [candidate for candidate in candidates if candidate.approved]

    if not candidates:
        return _payload(
            symbol,
            as_of,
            status="NO_SETUP",
            recommendation="HOLD",
            history=history,
            checklist=checklist,
            market_context=market_context,
            candidate_evaluations=candidate_evaluations,
            message="No explicit one-minute trigger from the latest closed candle.",
        )

    if not approved_candidates:
        checklist["playbook_setup"] = FAIL
        checklist["fast_trigger_quality"] = FAIL
        checklist["clean_range_to_fill"] = FAIL
        selected_rejected = candidate_evaluations[0] if candidate_evaluations else None
        return _payload(
            symbol,
            as_of,
            status="NO_SETUP",
            recommendation="HOLD",
            history=history,
            checklist=checklist,
            market_context=market_context,
            candidate_evaluations=candidate_evaluations,
            selected_candidate=selected_rejected,
            decision_stage="one_minute_no_approved_candidate",
            message="One Minute Scalper found candidates but none passed scoring.",
        )

    selected = approved_candidates[0]
    selected_telemetry = _candidate_to_telemetry(selected)
    risk = dict(selected.risk)
    story.update(
        {
            "classification": selected.trigger,
            "direction": selected.direction,
            "level": round(float(selected.level.level), 4),
            "touch_count": selected.level.touch_count,
            "level_type": selected.level.level_type,
            "reaction_type": selected.reaction_type,
            "confirmation_type": selected.confirmation_type,
            "score": round(selected.score, 2),
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
        level_type="support" if selected.level.side == "low" else "resistance",
        level=float(selected.level.level),
        tolerance=tolerance,
        touches=int(selected.level.touch_count),
    )
    setup = _candidate_to_setup(selected, latest, zone)
    return _payload(
        symbol,
        as_of,
        status="SETUP_FOUND",
        recommendation=selected.direction,
        history=history,
        checklist=checklist,
        market_context=market_context,
        setups=[setup],
        zones=[zone],
        risk=risk,
        candidate_evaluations=candidate_evaluations,
        selected_candidate=selected_telemetry,
        message=f"One Minute Scalper selected {selected.trigger} from the latest closed candle.",
    )


__all__ = [
    "HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS",
    "analyze_one_minute_entry",
]
