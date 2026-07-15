"""Causal broker-free state machine for the symmetric One Minute Scalper V1."""

from __future__ import annotations

import hashlib
import math
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any, Iterable, Literal

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
    HIGH_BREAK_BUY,
    HIGH_RESPECT_SELL,
    LOW_BREAK_SELL,
    LOW_RESPECT_BUY,
    _confirmation_type,
    _decisive_directional_close,
    _is_overlapping_chop,
)
from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
    detect_opening_opportunities,
)


CANDIDATE_NAME = "ONE_MINUTE_SYMMETRIC_POST_CLOSE_STATE_V1"
HISTORY_CANDLES = 60
CONFIRMATION_TO_TRIGGER_DELAY_SECONDS = 5.0
PLACEMENT_DELAY_SECONDS = 5.0
REACTION_EXPIRY_SECONDS = 45
BREAK_EXPIRY_SECONDS = 60
BREAK_HOLD_OBSERVATION_SECONDS = 1.0
MINIMUM_STOP_SPREAD_MULTIPLE = 1.2
MAXIMUM_STOP_DISTANCE = 1.0
RISK_REWARD = 1.5


class PostClosePhase(StrEnum):
    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    PLACED = "PLACED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"


Direction = Literal["BUY", "SELL"]
LevelSide = Literal["high", "low"]


def parse_utc(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return parse_utc(value).isoformat()


def _fingerprint(parts: Iterable[Any]) -> str:
    raw = "\0".join(str(part) for part in parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


@dataclass(frozen=True)
class QuoteObservation:
    time: str
    bid: float
    ask: float

    @property
    def time_utc(self) -> datetime:
        return parse_utc(self.time)

    @property
    def spread(self) -> float:
        return float(self.ask) - float(self.bid)

    @property
    def valid(self) -> bool:
        return (
            math.isfinite(float(self.bid))
            and math.isfinite(float(self.ask))
            and float(self.bid) > 0
            and float(self.ask) > 0
            and float(self.ask) >= float(self.bid)
        )


@dataclass(frozen=True)
class PostCloseArm:
    candidate: str
    arm_id: str
    family: str
    direction: Direction
    level_side: LevelSide
    level: float
    touch_count: int
    tolerance: float
    break_margin: float
    zone_low: float
    zone_high: float
    confirmation_type: str
    confirmation_time: str
    confirmation_closed_at: str
    trigger_eligible_at: str
    expires_at: str
    invalidation: float
    confirmation_open: float
    confirmation_high: float
    confirmation_low: float
    confirmation_close: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PostCloseState:
    arm: PostCloseArm
    phase: PostClosePhase = PostClosePhase.ARMED
    zone_observed: bool = False
    first_hold_at: str | None = None
    triggered_at: str | None = None
    placement_due_at: str | None = None
    last_quote_at: str | None = None
    terminal_reason: str | None = None
    sequence: int = 0

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["phase"] = self.phase.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PostCloseState":
        arm = PostCloseArm(**dict(payload["arm"]))
        return cls(
            arm=arm,
            phase=PostClosePhase(payload.get("phase", PostClosePhase.ARMED)),
            zone_observed=bool(payload.get("zone_observed", False)),
            first_hold_at=payload.get("first_hold_at"),
            triggered_at=payload.get("triggered_at"),
            placement_due_at=payload.get("placement_due_at"),
            last_quote_at=payload.get("last_quote_at"),
            terminal_reason=payload.get("terminal_reason"),
            sequence=int(payload.get("sequence", 0)),
        )


@dataclass(frozen=True)
class StateTransition:
    event: str
    state: PostCloseState
    quote: QuoteObservation | None = None
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "state": self.state.as_dict(),
            "quote": asdict(self.quote) if self.quote else None,
            "details": dict(self.details or {}),
        }


@dataclass(frozen=True)
class PlacementConfig:
    minimum_stop_distance: float = 0.35
    minimum_stop_spread_multiple: float = MINIMUM_STOP_SPREAD_MULTIPLE
    maximum_stop_distance: float = MAXIMUM_STOP_DISTANCE
    risk_reward: float = RISK_REWARD
    tick_size: float = 0.01


@dataclass(frozen=True)
class PlacementDecision:
    accepted: bool
    reason: str
    decided_at: str
    direction: Direction
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_distance: float | None = None
    spread: float | None = None
    entry_drift: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _family(opportunity: OpeningOpportunity) -> str:
    if opportunity.template in {
        OpeningTemplate.BREAK_HOLD,
        OpeningTemplate.BREAK_RETEST_HOLD,
    }:
        return HIGH_BREAK_BUY if opportunity.level_side == "high" else LOW_BREAK_SELL
    if opportunity.template == OpeningTemplate.FAILED_BREAK:
        return (
            FAILED_HIGH_BREAK_SELL
            if opportunity.level_side == "high"
            else FAILED_LOW_BREAK_BUY
        )
    return HIGH_RESPECT_SELL if opportunity.level_side == "high" else LOW_RESPECT_BUY


def _confirmation(
    family: str,
    previous: Candle,
    latest: Candle,
) -> str | None:
    confirmation = _confirmation_type(family, previous, latest)
    if family in {HIGH_BREAK_BUY, LOW_BREAK_SELL}:
        direction = "BUY" if family == HIGH_BREAK_BUY else "SELL"
        return "strong_close" if _decisive_directional_close(direction, latest) else None
    return confirmation if confirmation != "mixed" else None


def _invalidation(
    family: str,
    latest: Candle,
    *,
    zone_low: float,
    zone_high: float,
    break_margin: float,
) -> float:
    if family in {HIGH_RESPECT_SELL, FAILED_HIGH_BREAK_SELL}:
        return max(float(latest.high), zone_high + break_margin)
    if family in {LOW_RESPECT_BUY, FAILED_LOW_BREAK_BUY}:
        return min(float(latest.low), zone_low - break_margin)
    if family == HIGH_BREAK_BUY:
        return zone_low - break_margin
    return zone_high + break_margin


def _build_arm(
    opportunity: OpeningOpportunity,
    *,
    previous: Candle,
    latest: Candle,
    candidate_name: str = CANDIDATE_NAME,
) -> PostCloseArm | None:
    family = _family(opportunity)
    confirmation = _confirmation(family, previous, latest)
    if confirmation is None:
        return None
    tolerance = float(opportunity.tolerance)
    break_margin = max(0.05, tolerance * 0.25)
    zone_low = float(opportunity.level) - tolerance
    zone_high = float(opportunity.level) + tolerance
    closed_at = parse_utc(latest.timestamp) + timedelta(minutes=1)
    eligible_at = closed_at + timedelta(seconds=CONFIRMATION_TO_TRIGGER_DELAY_SECONDS)
    expiry_seconds = (
        BREAK_EXPIRY_SECONDS
        if family in {HIGH_BREAK_BUY, LOW_BREAK_SELL}
        else REACTION_EXPIRY_SECONDS
    )
    expires_at = closed_at + timedelta(seconds=expiry_seconds)
    invalidation = _invalidation(
        family,
        latest,
        zone_low=zone_low,
        zone_high=zone_high,
        break_margin=break_margin,
    )
    arm_id = _fingerprint(
        (
            candidate_name,
            family,
            opportunity.level_side,
            round(float(opportunity.level), 4),
            latest.timestamp,
            opportunity.touch_count,
        )
    )
    return PostCloseArm(
        candidate=candidate_name,
        arm_id=arm_id,
        family=family,
        direction=opportunity.direction,
        level_side=opportunity.level_side,
        level=round(float(opportunity.level), 4),
        touch_count=int(opportunity.touch_count),
        tolerance=round(tolerance, 4),
        break_margin=round(break_margin, 4),
        zone_low=round(zone_low, 4),
        zone_high=round(zone_high, 4),
        confirmation_type=confirmation,
        confirmation_time=str(latest.timestamp),
        confirmation_closed_at=_iso(closed_at),
        trigger_eligible_at=_iso(eligible_at),
        expires_at=_iso(expires_at),
        invalidation=round(invalidation, 4),
        confirmation_open=float(latest.open),
        confirmation_high=float(latest.high),
        confirmation_low=float(latest.low),
        confirmation_close=float(latest.close),
    )


def detect_post_close_arms(
    candles: Iterable[Candle],
    *,
    history_candles: int = HISTORY_CANDLES,
    clean_levels: bool = False,
    candidate_name: str = CANDIDATE_NAME,
) -> tuple[PostCloseArm, ...]:
    """Return strict arms created by only the latest fully closed candle."""
    closed = list(candles)[-int(history_candles) :]
    if len(closed) < 3 or _is_overlapping_chop(closed):
        return ()
    latest = closed[-1]
    previous = closed[-2]
    latest_time = parse_utc(latest.timestamp)
    arms: list[PostCloseArm] = []
    for opportunity in detect_opening_opportunities(
        closed,
        lookback=history_candles,
        clean_levels=clean_levels,
    ):
        if parse_utc(opportunity.signal_time) != latest_time:
            continue
        arm = _build_arm(
            opportunity,
            previous=previous,
            latest=latest,
            candidate_name=candidate_name,
        )
        if arm is not None:
            arms.append(arm)
    confirmation_rank = {"engulfing": 0, "rejection": 1, "strong_close": 2}
    unique = {arm.arm_id: arm for arm in arms}
    return tuple(
        sorted(
            unique.values(),
            key=lambda arm: (
                confirmation_rank.get(arm.confirmation_type, 9),
                -arm.touch_count,
                arm.family,
                arm.level_side,
                arm.level,
            ),
        )
    )


def select_post_close_arm(candles: Iterable[Candle]) -> PostCloseArm | None:
    arms = detect_post_close_arms(candles)
    return arms[0] if arms else None


def _terminal(
    state: PostCloseState,
    phase: PostClosePhase,
    reason: str,
    quote: QuoteObservation,
) -> StateTransition:
    updated = replace(
        state,
        phase=phase,
        terminal_reason=reason,
        last_quote_at=quote.time,
        sequence=state.sequence + 1,
    )
    return StateTransition(reason, updated, quote)


def _trigger(state: PostCloseState, quote: QuoteObservation, reason: str) -> StateTransition:
    triggered_at = quote.time_utc
    updated = replace(
        state,
        phase=PostClosePhase.TRIGGERED,
        triggered_at=_iso(triggered_at),
        placement_due_at=_iso(
            triggered_at + timedelta(seconds=PLACEMENT_DELAY_SECONDS)
        ),
        last_quote_at=quote.time,
        terminal_reason=None,
        sequence=state.sequence + 1,
    )
    return StateTransition(
        "TRIGGER_SATISFIED",
        updated,
        quote,
        {"trigger_reason": reason},
    )


def observe_post_close_quote(
    state: PostCloseState,
    quote: QuoteObservation,
    *,
    allow_break_retest_trigger: bool = True,
) -> StateTransition:
    """Advance an armed setup using one causally available quote."""
    if state.phase != PostClosePhase.ARMED:
        return StateTransition("STATE_NOT_ARMED", state, quote)
    if not quote.valid:
        return StateTransition("INVALID_QUOTE_IGNORED", state, quote)
    now = quote.time_utc
    if state.last_quote_at and now <= parse_utc(state.last_quote_at):
        return StateTransition("NON_MONOTONIC_QUOTE_IGNORED", state, quote)
    if now < parse_utc(state.arm.trigger_eligible_at):
        return StateTransition("PRE_CAUSAL_QUOTE_IGNORED", state, quote)
    if now >= parse_utc(state.arm.expires_at):
        return _terminal(state, PostClosePhase.EXPIRED, "ARM_EXPIRED", quote)

    arm = state.arm
    family = arm.family
    if family in {HIGH_RESPECT_SELL, FAILED_HIGH_BREAK_SELL} and quote.ask > arm.invalidation:
        return _terminal(state, PostClosePhase.INVALIDATED, "SELL_STORY_INVALIDATED", quote)
    if family in {LOW_RESPECT_BUY, FAILED_LOW_BREAK_BUY} and quote.bid < arm.invalidation:
        return _terminal(state, PostClosePhase.INVALIDATED, "BUY_STORY_INVALIDATED", quote)
    if family == HIGH_BREAK_BUY and quote.bid < arm.invalidation:
        return _terminal(state, PostClosePhase.INVALIDATED, "HIGH_BREAK_INVALIDATED", quote)
    if family == LOW_BREAK_SELL and quote.ask > arm.invalidation:
        return _terminal(state, PostClosePhase.INVALIDATED, "LOW_BREAK_INVALIDATED", quote)

    was_zone_observed = state.zone_observed
    mid = (quote.bid + quote.ask) / 2.0
    zone_observed = was_zone_observed or arm.zone_low <= mid <= arm.zone_high
    updated = replace(
        state,
        zone_observed=zone_observed,
        last_quote_at=quote.time,
        sequence=state.sequence + 1,
    )

    if family in {HIGH_RESPECT_SELL, FAILED_HIGH_BREAK_SELL}:
        if was_zone_observed and quote.bid <= arm.zone_low - arm.break_margin:
            return _trigger(updated, quote, "POST_CLOSE_ZONE_REJECTION_DOWN")
    elif family in {LOW_RESPECT_BUY, FAILED_LOW_BREAK_BUY}:
        if was_zone_observed and quote.ask >= arm.zone_high + arm.break_margin:
            return _trigger(updated, quote, "POST_CLOSE_ZONE_REJECTION_UP")
    elif family == HIGH_BREAK_BUY:
        if (
            allow_break_retest_trigger
            and was_zone_observed
            and quote.ask >= arm.zone_high + arm.break_margin
        ):
            return _trigger(updated, quote, "POST_CLOSE_BREAK_RETEST_RESUME_UP")
        if quote.bid > arm.zone_high:
            if state.first_hold_at is None:
                updated = replace(updated, first_hold_at=quote.time)
            elif now - parse_utc(state.first_hold_at) >= timedelta(
                seconds=BREAK_HOLD_OBSERVATION_SECONDS
            ):
                return _trigger(updated, quote, "POST_CLOSE_BREAK_HOLD_UP")
        else:
            updated = replace(updated, first_hold_at=None)
    elif family == LOW_BREAK_SELL:
        if (
            allow_break_retest_trigger
            and was_zone_observed
            and quote.bid <= arm.zone_low - arm.break_margin
        ):
            return _trigger(updated, quote, "POST_CLOSE_BREAK_RETEST_RESUME_DOWN")
        if quote.ask < arm.zone_low:
            if state.first_hold_at is None:
                updated = replace(updated, first_hold_at=quote.time)
            elif now - parse_utc(state.first_hold_at) >= timedelta(
                seconds=BREAK_HOLD_OBSERVATION_SECONDS
            ):
                return _trigger(updated, quote, "POST_CLOSE_BREAK_HOLD_DOWN")
        else:
            updated = replace(updated, first_hold_at=None)

    return StateTransition("POST_CLOSE_OBSERVATION", updated, quote)


def _snap(value: float, tick_size: float) -> float:
    size = max(float(tick_size), 1e-9)
    return round(round(float(value) / size) * size, 10)


def evaluate_post_close_placement(
    state: PostCloseState,
    quote: QuoteObservation,
    *,
    config: PlacementConfig | None = None,
) -> PlacementDecision:
    """Construct a current-quote placement without mutating a broker."""
    policy = config or PlacementConfig()
    now = quote.time_utc
    direction = state.arm.direction

    def rejected(reason: str) -> PlacementDecision:
        return PlacementDecision(False, reason, _iso(now), direction)

    if state.phase != PostClosePhase.TRIGGERED or not state.placement_due_at:
        return rejected("STATE_NOT_TRIGGERED")
    if not quote.valid:
        return rejected("INVALID_PLACEMENT_QUOTE")
    if now < parse_utc(state.placement_due_at):
        return rejected("PLACEMENT_DELAY_PENDING")
    if now >= parse_utc(state.arm.expires_at):
        return rejected("ARM_EXPIRED_BEFORE_PLACEMENT")

    arm = state.arm
    if direction == "BUY":
        if quote.bid < arm.invalidation:
            return rejected("BUY_STORY_INVALIDATED_AT_PLACEMENT")
        if quote.ask < arm.zone_high + arm.break_margin:
            return rejected("BUY_TRIGGER_CROSSED_AT_PLACEMENT")
        entry = float(quote.ask)
    else:
        if quote.ask > arm.invalidation:
            return rejected("SELL_STORY_INVALIDATED_AT_PLACEMENT")
        if quote.bid > arm.zone_low - arm.break_margin:
            return rejected("SELL_TRIGGER_CROSSED_AT_PLACEMENT")
        entry = float(quote.bid)

    spread = quote.spread
    minimum_risk = max(
        float(policy.minimum_stop_distance),
        spread * float(policy.minimum_stop_spread_multiple),
    )
    if direction == "BUY":
        stop = min(float(arm.invalidation), entry - minimum_risk)
        risk = entry - stop
    else:
        stop = max(float(arm.invalidation), entry + minimum_risk)
        risk = stop - entry
    if not math.isfinite(risk) or risk <= 0:
        return rejected("INVALID_STOP_GEOMETRY")
    if risk > float(policy.maximum_stop_distance):
        return rejected("STOP_DISTANCE_ABOVE_MAXIMUM")
    entry_drift = abs(entry - float(arm.level))
    maximum_drift = min(3.0 * arm.tolerance, 2.0 * risk)
    if entry_drift > maximum_drift:
        return rejected("ENTRY_DRIFT_ABOVE_MAXIMUM")

    entry = _snap(entry, policy.tick_size)
    stop = _snap(stop, policy.tick_size)
    target = (
        entry + risk * float(policy.risk_reward)
        if direction == "BUY"
        else entry - risk * float(policy.risk_reward)
    )
    target = _snap(target, policy.tick_size)
    return PlacementDecision(
        True,
        "PLACEMENT_ACCEPTED",
        _iso(now),
        direction,
        entry=entry,
        stop_loss=stop,
        take_profit=target,
        risk_distance=round(risk, 10),
        spread=round(spread, 10),
        entry_drift=round(entry_drift, 10),
    )


__all__ = [
    "BREAK_EXPIRY_SECONDS",
    "CANDIDATE_NAME",
    "CONFIRMATION_TO_TRIGGER_DELAY_SECONDS",
    "HISTORY_CANDLES",
    "PLACEMENT_DELAY_SECONDS",
    "PlacementConfig",
    "PlacementDecision",
    "PostCloseArm",
    "PostClosePhase",
    "PostCloseState",
    "QuoteObservation",
    "StateTransition",
    "detect_post_close_arms",
    "evaluate_post_close_placement",
    "observe_post_close_quote",
    "parse_utc",
    "select_post_close_arm",
]
