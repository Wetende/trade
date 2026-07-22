"""Deterministic tick replay for the symmetric post-close One Minute Scalper."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from math import ceil, floor
from typing import Any, Iterable

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    _dynamic_fast_exit_settings,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PlacementConfig,
    PostCloseArm,
    PostClosePhase,
    PostCloseState,
    QuoteObservation,
    detect_post_close_arms,
    evaluate_post_close_placement,
    observe_post_close_inside_pullback_quote,
    observe_post_close_quote,
    observe_post_close_reclaim_quote,
    parse_utc,
)
from tradingagents.agents.price_action.opening_tick_replay import MarketTick


@dataclass(frozen=True)
class PostCloseReplayConfig:
    placement: PlacementConfig = field(default_factory=PlacementConfig)
    cost_per_fill_r: float = 0.05
    intrabar_adverse_fraction: float = 0.65
    intrabar_adverse_confirmations: int = 2
    candle_rejection_partial_fraction: float = 0.50
    two_loss_pause_minutes: int = 15
    reset_move_away_tolerance_multiple: float = 2.0
    capture_events: bool = True
    entry_policy: str = "MARKET_V1"
    pending_expiry_seconds: int = 20
    reconfirmation_stop_expiry_seconds: int = 15
    hold_stop_expiry_seconds: int = 20
    maximum_hold_entry_drift_r: float = 0.75
    reclaim_stop_expiry_seconds: int = 20
    maximum_reclaim_entry_drift_r: float = 0.75
    inside_stop_expiry_seconds: int = 20
    maximum_inside_entry_drift_r: float = 0.15
    state_cap_seconds_after_confirmation_close: int = 90
    clean_levels: bool = False
    candidate_name: str = "ONE_MINUTE_SYMMETRIC_POST_CLOSE_STATE_V1"
    signal_model: str = "REPEATED_LEVEL"
    evidence_start: str | None = None
    evidence_end: str | None = None


@dataclass(frozen=True)
class PostCloseReplayRow:
    arm_id: str
    session_id: str
    family: str
    direction: str
    touch_count: int
    confirmation_type: str
    armed_at: str
    triggered_at: str | None
    retest_at: str | None
    placed_at: str | None
    filled_at: str | None
    closed_at: str | None
    accepted: bool
    filled: bool
    outcome: str
    reason: str
    profit_r: float | None
    mfe_r: float | None
    mae_r: float | None
    spread_r: float | None
    entry_drift_r: float | None
    trigger_delay_seconds: float | None
    placement_delay_seconds: float | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PostCloseReplayResult:
    rows: tuple[PostCloseReplayRow, ...]
    events: tuple[dict[str, Any], ...]
    arms_detected: int
    broker_mutation_enabled: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "broker_mutation_enabled": False,
            "arms_detected": self.arms_detected,
            "rows": [row.as_dict() for row in self.rows],
            "events": list(self.events),
        }


@dataclass
class _ActivePosition:
    state: PostCloseState
    entry: float
    stop: float
    target: float
    risk: float
    spread_r: float
    drift_r: float
    opened_at: str
    order_placed_at: str | None = None
    retest_at: str | None = None
    volume: float = 1.0
    realized_r: float = 0.0
    mfe_r: float = 0.0
    mae_r: float = 0.0
    adverse_observations: int = 0
    first_partial_done: bool = False
    rejection_stage: int = 0
    last_quote: QuoteObservation | None = None

    @property
    def arm(self) -> PostCloseArm:
        return self.state.arm

    def favorable_price(self, quote: QuoteObservation) -> float:
        mark = quote.bid if self.arm.direction == "BUY" else quote.ask
        return mark - self.entry if self.arm.direction == "BUY" else self.entry - mark


@dataclass
class _ConsumedZone:
    arm: PostCloseArm
    moved_away: bool = False
    reset_complete: bool = False

    def observe(self, quote: QuoteObservation, multiple: float) -> None:
        mid = (quote.bid + quote.ask) / 2.0
        distance = float(multiple) * self.arm.tolerance
        if mid < self.arm.zone_low - distance or mid > self.arm.zone_high + distance:
            self.moved_away = True
        elif self.moved_away and self.arm.zone_low <= mid <= self.arm.zone_high:
            self.reset_complete = True

    def blocks(self, arm: PostCloseArm) -> bool:
        same_zone = (
            arm.level_side == self.arm.level_side
            and abs(arm.level - self.arm.level)
            <= max(arm.tolerance, self.arm.tolerance)
        )
        return same_zone and arm.family == self.arm.family and not self.reset_complete


@dataclass
class _PendingRetest:
    state: PostCloseState
    placed_at: str
    expires_at: str
    entry: float
    stop: float
    target: float
    intended_risk: float
    spread_r: float
    structural_distance_r: float
    order_kind: str = "LIMIT"
    retest_at: str | None = None
    expiry_reason: str = "PENDING_RETEST_EXPIRED"
    drift_basis: str = "EXECUTION"

    @property
    def arm(self) -> PostCloseArm:
        return self.state.arm


@dataclass
class _ReconfirmWatch:
    state: PostCloseState
    started_at: str
    expires_at: str
    retest_at: str | None = None
    placement_due_at: str | None = None

    @property
    def arm(self) -> PostCloseArm:
        return self.state.arm


class _EventBuffer(list[dict[str, Any]]):
    def __init__(self, enabled: bool) -> None:
        super().__init__()
        self.enabled = bool(enabled)

    def append(self, item: dict[str, Any]) -> None:
        if self.enabled:
            super().append(item)


def detect_replay_arms(
    candles: Iterable[Candle],
    *,
    clean_levels: bool = False,
    candidate_name: str = "ONE_MINUTE_SYMMETRIC_POST_CLOSE_STATE_V1",
    signal_model: str = "REPEATED_LEVEL",
) -> tuple[PostCloseArm, ...]:
    """Detect one selected arm per closed-candle decision without future data."""
    ordered = sorted(candles, key=lambda candle: parse_utc(candle.timestamp))
    arms: list[PostCloseArm] = []
    for index in range(2, len(ordered)):
        window = ordered[max(0, index - 59) : index + 1]
        if signal_model == "IMPULSE_INSIDE_PULLBACK":
            from tradingagents.agents.price_action.one_minute_impulse_inside_pullback import (
                detect_impulse_inside_pullback_arms,
            )

            candidates = detect_impulse_inside_pullback_arms(
                window,
                candidate_name=candidate_name,
            )
        elif signal_model == "CAUSAL_MICROBURST":
            from tradingagents.agents.price_action.one_minute_causal_microburst_v9 import (
                detect_causal_microburst_arms,
            )

            candidates = detect_causal_microburst_arms(
                window,
                candidate_name=candidate_name,
            )
        elif signal_model == "SHOCK_RECLAIM":
            from tradingagents.agents.price_action.one_minute_shock_reclaim import (
                detect_shock_reclaim_arms,
            )

            candidates = detect_shock_reclaim_arms(
                window,
                candidate_name=candidate_name,
            )
        elif signal_model == "COMPRESSION_EXPANSION":
            from tradingagents.agents.price_action.one_minute_compression_expansion import (
                detect_compression_expansion_arms,
            )

            candidates = detect_compression_expansion_arms(
                window,
                candidate_name=candidate_name,
            )
        else:
            candidates = detect_post_close_arms(
                window,
                clean_levels=clean_levels,
                candidate_name=candidate_name,
            )
        if candidates:
            arms.append(candidates[0])
    unique = {arm.arm_id: arm for arm in arms}
    return tuple(
        sorted(unique.values(), key=lambda arm: (parse_utc(arm.confirmation_closed_at), arm.arm_id))
    )


def _row(
    arm: PostCloseArm,
    *,
    state: PostCloseState | None = None,
    position: _ActivePosition | None = None,
    pending: _PendingRetest | None = None,
    accepted: bool,
    filled: bool,
    outcome: str,
    reason: str,
    closed_at: str | None = None,
    profit_r: float | None = None,
    retest_at_value: str | None = None,
) -> PostCloseReplayRow:
    lifecycle = state or (position.state if position else None) or (pending.state if pending else None)
    triggered_at = lifecycle.triggered_at if lifecycle else None
    retest_at = (
        position.retest_at
        if position
        else pending.retest_at if pending else retest_at_value
    )
    placed_at = (
        (position.order_placed_at or position.opened_at)
        if position
        else pending.placed_at if pending else None
    )
    filled_at = position.opened_at if position else None
    confirmation_close = parse_utc(arm.confirmation_closed_at)
    return PostCloseReplayRow(
        arm_id=arm.arm_id,
        session_id=confirmation_close.date().isoformat(),
        family=arm.family,
        direction=arm.direction,
        touch_count=arm.touch_count,
        confirmation_type=arm.confirmation_type,
        armed_at=arm.confirmation_closed_at,
        triggered_at=triggered_at,
        retest_at=retest_at,
        placed_at=placed_at,
        filled_at=filled_at,
        closed_at=closed_at,
        accepted=accepted,
        filled=filled,
        outcome=outcome,
        reason=reason,
        profit_r=round(profit_r, 6) if profit_r is not None else None,
        mfe_r=round(position.mfe_r, 6) if position else None,
        mae_r=round(position.mae_r, 6) if position else None,
        spread_r=round(position.spread_r, 6) if position else None,
        entry_drift_r=round(position.drift_r, 6) if position else None,
        trigger_delay_seconds=(
            round((parse_utc(triggered_at) - confirmation_close).total_seconds(), 4)
            if triggered_at
            else None
        ),
        placement_delay_seconds=(
            round((parse_utc(placed_at) - parse_utc(triggered_at)).total_seconds(), 4)
            if placed_at and triggered_at
            else None
        ),
    )


def _pending_invalidation_reason(pending: _PendingRetest, quote: QuoteObservation) -> str | None:
    arm = pending.arm
    if arm.direction == "BUY" and quote.bid < arm.invalidation:
        return "BUY_STORY_INVALIDATED_BEFORE_FILL"
    if arm.direction == "SELL" and quote.ask > arm.invalidation:
        return "SELL_STORY_INVALIDATED_BEFORE_FILL"
    return None


def _build_retest_pending(
    state: PostCloseState,
    quote: QuoteObservation,
    policy: PostCloseReplayConfig,
) -> tuple[_PendingRetest | None, str]:
    arm = state.arm
    now = quote.time_utc
    if not quote.valid:
        return None, "INVALID_PLACEMENT_QUOTE"
    if now >= parse_utc(arm.expires_at):
        return None, "ARM_EXPIRED_BEFORE_PLACEMENT"
    entry = arm.zone_high if arm.direction == "BUY" else arm.zone_low
    if arm.direction == "BUY":
        if quote.bid < arm.invalidation:
            return None, "BUY_STORY_INVALIDATED_AT_PLACEMENT"
        if quote.ask <= entry:
            return None, "BUY_RETEST_ALREADY_CROSSED_AT_PLACEMENT"
    else:
        if quote.ask > arm.invalidation:
            return None, "SELL_STORY_INVALIDATED_AT_PLACEMENT"
        if quote.bid >= entry:
            return None, "SELL_RETEST_ALREADY_CROSSED_AT_PLACEMENT"
    spread = quote.spread
    minimum_risk = max(
        policy.placement.minimum_stop_distance,
        spread * policy.placement.minimum_stop_spread_multiple,
    )
    if arm.direction == "BUY":
        stop = min(arm.invalidation, entry - minimum_risk)
        risk = entry - stop
        target = entry + risk * policy.placement.risk_reward
    else:
        stop = max(arm.invalidation, entry + minimum_risk)
        risk = stop - entry
        target = entry - risk * policy.placement.risk_reward
    if risk <= 0:
        return None, "INVALID_STOP_GEOMETRY"
    if risk > policy.placement.maximum_stop_distance:
        return None, "STOP_DISTANCE_ABOVE_MAXIMUM"
    pending_horizon = now + timedelta(seconds=max(1, policy.pending_expiry_seconds))
    confirmation_cap = parse_utc(arm.confirmation_closed_at) + timedelta(
        seconds=90 if arm.family in {"HIGH_BREAK_BUY", "LOW_BREAK_SELL"} else 75
    )
    expires_at = min(pending_horizon, confirmation_cap)
    tick_size = policy.placement.tick_size
    entry = round(round(entry / tick_size) * tick_size, 10)
    stop = round(round(stop / tick_size) * tick_size, 10)
    target = round(round(target / tick_size) * tick_size, 10)
    return (
        _PendingRetest(
            state=replace(state, phase=PostClosePhase.PLACED),
            placed_at=quote.time,
            expires_at=expires_at.isoformat(),
            entry=entry,
            stop=stop,
            target=target,
            intended_risk=risk,
            spread_r=spread / risk,
            structural_distance_r=abs(entry - arm.level) / risk,
            order_kind="LIMIT",
        ),
        "PLACEMENT_ACCEPTED",
    )


def _build_reconfirmation_stop(
    watch: _ReconfirmWatch,
    quote: QuoteObservation,
    policy: PostCloseReplayConfig,
) -> tuple[_PendingRetest | None, str]:
    arm = watch.arm
    now = quote.time_utc
    entry = (
        arm.zone_high + arm.break_margin
        if arm.direction == "BUY"
        else arm.zone_low - arm.break_margin
    )
    if arm.direction == "BUY":
        if quote.bid < arm.invalidation:
            return None, "BUY_STORY_INVALIDATED_AT_STOP_PLACEMENT"
        if quote.ask >= entry:
            return None, "BUY_RECONFIRMATION_ALREADY_CROSSED_AT_PLACEMENT"
    else:
        if quote.ask > arm.invalidation:
            return None, "SELL_STORY_INVALIDATED_AT_STOP_PLACEMENT"
        if quote.bid <= entry:
            return None, "SELL_RECONFIRMATION_ALREADY_CROSSED_AT_PLACEMENT"
    spread = quote.spread
    minimum_risk = max(
        policy.placement.minimum_stop_distance,
        spread * policy.placement.minimum_stop_spread_multiple,
    )
    if arm.direction == "BUY":
        stop = min(arm.invalidation, entry - minimum_risk)
        risk = entry - stop
        target = entry + risk * policy.placement.risk_reward
    else:
        stop = max(arm.invalidation, entry + minimum_risk)
        risk = stop - entry
        target = entry - risk * policy.placement.risk_reward
    if risk <= 0:
        return None, "INVALID_STOP_GEOMETRY"
    if risk > policy.placement.maximum_stop_distance:
        return None, "STOP_DISTANCE_ABOVE_MAXIMUM"
    expires_at = min(
        now + timedelta(seconds=max(1, policy.reconfirmation_stop_expiry_seconds)),
        parse_utc(watch.expires_at),
    )
    tick_size = policy.placement.tick_size
    entry = round(round(entry / tick_size) * tick_size, 10)
    stop = round(round(stop / tick_size) * tick_size, 10)
    target = round(round(target / tick_size) * tick_size, 10)
    return (
        _PendingRetest(
            state=replace(watch.state, phase=PostClosePhase.PLACED),
            placed_at=quote.time,
            expires_at=expires_at.isoformat(),
            entry=entry,
            stop=stop,
            target=target,
            intended_risk=risk,
            spread_r=spread / risk,
            structural_distance_r=abs(entry - arm.level) / risk,
            order_kind="STOP",
            retest_at=watch.retest_at,
        ),
        "PLACEMENT_ACCEPTED",
    )


def _build_hold_continuation_stop(
    state: PostCloseState,
    quote: QuoteObservation,
    policy: PostCloseReplayConfig,
) -> tuple[_PendingRetest | None, str]:
    """Build a future stop after a causally confirmed post-close hold."""
    arm = state.arm
    now = quote.time_utc
    if not quote.valid:
        return None, "INVALID_PLACEMENT_QUOTE"
    state_cap = parse_utc(arm.confirmation_closed_at) + timedelta(
        seconds=max(1, policy.state_cap_seconds_after_confirmation_close)
    )
    if now >= state_cap:
        return None, "STATE_CAP_EXPIRED_BEFORE_PLACEMENT"
    tick_size = max(float(policy.placement.tick_size), 1e-9)
    if arm.direction == "BUY":
        if quote.bid < arm.invalidation:
            return None, "BUY_STORY_INVALIDATED_AT_HOLD_STOP_PLACEMENT"
        structural_trigger = arm.zone_high + arm.break_margin
        entry = round(
            ceil(
                max(structural_trigger, float(quote.ask) + tick_size)
                / tick_size
                - 1e-9
            )
            * tick_size,
            10,
        )
    else:
        if quote.ask > arm.invalidation:
            return None, "SELL_STORY_INVALIDATED_AT_HOLD_STOP_PLACEMENT"
        structural_trigger = arm.zone_low - arm.break_margin
        entry = round(
            floor(
                min(structural_trigger, float(quote.bid) - tick_size)
                / tick_size
                + 1e-9
            )
            * tick_size,
            10,
        )

    spread = quote.spread
    minimum_risk = max(
        policy.placement.minimum_stop_distance,
        spread * policy.placement.minimum_stop_spread_multiple,
    )
    if arm.direction == "BUY":
        stop = round(
            floor(
                min(arm.invalidation, entry - minimum_risk) / tick_size + 1e-9
            )
            * tick_size,
            10,
        )
        risk = entry - stop
    else:
        stop = round(
            ceil(
                max(arm.invalidation, entry + minimum_risk) / tick_size - 1e-9
            )
            * tick_size,
            10,
        )
        risk = stop - entry
    if risk <= 0:
        return None, "INVALID_STOP_GEOMETRY"
    if risk > policy.placement.maximum_stop_distance:
        return None, "STOP_DISTANCE_ABOVE_MAXIMUM"
    drift_r = abs(entry - arm.level) / risk
    if drift_r > float(policy.maximum_hold_entry_drift_r):
        return None, "HOLD_ENTRY_DRIFT_ABOVE_MAXIMUM"

    if arm.direction == "BUY":
        target = round(
            floor(
                (entry + risk * policy.placement.risk_reward) / tick_size + 1e-9
            )
            * tick_size,
            10,
        )
    else:
        target = round(
            ceil(
                (entry - risk * policy.placement.risk_reward) / tick_size - 1e-9
            )
            * tick_size,
            10,
        )

    expires_at = min(
        now + timedelta(seconds=max(1, policy.hold_stop_expiry_seconds)),
        state_cap,
    )
    return (
        _PendingRetest(
            state=replace(state, phase=PostClosePhase.PLACED),
            placed_at=quote.time,
            expires_at=expires_at.isoformat(),
            entry=entry,
            stop=stop,
            target=target,
            intended_risk=risk,
            spread_r=spread / risk,
            structural_distance_r=drift_r,
            order_kind="STOP",
            expiry_reason="PENDING_HOLD_STOP_EXPIRED",
        ),
        "PLACEMENT_ACCEPTED",
    )


def _build_reclaim_stop(
    state: PostCloseState,
    quote: QuoteObservation,
    policy: PostCloseReplayConfig,
) -> tuple[_PendingRetest | None, str]:
    """Build the frozen V6 future stop after a post-close reclaim hold."""
    arm = state.arm
    now = quote.time_utc
    if not quote.valid:
        return None, "INVALID_PLACEMENT_QUOTE"
    state_cap = parse_utc(arm.confirmation_closed_at) + timedelta(
        seconds=max(1, policy.state_cap_seconds_after_confirmation_close)
    )
    if now >= state_cap:
        return None, "STATE_CAP_EXPIRED_BEFORE_PLACEMENT"

    tick_size = max(float(policy.placement.tick_size), 1e-9)
    if arm.direction == "BUY":
        if quote.bid < arm.invalidation:
            return None, "BUY_STORY_INVALIDATED_AT_RECLAIM_STOP_PLACEMENT"
        entry = round(
            ceil((float(quote.ask) + tick_size) / tick_size - 1e-9)
            * tick_size,
            10,
        )
    else:
        if quote.ask > arm.invalidation:
            return None, "SELL_STORY_INVALIDATED_AT_RECLAIM_STOP_PLACEMENT"
        entry = round(
            floor((float(quote.bid) - tick_size) / tick_size + 1e-9)
            * tick_size,
            10,
        )

    spread = quote.spread
    minimum_risk = max(
        policy.placement.minimum_stop_distance,
        spread * policy.placement.minimum_stop_spread_multiple,
    )
    if arm.direction == "BUY":
        stop = round(
            floor(
                min(arm.invalidation, entry - minimum_risk) / tick_size + 1e-9
            )
            * tick_size,
            10,
        )
        risk = entry - stop
    else:
        stop = round(
            ceil(
                max(arm.invalidation, entry + minimum_risk) / tick_size - 1e-9
            )
            * tick_size,
            10,
        )
        risk = stop - entry
    if risk <= 0:
        return None, "INVALID_STOP_GEOMETRY"
    if risk > policy.placement.maximum_stop_distance:
        return None, "STOP_DISTANCE_ABOVE_MAXIMUM"
    drift_r = abs(entry - arm.level) / risk
    if drift_r > float(policy.maximum_reclaim_entry_drift_r):
        return None, "RECLAIM_ENTRY_DRIFT_ABOVE_MAXIMUM"

    if arm.direction == "BUY":
        target = round(
            floor(
                (entry + risk * policy.placement.risk_reward) / tick_size + 1e-9
            )
            * tick_size,
            10,
        )
    else:
        target = round(
            ceil(
                (entry - risk * policy.placement.risk_reward) / tick_size - 1e-9
            )
            * tick_size,
            10,
        )

    expires_at = min(
        now + timedelta(seconds=max(1, policy.reclaim_stop_expiry_seconds)),
        state_cap,
    )
    return (
        _PendingRetest(
            state=replace(state, phase=PostClosePhase.PLACED),
            placed_at=quote.time,
            expires_at=expires_at.isoformat(),
            entry=entry,
            stop=stop,
            target=target,
            intended_risk=risk,
            spread_r=spread / risk,
            structural_distance_r=drift_r,
            order_kind="STOP",
            expiry_reason="PENDING_RECLAIM_STOP_EXPIRED",
            drift_basis="LEVEL",
        ),
        "PLACEMENT_ACCEPTED",
    )


def _build_inside_breakout_stop(
    state: PostCloseState,
    quote: QuoteObservation,
    policy: PostCloseReplayConfig,
) -> tuple[_PendingRetest | None, str]:
    """Build the frozen V7 future stop beyond the pullback boundary."""
    arm = state.arm
    now = quote.time_utc
    if not quote.valid:
        return None, "INVALID_PLACEMENT_QUOTE"
    state_cap = parse_utc(arm.confirmation_closed_at) + timedelta(
        seconds=max(1, policy.state_cap_seconds_after_confirmation_close)
    )
    if now >= state_cap:
        return None, "STATE_CAP_EXPIRED_BEFORE_PLACEMENT"

    tick_size = max(float(policy.placement.tick_size), 1e-9)
    if arm.direction == "BUY":
        if quote.bid < arm.invalidation:
            return None, "BUY_INSIDE_PULLBACK_INVALIDATED_AT_PLACEMENT"
        entry = round(
            ceil((arm.level + tick_size) / tick_size - 1e-9) * tick_size,
            10,
        )
        if quote.ask >= entry:
            return None, "BUY_INSIDE_BREAKOUT_ALREADY_CROSSED_AT_PLACEMENT"
    else:
        if quote.ask > arm.invalidation:
            return None, "SELL_INSIDE_PULLBACK_INVALIDATED_AT_PLACEMENT"
        entry = round(
            floor((arm.level - tick_size) / tick_size + 1e-9) * tick_size,
            10,
        )
        if quote.bid <= entry:
            return None, "SELL_INSIDE_BREAKOUT_ALREADY_CROSSED_AT_PLACEMENT"

    spread = quote.spread
    minimum_risk = max(
        policy.placement.minimum_stop_distance,
        spread * policy.placement.minimum_stop_spread_multiple,
    )
    if arm.direction == "BUY":
        stop = round(
            floor(
                min(arm.invalidation, entry - minimum_risk) / tick_size + 1e-9
            )
            * tick_size,
            10,
        )
        risk = entry - stop
    else:
        stop = round(
            ceil(
                max(arm.invalidation, entry + minimum_risk) / tick_size - 1e-9
            )
            * tick_size,
            10,
        )
        risk = stop - entry
    if risk <= 0:
        return None, "INVALID_STOP_GEOMETRY"
    if risk > policy.placement.maximum_stop_distance:
        return None, "STOP_DISTANCE_ABOVE_MAXIMUM"
    drift_r = abs(entry - arm.level) / risk
    if drift_r > float(policy.maximum_inside_entry_drift_r):
        return None, "INSIDE_ENTRY_DRIFT_ABOVE_MAXIMUM"

    if arm.direction == "BUY":
        target = round(
            floor(
                (entry + risk * policy.placement.risk_reward) / tick_size + 1e-9
            )
            * tick_size,
            10,
        )
    else:
        target = round(
            ceil(
                (entry - risk * policy.placement.risk_reward) / tick_size - 1e-9
            )
            * tick_size,
            10,
        )

    expires_at = min(
        now + timedelta(seconds=max(1, policy.inside_stop_expiry_seconds)),
        state_cap,
    )
    return (
        _PendingRetest(
            state=replace(state, phase=PostClosePhase.PLACED),
            placed_at=quote.time,
            expires_at=expires_at.isoformat(),
            entry=entry,
            stop=stop,
            target=target,
            intended_risk=risk,
            spread_r=spread / risk,
            structural_distance_r=drift_r,
            order_kind="STOP",
            expiry_reason="PENDING_INSIDE_BREAKOUT_STOP_EXPIRED",
            drift_basis="LEVEL",
        ),
        "PLACEMENT_ACCEPTED",
    )


def _event(name: str, time: str, arm: PostCloseArm, **details: Any) -> dict[str, Any]:
    return {
        "event": name,
        "time": time,
        "arm_id": arm.arm_id,
        "family": arm.family,
        "direction": arm.direction,
        **details,
    }


def _close_position(
    position: _ActivePosition,
    quote: QuoteObservation,
    *,
    reason: str,
    config: PostCloseReplayConfig,
) -> PostCloseReplayRow:
    favorable_r = position.favorable_price(quote) / position.risk
    profit_r = (
        position.realized_r
        + position.volume * favorable_r
        - float(config.cost_per_fill_r)
    )
    outcome = "WIN" if profit_r > 0 else "LOSS" if profit_r < 0 else "BREAK_EVEN"
    return _row(
        position.arm,
        position=position,
        accepted=True,
        filled=True,
        outcome=outcome,
        reason=reason,
        closed_at=quote.time,
        profit_r=profit_r,
    )


def _opposing_candle(candle: Candle, direction: str) -> bool:
    if float(candle.close) == float(candle.open):
        return False
    return (
        float(candle.close) < float(candle.open)
        if direction == "BUY"
        else float(candle.close) > float(candle.open)
    )


def replay_post_close_arms(
    arms: Iterable[PostCloseArm],
    ticks: Iterable[MarketTick | QuoteObservation],
    *,
    candles: Iterable[Candle] = (),
    config: PostCloseReplayConfig | None = None,
) -> PostCloseReplayResult:
    """Replay frozen arms with one active lifecycle and protective management."""
    policy = config or PostCloseReplayConfig()
    ordered_arms = sorted(
        arms,
        key=lambda arm: (parse_utc(arm.confirmation_closed_at), arm.arm_id),
    )
    ordered_ticks = sorted(
        (
            tick
            if isinstance(tick, QuoteObservation)
            else QuoteObservation(time=tick.time, bid=tick.bid, ask=tick.ask)
            for tick in ticks
        ),
        key=lambda tick: tick.time_utc,
    )
    candle_events = sorted(
        (
            (parse_utc(candle.timestamp) + timedelta(minutes=1), candle)
            for candle in candles
        ),
        key=lambda item: item[0],
    )
    rows: list[PostCloseReplayRow] = []
    events = _EventBuffer(policy.capture_events)
    state: PostCloseState | None = None
    position: _ActivePosition | None = None
    pending: _PendingRetest | None = None
    watch: _ReconfirmWatch | None = None
    consumed: _ConsumedZone | None = None
    loss_streak = 0
    pause_until: datetime | None = None

    arm_index = tick_index = candle_index = 0
    infinity = datetime.max.replace(tzinfo=parse_utc("2000-01-01T00:00:00+00:00").tzinfo)

    def finish_position(row: PostCloseReplayRow, quote: QuoteObservation) -> None:
        nonlocal position, state, consumed, loss_streak, pause_until
        assert position is not None
        arm = position.arm
        rows.append(row)
        events.append(_event("EXIT_SIMULATED", quote.time, arm, reason=row.reason, profit_r=row.profit_r))
        consumed = _ConsumedZone(arm)
        if row.profit_r is not None and row.profit_r < 0:
            loss_streak += 1
        else:
            loss_streak = 0
        if loss_streak >= 2:
            pause_until = quote.time_utc + timedelta(minutes=policy.two_loss_pause_minutes)
            events.append(
                _event(
                    "LOSS_PAUSE_STARTED",
                    quote.time,
                    arm,
                    loss_streak=loss_streak,
                    pause_until=pause_until.isoformat(),
                )
            )
        position = None
        state = None

    while arm_index < len(ordered_arms) or tick_index < len(ordered_ticks) or candle_index < len(candle_events):
        arm_time = (
            parse_utc(ordered_arms[arm_index].confirmation_closed_at)
            if arm_index < len(ordered_arms)
            else infinity
        )
        tick_time = ordered_ticks[tick_index].time_utc if tick_index < len(ordered_ticks) else infinity
        candle_time = candle_events[candle_index][0] if candle_index < len(candle_events) else infinity
        current = min(arm_time, tick_time, candle_time)

        if candle_time == current:
            candle = candle_events[candle_index][1]
            candle_index += 1
            if (
                position is not None
                and position.last_quote is not None
                and parse_utc(candle.timestamp) + timedelta(minutes=1)
                > parse_utc(position.opened_at)
                and _opposing_candle(candle, position.arm.direction)
            ):
                quote = position.last_quote
                favorable_r = position.favorable_price(quote) / position.risk
                if position.rejection_stage >= 1 or favorable_r <= 0:
                    finish_position(
                        _close_position(
                            position,
                            quote,
                            reason=(
                                "CANDLE_REJECTION_FULL_EXIT"
                                if position.rejection_stage >= 1
                                else "CANDLE_REJECTION_FULL_EXIT_UNPROTECTED"
                            ),
                            config=policy,
                        ),
                        quote,
                    )
                else:
                    fraction = min(position.volume, policy.candle_rejection_partial_fraction)
                    position.realized_r += fraction * favorable_r
                    position.volume -= fraction
                    position.rejection_stage = 1
                    position.stop = position.entry
                    events.append(
                        _event(
                            "MANAGEMENT_ACTION",
                            quote.time,
                            position.arm,
                            action="CANDLE_REJECTION_PARTIAL_EXIT",
                            favorable_r=round(favorable_r, 6),
                        )
                    )
            continue

        if arm_time == current:
            arm = ordered_arms[arm_index]
            arm_index += 1
            if position is not None or pending is not None or watch is not None or (
                state is not None
                and state.phase in {PostClosePhase.ARMED, PostClosePhase.TRIGGERED}
            ):
                rows.append(
                    _row(
                        arm,
                        accepted=False,
                        filled=False,
                        outcome="SKIPPED",
                        reason="ONE_ACTIVE_LIFECYCLE",
                    )
                )
                events.append(_event("CANDIDATE_REJECTED", arm.confirmation_closed_at, arm, reason="ONE_ACTIVE_LIFECYCLE"))
                continue
            pause_complete = pause_until is None or current >= pause_until
            reset_complete = consumed is None or consumed.reset_complete
            if pause_until is not None and (not pause_complete or not reset_complete):
                rows.append(
                    _row(
                        arm,
                        accepted=False,
                        filled=False,
                        outcome="SKIPPED",
                        reason="TWO_LOSS_PAUSE_ACTIVE",
                    )
                )
                events.append(_event("CANDIDATE_REJECTED", arm.confirmation_closed_at, arm, reason="TWO_LOSS_PAUSE_ACTIVE"))
                continue
            if pause_until is not None:
                events.append(_event("LOSS_PAUSE_ENDED", arm.confirmation_closed_at, arm))
                pause_until = None
                loss_streak = 0
            if consumed is not None and consumed.blocks(arm):
                rows.append(
                    _row(
                        arm,
                        accepted=False,
                        filled=False,
                        outcome="SKIPPED",
                        reason="SAME_OPENING_RESET_REQUIRED",
                    )
                )
                events.append(_event("CANDIDATE_REJECTED", arm.confirmation_closed_at, arm, reason="SAME_OPENING_RESET_REQUIRED"))
                continue
            state = PostCloseState(arm)
            events.append(_event("ARM_CREATED", arm.confirmation_closed_at, arm, expires_at=arm.expires_at))
            continue

        quote = ordered_ticks[tick_index]
        tick_index += 1
        if not quote.valid:
            continue
        if consumed is not None and not consumed.reset_complete:
            consumed.observe(quote, policy.reset_move_away_tolerance_multiple)
            if consumed.reset_complete:
                events.append(_event("RESET_SATISFIED", quote.time, consumed.arm))

        if pending is not None:
            if quote.time_utc <= parse_utc(pending.placed_at):
                continue
            invalidation = _pending_invalidation_reason(pending, quote)
            if invalidation is not None:
                rows.append(
                    _row(
                        pending.arm,
                        pending=pending,
                        accepted=True,
                        filled=False,
                        outcome="INVALIDATED",
                        reason=invalidation,
                        closed_at=quote.time,
                    )
                )
                events.append(_event("PENDING_INVALIDATED", quote.time, pending.arm, reason=invalidation))
                consumed = _ConsumedZone(pending.arm)
                state = None
                pending = None
                continue
            if quote.time_utc >= parse_utc(pending.expires_at):
                expiry_reason = pending.expiry_reason
                rows.append(
                    _row(
                        pending.arm,
                        pending=pending,
                        accepted=True,
                        filled=False,
                        outcome="EXPIRED",
                        reason=expiry_reason,
                        closed_at=quote.time,
                    )
                )
                events.append(
                    _event(
                        "PENDING_EXPIRED",
                        quote.time,
                        pending.arm,
                        reason=expiry_reason,
                    )
                )
                consumed = _ConsumedZone(pending.arm)
                state = None
                pending = None
                continue
            if pending.order_kind == "STOP":
                fillable = (
                    quote.ask >= pending.entry
                    if pending.arm.direction == "BUY"
                    else quote.bid <= pending.entry
                )
            else:
                fillable = (
                    quote.ask <= pending.entry
                    if pending.arm.direction == "BUY"
                    else quote.bid >= pending.entry
                )
            if not fillable:
                continue
            if pending.order_kind == "STOP":
                fill = float(quote.ask) if pending.arm.direction == "BUY" else float(quote.bid)
            else:
                fill = min(float(quote.ask), pending.entry) if pending.arm.direction == "BUY" else max(float(quote.bid), pending.entry)
            risk = fill - pending.stop if pending.arm.direction == "BUY" else pending.stop - fill
            if risk <= 0:
                rows.append(
                    _row(
                        pending.arm,
                        pending=pending,
                        accepted=True,
                        filled=False,
                        outcome="REJECTED",
                        reason="INVALID_FILL_GEOMETRY",
                        closed_at=quote.time,
                    )
                )
                consumed = _ConsumedZone(pending.arm)
                state = None
                pending = None
                continue
            execution_drift_r = (
                abs(fill - pending.arm.level) / risk
                if pending.drift_basis == "LEVEL"
                else abs(fill - pending.entry) / risk
            )
            position = _ActivePosition(
                state=pending.state,
                entry=fill,
                stop=pending.stop,
                target=pending.target,
                risk=risk,
                spread_r=pending.spread_r,
                drift_r=execution_drift_r,
                opened_at=quote.time,
                order_placed_at=pending.placed_at,
                retest_at=pending.retest_at,
                last_quote=quote,
            )
            events.append(_event("FILL_SIMULATED", quote.time, pending.arm, entry=fill, intended_entry=pending.entry, stop_loss=pending.stop, take_profit=pending.target))
            pending = None
            continue

        if watch is not None:
            arm = watch.arm
            if quote.time_utc >= parse_utc(watch.expires_at):
                rows.append(
                    _row(
                        arm,
                        state=watch.state,
                        accepted=True,
                        filled=False,
                        outcome="EXPIRED",
                        reason="RECONFIRMATION_STATE_EXPIRED",
                        closed_at=quote.time,
                        retest_at_value=watch.retest_at,
                    )
                )
                events.append(_event("RECONFIRMATION_STATE_EXPIRED", quote.time, arm, retest_at=watch.retest_at))
                consumed = _ConsumedZone(arm)
                state = None
                watch = None
                continue
            invalidated = (
                quote.bid < arm.invalidation
                if arm.direction == "BUY"
                else quote.ask > arm.invalidation
            )
            if invalidated:
                reason = f"{arm.direction}_STORY_INVALIDATED_DURING_RETEST_WATCH"
                rows.append(
                    _row(
                        arm,
                        state=watch.state,
                        accepted=True,
                        filled=False,
                        outcome="INVALIDATED",
                        reason=reason,
                        closed_at=quote.time,
                        retest_at_value=watch.retest_at,
                    )
                )
                events.append(_event("RETEST_WATCH_INVALIDATED", quote.time, arm, reason=reason))
                consumed = _ConsumedZone(arm)
                state = None
                watch = None
                continue
            if watch.retest_at is None:
                retested = (
                    quote.ask <= arm.zone_high
                    if arm.direction == "BUY"
                    else quote.bid >= arm.zone_low
                )
                if retested:
                    watch.retest_at = quote.time
                    watch.placement_due_at = (
                        quote.time_utc + timedelta(seconds=5)
                    ).isoformat()
                    events.append(_event("RETEST_OBSERVED", quote.time, arm, placement_due_at=watch.placement_due_at))
                continue
            if quote.time_utc < parse_utc(watch.placement_due_at or watch.expires_at):
                continue
            pending_order, reason = _build_reconfirmation_stop(watch, quote, policy)
            events.append(_event("PLACEMENT_SIMULATED" if pending_order else "PLACEMENT_REJECTED", quote.time, arm, reason=reason, retest_at=watch.retest_at))
            if pending_order is None:
                rows.append(
                    _row(
                        arm,
                        state=watch.state,
                        accepted=True,
                        filled=False,
                        outcome="REJECTED",
                        reason=reason,
                        closed_at=quote.time,
                        retest_at_value=watch.retest_at,
                    )
                )
                consumed = _ConsumedZone(arm)
                state = None
            else:
                pending = pending_order
                state = pending_order.state
            watch = None
            continue

        if position is not None:
            position.last_quote = quote
            favorable = position.favorable_price(quote)
            favorable_r = favorable / position.risk
            position.mfe_r = max(position.mfe_r, favorable_r)
            position.mae_r = min(position.mae_r, favorable_r)
            mark = quote.bid if position.arm.direction == "BUY" else quote.ask
            stop_hit = mark <= position.stop if position.arm.direction == "BUY" else mark >= position.stop
            target_hit = mark >= position.target if position.arm.direction == "BUY" else mark <= position.target
            if stop_hit and target_hit:
                finish_position(
                    _close_position(position, quote, reason="AMBIGUOUS_STOP_TARGET", config=policy),
                    quote,
                )
                continue
            if stop_hit:
                finish_position(_close_position(position, quote, reason="STOP_EXIT", config=policy), quote)
                continue
            if target_hit:
                finish_position(_close_position(position, quote, reason="TARGET_EXIT", config=policy), quote)
                continue

            management = _dynamic_fast_exit_settings(position.risk, position.spread_r * position.risk)
            if (
                not position.first_partial_done
                and favorable >= float(management["partial_first_trigger_points"])
            ):
                position.realized_r += 0.5 * favorable_r
                position.volume = 0.5
                position.first_partial_done = True
                lock = float(management["break_even_lock_points"])
                position.stop = (
                    position.entry + lock
                    if position.arm.direction == "BUY"
                    else position.entry - lock
                )
                events.append(_event("MANAGEMENT_ACTION", quote.time, position.arm, action="PARTIAL_1_AND_BREAK_EVEN", favorable_r=round(favorable_r, 6)))
                continue
            if favorable >= float(management["scalp_profit_points"]):
                finish_position(_close_position(position, quote, reason="SCALP_PROFIT_EXIT", config=policy), quote)
                continue
            if favorable_r <= -float(policy.intrabar_adverse_fraction):
                position.adverse_observations += 1
            else:
                position.adverse_observations = 0
            if position.adverse_observations >= policy.intrabar_adverse_confirmations:
                finish_position(_close_position(position, quote, reason="INTRABAR_ADVERSE_EXIT", config=policy), quote)
                continue
            break_even = float(management["break_even_trigger_points"])
            if favorable >= break_even:
                lock = float(management["break_even_lock_points"])
                candidate = position.entry + lock if position.arm.direction == "BUY" else position.entry - lock
                if position.arm.direction == "BUY":
                    position.stop = max(position.stop, candidate)
                else:
                    position.stop = min(position.stop, candidate)
            continue

        if state is None:
            continue
        if state.phase == PostClosePhase.ARMED:
            if policy.entry_policy == "INSIDE_BREAKOUT_STOP_V7":
                transition = observe_post_close_inside_pullback_quote(state, quote)
            elif policy.entry_policy == "SHOCK_RECLAIM_STOP_V6":
                transition = observe_post_close_reclaim_quote(state, quote)
            else:
                transition = observe_post_close_quote(
                    state,
                    quote,
                    allow_break_retest_trigger=(
                        policy.entry_policy != "HOLD_CONTINUATION_STOP_V5_1"
                    ),
                )
            state = transition.state
            events.append(transition.as_dict())
            if state.phase in {PostClosePhase.EXPIRED, PostClosePhase.INVALIDATED}:
                rows.append(
                    _row(
                        state.arm,
                        state=state,
                        accepted=True,
                        filled=False,
                        outcome=state.phase.value,
                        reason=state.terminal_reason or transition.event,
                        closed_at=quote.time,
                    )
                )
                consumed = _ConsumedZone(state.arm)
                state = None
            continue
        if state.phase == PostClosePhase.TRIGGERED:
            if policy.entry_policy == "INSIDE_BREAKOUT_STOP_V7":
                if quote.time_utc < parse_utc(
                    state.placement_due_at or state.arm.expires_at
                ):
                    continue
                pending_order, reason = _build_inside_breakout_stop(
                    state,
                    quote,
                    policy,
                )
                events.append(
                    _event(
                        "PLACEMENT_SIMULATED" if pending_order else "PLACEMENT_REJECTED",
                        quote.time,
                        state.arm,
                        reason=reason,
                    )
                )
                if pending_order is None:
                    rows.append(
                        _row(
                            state.arm,
                            state=state,
                            accepted=True,
                            filled=False,
                            outcome="REJECTED",
                            reason=reason,
                            closed_at=quote.time,
                        )
                    )
                    consumed = _ConsumedZone(state.arm)
                    state = None
                else:
                    pending = pending_order
                    state = pending_order.state
                continue
            if policy.entry_policy == "SHOCK_RECLAIM_STOP_V6":
                if quote.time_utc < parse_utc(
                    state.placement_due_at or state.arm.expires_at
                ):
                    continue
                pending_order, reason = _build_reclaim_stop(
                    state,
                    quote,
                    policy,
                )
                events.append(
                    _event(
                        "PLACEMENT_SIMULATED" if pending_order else "PLACEMENT_REJECTED",
                        quote.time,
                        state.arm,
                        reason=reason,
                    )
                )
                if pending_order is None:
                    rows.append(
                        _row(
                            state.arm,
                            state=state,
                            accepted=True,
                            filled=False,
                            outcome="REJECTED",
                            reason=reason,
                            closed_at=quote.time,
                        )
                    )
                    consumed = _ConsumedZone(state.arm)
                    state = None
                else:
                    pending = pending_order
                    state = pending_order.state
                continue
            if policy.entry_policy == "HOLD_CONTINUATION_STOP_V5_1":
                if quote.time_utc < parse_utc(
                    state.placement_due_at or state.arm.expires_at
                ):
                    continue
                pending_order, reason = _build_hold_continuation_stop(
                    state,
                    quote,
                    policy,
                )
                events.append(
                    _event(
                        "PLACEMENT_SIMULATED" if pending_order else "PLACEMENT_REJECTED",
                        quote.time,
                        state.arm,
                        reason=reason,
                    )
                )
                if pending_order is None:
                    rows.append(
                        _row(
                            state.arm,
                            state=state,
                            accepted=True,
                            filled=False,
                            outcome="REJECTED",
                            reason=reason,
                            closed_at=quote.time,
                        )
                    )
                    consumed = _ConsumedZone(state.arm)
                    state = None
                else:
                    pending = pending_order
                    state = pending_order.state
                continue
            if policy.entry_policy == "RETEST_RECONFIRM_STOP_V3":
                if quote.time_utc < parse_utc(state.placement_due_at or state.arm.expires_at):
                    continue
                cap = parse_utc(state.arm.confirmation_closed_at) + timedelta(
                    seconds=max(1, policy.state_cap_seconds_after_confirmation_close)
                )
                watch = _ReconfirmWatch(
                    state=state,
                    started_at=quote.time,
                    expires_at=cap.isoformat(),
                )
                events.append(_event("RETEST_WATCH_STARTED", quote.time, state.arm, expires_at=watch.expires_at))
                continue
            if policy.entry_policy == "RETEST_LIMIT_V2":
                if quote.time_utc < parse_utc(state.placement_due_at or state.arm.expires_at):
                    continue
                pending_order, reason = _build_retest_pending(state, quote, policy)
                events.append(_event("PLACEMENT_SIMULATED" if pending_order else "PLACEMENT_REJECTED", quote.time, state.arm, reason=reason))
                if pending_order is None:
                    rows.append(
                        _row(
                            state.arm,
                            state=state,
                            accepted=True,
                            filled=False,
                            outcome="REJECTED",
                            reason=reason,
                            closed_at=quote.time,
                        )
                    )
                    consumed = _ConsumedZone(state.arm)
                    state = None
                else:
                    pending = pending_order
                    state = pending_order.state
                continue
            decision = evaluate_post_close_placement(state, quote, config=policy.placement)
            if decision.reason == "PLACEMENT_DELAY_PENDING":
                continue
            events.append(_event("PLACEMENT_SIMULATED" if decision.accepted else "PLACEMENT_REJECTED", quote.time, state.arm, **decision.as_dict()))
            if not decision.accepted:
                rows.append(
                    _row(
                        state.arm,
                        state=state,
                        accepted=True,
                        filled=False,
                        outcome="REJECTED",
                        reason=decision.reason,
                        closed_at=quote.time,
                    )
                )
                consumed = _ConsumedZone(state.arm)
                state = None
                continue
            assert decision.entry is not None
            assert decision.stop_loss is not None
            assert decision.take_profit is not None
            assert decision.risk_distance is not None
            spread_r = float(decision.spread or 0.0) / decision.risk_distance
            drift_r = float(decision.entry_drift or 0.0) / decision.risk_distance
            state = replace(state, phase=PostClosePhase.PLACED)
            position = _ActivePosition(
                state=state,
                entry=decision.entry,
                stop=decision.stop_loss,
                target=decision.take_profit,
                risk=decision.risk_distance,
                spread_r=spread_r,
                drift_r=drift_r,
                opened_at=quote.time,
                order_placed_at=quote.time,
                last_quote=quote,
            )
            events.append(_event("FILL_SIMULATED", quote.time, state.arm, entry=decision.entry, stop_loss=decision.stop_loss, take_profit=decision.take_profit))

    if position is not None:
        quote = position.last_quote
        if quote is not None:
            rows.append(
                _row(
                    position.arm,
                    position=position,
                    accepted=True,
                    filled=True,
                    outcome="OPEN",
                    reason="OPEN_AT_EVIDENCE_END",
                    closed_at=quote.time,
                )
            )
    elif pending is not None:
        rows.append(
            _row(
                pending.arm,
                pending=pending,
                accepted=True,
                filled=False,
                outcome="INCOMPLETE",
                reason="PENDING_AT_EVIDENCE_END",
            )
        )
    elif watch is not None:
        rows.append(
            _row(
                watch.arm,
                state=watch.state,
                accepted=True,
                filled=False,
                outcome="INCOMPLETE",
                reason="RECONFIRMATION_STATE_AT_EVIDENCE_END",
                retest_at_value=watch.retest_at,
            )
        )
    elif state is not None:
        rows.append(
            _row(
                state.arm,
                state=state,
                accepted=True,
                filled=False,
                outcome="INCOMPLETE",
                reason="INCOMPLETE_AT_EVIDENCE_END",
            )
        )

    return PostCloseReplayResult(
        rows=tuple(rows),
        events=tuple(events),
        arms_detected=len(ordered_arms),
    )


def replay_post_close_fixture(
    fixture: Any,
    *,
    config: PostCloseReplayConfig | None = None,
) -> PostCloseReplayResult:
    policy = config or PostCloseReplayConfig()
    evidence_start = parse_utc(policy.evidence_start) if policy.evidence_start else None
    evidence_end = parse_utc(policy.evidence_end) if policy.evidence_end else None
    if evidence_start is not None and evidence_end is not None and evidence_end <= evidence_start:
        raise ValueError("evidence_end must be after evidence_start")
    arms = detect_replay_arms(
        fixture.candles,
        clean_levels=policy.clean_levels,
        candidate_name=policy.candidate_name,
        signal_model=policy.signal_model,
    )
    if evidence_start is not None:
        arms = tuple(
            arm
            for arm in arms
            if parse_utc(arm.confirmation_closed_at) >= evidence_start
        )
    if evidence_end is not None:
        arms = tuple(
            arm for arm in arms if parse_utc(arm.confirmation_closed_at) < evidence_end
        )
    ticks = tuple(fixture.ticks)
    if evidence_start is not None:
        ticks = tuple(tick for tick in ticks if parse_utc(tick.time) >= evidence_start)
    if evidence_end is not None:
        ticks = tuple(tick for tick in ticks if parse_utc(tick.time) < evidence_end)
    return replay_post_close_arms(
        arms,
        ticks,
        candles=fixture.candles,
        config=policy,
    )


__all__ = [
    "PostCloseReplayConfig",
    "PostCloseReplayResult",
    "PostCloseReplayRow",
    "detect_replay_arms",
    "replay_post_close_arms",
    "replay_post_close_fixture",
]
