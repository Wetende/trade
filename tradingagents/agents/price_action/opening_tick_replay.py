"""Broker-free tick replay for M1 opening-state research."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.price_action.opening_state import OpeningOpportunity


class MarketTick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    time: str
    bid: float
    ask: float


class ReplayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reaction_expiry_seconds: int = 20
    continuation_expiry_seconds: int = 45
    risk_reward: float = 1.5
    minimum_stop_distance: float = 0.30
    max_quote_drift: float = 0.60


class SimulatedOpeningTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["CLOSED", "EXPIRED", "INSUFFICIENT_TICK_EVIDENCE"]
    reason: str | None = None
    direction: Literal["BUY", "SELL"]
    placed_at: str
    filled_at: str | None
    closed_at: str | None
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    exit_reason: str | None
    profit: float | None
    mfe: float | None
    mae: float | None
    spread_at_decision: float | None = Field(default=None, ge=0)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _entry_price(opportunity: OpeningOpportunity) -> float:
    if opportunity.direction == "BUY":
        return round(float(opportunity.level) + float(opportunity.tolerance), 4)
    return round(float(opportunity.level) - float(opportunity.tolerance), 4)


def _fill_price(direction: str, tick: MarketTick) -> float:
    return float(tick.ask if direction == "BUY" else tick.bid)


def _exit_mark(direction: str, tick: MarketTick) -> float:
    return float(tick.bid if direction == "BUY" else tick.ask)


def _profit(direction: str, entry: float, exit_price: float) -> float:
    if direction == "BUY":
        return round(exit_price - entry, 4)
    return round(entry - exit_price, 4)


def _levels(
    opportunity: OpeningOpportunity,
    entry: float,
    config: ReplayConfig,
) -> tuple[float, float]:
    risk = max(
        abs(entry - float(opportunity.level)) + float(opportunity.tolerance),
        float(config.minimum_stop_distance),
    )
    if opportunity.direction == "BUY":
        return round(entry - risk, 4), round(entry + risk * config.risk_reward, 4)
    return round(entry + risk, 4), round(entry - risk * config.risk_reward, 4)


def _fills(direction: str, entry: float, tick: MarketTick, max_drift: float) -> bool:
    price = _fill_price(direction, tick)
    if direction == "BUY":
        return entry <= price <= entry + max_drift
    return entry - max_drift <= price <= entry


def _ambiguous_quote_span(
    direction: str,
    tick: MarketTick,
    *,
    stop: float,
    target: float,
) -> bool:
    if direction == "BUY":
        return float(tick.bid) <= stop and float(tick.ask) >= target
    return float(tick.ask) >= stop and float(tick.bid) <= target


def _hit_stop(direction: str, mark: float, stop: float) -> bool:
    return mark <= stop if direction == "BUY" else mark >= stop


def _hit_target(direction: str, mark: float, target: float) -> bool:
    return mark >= target if direction == "BUY" else mark <= target


def _base_result(
    status: Literal["CLOSED", "EXPIRED", "INSUFFICIENT_TICK_EVIDENCE"],
    opportunity: OpeningOpportunity,
    *,
    reason: str | None = None,
    filled_at: str | None = None,
    closed_at: str | None = None,
    entry: float | None = None,
    stop: float | None = None,
    target: float | None = None,
    exit_reason: str | None = None,
    profit: float | None = None,
    mfe: float | None = None,
    mae: float | None = None,
    spread_at_decision: float | None = None,
) -> SimulatedOpeningTrade:
    return SimulatedOpeningTrade(
        status=status,
        reason=reason,
        direction=opportunity.direction,
        placed_at=opportunity.signal_time,
        filled_at=filled_at,
        closed_at=closed_at,
        entry_price=round(entry, 4) if entry is not None else None,
        stop_loss=stop,
        take_profit=target,
        exit_reason=exit_reason,
        profit=profit,
        mfe=mfe,
        mae=mae,
        spread_at_decision=spread_at_decision,
    )


def simulate_opportunity(
    opportunity: OpeningOpportunity,
    ticks: list[MarketTick] | tuple[MarketTick, ...],
    config: ReplayConfig,
) -> SimulatedOpeningTrade:
    """Simulate one pending opening with conservative tick ambiguity handling."""
    ordered = sorted(ticks, key=lambda item: _parse(item.time))
    decision_time = _parse(opportunity.signal_time)
    usable = [tick for tick in ordered if _parse(tick.time) >= decision_time]
    if not usable:
        return _base_result(
            "INSUFFICIENT_TICK_EVIDENCE",
            opportunity,
            reason="NO_DECISION_TICK",
        )

    decision_tick = usable[0]
    spread = round(float(decision_tick.ask) - float(decision_tick.bid), 4)
    entry = _entry_price(opportunity)
    stop, target = _levels(opportunity, entry, config)
    expiry = decision_time + timedelta(
        seconds=(
            config.reaction_expiry_seconds
            if opportunity.entry_kind == "reaction"
            else config.continuation_expiry_seconds
        )
    )
    fill_index: int | None = None
    for index, tick in enumerate(usable):
        if _parse(tick.time) > expiry:
            break
        if _fills(opportunity.direction, entry, tick, config.max_quote_drift):
            fill_index = index
            break

    if fill_index is None:
        return _base_result(
            "EXPIRED",
            opportunity,
            reason="ENTRY_NOT_TOUCHED_BEFORE_EXPIRY",
            entry=entry,
            stop=stop,
            target=target,
            spread_at_decision=spread,
        )

    fill = usable[fill_index]
    mfe = 0.0
    mae = 0.0
    for tick in usable[fill_index:]:
        if _ambiguous_quote_span(
            opportunity.direction,
            tick,
            stop=stop,
            target=target,
        ):
            return _base_result(
                "INSUFFICIENT_TICK_EVIDENCE",
                opportunity,
                reason="AMBIGUOUS_STOP_AND_TARGET",
                filled_at=fill.time,
                entry=entry,
                stop=stop,
                target=target,
                mfe=round(mfe, 4),
                mae=round(mae, 4),
                spread_at_decision=spread,
            )

        mark = _exit_mark(opportunity.direction, tick)
        favorable = _profit(opportunity.direction, entry, mark)
        mfe = max(mfe, favorable)
        mae = min(mae, favorable)
        stop_hit = _hit_stop(opportunity.direction, mark, stop)
        target_hit = _hit_target(opportunity.direction, mark, target)
        if stop_hit or target_hit:
            exit_reason = "TARGET" if target_hit else "STOP"
            exit_price = target if target_hit else stop
            return _base_result(
                "CLOSED",
                opportunity,
                filled_at=fill.time,
                closed_at=tick.time,
                entry=entry,
                stop=stop,
                target=target,
                exit_reason=exit_reason,
                profit=_profit(opportunity.direction, entry, exit_price),
                mfe=round(mfe, 4),
                mae=round(mae, 4),
                spread_at_decision=spread,
            )

    return _base_result(
        "INSUFFICIENT_TICK_EVIDENCE",
        opportunity,
        reason="NO_EXIT_TICK",
        filled_at=fill.time,
        entry=entry,
        stop=stop,
        target=target,
        mfe=round(mfe, 4),
        mae=round(mae, 4),
        spread_at_decision=spread,
    )


__all__ = [
    "MarketTick",
    "ReplayConfig",
    "SimulatedOpeningTrade",
    "simulate_opportunity",
]
