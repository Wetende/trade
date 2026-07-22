"""Deterministic, broker-free replay for One Minute Quote Pressure V8."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_post_close_replay import (
    detect_replay_arms,
)
from tradingagents.agents.price_action.one_minute_post_close_state import (
    PostCloseArm,
    QuoteObservation,
    parse_utc,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import (
    CANDIDATE_NAME,
    TERMINAL_PHASES,
    V8Config,
    V8Phase,
    V8State,
    evaluate_v8_stop_order,
    mark_v8_placed,
    observe_v8_quote,
    start_v8_state,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_evidence import (
    V8EvidenceCounters,
    V8EvidenceRow,
)
from tradingagents.agents.price_action.opening_tick_replay import MarketTick


@dataclass(frozen=True)
class V8ReplayConfig:
    strategy: V8Config = field(default_factory=V8Config)
    cost_per_fill_r: float = 0.05
    two_loss_pause_minutes: int = 15
    clean_levels: bool = False
    evidence_start: str | None = None
    evidence_end: str | None = None
    capture_events: bool = True
    ordered_ticks: bool = False
    candidate_name: str = CANDIDATE_NAME
    signal_model: str = "REPEATED_LEVEL"
    session_bucket_hours: int = 24

    def __post_init__(self) -> None:
        if self.cost_per_fill_r < 0:
            raise ValueError("cost_per_fill_r must be non-negative")
        if self.two_loss_pause_minutes <= 0:
            raise ValueError("two_loss_pause_minutes must be positive")
        if not str(self.candidate_name).strip():
            raise ValueError("candidate_name must be non-empty")
        if not str(self.signal_model).strip():
            raise ValueError("signal_model must be non-empty")
        if self.session_bucket_hours <= 0 or 24 % self.session_bucket_hours:
            raise ValueError("session_bucket_hours must divide 24")


@dataclass(frozen=True)
class V8ReplayResult:
    rows: tuple[V8EvidenceRow, ...]
    events: tuple[dict[str, Any], ...]
    counters: V8EvidenceCounters
    broker_mutation_enabled: bool = False
    candidate: str = CANDIDATE_NAME

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "broker_mutation_enabled": False,
            "rows": [row.as_dict() for row in self.rows],
            "events": list(self.events),
            "counters": self.counters.as_dict(),
        }


@dataclass
class _Pending:
    state: V8State
    placed_at: str
    expires_at: str
    entry: float
    stop: float
    target: float
    risk: float

    @property
    def arm(self) -> PostCloseArm:
        return self.state.arm


@dataclass
class _Position:
    state: V8State
    placed_at: str
    filled_at: str
    entry: float
    intended_entry: float
    stop: float
    target: float
    risk: float

    @property
    def arm(self) -> PostCloseArm:
        return self.state.arm


def replay_v8_fixture(
    fixture: Any,
    *,
    config: V8ReplayConfig | None = None,
) -> V8ReplayResult:
    policy = config or V8ReplayConfig()
    return replay_v8(
        fixture.candles,
        fixture.ticks,
        config=policy,
    )


def replay_v8(
    candles: Iterable[Candle],
    ticks: Iterable[MarketTick | QuoteObservation],
    *,
    config: V8ReplayConfig | None = None,
) -> V8ReplayResult:
    """Replay V8 with one active arm/order/position and no future data."""
    policy = config or V8ReplayConfig()
    start = parse_utc(policy.evidence_start) if policy.evidence_start else None
    end = parse_utc(policy.evidence_end) if policy.evidence_end else None
    if start is not None and end is not None and end <= start:
        raise ValueError("evidence_end must be after evidence_start")
    candle_values = tuple(candles)
    arms = detect_replay_arms(
        candle_values,
        clean_levels=policy.clean_levels,
        candidate_name=policy.candidate_name,
        signal_model=policy.signal_model,
    )
    arms = tuple(
        arm
        for arm in arms
        if (start is None or parse_utc(arm.confirmation_closed_at) >= start)
        and (end is None or parse_utc(arm.confirmation_closed_at) < end)
    )
    quotes = (
        tick
        if isinstance(tick, QuoteObservation)
        else QuoteObservation(time=tick.time, bid=tick.bid, ask=tick.ask)
        for tick in ticks
        if (start is None or parse_utc(tick.time) >= start)
        and (end is None or parse_utc(tick.time) < end)
    )
    return replay_v8_arms(
        arms,
        quotes,
        config=policy,
        ordered_ticks=policy.ordered_ticks,
    )


def replay_v8_arms(
    arms: Iterable[PostCloseArm],
    ticks: Iterable[MarketTick | QuoteObservation],
    *,
    config: V8ReplayConfig | None = None,
    ordered_ticks: bool = False,
) -> V8ReplayResult:
    policy = config or V8ReplayConfig()
    ordered_arms = tuple(
        sorted(
            arms,
            key=lambda arm: (parse_utc(arm.confirmation_closed_at), arm.arm_id),
        )
    )
    quote_values = (
        tick
        if isinstance(tick, QuoteObservation)
        else QuoteObservation(time=tick.time, bid=tick.bid, ask=tick.ask)
        for tick in ticks
    )
    quotes = quote_values if ordered_ticks else iter(sorted(quote_values, key=lambda item: item.time_utc))
    events: list[dict[str, Any]] = []
    rows: list[V8EvidenceRow] = []
    state: V8State | None = None
    triggered_at: str | None = None
    pending: _Pending | None = None
    position: _Position | None = None
    arm_index = 0
    loss_streak = 0
    pause_until: datetime | None = None
    reset_confirmation_after: datetime | None = None
    valid_triggers = placements = fills = 0
    crossed = geometry = 0
    last_quote: QuoteObservation | None = None
    previous_quote_time: datetime | None = None

    def event(name: str, quote: QuoteObservation, arm: PostCloseArm, **details: Any) -> None:
        if policy.capture_events:
            events.append(
                {
                    "event": name,
                    "time": quote.time,
                    "arm_id": arm.arm_id,
                    "family": arm.family,
                    "direction": arm.direction,
                    **details,
                }
            )

    def append_terminal(
        arm: PostCloseArm,
        *,
        outcome: str,
        reason: str,
        closed_at: str | None,
        local_state: V8State | None = None,
        local_triggered_at: str | None = None,
        local_pending: _Pending | None = None,
        local_position: _Position | None = None,
        profit_r: float | None = None,
    ) -> None:
        rows.append(
            V8EvidenceRow(
                arm_id=arm.arm_id,
                session_id=_session_id(
                    arm.confirmation_closed_at,
                    policy.session_bucket_hours,
                ),
                family=arm.family,
                direction=arm.direction,
                armed_at=arm.confirmation_closed_at,
                triggered_at=local_triggered_at,
                placed_at=(
                    local_pending.placed_at
                    if local_pending
                    else local_position.placed_at if local_position else None
                ),
                filled_at=local_position.filled_at if local_position else None,
                closed_at=closed_at,
                outcome=outcome,
                reason=reason,
                profit_r=round(profit_r, 10) if profit_r is not None else None,
            )
        )

    for quote in quotes:
        quote_time = quote.time_utc
        if ordered_ticks and previous_quote_time is not None and quote_time < previous_quote_time:
            raise ValueError("ordered V8 quote stream is not monotonic")
        previous_quote_time = quote_time
        last_quote = quote
        # Make arms visible only after their confirmation candle has closed.
        while (
            arm_index < len(ordered_arms)
            and parse_utc(ordered_arms[arm_index].confirmation_closed_at)
            <= quote_time
        ):
            arm = ordered_arms[arm_index]
            arm_index += 1
            if state is not None or pending is not None or position is not None:
                append_terminal(
                    arm,
                    outcome="SKIPPED",
                    reason="ONE_ACTIVE_LIFECYCLE_BLOCK",
                    closed_at=quote.time,
                )
                event("ARM_SKIPPED", quote, arm, reason="ONE_ACTIVE_LIFECYCLE_BLOCK")
                continue
            if pause_until is not None and quote_time < pause_until:
                append_terminal(
                    arm,
                    outcome="SKIPPED",
                    reason="TWO_LOSS_PAUSE_ACTIVE",
                    closed_at=quote.time,
                )
                event("ARM_SKIPPED", quote, arm, reason="TWO_LOSS_PAUSE_ACTIVE")
                continue
            if (
                reset_confirmation_after is not None
                and parse_utc(arm.confirmation_closed_at) <= reset_confirmation_after
            ):
                append_terminal(
                    arm,
                    outcome="SKIPPED",
                    reason="STRUCTURAL_RESET_REQUIRED",
                    closed_at=quote.time,
                )
                event("ARM_SKIPPED", quote, arm, reason="STRUCTURAL_RESET_REQUIRED")
                continue
            try:
                state = start_v8_state(arm, quote, config=policy.strategy)
            except ValueError:
                append_terminal(
                    arm,
                    outcome="REJECTED",
                    reason="INVALID_ARM_QUOTE",
                    closed_at=quote.time,
                )
                continue
            triggered_at = None
            event("ARMED", quote, arm, arm_time_spread=state.arm_time_spread)

        if position is not None:
            mark = quote.bid if position.arm.direction == "BUY" else quote.ask
            stop_hit = (
                mark <= position.stop
                if position.arm.direction == "BUY"
                else mark >= position.stop
            )
            target_hit = (
                mark >= position.target
                if position.arm.direction == "BUY"
                else mark <= position.target
            )
            if stop_hit or target_hit:
                movement = (
                    mark - position.entry
                    if position.arm.direction == "BUY"
                    else position.entry - mark
                )
                profit_r = movement / position.risk - policy.cost_per_fill_r
                outcome = "WIN" if profit_r > 0 else "LOSS" if profit_r < 0 else "BREAK_EVEN"
                reason = "STOP_EXIT" if stop_hit else "TARGET_EXIT"
                append_terminal(
                    position.arm,
                    outcome=outcome,
                    reason=reason,
                    closed_at=quote.time,
                    local_triggered_at=triggered_at,
                    local_position=position,
                    profit_r=profit_r,
                )
                event("POSITION_CLOSED", quote, position.arm, reason=reason, profit_r=profit_r)
                if profit_r < 0:
                    loss_streak += 1
                else:
                    loss_streak = 0
                if loss_streak >= 2:
                    pause_until = quote_time + timedelta(
                        minutes=policy.two_loss_pause_minutes
                    )
                    reset_confirmation_after = pause_until
                    event(
                        "TWO_LOSS_PAUSE_STARTED",
                        quote,
                        position.arm,
                        pause_until=pause_until.isoformat(),
                        structural_reset_after=reset_confirmation_after.isoformat(),
                    )
                position = None
                state = None
                triggered_at = None
            continue

        if pending is not None:
            if quote_time >= parse_utc(pending.expires_at):
                append_terminal(
                    pending.arm,
                    outcome="EXPIRED",
                    reason="PENDING_ORDER_EXPIRED",
                    closed_at=quote.time,
                    local_triggered_at=triggered_at,
                    local_pending=pending,
                )
                event("PENDING_EXPIRED", quote, pending.arm)
                pending = None
                state = None
                triggered_at = None
                continue
            if pending.arm.direction == "BUY" and quote.bid < pending.arm.invalidation:
                invalid = "BUY_STORY_INVALIDATED_BEFORE_FILL"
            elif pending.arm.direction == "SELL" and quote.ask > pending.arm.invalidation:
                invalid = "SELL_STORY_INVALIDATED_BEFORE_FILL"
            else:
                invalid = None
            if invalid:
                append_terminal(
                    pending.arm,
                    outcome="INVALIDATED",
                    reason=invalid,
                    closed_at=quote.time,
                    local_triggered_at=triggered_at,
                    local_pending=pending,
                )
                event("PENDING_CANCELLED", quote, pending.arm, reason=invalid)
                pending = None
                state = None
                triggered_at = None
                continue
            fill = (
                quote.ask >= pending.entry
                if pending.arm.direction == "BUY"
                else quote.bid <= pending.entry
            )
            if fill:
                actual_entry = quote.ask if pending.arm.direction == "BUY" else quote.bid
                position = _Position(
                    state=pending.state,
                    placed_at=pending.placed_at,
                    filled_at=quote.time,
                    entry=actual_entry,
                    intended_entry=pending.entry,
                    stop=pending.stop,
                    target=pending.target,
                    risk=pending.risk,
                )
                fills += 1
                event(
                    "ORDER_FILLED",
                    quote,
                    pending.arm,
                    intended_entry=pending.entry,
                    actual_entry=actual_entry,
                    entry_drift_r=abs(actual_entry - pending.entry) / pending.risk,
                )
                pending = None
            continue

        if state is None:
            continue
        transition = observe_v8_quote(state, quote, config=policy.strategy)
        state = transition.state
        if policy.capture_events:
            events.append(transition.as_dict())
        if transition.event == "PRESSURE_ACCEPTED":
            valid_triggers += 1
            triggered_at = quote.time
        if state.phase in TERMINAL_PHASES:
            reason = state.terminal_reason or transition.event
            if "CROSSED" in reason:
                crossed += 1
            if "STOP_DISTANCE" in reason or "GEOMETRY" in reason:
                geometry += 1
            append_terminal(
                state.arm,
                outcome=state.phase.value,
                reason=reason,
                closed_at=quote.time,
                local_state=state,
                local_triggered_at=triggered_at,
            )
            state = None
            triggered_at = None
            continue
        if transition.event != "PLACEMENT_READY":
            continue
        decision = evaluate_v8_stop_order(state, quote, config=policy.strategy)
        if not decision.accepted:
            reason = decision.reason
            if "CROSSED" in reason:
                crossed += 1
            if "STOP_DISTANCE" in reason or "GEOMETRY" in reason:
                geometry += 1
            append_terminal(
                state.arm,
                outcome="REJECTED",
                reason=reason,
                closed_at=quote.time,
                local_state=state,
                local_triggered_at=triggered_at,
            )
            state = None
            triggered_at = None
            continue
        state = mark_v8_placed(state, decision)
        pending = _Pending(
            state=state,
            placed_at=quote.time,
            expires_at=str(decision.expires_at),
            entry=float(decision.entry),
            stop=float(decision.stop_loss),
            target=float(decision.take_profit),
            risk=float(decision.risk_distance),
        )
        placements += 1
        event("PENDING_PLACED", quote, state.arm, decision=decision.as_dict())

    if position is not None:
        append_terminal(
            position.arm,
            outcome="OPEN",
            reason="POSITION_OPEN_AT_EVIDENCE_END",
            closed_at=last_quote.time if last_quote else None,
            local_triggered_at=triggered_at,
            local_position=position,
        )
    elif pending is not None:
        append_terminal(
            pending.arm,
            outcome="INCOMPLETE",
            reason="PENDING_AT_EVIDENCE_END",
            closed_at=last_quote.time if last_quote else None,
            local_triggered_at=triggered_at,
            local_pending=pending,
        )
    elif state is not None:
        append_terminal(
            state.arm,
            outcome="INCOMPLETE",
            reason="STATE_AT_EVIDENCE_END",
            closed_at=last_quote.time if last_quote else None,
            local_state=state,
            local_triggered_at=triggered_at,
        )
    # Arms after the final available tick are explicitly unevaluable.
    for arm in ordered_arms[arm_index:]:
        append_terminal(
            arm,
            outcome="INCOMPLETE",
            reason="NO_POST_CLOSE_QUOTES",
            closed_at=None,
        )

    counters = V8EvidenceCounters(
        arms_detected=len(ordered_arms),
        valid_triggers=valid_triggers,
        placements=placements,
        fills=fills,
        crossed_rejections=crossed,
        geometry_rejections=geometry,
    )
    return V8ReplayResult(
        tuple(rows),
        tuple(events),
        counters,
        candidate=policy.candidate_name,
    )


def _session_id(timestamp: str, bucket_hours: int) -> str:
    observed = parse_utc(timestamp)
    bucket = (observed.hour // bucket_hours) * bucket_hours
    return observed.replace(
        hour=bucket,
        minute=0,
        second=0,
        microsecond=0,
    ).isoformat()


__all__ = [
    "V8ReplayConfig",
    "V8ReplayResult",
    "replay_v8",
    "replay_v8_arms",
    "replay_v8_fixture",
]
