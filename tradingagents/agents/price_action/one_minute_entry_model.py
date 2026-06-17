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
MINIMUM_CANDLES_FOR_COMPARISON = 2
DEFAULT_MAX_STOP_DISTANCE = 2.0
DEFAULT_BOOST_MAX_STOP_DISTANCE = 1.2
DEFAULT_MIN_CANDIDATE_SCORE = 8.0
DEFAULT_MIN_STOP_SPREAD_MULTIPLE = 2.0
DEFAULT_RISK_REWARD = 1.5
MINIMUM_STOP_DISTANCE_BUFFER = 0.05
MODEL_NAME = "One Minute Scalper"
TWO_TOUCH = "two_touch"
THREE_TOUCH = "three_touch"
RAW_BREAK_EXECUTION_DISABLED = "RAW_BREAK_EXECUTION_DISABLED"
SPREAD_SAFE_STOP_TOO_WIDE = "SPREAD_SAFE_STOP_TOO_WIDE"
SPREAD_SAFE_STOP_ADJUSTED = "SPREAD_SAFE_STOP_ADJUSTED"
CONFLICTED_ONE_MINUTE_MEMORY = "CONFLICTED_ONE_MINUTE_MEMORY"
RESPECT_ENTRY_CONFLICTS_WITH_LATEST_RELATION = (
    "RESPECT_ENTRY_CONFLICTS_WITH_LATEST_RELATION"
)

LOW_RESPECT_BUY = "LOW_RESPECT_BUY"
HIGH_RESPECT_SELL = "HIGH_RESPECT_SELL"
LOW_BREAK_SELL = "LOW_BREAK_SELL"
HIGH_BREAK_BUY = "HIGH_BREAK_BUY"
CLEAN_LOW_IMPULSE_SELL = "CLEAN_LOW_IMPULSE_SELL"
CLEAN_HIGH_IMPULSE_BUY = "CLEAN_HIGH_IMPULSE_BUY"
FAILED_LOW_BREAK_BUY = "FAILED_LOW_BREAK_BUY"
FAILED_HIGH_BREAK_SELL = "FAILED_HIGH_BREAK_SELL"

HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS = {
    LOW_RESPECT_BUY,
    HIGH_RESPECT_SELL,
    FAILED_LOW_BREAK_BUY,
    FAILED_HIGH_BREAK_SELL,
}

RESPECT_ONE_MINUTE_TRIGGERS = {
    LOW_RESPECT_BUY,
    HIGH_RESPECT_SELL,
}

FAKEOUT_ONE_MINUTE_TRIGGERS = {
    FAILED_LOW_BREAK_BUY,
    FAILED_HIGH_BREAK_SELL,
}

RAW_BREAK_ONE_MINUTE_TRIGGERS = {
    LOW_BREAK_SELL,
    HIGH_BREAK_BUY,
}

CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS = {
    CLEAN_LOW_IMPULSE_SELL,
    CLEAN_HIGH_IMPULSE_BUY,
}

MEMORY_OVERRIDE_ONE_MINUTE_TRIGGERS = {
    *FAKEOUT_ONE_MINUTE_TRIGGERS,
    *CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS,
}

BREAK_ONE_MINUTE_TRIGGERS = {
    *RAW_BREAK_ONE_MINUTE_TRIGGERS,
    *CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS,
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
    minimum_required_score: float = DEFAULT_MIN_CANDIDATE_SCORE
    approved: bool = False
    score_reasons: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    volume_decision: str = "REJECTED"
    volume_multiplier: float | None = None


@dataclass(frozen=True)
class OneMinuteCandleRelation:
    equal_high: bool
    equal_low: bool
    higher_high: bool
    higher_low: bool
    lower_high: bool
    lower_low: bool
    broke_high_zone: bool
    broke_low_zone: bool
    rejected_high_zone: bool
    rejected_low_zone: bool
    failed_high_break: bool
    failed_low_break: bool


@dataclass(frozen=True)
class OneMinuteOpeningMemory:
    side: str
    level: float
    touch_count: int
    level_type: str
    first_touch_index: int
    last_touch_index: int
    tolerance: float
    state: str


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


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


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


def _opening_state(level: OneMinuteLevel, latest: Candle, tolerance: float) -> str:
    margin = max(0.05, tolerance * 0.25)
    if level.side == "high":
        if float(latest.close) > level.level + margin:
            return "broken_up"
        if (
            float(latest.high) > level.level + margin
            and float(latest.close) < level.level
        ):
            return "failed_break_up"
        if abs(float(latest.high) - level.level) <= tolerance:
            return "respected_high"
        return "watching_high"
    if float(latest.close) < level.level - margin:
        return "broken_down"
    if (
        float(latest.low) < level.level - margin
        and float(latest.close) > level.level
    ):
        return "failed_break_down"
    if abs(float(latest.low) - level.level) <= tolerance:
        return "respected_low"
    return "watching_low"


def _opening_to_dict(opening: OneMinuteOpeningMemory) -> dict[str, Any]:
    return {
        "side": opening.side,
        "level": round(opening.level, 4),
        "touch_count": opening.touch_count,
        "level_type": opening.level_type,
        "first_touch_index": opening.first_touch_index,
        "last_touch_index": opening.last_touch_index,
        "tolerance": round(opening.tolerance, 4),
        "state": opening.state,
    }


def _build_opening_memory(
    history: list[Candle],
    tolerance: float,
) -> list[OneMinuteOpeningMemory]:
    if len(history) < 2:
        return []
    latest = history[-1]
    prior = history[:-1]
    levels = [
        *_detect_equal_levels(prior, tolerance, side="low"),
        *_detect_equal_levels(prior, tolerance, side="high"),
    ]
    memory: list[OneMinuteOpeningMemory] = []
    for level in levels:
        memory.append(
            OneMinuteOpeningMemory(
                side=level.side,
                level=level.level,
                touch_count=level.touch_count,
                level_type=level.level_type,
                first_touch_index=level.first_touch_index,
                last_touch_index=level.last_touch_index,
                tolerance=level.tolerance,
                state=_opening_state(level, latest, tolerance),
            )
        )
    return sorted(
        memory,
        key=lambda item: (
            item.state.startswith("broken"),
            item.state.startswith("failed"),
            item.touch_count,
            item.last_touch_index,
        ),
        reverse=True,
    )


def _latest_candle_relation(
    history: list[Candle],
    tolerance: float,
    openings: list[OneMinuteOpeningMemory],
) -> OneMinuteCandleRelation:
    latest = history[-1]
    previous = history[-2]
    latest_high = float(latest.high)
    latest_low = float(latest.low)
    previous_high = float(previous.high)
    previous_low = float(previous.low)

    broke_high_zone = any(
        opening.side == "high" and opening.state == "broken_up"
        for opening in openings
    )
    broke_low_zone = any(
        opening.side == "low" and opening.state == "broken_down"
        for opening in openings
    )
    rejected_high_zone = any(
        opening.side == "high" and opening.state == "respected_high"
        for opening in openings
    )
    rejected_low_zone = any(
        opening.side == "low" and opening.state == "respected_low"
        for opening in openings
    )
    failed_high_break = any(
        opening.side == "high" and opening.state == "failed_break_up"
        for opening in openings
    )
    failed_low_break = any(
        opening.side == "low" and opening.state == "failed_break_down"
        for opening in openings
    )

    return OneMinuteCandleRelation(
        equal_high=abs(latest_high - previous_high) <= tolerance,
        equal_low=abs(latest_low - previous_low) <= tolerance,
        higher_high=latest_high > previous_high,
        higher_low=latest_low > previous_low,
        lower_high=latest_high < previous_high,
        lower_low=latest_low < previous_low,
        broke_high_zone=broke_high_zone,
        broke_low_zone=broke_low_zone,
        rejected_high_zone=rejected_high_zone,
        rejected_low_zone=rejected_low_zone,
        failed_high_break=failed_high_break,
        failed_low_break=failed_low_break,
    )


def _latest_touch_level(
    prior: list[Candle],
    latest: Candle,
    tolerance: float,
    *,
    side: str,
) -> OneMinuteLevel | None:
    anchor = float(latest.high if side == "high" else latest.low)
    prices = [
        (index, float(candle.high if side == "high" else candle.low))
        for index, candle in enumerate(prior)
    ]
    touches = [
        (touch_index, price)
        for touch_index, price in prices
        if abs(price - anchor) <= tolerance
    ]
    if not touches:
        return None
    touch_prices = [price for _touch_index, price in touches] + [anchor]
    return OneMinuteLevel(
        side=side,
        level=sum(touch_prices) / len(touch_prices),
        touch_count=len(touch_prices),
        first_touch_index=min(touch_index for touch_index, _price in touches),
        last_touch_index=len(prior),
        spread=max(touch_prices) - min(touch_prices),
        tolerance=tolerance,
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
    if (
        trigger in {HIGH_BREAK_BUY, CLEAN_HIGH_IMPULSE_BUY}
        and _strong_bullish_close(latest)
    ):
        return "strong_close"
    if (
        trigger in {LOW_BREAK_SELL, CLEAN_LOW_IMPULSE_SELL}
        and _strong_bearish_close(latest)
    ):
        return "strong_close"
    return "mixed"


def _is_clean_impulse_break(
    *,
    direction: str,
    level: OneMinuteLevel,
    latest: Candle,
    tolerance: float,
    current_spread_price: float,
) -> bool:
    if level.touch_count < 2:
        return False
    extension = abs(float(latest.close) - float(level.level))
    max_extension = max(tolerance * 3.0, current_spread_price * 2.0, 0.45)
    if extension > max_extension:
        return False
    if direction == "BUY":
        return _decisive_directional_close("BUY", latest)
    if direction == "SELL":
        return _decisive_directional_close("SELL", latest)
    return False


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
    if name in {
        LOW_BREAK_SELL,
        HIGH_BREAK_BUY,
        CLEAN_LOW_IMPULSE_SELL,
        CLEAN_HIGH_IMPULSE_BUY,
    }:
        return float(latest.close)
    return level


def _risk_for_trigger(
    trigger: dict[str, Any],
    latest: Candle,
    *,
    tolerance: float,
    minimum_stop_distance: float,
    current_spread_price: float,
    minimum_stop_spread_multiple: float,
    max_stop_distance: float,
    boost_max_stop_distance: float,
    risk_reward: float,
) -> dict[str, Any]:
    direction = trigger["direction"]
    level = float(trigger["level"])
    name = trigger["name"]
    entry = _entry_price(trigger, latest)
    spread_safe_stop_adjusted = False
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
    spread_floor = (
        current_spread_price * minimum_stop_spread_multiple
        if current_spread_price > 0 and minimum_stop_spread_multiple > 0
        else 0.0
    )
    if spread_floor > 0 and risk_distance < spread_floor:
        if name in HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS:
            adjusted_risk_distance = spread_floor + MINIMUM_STOP_DISTANCE_BUFFER
            if adjusted_risk_distance > boost_max_stop_distance:
                return {
                    "approved": False,
                    "reason_code": SPREAD_SAFE_STOP_TOO_WIDE,
                    "reason": (
                        "Spread-safe one-minute stop exceeds scalp maximum: "
                        f"distance={adjusted_risk_distance:.2f}, "
                        f"spread={current_spread_price:.2f}, "
                        f"maximum={boost_max_stop_distance:.2f}"
                    ),
                }
            risk_distance = adjusted_risk_distance
            stop = entry - risk_distance if direction == "BUY" else entry + risk_distance
            spread_safe_stop_adjusted = True
        else:
            return {
                "approved": False,
                "reason_code": "STOP_TOO_CLOSE_TO_SPREAD",
                "reason": (
                    "Stop distance too close to spread: "
                    f"distance={risk_distance:.2f}, spread={current_spread_price:.2f}, "
                    f"minimum={spread_floor:.2f}"
                ),
            }
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
            "current_spread_price": round(current_spread_price, 4),
            "minimum_stop_spread_multiple": round(minimum_stop_spread_multiple, 4),
            "spread_floor": round(spread_floor, 4),
            "spread_safe_stop_adjusted": spread_safe_stop_adjusted,
        },
        "position_lifecycle": "FAST_PARTIAL_SCALE",
        **_dynamic_fast_exit_settings(risk_distance),
    }
    return risk


def _reprice_risk_to_live_quote(
    risk: dict[str, Any],
    *,
    direction: str,
    current_bid_price: float,
    current_ask_price: float,
    current_spread_price: float,
    minimum_stop_spread_multiple: float,
    max_stop_distance: float,
    risk_reward: float,
) -> dict[str, Any] | None:
    quote = current_ask_price if direction == "BUY" else current_bid_price
    if quote <= 0:
        return None
    stop = float(risk["stop_loss"])
    buffer = max(0.05, current_spread_price * 0.25)
    entry = quote + buffer if direction == "BUY" else quote - buffer
    if direction == "BUY" and stop >= entry:
        return None
    if direction == "SELL" and stop <= entry:
        return None

    risk_distance = abs(entry - stop)
    spread_floor = (
        current_spread_price * minimum_stop_spread_multiple
        if current_spread_price > 0 and minimum_stop_spread_multiple > 0
        else 0.0
    )
    if spread_floor > 0 and risk_distance < spread_floor:
        return None
    if risk_distance <= 0 or risk_distance > max_stop_distance:
        return None

    reward_distance = risk_distance * risk_reward
    reward_sign = 1 if direction == "BUY" else -1
    repriced = dict(risk)
    repriced.update(
        {
            "entry_price": round(entry, 4),
            "take_profit": round(entry + (reward_distance * reward_sign), 4),
            "risk_distance": round(risk_distance, 4),
            "reward_distance": round(reward_distance, 4),
            "risk_reward": round(risk_reward, 2),
            "available_risk_reward": round(risk_reward, 2),
        }
    )
    repriced["fast_trigger_quality"] = {
        **risk.get("fast_trigger_quality", {}),
        "live_repriced": True,
        "live_reprice_quote": round(quote, 4),
        "live_reprice_buffer": round(buffer, 4),
        "live_reprice_entry": round(entry, 4),
    }
    return repriced


def _candidate_from_level(
    level: OneMinuteLevel,
    previous: Candle,
    latest: Candle,
    *,
    tolerance: float,
    minimum_stop_distance: float,
    current_spread_price: float,
    current_bid_price: float,
    current_ask_price: float,
    max_live_entry_drift: float,
    minimum_stop_spread_multiple: float,
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
            direction = "SELL"
            if _is_clean_impulse_break(
                direction=direction,
                level=level,
                latest=latest,
                tolerance=tolerance,
                current_spread_price=current_spread_price,
            ):
                trigger_name = CLEAN_LOW_IMPULSE_SELL
                reaction_type = "impulse_break"
            else:
                trigger_name = LOW_BREAK_SELL
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
            direction = "BUY"
            if _is_clean_impulse_break(
                direction=direction,
                level=level,
                latest=latest,
                tolerance=tolerance,
                current_spread_price=current_spread_price,
            ):
                trigger_name = CLEAN_HIGH_IMPULSE_BUY
                reaction_type = "impulse_break"
            else:
                trigger_name = HIGH_BREAK_BUY
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
        current_spread_price=current_spread_price,
        minimum_stop_spread_multiple=minimum_stop_spread_multiple,
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
        reason_code = str(risk.get("reason_code") or "").strip()
        if reason_code:
            candidate.rejection_reasons.append(reason_code)
        candidate.rejection_reasons.append(str(risk.get("reason") or "RISK_REJECTED"))
        return candidate

    quote = current_ask_price if direction == "BUY" else current_bid_price
    if quote > 0:
        drift = abs(quote - float(risk["entry_price"]))
        if drift > max_live_entry_drift:
            repriced_risk = None
            if trigger_name in MEMORY_OVERRIDE_ONE_MINUTE_TRIGGERS:
                repriced_risk = _reprice_risk_to_live_quote(
                    risk,
                    direction=direction,
                    current_bid_price=current_bid_price,
                    current_ask_price=current_ask_price,
                    current_spread_price=current_spread_price,
                    minimum_stop_spread_multiple=minimum_stop_spread_multiple,
                    max_stop_distance=max_stop_distance,
                    risk_reward=risk_reward,
                )
            if repriced_risk is not None:
                risk = repriced_risk
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
            candidate = OneMinuteCandidate(
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
            reason = (
                "IMPULSE_ENTRY_MOVED_AWAY"
                if trigger_name in CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS
                else "LIVE_ENTRY_MOVED_AWAY"
            )
            candidate.rejection_reasons.append(reason)
            candidate.risk["fast_trigger_quality"] = {
                **candidate.risk.get("fast_trigger_quality", {}),
                "live_quote": round(quote, 4),
                "live_entry_drift": round(drift, 4),
                "max_live_entry_drift": round(max_live_entry_drift, 4),
            }
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
    latest_relation: OneMinuteCandleRelation,
    is_chop: bool,
    max_stop_distance: float,
    boost_max_stop_distance: float,
    min_candidate_score: float,
    volume_boost_enabled: bool,
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

    if candidate.trigger in BREAK_ONE_MINUTE_TRIGGERS:
        extension = abs(float(candidate.entry_price) - float(candidate.level.level))
        live_repriced = bool(
            candidate.risk.get("fast_trigger_quality", {}).get("live_repriced")
        )
        if candidate.trigger in CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS:
            current_spread_price = float(
                candidate.risk.get("fast_trigger_quality", {}).get(
                    "current_spread_price",
                    0.0,
                )
            )
            max_extension = max(
                float(candidate.level.tolerance) * 3.0,
                current_spread_price * 2.0,
                0.45,
            )
        else:
            max_extension = max(float(candidate.level.tolerance) * 2.0, 0.30)
        tight_break = (
            candidate.risk_distance <= max_stop_distance
            if live_repriced
            else extension <= max_extension
        )
        candidate.risk["fast_trigger_quality"] = {
            **candidate.risk.get("fast_trigger_quality", {}),
            "break_extension": round(extension, 4),
            "max_break_extension": round(max_extension, 4),
            "break_tightness_basis": (
                "repriced_risk_distance" if live_repriced else "level_extension"
            ),
        }
        if tight_break:
            candidate.score += 1
            candidate.score_reasons.append("BREAK_ENTRY_TIGHT")
        else:
            candidate.rejection_reasons.append("BREAK_ENTRY_TOO_EXTENDED")
        if candidate.trigger in RAW_BREAK_ONE_MINUTE_TRIGGERS:
            if candidate.level.touch_count < 3:
                candidate.rejection_reasons.append("BREAK_ENTRY_REQUIRES_THIRD_TOUCH")
            if "DECISIVE_CLOSE" not in candidate.score_reasons:
                candidate.rejection_reasons.append("BREAK_ENTRY_REQUIRES_DECISIVE_CLOSE")
            if candidate.risk_distance > boost_max_stop_distance:
                candidate.rejection_reasons.append("BREAK_ENTRY_STOP_TOO_WIDE")
            candidate.rejection_reasons.append(RAW_BREAK_EXECUTION_DISABLED)
        elif candidate.trigger in CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS:
            candidate.score += 2
            candidate.score_reasons.append("CLEAN_IMPULSE_BREAK")

    if candidate.confirmation_type == "mixed":
        candidate.score -= 3
        candidate.rejection_reasons.append("LATEST_CANDLE_NOT_CONFIRMING")
        candidate.rejection_reasons.append("MIXED_CONFIRMATION")
    if is_chop:
        candidate.score -= 3
        candidate.rejection_reasons.append("OVERLAPPING_CHOP")
    if candidate.risk_distance <= 0:
        candidate.rejection_reasons.append("INVALID_STOP_DISTANCE")
    relation_reason = _latest_relation_rejection(candidate, latest_relation)
    if relation_reason is not None:
        if relation_reason == CONFLICTED_ONE_MINUTE_MEMORY and (
            _can_override_memory_conflict(candidate)
        ):
            candidate.score += 1
            candidate.score_reasons.append(
                "MEMORY_CONFLICT_OVERRIDDEN_BY_STRONG_REVERSAL"
            )
            candidate.risk["fast_trigger_quality"] = {
                **candidate.risk.get("fast_trigger_quality", {}),
                "memory_conflict_overridden": True,
            }
        else:
            candidate.rejection_reasons.append(relation_reason)
            candidate.risk["fast_trigger_quality"] = {
                **candidate.risk.get("fast_trigger_quality", {}),
                "latest_relation_rejection": relation_reason,
            }

    candidate.minimum_required_score = _minimum_required_score(
        candidate,
        min_candidate_score,
    )
    if candidate.score < candidate.minimum_required_score:
        candidate.rejection_reasons.append("LOW_ONE_MINUTE_SCORE")

    candidate.rejection_reasons = list(dict.fromkeys(candidate.rejection_reasons))
    candidate.approved = (
        candidate.score >= candidate.minimum_required_score
        and not candidate.rejection_reasons
    )
    if not candidate.approved:
        candidate.volume_decision = "REJECTED"
        candidate.volume_multiplier = None
        return candidate

    high_confidence = (
        volume_boost_enabled
        and candidate.score >= 10
        and "DECISIVE_CLOSE" in candidate.score_reasons
        and candidate.confirmation_type in {"engulfing", "rejection"}
        and candidate.risk_distance <= boost_max_stop_distance
        and candidate.level.touch_count >= 3
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
        "minimum_required_score": round(candidate.minimum_required_score, 2),
        "score_reasons": list(candidate.score_reasons),
        "volume_decision": candidate.volume_decision,
    }
    return candidate


def _can_override_memory_conflict(candidate: OneMinuteCandidate) -> bool:
    return (
        candidate.trigger in MEMORY_OVERRIDE_ONE_MINUTE_TRIGGERS
        and candidate.confirmation_type in {"engulfing", "rejection", "strong_close"}
        and candidate.risk_distance > 0
        and "MIXED_CONFIRMATION" not in candidate.rejection_reasons
    )


def _latest_relation_rejection(
    candidate: OneMinuteCandidate,
    latest_relation: OneMinuteCandleRelation,
) -> str | None:
    if latest_relation.broke_high_zone and latest_relation.broke_low_zone:
        return CONFLICTED_ONE_MINUTE_MEMORY
    if candidate.trigger == HIGH_RESPECT_SELL and (
        latest_relation.broke_high_zone
        or (latest_relation.higher_high and latest_relation.higher_low)
    ):
        return RESPECT_ENTRY_CONFLICTS_WITH_LATEST_RELATION
    if candidate.trigger == LOW_RESPECT_BUY and latest_relation.broke_low_zone:
        return RESPECT_ENTRY_CONFLICTS_WITH_LATEST_RELATION
    return None


def _minimum_required_score(
    candidate: OneMinuteCandidate,
    configured_minimum: float,
) -> float:
    can_relax = (
        candidate.confirmation_type in {"engulfing", "rejection"}
        and "CLOSE_INVALIDATION" in candidate.score_reasons
    )
    if not can_relax:
        return configured_minimum
    if candidate.trigger in RESPECT_ONE_MINUTE_TRIGGERS:
        candidate.score_reasons.append("RELAXED_RESPECT_SCORE_FLOOR")
        return max(6.0, configured_minimum - 2.0)
    if candidate.trigger in FAKEOUT_ONE_MINUTE_TRIGGERS:
        candidate.score_reasons.append("RELAXED_FAKEOUT_SCORE_FLOOR")
        return max(6.0, configured_minimum - 2.0)
    return configured_minimum


def _selection_priority(candidate: OneMinuteCandidate) -> int:
    if candidate.reaction_type == "impulse_break":
        return 3
    if candidate.reaction_type in {"fakeout", "respect"}:
        return 2
    if candidate.reaction_type == "break":
        return 1
    return 0


def _build_candidates(
    history: list[Candle],
    *,
    tolerance: float,
    minimum_stop_distance: float,
    current_spread_price: float,
    current_bid_price: float,
    current_ask_price: float,
    max_live_entry_drift: float,
    minimum_stop_spread_multiple: float,
    max_stop_distance: float,
    boost_max_stop_distance: float,
    min_candidate_score: float,
    volume_boost_enabled: bool,
    risk_reward: float,
    latest_relation: OneMinuteCandleRelation,
) -> list[OneMinuteCandidate]:
    latest = history[-1]
    previous = history[-2]
    prior = history[:-1]
    latest_low_level = _latest_touch_level(prior, latest, tolerance, side="low")
    latest_high_level = _latest_touch_level(prior, latest, tolerance, side="high")
    levels = [
        *_detect_equal_levels(prior, tolerance, side="low"),
        *_detect_equal_levels(prior, tolerance, side="high"),
    ]
    for latest_level in (latest_low_level, latest_high_level):
        if latest_level is None:
            continue
        if any(
            level.side == latest_level.side
            and abs(level.level - latest_level.level) <= tolerance
            for level in levels
        ):
            continue
        levels.append(latest_level)
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
            current_spread_price=current_spread_price,
            current_bid_price=current_bid_price,
            current_ask_price=current_ask_price,
            max_live_entry_drift=max_live_entry_drift,
            minimum_stop_spread_multiple=minimum_stop_spread_multiple,
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
                latest_relation=latest_relation,
                is_chop=is_chop,
                max_stop_distance=max_stop_distance,
                boost_max_stop_distance=boost_max_stop_distance,
                min_candidate_score=min_candidate_score,
                volume_boost_enabled=volume_boost_enabled,
            )
        )
    return sorted(
        candidates,
        key=lambda item: (
            item.approved,
            _selection_priority(item),
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
    early_loss = max(0.25, min(0.75, risk_distance * 0.55))
    scalp_profit = max(partial_first, min(1.5, risk_distance * 1.0))
    return {
        "break_even_trigger_points": round(break_even_trigger, 2),
        "break_even_lock_points": round(max(0.05, min(0.25, risk_distance * 0.12)), 2),
        "min_stop_update_points": round(max(0.05, min(0.25, risk_distance * 0.15)), 2),
        "early_loss_exit_points": round(early_loss, 2),
        "scalp_profit_points": round(scalp_profit, 2),
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
        "min_stop_update_points",
        "early_loss_exit_points",
        "scalp_profit_points",
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
        "minimum_required_score": round(candidate.minimum_required_score, 2),
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
    max_stop_distance = _positive_float(
        config.get("fast_max_stop_distance_price"),
        DEFAULT_MAX_STOP_DISTANCE,
    )
    minimum_stop_distance = _positive_float(
        config.get("minimum_stop_distance_price"),
        0.0,
    )
    minimum_stop_spread_multiple = max(
        _positive_float(
            config.get("minimum_stop_spread_multiple"),
            DEFAULT_MIN_STOP_SPREAD_MULTIPLE,
        ),
        _positive_float(
            config.get("fast_min_stop_spread_multiple"),
            DEFAULT_MIN_STOP_SPREAD_MULTIPLE,
        ),
    )
    current_spread_price = _positive_float(
        config.get("current_spread_price", config.get("spread_price")),
        0.0,
    )
    current_bid_price = _positive_float(config.get("current_bid_price"), 0.0)
    current_ask_price = _positive_float(config.get("current_ask_price"), 0.0)
    max_live_entry_drift = _positive_float(
        config.get("fast_impulse_max_live_entry_drift_price"),
        max(current_spread_price * 3.0, 0.60),
    )
    boost_max_stop_distance = _positive_float(
        config.get("fast_boost_max_stop_distance_price"),
        DEFAULT_BOOST_MAX_STOP_DISTANCE,
    )
    min_candidate_score = _positive_float(
        config.get("fast_min_candidate_score"),
        DEFAULT_MIN_CANDIDATE_SCORE,
    )
    volume_boost_enabled = _bool_value(
        config.get("fast_volume_boost_enabled"),
        False,
    )
    risk_reward = _positive_float(
        config.get("fast_risk_reward"),
        DEFAULT_RISK_REWARD,
    )
    activation_window_minutes = _positive_int(
        config.get("fast_activation_window_minutes"),
        1,
    )

    all_candles = normalize_candles(timeframe_data.get("1m"))
    history = all_candles[-history_window:]
    tolerance = _recent_tolerance(history)
    openings = _build_opening_memory(history, tolerance) if len(history) >= 2 else []
    latest_relation = (
        _latest_candle_relation(history, tolerance, openings)
        if len(history) >= 2
        else OneMinuteCandleRelation(
            equal_high=False,
            equal_low=False,
            higher_high=False,
            higher_low=False,
            lower_high=False,
            lower_low=False,
            broke_high_zone=False,
            broke_low_zone=False,
            rejected_high_zone=False,
            rejected_low_zone=False,
            failed_high_break=False,
            failed_low_break=False,
        )
    )
    story = {
        "model_name": MODEL_NAME,
        "classification": "UNCLEAR",
        "history_candles": len(history),
        "history_window_candles": history_window,
        "tolerance": round(tolerance, 4),
        "min_candidate_score": round(min_candidate_score, 2),
        "current_spread_price": round(current_spread_price, 4),
        "current_bid_price": round(current_bid_price, 4),
        "current_ask_price": round(current_ask_price, 4),
        "max_live_entry_drift": round(max_live_entry_drift, 4),
        "minimum_stop_spread_multiple": round(minimum_stop_spread_multiple, 4),
        "latest_candle_relation": asdict(latest_relation),
        "active_openings": [_opening_to_dict(opening) for opening in openings],
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
            "trigger_selection": "cleanest_recent_story",
            "candidate_memory_candles": len(history),
            "rules": [
                LOW_RESPECT_BUY,
                HIGH_RESPECT_SELL,
                LOW_BREAK_SELL,
                HIGH_BREAK_BUY,
                CLEAN_LOW_IMPULSE_SELL,
                CLEAN_HIGH_IMPULSE_BUY,
                FAILED_LOW_BREAK_BUY,
                FAILED_HIGH_BREAK_SELL,
            ],
        },
    }
    checklist = _base_checklist()
    candidate_evaluations: list[dict[str, Any]] = []

    if len(history) < MINIMUM_CANDLES_FOR_COMPARISON:
        return _payload(
            symbol,
            as_of,
            status="NO_SETUP",
            recommendation="HOLD",
            history=history,
            checklist=checklist,
            market_context=market_context,
            candidate_evaluations=candidate_evaluations,
            message="Not enough closed 1m candles for one-minute candidate comparison.",
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
        current_spread_price=current_spread_price,
        current_bid_price=current_bid_price,
        current_ask_price=current_ask_price,
        max_live_entry_drift=max_live_entry_drift,
        minimum_stop_spread_multiple=minimum_stop_spread_multiple,
        max_stop_distance=max_stop_distance,
        boost_max_stop_distance=boost_max_stop_distance,
        min_candidate_score=min_candidate_score,
        volume_boost_enabled=volume_boost_enabled,
        risk_reward=risk_reward,
        latest_relation=latest_relation,
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
