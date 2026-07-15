"""Causal quote-pressure state machine for the One Minute Scalper V8.

The module is deliberately broker free.  It converts a fully closed-candle arm
into a direction-safe pending-stop proposal using only quotes observed after
the family-specific post-close structural test.  "Quote pressure" here is a
best-quote proxy; it is not order-flow imbalance because the MT5 feed exposes
neither depth nor reliable traded volume for this instrument.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from enum import StrEnum
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PostCloseArm,
    PostClosePhase,
    PostCloseState,
    QuoteObservation,
    detect_post_close_arms,
    observe_post_close_quote,
    parse_utc,
)


CANDIDATE_NAME = "ONE_MINUTE_QUOTE_PRESSURE_V8"
HISTORY_CANDLES = 60
PRESSURE_CHANGE_COUNT = 20
PRESSURE_WINDOW_SECONDS = 3.0
MINIMUM_NONZERO_MOVES = 10
MINIMUM_DIRECTIONAL_PRESSURE = 0.60
MINIMUM_DISPLACEMENT_R = 0.10
MAXIMUM_ADVERSE_R = 0.15
MAXIMUM_SPREAD_MULTIPLE = 1.10
PLACEMENT_DELAY_SECONDS = 5.0
PENDING_EXPIRY_SECONDS = 20
MAXIMUM_STOP_DISTANCE = 1.0
RISK_REWARD = 1.5


class V8Phase(StrEnum):
    """Durable phases for the single active V8 lifecycle."""

    ARMED = "ARMED"
    PRESSURE = "PRESSURE"
    WAITING = "WAITING"
    PLACED = "PLACED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    CONSUMED = "CONSUMED"


TERMINAL_PHASES = {
    V8Phase.INVALIDATED,
    V8Phase.EXPIRED,
    V8Phase.REJECTED,
    V8Phase.CONSUMED,
}


@dataclass(frozen=True)
class V8Config:
    history_candles: int = HISTORY_CANDLES
    pressure_change_count: int = PRESSURE_CHANGE_COUNT
    pressure_window_seconds: float = PRESSURE_WINDOW_SECONDS
    minimum_nonzero_moves: int = MINIMUM_NONZERO_MOVES
    minimum_directional_pressure: float = MINIMUM_DIRECTIONAL_PRESSURE
    minimum_displacement_r: float = MINIMUM_DISPLACEMENT_R
    maximum_adverse_r: float = MAXIMUM_ADVERSE_R
    maximum_spread_multiple: float = MAXIMUM_SPREAD_MULTIPLE
    placement_delay_seconds: float = PLACEMENT_DELAY_SECONDS
    pending_expiry_seconds: int = PENDING_EXPIRY_SECONDS
    minimum_stop_distance: float = 0.35
    minimum_stop_spread_multiple: float = 1.2
    maximum_stop_distance: float = MAXIMUM_STOP_DISTANCE
    risk_reward: float = RISK_REWARD
    tick_size: float = 0.01
    broker_stop_distance: float = 0.0
    broker_freeze_distance: float = 0.0

    def __post_init__(self) -> None:
        positive = (
            "history_candles",
            "pressure_change_count",
            "pressure_window_seconds",
            "minimum_nonzero_moves",
            "placement_delay_seconds",
            "pending_expiry_seconds",
            "maximum_stop_distance",
            "risk_reward",
            "tick_size",
        )
        for field_name in positive:
            if float(getattr(self, field_name)) <= 0:
                raise ValueError(f"{field_name} must be positive")
        if self.minimum_nonzero_moves > self.pressure_change_count:
            raise ValueError(
                "minimum_nonzero_moves cannot exceed pressure_change_count"
            )
        for field_name in (
            "minimum_directional_pressure",
            "minimum_displacement_r",
            "maximum_adverse_r",
            "maximum_spread_multiple",
            "minimum_stop_distance",
            "minimum_stop_spread_multiple",
            "broker_stop_distance",
            "broker_freeze_distance",
        ):
            value = float(getattr(self, field_name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{field_name} must be finite and non-negative")
        if not 0 <= self.minimum_directional_pressure <= 1:
            raise ValueError("minimum_directional_pressure must be between zero and one")


@dataclass(frozen=True)
class V8State:
    """Serializable V8 state.  Absolute timestamps never move on restart."""

    structural: PostCloseState
    phase: V8Phase = V8Phase.ARMED
    arm_time_spread: float | None = None
    pressure_started_at: str | None = None
    pressure_deadline_at: str | None = None
    pressure_mids: tuple[float, ...] = ()
    pressure_spreads: tuple[float, ...] = ()
    pressure_min_bid: float | None = None
    pressure_max_ask: float | None = None
    pressure_score: float | None = None
    pressure_displacement: float | None = None
    pressure_adverse: float | None = None
    pressure_median_spread: float | None = None
    reference_risk: float | None = None
    placement_due_at: str | None = None
    pending_expires_at: str | None = None
    last_quote_at: str | None = None
    last_bid: float | None = None
    last_ask: float | None = None
    terminal_reason: str | None = None
    sequence: int = 0

    @property
    def arm(self) -> PostCloseArm:
        return self.structural.arm

    @property
    def change_count(self) -> int:
        return max(0, len(self.pressure_mids) - 1)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["phase"] = self.phase.value
        payload["structural"]["phase"] = self.structural.phase.value
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "V8State":
        return cls(
            structural=PostCloseState.from_dict(dict(payload["structural"])),
            phase=V8Phase(payload.get("phase", V8Phase.ARMED)),
            arm_time_spread=_optional_float(payload.get("arm_time_spread")),
            pressure_started_at=payload.get("pressure_started_at"),
            pressure_deadline_at=payload.get("pressure_deadline_at"),
            pressure_mids=tuple(float(value) for value in payload.get("pressure_mids", ())),
            pressure_spreads=tuple(
                float(value) for value in payload.get("pressure_spreads", ())
            ),
            pressure_min_bid=_optional_float(payload.get("pressure_min_bid")),
            pressure_max_ask=_optional_float(payload.get("pressure_max_ask")),
            pressure_score=_optional_float(payload.get("pressure_score")),
            pressure_displacement=_optional_float(
                payload.get("pressure_displacement")
            ),
            pressure_adverse=_optional_float(payload.get("pressure_adverse")),
            pressure_median_spread=_optional_float(
                payload.get("pressure_median_spread")
            ),
            reference_risk=_optional_float(payload.get("reference_risk")),
            placement_due_at=payload.get("placement_due_at"),
            pending_expires_at=payload.get("pending_expires_at"),
            last_quote_at=payload.get("last_quote_at"),
            last_bid=_optional_float(payload.get("last_bid")),
            last_ask=_optional_float(payload.get("last_ask")),
            terminal_reason=payload.get("terminal_reason"),
            sequence=int(payload.get("sequence", 0)),
        )


@dataclass(frozen=True)
class V8Transition:
    event: str
    state: V8State
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
class V8PendingDecision:
    accepted: bool
    reason: str
    decided_at: str
    direction: str
    order_kind: str | None = None
    entry: float | None = None
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_distance: float | None = None
    spread: float | None = None
    expires_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_v8_arms(
    candles: Iterable[Candle],
    *,
    config: V8Config | None = None,
    clean_levels: bool = False,
) -> tuple[PostCloseArm, ...]:
    """Detect V8 arms from at most 60 supplied fully closed M1 candles."""
    policy = config or V8Config()
    return detect_post_close_arms(
        list(candles)[-policy.history_candles :],
        history_candles=policy.history_candles,
        clean_levels=clean_levels,
        candidate_name=CANDIDATE_NAME,
    )


def start_v8_state(arm: PostCloseArm, arm_quote: QuoteObservation) -> V8State:
    """Create an armed V8 lifecycle and freeze its arm-time spread."""
    if arm.candidate != CANDIDATE_NAME:
        raise ValueError(f"V8 requires candidate {CANDIDATE_NAME}")
    if not arm_quote.valid:
        raise ValueError("arm quote must be valid")
    if arm_quote.time_utc < parse_utc(arm.confirmation_closed_at):
        raise ValueError("arm quote cannot predate the closed confirmation candle")
    return V8State(
        structural=PostCloseState(arm=arm),
        arm_time_spread=round(arm_quote.spread, 10),
    )


def observe_v8_quote(
    state: V8State,
    quote: QuoteObservation,
    *,
    config: V8Config | None = None,
) -> V8Transition:
    """Advance V8 with one quote while enforcing causality and fixed deadlines."""
    policy = config or V8Config()
    if state.phase in TERMINAL_PHASES or state.phase == V8Phase.PLACED:
        return V8Transition("STATE_NOT_OBSERVABLE", state, quote)
    if not quote.valid:
        return V8Transition("INVALID_QUOTE_IGNORED", state, quote)
    if state.last_quote_at and quote.time_utc <= parse_utc(state.last_quote_at):
        return V8Transition("NON_MONOTONIC_QUOTE_IGNORED", state, quote)
    if (
        state.phase != V8Phase.WAITING
        and state.last_bid is not None
        and state.last_ask is not None
        and quote.bid == state.last_bid
        and quote.ask == state.last_ask
    ):
        return V8Transition("DUPLICATE_QUOTE_IGNORED", state, quote)

    if state.phase == V8Phase.ARMED:
        return _observe_structural(state, quote, policy)
    if state.phase == V8Phase.PRESSURE:
        return _observe_pressure(state, quote, policy)
    return _observe_waiting(state, quote, policy)


def evaluate_v8_stop_order(
    state: V8State,
    quote: QuoteObservation,
    *,
    config: V8Config | None = None,
) -> V8PendingDecision:
    """Build a direction-safe stop one tick outside the frozen pressure extreme."""
    policy = config or V8Config()
    direction = state.arm.direction
    now = quote.time_utc

    def reject(reason: str) -> V8PendingDecision:
        return V8PendingDecision(
            False,
            reason,
            now.isoformat(),
            direction,
        )

    if state.phase != V8Phase.WAITING or not state.placement_due_at:
        return reject("STATE_NOT_WAITING")
    if not quote.valid:
        return reject("INVALID_PLACEMENT_QUOTE")
    if now < parse_utc(state.placement_due_at):
        return reject("PLACEMENT_DELAY_PENDING")
    story_reason = _story_failure(state, quote, policy)
    if story_reason:
        return reject(story_reason)
    if state.pressure_min_bid is None or state.pressure_max_ask is None:
        return reject("PRESSURE_EXTREME_MISSING")

    if direction == "BUY":
        entry = _snap_up(state.pressure_max_ask, policy.tick_size) + policy.tick_size
        entry = _snap_up(entry, policy.tick_size)
        if quote.ask >= entry:
            return reject("BUY_STOP_ALREADY_CROSSED")
    else:
        entry = _snap_down(state.pressure_min_bid, policy.tick_size) - policy.tick_size
        entry = _snap_down(entry, policy.tick_size)
        if quote.bid <= entry:
            return reject("SELL_STOP_ALREADY_CROSSED")

    geometry = _stop_geometry(state.arm, entry, quote.spread, policy)
    if geometry is None:
        return reject("STOP_DISTANCE_ABOVE_MAXIMUM")
    stop, risk = geometry
    if direction == "BUY":
        target = _snap_up(entry + risk * policy.risk_reward, policy.tick_size)
        kind = "BUY_STOP"
    else:
        target = _snap_down(entry - risk * policy.risk_reward, policy.tick_size)
        kind = "SELL_STOP"
    expires_at = now + timedelta(seconds=policy.pending_expiry_seconds)
    return V8PendingDecision(
        True,
        "PLACEMENT_ACCEPTED",
        now.isoformat(),
        direction,
        order_kind=kind,
        entry=round(entry, 10),
        stop_loss=round(stop, 10),
        take_profit=round(target, 10),
        risk_distance=round(risk, 10),
        spread=round(quote.spread, 10),
        expires_at=expires_at.isoformat(),
    )


def mark_v8_placed(state: V8State, decision: V8PendingDecision) -> V8State:
    if state.phase != V8Phase.WAITING or not decision.accepted:
        raise ValueError("only an accepted waiting decision can be marked placed")
    return replace(
        state,
        phase=V8Phase.PLACED,
        pending_expires_at=decision.expires_at,
        sequence=state.sequence + 1,
    )


def expire_v8_pending(state: V8State, now: str) -> V8State:
    """Expire a placed state without ever extending its original deadline."""
    if state.phase != V8Phase.PLACED or not state.pending_expires_at:
        return state
    if parse_utc(now) < parse_utc(state.pending_expires_at):
        return state
    return replace(
        state,
        phase=V8Phase.EXPIRED,
        terminal_reason="PENDING_ORDER_EXPIRED",
        sequence=state.sequence + 1,
    )


class AtomicV8StateStore:
    """Crash-safe JSON store used for lifecycle and cooldown persistence."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def save(self, payload: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        try:
            with temporary.open("wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("V8 state store payload must be an object")
        return payload


def _observe_structural(
    state: V8State,
    quote: QuoteObservation,
    policy: V8Config,
) -> V8Transition:
    transition = observe_post_close_quote(state.structural, quote)
    structural = transition.state
    common = {
        "structural": structural,
        "last_quote_at": quote.time,
        "last_bid": quote.bid,
        "last_ask": quote.ask,
        "sequence": state.sequence + 1,
    }
    if structural.phase == PostClosePhase.EXPIRED:
        return _terminal(state, quote, V8Phase.EXPIRED, transition.event, **common)
    if structural.phase == PostClosePhase.INVALIDATED:
        return _terminal(state, quote, V8Phase.INVALIDATED, transition.event, **common)
    if structural.phase != PostClosePhase.TRIGGERED:
        if transition.state == state.structural:
            return V8Transition(transition.event, state, quote, transition.details)
        return V8Transition(
            transition.event,
            replace(state, **common),
            quote,
            transition.details,
        )

    mid = _mid(quote)
    deadline = quote.time_utc + timedelta(seconds=policy.pressure_window_seconds)
    updated = replace(
        state,
        phase=V8Phase.PRESSURE,
        pressure_started_at=quote.time,
        pressure_deadline_at=deadline.isoformat(),
        pressure_mids=(mid,),
        pressure_spreads=(quote.spread,),
        pressure_min_bid=quote.bid,
        pressure_max_ask=quote.ask,
        terminal_reason=None,
        **common,
    )
    return V8Transition(
        "PRESSURE_WINDOW_STARTED",
        updated,
        quote,
        {"structural_event": transition.event, "deadline_at": deadline.isoformat()},
    )


def _observe_pressure(
    state: V8State,
    quote: QuoteObservation,
    policy: V8Config,
) -> V8Transition:
    story_reason = _story_failure(state, quote, policy, include_moved_away=False)
    if story_reason:
        return _terminal(state, quote, V8Phase.INVALIDATED, story_reason)
    if not state.pressure_deadline_at:
        return _terminal(
            state,
            quote,
            V8Phase.REJECTED,
            "PRESSURE_DEADLINE_MISSING",
        )
    if quote.time_utc > parse_utc(state.pressure_deadline_at):
        return _terminal(
            state,
            quote,
            V8Phase.REJECTED,
            "PRESSURE_SAMPLE_TIMEOUT",
            details={"change_count": state.change_count},
        )

    mid = _mid(quote)
    if state.pressure_mids and mid == state.pressure_mids[-1]:
        updated = replace(
            state,
            last_quote_at=quote.time,
            last_bid=quote.bid,
            last_ask=quote.ask,
            sequence=state.sequence + 1,
        )
        return V8Transition("UNCHANGED_MID_IGNORED", updated, quote)

    mids = state.pressure_mids + (mid,)
    spreads = state.pressure_spreads + (quote.spread,)
    updated = replace(
        state,
        pressure_mids=mids,
        pressure_spreads=spreads,
        pressure_min_bid=min(state.pressure_min_bid or quote.bid, quote.bid),
        pressure_max_ask=max(state.pressure_max_ask or quote.ask, quote.ask),
        last_quote_at=quote.time,
        last_bid=quote.bid,
        last_ask=quote.ask,
        sequence=state.sequence + 1,
    )
    if updated.change_count < policy.pressure_change_count:
        return V8Transition(
            "PRESSURE_OBSERVATION",
            updated,
            quote,
            {"change_count": updated.change_count},
        )
    return _score_pressure(updated, quote, policy)


def _score_pressure(
    state: V8State,
    quote: QuoteObservation,
    policy: V8Config,
) -> V8Transition:
    mids = state.pressure_mids
    changes = tuple(current - previous for previous, current in zip(mids, mids[1:]))
    nonzero = tuple(change for change in changes if change != 0)
    sign = 1.0 if state.arm.direction == "BUY" else -1.0
    favorable = sum(1 for change in nonzero if change * sign > 0)
    pressure = favorable / len(nonzero) if nonzero else 0.0
    displacement = (mids[-1] - mids[0]) * sign
    adverse = (
        mids[0] - min(mids)
        if state.arm.direction == "BUY"
        else max(mids) - mids[0]
    )
    spread_median = float(median(state.pressure_spreads))
    extreme_entry = (
        _snap_up(float(state.pressure_max_ask), policy.tick_size) + policy.tick_size
        if state.arm.direction == "BUY"
        else _snap_down(float(state.pressure_min_bid), policy.tick_size)
        - policy.tick_size
    )
    geometry = _stop_geometry(state.arm, extreme_entry, spread_median, policy)
    if geometry is None:
        return _terminal(
            state,
            quote,
            V8Phase.REJECTED,
            "PRESSURE_STOP_DISTANCE_ABOVE_MAXIMUM",
        )
    _, risk = geometry
    details = {
        "nonzero_moves": len(nonzero),
        "directional_pressure": round(pressure, 10),
        "directional_displacement": round(displacement, 10),
        "adverse_movement": round(adverse, 10),
        "median_spread": round(spread_median, 10),
        "reference_risk": round(risk, 10),
    }
    reason = None
    if len(nonzero) < policy.minimum_nonzero_moves:
        reason = "PRESSURE_NONZERO_MOVES_BELOW_MINIMUM"
    elif pressure < policy.minimum_directional_pressure:
        reason = "DIRECTIONAL_PRESSURE_BELOW_MINIMUM"
    elif displacement < max(spread_median, policy.minimum_displacement_r * risk):
        reason = "DIRECTIONAL_DISPLACEMENT_BELOW_MINIMUM"
    elif adverse > policy.maximum_adverse_r * risk:
        reason = "ADVERSE_MOVEMENT_ABOVE_MAXIMUM"
    elif state.arm_time_spread is None or spread_median > (
        policy.maximum_spread_multiple * state.arm_time_spread
    ):
        reason = "PRESSURE_SPREAD_ABOVE_MAXIMUM"
    if reason:
        return _terminal(
            state,
            quote,
            V8Phase.REJECTED,
            reason,
            details=details,
        )

    due = quote.time_utc + timedelta(seconds=policy.placement_delay_seconds)
    updated = replace(
        state,
        phase=V8Phase.WAITING,
        pressure_score=round(pressure, 10),
        pressure_displacement=round(displacement, 10),
        pressure_adverse=round(adverse, 10),
        pressure_median_spread=round(spread_median, 10),
        reference_risk=round(risk, 10),
        placement_due_at=due.isoformat(),
        sequence=state.sequence + 1,
    )
    return V8Transition("PRESSURE_ACCEPTED", updated, quote, details)


def _observe_waiting(
    state: V8State,
    quote: QuoteObservation,
    policy: V8Config,
) -> V8Transition:
    reason = _story_failure(state, quote, policy)
    if reason:
        phase = V8Phase.INVALIDATED if "INVALIDATED" in reason else V8Phase.REJECTED
        return _terminal(state, quote, phase, reason)
    if state.placement_due_at and quote.time_utc < parse_utc(state.placement_due_at):
        return V8Transition(
            "PLACEMENT_DELAY_PENDING",
            replace(
                state,
                last_quote_at=quote.time,
                last_bid=quote.bid,
                last_ask=quote.ask,
                sequence=state.sequence + 1,
            ),
            quote,
        )
    decision = evaluate_v8_stop_order(state, quote, config=policy)
    if decision.accepted:
        return V8Transition("PLACEMENT_READY", state, quote, decision.as_dict())
    return _terminal(
        state,
        quote,
        V8Phase.REJECTED,
        decision.reason,
        details=decision.as_dict(),
    )


def _story_failure(
    state: V8State,
    quote: QuoteObservation,
    policy: V8Config,
    *,
    include_moved_away: bool = True,
) -> str | None:
    arm = state.arm
    if arm.direction == "BUY" and quote.bid < arm.invalidation:
        return "BUY_STORY_INVALIDATED"
    if arm.direction == "SELL" and quote.ask > arm.invalidation:
        return "SELL_STORY_INVALIDATED"
    if not include_moved_away or state.reference_risk is None or not state.pressure_mids:
        return None
    start = state.pressure_mids[0]
    adverse_limit = policy.maximum_adverse_r * state.reference_risk
    mid = _mid(quote)
    if arm.direction == "BUY" and mid < start - adverse_limit:
        return "BUY_STORY_MOVED_AWAY"
    if arm.direction == "SELL" and mid > start + adverse_limit:
        return "SELL_STORY_MOVED_AWAY"
    if state.pressure_max_ask is not None and arm.direction == "BUY":
        entry = _snap_up(state.pressure_max_ask, policy.tick_size) + policy.tick_size
        if quote.ask >= _snap_up(entry, policy.tick_size):
            return "BUY_STOP_ALREADY_CROSSED"
    if state.pressure_min_bid is not None and arm.direction == "SELL":
        entry = _snap_down(state.pressure_min_bid, policy.tick_size) - policy.tick_size
        if quote.bid <= _snap_down(entry, policy.tick_size):
            return "SELL_STOP_ALREADY_CROSSED"
    return None


def _stop_geometry(
    arm: PostCloseArm,
    entry: float,
    spread: float,
    policy: V8Config,
) -> tuple[float, float] | None:
    minimum = max(
        policy.minimum_stop_distance,
        spread * policy.minimum_stop_spread_multiple,
        policy.broker_stop_distance,
        policy.broker_freeze_distance,
    )
    if arm.direction == "BUY":
        stop = min(arm.invalidation, entry - minimum)
        stop = _snap_down(stop, policy.tick_size)
        risk = entry - stop
    else:
        stop = max(arm.invalidation, entry + minimum)
        stop = _snap_up(stop, policy.tick_size)
        risk = stop - entry
    if not math.isfinite(risk) or risk <= 0 or risk > policy.maximum_stop_distance:
        return None
    return round(stop, 10), round(risk, 10)


def _terminal(
    state: V8State,
    quote: QuoteObservation,
    phase: V8Phase,
    reason: str,
    *,
    details: dict[str, Any] | None = None,
    **changes: Any,
) -> V8Transition:
    updated = replace(
        state,
        phase=phase,
        terminal_reason=reason,
        last_quote_at=changes.pop("last_quote_at", quote.time),
        last_bid=changes.pop("last_bid", quote.bid),
        last_ask=changes.pop("last_ask", quote.ask),
        sequence=changes.pop("sequence", state.sequence + 1),
        **changes,
    )
    return V8Transition(reason, updated, quote, details)


def _mid(quote: QuoteObservation) -> float:
    return round((float(quote.bid) + float(quote.ask)) / 2.0, 10)


def _snap_up(value: float, tick_size: float) -> float:
    size = max(float(tick_size), 1e-12)
    return round(math.ceil((float(value) - 1e-12) / size) * size, 10)


def _snap_down(value: float, tick_size: float) -> float:
    size = max(float(tick_size), 1e-12)
    return round(math.floor((float(value) + 1e-12) / size) * size, 10)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


__all__ = [
    "AtomicV8StateStore",
    "CANDIDATE_NAME",
    "HISTORY_CANDLES",
    "PENDING_EXPIRY_SECONDS",
    "PRESSURE_CHANGE_COUNT",
    "V8Config",
    "V8PendingDecision",
    "V8Phase",
    "V8State",
    "V8Transition",
    "detect_v8_arms",
    "evaluate_v8_stop_order",
    "expire_v8_pending",
    "mark_v8_placed",
    "observe_v8_quote",
    "start_v8_state",
]
