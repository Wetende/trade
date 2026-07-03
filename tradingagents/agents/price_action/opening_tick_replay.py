"""Broker-free tick replay for M1 opening-state research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

import numpy as np
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
    completed_at: str | None
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


def _valid_quote(tick: MarketTick) -> bool:
    bid = float(tick.bid)
    ask = float(tick.ask)
    return bid > 0 and ask > 0 and ask >= bid


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
    placed_at: str | None = None,
    completed_at: str | None = None,
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
        placed_at=placed_at or opportunity.signal_time,
        completed_at=completed_at,
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


def _timestamp(value: str) -> float:
    return _parse(value).timestamp()


def _favorable_points(
    direction: str,
    *,
    entry: float,
    marks: np.ndarray,
) -> np.ndarray:
    if direction == "BUY":
        return marks - entry
    return entry - marks


@dataclass(frozen=True)
class PreparedTickSeries:
    """Pre-sorted vectorized tick series for exact repeated opportunity replay."""

    ticks: tuple[MarketTick, ...]
    epoch_seconds: np.ndarray
    bids: np.ndarray
    asks: np.ndarray
    valid: np.ndarray

    @classmethod
    def from_ticks(
        cls,
        ticks: list[MarketTick] | tuple[MarketTick, ...],
    ) -> "PreparedTickSeries":
        ordered = tuple(sorted(ticks, key=lambda item: _parse(item.time)))
        epoch_seconds = np.array([_timestamp(tick.time) for tick in ordered], dtype=float)
        bids = np.array([float(tick.bid) for tick in ordered], dtype=float)
        asks = np.array([float(tick.ask) for tick in ordered], dtype=float)
        return cls(
            ticks=ordered,
            epoch_seconds=epoch_seconds,
            bids=bids,
            asks=asks,
            valid=(bids > 0) & (asks > 0) & (asks >= bids),
        )

    def simulate(
        self,
        opportunity: OpeningOpportunity,
        config: ReplayConfig,
        *,
        start_index: int = 0,
    ) -> SimulatedOpeningTrade:
        decision_seconds = _timestamp(opportunity.signal_time)
        first_index = max(
            0,
            int(start_index),
            int(np.searchsorted(self.epoch_seconds, decision_seconds, side="left")),
        )
        if first_index >= len(self.ticks):
            return _base_result(
                "INSUFFICIENT_TICK_EVIDENCE",
                opportunity,
                reason="NO_DECISION_TICK",
                completed_at=opportunity.signal_time,
            )

        valid_after = np.flatnonzero(self.valid[first_index:])
        if valid_after.size == 0:
            return _base_result(
                "INSUFFICIENT_TICK_EVIDENCE",
                opportunity,
                reason="NO_VALID_DECISION_TICK",
                completed_at=opportunity.signal_time,
            )
        decision_index = int(valid_after[0] + first_index)
        spread = round(float(self.asks[decision_index] - self.bids[decision_index]), 4)
        entry = _entry_price(opportunity)
        stop, target = _levels(opportunity, entry, config)
        expiry_duration = (
            config.reaction_expiry_seconds
            if opportunity.entry_kind == "reaction"
            else config.continuation_expiry_seconds
        )
        expiry_seconds = self.epoch_seconds[decision_index] + expiry_duration
        expiry_time = _parse(self.ticks[decision_index].time) + timedelta(
            seconds=expiry_duration
        )
        expiry_index = int(
            np.searchsorted(self.epoch_seconds, expiry_seconds, side="right")
        )
        valid_window = self.valid[decision_index:expiry_index]
        if opportunity.direction == "BUY":
            fill_window = (
                valid_window
                & (self.asks[decision_index:expiry_index] >= entry)
                & (
                    self.asks[decision_index:expiry_index]
                    <= entry + config.max_quote_drift
                )
            )
        else:
            fill_window = (
                valid_window
                & (self.bids[decision_index:expiry_index] <= entry)
                & (
                    self.bids[decision_index:expiry_index]
                    >= entry - config.max_quote_drift
                )
            )
        fills = np.flatnonzero(fill_window)
        if fills.size == 0:
            return _base_result(
                "EXPIRED",
                opportunity,
                reason="ENTRY_NOT_TOUCHED_BEFORE_EXPIRY",
                completed_at=expiry_time.isoformat(),
                entry=entry,
                stop=stop,
                target=target,
                spread_at_decision=spread,
            )

        fill_index = int(fills[0] + decision_index)
        fill_tick = self.ticks[fill_index]
        tail = slice(fill_index, len(self.ticks))
        valid_tail = self.valid[tail]
        if opportunity.direction == "BUY":
            ambiguous = valid_tail & (self.bids[tail] <= stop) & (self.asks[tail] >= target)
            stop_hits = valid_tail & (self.bids[tail] <= stop)
            target_hits = valid_tail & (self.bids[tail] >= target)
            marks = self.bids
        else:
            ambiguous = valid_tail & (self.asks[tail] >= stop) & (self.bids[tail] <= target)
            stop_hits = valid_tail & (self.asks[tail] >= stop)
            target_hits = valid_tail & (self.asks[tail] <= target)
            marks = self.asks

        candidates: list[tuple[int, str]] = []
        for name, mask in (
            ("AMBIGUOUS", ambiguous),
            ("TARGET", target_hits),
            ("STOP", stop_hits),
        ):
            hits = np.flatnonzero(mask)
            if hits.size:
                priority = 0 if name == "AMBIGUOUS" else 1 if name == "TARGET" else 2
                candidates.append((int(hits[0] + fill_index), f"{priority}:{name}"))

        if candidates:
            event_index, encoded = min(candidates, key=lambda item: (item[0], item[1]))
            event_type = encoded.split(":", 1)[1]
            if event_type == "AMBIGUOUS":
                mark_slice = marks[fill_index:event_index][
                    self.valid[fill_index:event_index]
                ]
                favorable = _favorable_points(
                    opportunity.direction,
                    entry=entry,
                    marks=mark_slice,
                )
                mfe = round(float(favorable.max()), 4) if favorable.size else 0.0
                mae = round(float(favorable.min()), 4) if favorable.size else 0.0
                return _base_result(
                    "INSUFFICIENT_TICK_EVIDENCE",
                    opportunity,
                    reason="AMBIGUOUS_STOP_AND_TARGET",
                    completed_at=self.ticks[event_index].time,
                    filled_at=fill_tick.time,
                    entry=entry,
                    stop=stop,
                    target=target,
                    mfe=mfe,
                    mae=mae,
                    spread_at_decision=spread,
                )

            mark_slice = marks[fill_index : event_index + 1][
                self.valid[fill_index : event_index + 1]
            ]
            favorable = _favorable_points(
                opportunity.direction,
                entry=entry,
                marks=mark_slice,
            )
            exit_price = target if event_type == "TARGET" else stop
            return _base_result(
                "CLOSED",
                opportunity,
                completed_at=self.ticks[event_index].time,
                filled_at=fill_tick.time,
                closed_at=self.ticks[event_index].time,
                entry=entry,
                stop=stop,
                target=target,
                exit_reason=event_type,
                profit=_profit(opportunity.direction, entry, exit_price),
                mfe=round(float(favorable.max()), 4) if favorable.size else 0.0,
                mae=round(float(favorable.min()), 4) if favorable.size else 0.0,
                spread_at_decision=spread,
            )

        valid_after_fill = np.flatnonzero(self.valid[fill_index:])
        mark_slice = marks[fill_index:][self.valid[fill_index:]]
        favorable = _favorable_points(
            opportunity.direction,
            entry=entry,
            marks=mark_slice,
        )
        completed_at = (
            self.ticks[int(valid_after_fill[-1] + fill_index)].time
            if valid_after_fill.size
            else fill_tick.time
        )
        return _base_result(
            "INSUFFICIENT_TICK_EVIDENCE",
            opportunity,
            reason="NO_EXIT_TICK",
            completed_at=completed_at,
            filled_at=fill_tick.time,
            entry=entry,
            stop=stop,
            target=target,
            mfe=round(float(favorable.max()), 4) if favorable.size else 0.0,
            mae=round(float(favorable.min()), 4) if favorable.size else 0.0,
            spread_at_decision=spread,
        )

    def simulate_window(
        self,
        opportunity: OpeningOpportunity,
        config: ReplayConfig,
        *,
        available_at: datetime,
        expires_at: datetime,
    ) -> SimulatedOpeningTrade:
        signal_time = _parse(opportunity.signal_time)
        placed_time = max(signal_time, available_at)
        placed_at = placed_time.isoformat()
        entry = _entry_price(opportunity)
        stop, target = _levels(opportunity, entry, config)
        if placed_time >= expires_at:
            return _base_result(
                "EXPIRED",
                opportunity,
                reason="QUEUE_EXPIRED_BEFORE_AVAILABLE",
                placed_at=placed_at,
                completed_at=expires_at.isoformat(),
                entry=entry,
                stop=stop,
                target=target,
            )

        first_index = int(
            np.searchsorted(
                self.epoch_seconds,
                placed_time.timestamp(),
                side="left",
            )
        )
        expiry_index = int(
            np.searchsorted(
                self.epoch_seconds,
                expires_at.timestamp(),
                side="right",
            )
        )
        if first_index >= len(self.ticks):
            return _base_result(
                "INSUFFICIENT_TICK_EVIDENCE",
                opportunity,
                reason="NO_DECISION_TICK",
                placed_at=placed_at,
                completed_at=placed_at,
                entry=entry,
                stop=stop,
                target=target,
            )

        valid_after = np.flatnonzero(self.valid[first_index:expiry_index])
        if valid_after.size == 0:
            return _base_result(
                "INSUFFICIENT_TICK_EVIDENCE",
                opportunity,
                reason="NO_VALID_DECISION_TICK",
                placed_at=placed_at,
                completed_at=placed_at,
                entry=entry,
                stop=stop,
                target=target,
            )
        decision_index = int(valid_after[0] + first_index)
        spread = round(float(self.asks[decision_index] - self.bids[decision_index]), 4)
        if opportunity.direction == "BUY":
            fill_window = (
                self.valid[decision_index:expiry_index]
                & (self.asks[decision_index:expiry_index] >= entry)
                & (
                    self.asks[decision_index:expiry_index]
                    <= entry + config.max_quote_drift
                )
            )
        else:
            fill_window = (
                self.valid[decision_index:expiry_index]
                & (self.bids[decision_index:expiry_index] <= entry)
                & (
                    self.bids[decision_index:expiry_index]
                    >= entry - config.max_quote_drift
                )
            )
        fills = np.flatnonzero(fill_window)
        if fills.size == 0:
            return _base_result(
                "EXPIRED",
                opportunity,
                reason="ENTRY_NOT_TOUCHED_BEFORE_EXPIRY",
                placed_at=placed_at,
                completed_at=expires_at.isoformat(),
                entry=entry,
                stop=stop,
                target=target,
                spread_at_decision=spread,
            )

        fill_index = int(fills[0] + decision_index)
        fill_tick = self.ticks[fill_index]
        tail = slice(fill_index, len(self.ticks))
        valid_tail = self.valid[tail]
        if opportunity.direction == "BUY":
            ambiguous = valid_tail & (self.bids[tail] <= stop) & (
                self.asks[tail] >= target
            )
            stop_hits = valid_tail & (self.bids[tail] <= stop)
            target_hits = valid_tail & (self.bids[tail] >= target)
            marks = self.bids
        else:
            ambiguous = valid_tail & (self.asks[tail] >= stop) & (
                self.bids[tail] <= target
            )
            stop_hits = valid_tail & (self.asks[tail] >= stop)
            target_hits = valid_tail & (self.asks[tail] <= target)
            marks = self.asks

        candidates: list[tuple[int, str]] = []
        for name, mask in (
            ("AMBIGUOUS", ambiguous),
            ("TARGET", target_hits),
            ("STOP", stop_hits),
        ):
            hits = np.flatnonzero(mask)
            if hits.size:
                priority = 0 if name == "AMBIGUOUS" else 1 if name == "TARGET" else 2
                candidates.append((int(hits[0] + fill_index), f"{priority}:{name}"))

        if candidates:
            event_index, encoded = min(candidates, key=lambda item: (item[0], item[1]))
            event_type = encoded.split(":", 1)[1]
            if event_type == "AMBIGUOUS":
                mark_slice = marks[fill_index:event_index][
                    self.valid[fill_index:event_index]
                ]
                favorable = _favorable_points(
                    opportunity.direction,
                    entry=entry,
                    marks=mark_slice,
                )
                mfe = round(float(favorable.max()), 4) if favorable.size else 0.0
                mae = round(float(favorable.min()), 4) if favorable.size else 0.0
                return _base_result(
                    "INSUFFICIENT_TICK_EVIDENCE",
                    opportunity,
                    reason="AMBIGUOUS_STOP_AND_TARGET",
                    placed_at=placed_at,
                    completed_at=self.ticks[event_index].time,
                    filled_at=fill_tick.time,
                    entry=entry,
                    stop=stop,
                    target=target,
                    mfe=mfe,
                    mae=mae,
                    spread_at_decision=spread,
                )

            mark_slice = marks[fill_index : event_index + 1][
                self.valid[fill_index : event_index + 1]
            ]
            favorable = _favorable_points(
                opportunity.direction,
                entry=entry,
                marks=mark_slice,
            )
            exit_price = target if event_type == "TARGET" else stop
            return _base_result(
                "CLOSED",
                opportunity,
                placed_at=placed_at,
                completed_at=self.ticks[event_index].time,
                filled_at=fill_tick.time,
                closed_at=self.ticks[event_index].time,
                entry=entry,
                stop=stop,
                target=target,
                exit_reason=event_type,
                profit=_profit(opportunity.direction, entry, exit_price),
                mfe=round(float(favorable.max()), 4) if favorable.size else 0.0,
                mae=round(float(favorable.min()), 4) if favorable.size else 0.0,
                spread_at_decision=spread,
            )

        valid_after_fill = np.flatnonzero(self.valid[fill_index:])
        mark_slice = marks[fill_index:][self.valid[fill_index:]]
        favorable = _favorable_points(
            opportunity.direction,
            entry=entry,
            marks=mark_slice,
        )
        completed_at = (
            self.ticks[int(valid_after_fill[-1] + fill_index)].time
            if valid_after_fill.size
            else fill_tick.time
        )
        return _base_result(
            "INSUFFICIENT_TICK_EVIDENCE",
            opportunity,
            reason="NO_EXIT_TICK",
            placed_at=placed_at,
            completed_at=completed_at,
            filled_at=fill_tick.time,
            entry=entry,
            stop=stop,
            target=target,
            mfe=round(float(favorable.max()), 4) if favorable.size else 0.0,
            mae=round(float(favorable.min()), 4) if favorable.size else 0.0,
            spread_at_decision=spread,
        )


def simulate_opportunity(
    opportunity: OpeningOpportunity,
    ticks: list[MarketTick] | tuple[MarketTick, ...],
    config: ReplayConfig,
) -> SimulatedOpeningTrade:
    """Simulate one pending opening with conservative tick ambiguity handling."""
    ordered = sorted(ticks, key=lambda item: _parse(item.time))
    return simulate_opportunity_from_sorted_ticks(
        opportunity,
        ordered,
        config,
        start_index=0,
    )


def simulate_opportunity_from_sorted_ticks(
    opportunity: OpeningOpportunity,
    sorted_ticks: list[MarketTick] | tuple[MarketTick, ...],
    config: ReplayConfig,
    *,
    start_index: int = 0,
) -> SimulatedOpeningTrade:
    """Simulate one pending opening from a pre-sorted tick sequence."""
    ordered = tuple(sorted_ticks)
    decision_time = _parse(opportunity.signal_time)
    first_index = max(0, int(start_index))
    saw_after_signal = False
    decision_index: int | None = None
    for index in range(first_index, len(ordered)):
        tick = ordered[index]
        if _parse(tick.time) < decision_time:
            continue
        saw_after_signal = True
        if _valid_quote(tick):
            decision_index = index
            break
    if not saw_after_signal:
        return _base_result(
            "INSUFFICIENT_TICK_EVIDENCE",
            opportunity,
            reason="NO_DECISION_TICK",
            completed_at=opportunity.signal_time,
        )
    if decision_index is None:
        return _base_result(
            "INSUFFICIENT_TICK_EVIDENCE",
            opportunity,
            reason="NO_VALID_DECISION_TICK",
            completed_at=opportunity.signal_time,
        )

    decision_tick = ordered[decision_index]
    spread = round(float(decision_tick.ask) - float(decision_tick.bid), 4)
    entry = _entry_price(opportunity)
    stop, target = _levels(opportunity, entry, config)
    decision_tick_time = _parse(decision_tick.time)
    expiry_duration = (
        config.reaction_expiry_seconds
        if opportunity.entry_kind == "reaction"
        else config.continuation_expiry_seconds
    )
    expiry = decision_tick_time + timedelta(seconds=expiry_duration)
    fill_index: int | None = None
    for index in range(decision_index, len(ordered)):
        tick = ordered[index]
        if not _valid_quote(tick):
            continue
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
            completed_at=expiry.isoformat(),
            entry=entry,
            stop=stop,
            target=target,
            spread_at_decision=spread,
        )

    fill = ordered[fill_index]
    mfe = 0.0
    mae = 0.0
    last_valid_time = fill.time
    for tick in ordered[fill_index:]:
        if not _valid_quote(tick):
            continue
        last_valid_time = tick.time
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
                completed_at=tick.time,
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
                completed_at=tick.time,
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
        completed_at=last_valid_time,
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
    "PreparedTickSeries",
    "ReplayConfig",
    "SimulatedOpeningTrade",
    "simulate_opportunity",
    "simulate_opportunity_from_sorted_ticks",
]
