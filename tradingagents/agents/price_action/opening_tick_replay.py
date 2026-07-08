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
    minimum_stop_spread_multiple: float = 0.0
    max_quote_drift: float = 0.60
    max_entry_distance: float = 0.0
    candle_close_delay_seconds: float = 0.0
    placement_delay_seconds: float = 0.0
    absolute_pending_expiry: bool = False
    skip_if_entry_crossed_at_placement: bool = False


class SimulatedOpeningTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["CLOSED", "EXPIRED", "INSUFFICIENT_TICK_EVIDENCE", "SKIPPED"]
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


def _expiry_duration(opportunity: OpeningOpportunity, config: ReplayConfig) -> int:
    return (
        config.reaction_expiry_seconds
        if opportunity.entry_kind == "reaction"
        else config.continuation_expiry_seconds
    )


def orderable_at(
    opportunity: OpeningOpportunity,
    config: ReplayConfig,
) -> datetime:
    """Return when the closed-candle signal can first be acted on."""
    return _parse(opportunity.signal_time) + timedelta(
        seconds=float(config.candle_close_delay_seconds)
    )


def expires_at(
    opportunity: OpeningOpportunity,
    config: ReplayConfig,
) -> datetime:
    """Return the original absolute expiry tied to the signal story."""
    return orderable_at(opportunity, config) + timedelta(
        seconds=_expiry_duration(opportunity, config)
    )


def placement_time(
    opportunity: OpeningOpportunity,
    config: ReplayConfig,
    *,
    available_at: datetime,
) -> datetime:
    """Return the simulated broker submission time after slot availability."""
    return max(orderable_at(opportunity, config), available_at) + timedelta(
        seconds=float(config.placement_delay_seconds)
    )


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
    *,
    spread: float | None = None,
) -> tuple[float, float]:
    spread_floor = (
        max(0.0, float(spread or 0.0)) * float(config.minimum_stop_spread_multiple)
    )
    risk = max(
        abs(entry - float(opportunity.level)) + float(opportunity.tolerance),
        float(config.minimum_stop_distance),
        spread_floor,
    )
    if opportunity.direction == "BUY":
        return round(entry - risk, 4), round(entry + risk * config.risk_reward, 4)
    return round(entry + risk, 4), round(entry - risk * config.risk_reward, 4)


def _fills(direction: str, entry: float, tick: MarketTick, max_drift: float) -> bool:
    price = _fill_price(direction, tick)
    if direction == "BUY":
        return entry <= price <= entry + max_drift
    return entry - max_drift <= price <= entry


def _entry_crossed_at_placement(
    direction: str,
    entry: float,
    tick: MarketTick,
) -> bool:
    if direction == "BUY":
        return float(tick.ask) >= entry
    return float(tick.bid) <= entry


def _entry_distance_exceeded(
    entry: float,
    tick: MarketTick,
    max_distance: float,
) -> bool:
    if max_distance <= 0:
        return False
    distance = min(abs(entry - float(tick.bid)), abs(entry - float(tick.ask)))
    return distance > max_distance


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
    status: Literal["CLOSED", "EXPIRED", "INSUFFICIENT_TICK_EVIDENCE", "SKIPPED"],
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
        orderable = orderable_at(opportunity, config)
        placed_time = placement_time(
            opportunity,
            config,
            available_at=orderable,
        )
        entry = _entry_price(opportunity)
        absolute_expiry = bool(config.absolute_pending_expiry)
        expiry_time = expires_at(opportunity, config) if absolute_expiry else None
        if expiry_time is not None and placed_time >= expiry_time:
            stop, target = _levels(opportunity, entry, config)
            return _base_result(
                "EXPIRED",
                opportunity,
                reason="PLACEMENT_DELAY_EXCEEDED_EXPIRY",
                placed_at=placed_time.isoformat(),
                completed_at=expiry_time.isoformat(),
                entry=entry,
                stop=stop,
                target=target,
            )

        decision_seconds = placed_time.timestamp()
        first_index = max(
            0,
            int(start_index),
            int(np.searchsorted(self.epoch_seconds, decision_seconds, side="left")),
        )
        expiry_index = (
            int(
                np.searchsorted(
                    self.epoch_seconds,
                    expiry_time.timestamp(),
                    side="right",
                )
            )
            if expiry_time is not None
            else len(self.ticks)
        )
        if first_index >= len(self.ticks):
            stop, target = _levels(opportunity, entry, config)
            return _base_result(
                "INSUFFICIENT_TICK_EVIDENCE",
                opportunity,
                reason="NO_DECISION_TICK",
                placed_at=placed_time.isoformat(),
                completed_at=placed_time.isoformat(),
                entry=entry,
                stop=stop,
                target=target,
            )
        if first_index >= expiry_index:
            stop, target = _levels(opportunity, entry, config)
            return _base_result(
                "EXPIRED",
                opportunity,
                reason="NO_DECISION_TICK_BEFORE_EXPIRY",
                placed_at=placed_time.isoformat(),
                completed_at=expiry_time.isoformat(),
                entry=entry,
                stop=stop,
                target=target,
            )

        valid_after = np.flatnonzero(self.valid[first_index:expiry_index])
        if valid_after.size == 0:
            no_valid_reason = (
                "NO_VALID_DECISION_TICK_BEFORE_EXPIRY"
                if expiry_time is not None
                else "NO_VALID_DECISION_TICK"
            )
            return _base_result(
                "INSUFFICIENT_TICK_EVIDENCE",
                opportunity,
                reason=no_valid_reason,
                placed_at=placed_time.isoformat(),
                completed_at=(
                    expiry_time.isoformat()
                    if expiry_time is not None
                    else placed_time.isoformat()
                ),
            )
        decision_index = int(valid_after[0] + first_index)
        spread = round(float(self.asks[decision_index] - self.bids[decision_index]), 4)
        stop, target = _levels(opportunity, entry, config, spread=spread)
        decision_tick = self.ticks[decision_index]
        if expiry_time is None:
            expiry_time = _parse(decision_tick.time) + timedelta(
                seconds=_expiry_duration(opportunity, config)
            )
            expiry_index = int(
                np.searchsorted(
                    self.epoch_seconds,
                    expiry_time.timestamp(),
                    side="right",
                )
            )
        if config.skip_if_entry_crossed_at_placement and _entry_crossed_at_placement(
            opportunity.direction,
            entry,
            decision_tick,
        ):
            return _base_result(
                "SKIPPED",
                opportunity,
                reason="ENTRY_ALREADY_CROSSED_AT_PLACEMENT",
                placed_at=placed_time.isoformat(),
                completed_at=decision_tick.time,
                entry=entry,
                stop=stop,
                target=target,
                spread_at_decision=spread,
            )
        if _entry_distance_exceeded(entry, decision_tick, config.max_entry_distance):
            return _base_result(
                "SKIPPED",
                opportunity,
                reason="ENTRY_TOO_FAR_FROM_PLACEMENT_QUOTE",
                placed_at=placed_time.isoformat(),
                completed_at=decision_tick.time,
                entry=entry,
                stop=stop,
                target=target,
                spread_at_decision=spread,
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
                placed_at=placed_time.isoformat(),
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
                    placed_at=placed_time.isoformat(),
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
                placed_at=placed_time.isoformat(),
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
            placed_at=placed_time.isoformat(),
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
        placed_time = placement_time(
            opportunity,
            config,
            available_at=available_at,
        )
        placed_at = placed_time.isoformat()
        entry = _entry_price(opportunity)
        if placed_time >= expires_at:
            stop, target = _levels(opportunity, entry, config)
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
            stop, target = _levels(opportunity, entry, config)
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
        if first_index >= expiry_index:
            stop, target = _levels(opportunity, entry, config)
            return _base_result(
                "EXPIRED",
                opportunity,
                reason="NO_DECISION_TICK_BEFORE_EXPIRY",
                placed_at=placed_at,
                completed_at=expires_at.isoformat(),
                entry=entry,
                stop=stop,
                target=target,
            )

        valid_after = np.flatnonzero(self.valid[first_index:expiry_index])
        if valid_after.size == 0:
            return _base_result(
                "INSUFFICIENT_TICK_EVIDENCE",
                opportunity,
                reason="NO_VALID_DECISION_TICK_BEFORE_EXPIRY",
                placed_at=placed_at,
                completed_at=expires_at.isoformat(),
            )
        decision_index = int(valid_after[0] + first_index)
        spread = round(float(self.asks[decision_index] - self.bids[decision_index]), 4)
        stop, target = _levels(opportunity, entry, config, spread=spread)
        decision_tick = self.ticks[decision_index]
        if config.skip_if_entry_crossed_at_placement and _entry_crossed_at_placement(
            opportunity.direction,
            entry,
            decision_tick,
        ):
            return _base_result(
                "SKIPPED",
                opportunity,
                reason="ENTRY_ALREADY_CROSSED_AT_PLACEMENT",
                placed_at=placed_at,
                completed_at=decision_tick.time,
                entry=entry,
                stop=stop,
                target=target,
                spread_at_decision=spread,
            )
        if _entry_distance_exceeded(entry, decision_tick, config.max_entry_distance):
            return _base_result(
                "SKIPPED",
                opportunity,
                reason="ENTRY_TOO_FAR_FROM_PLACEMENT_QUOTE",
                placed_at=placed_at,
                completed_at=decision_tick.time,
                entry=entry,
                stop=stop,
                target=target,
                spread_at_decision=spread,
            )
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
    return PreparedTickSeries.from_ticks(tuple(sorted_ticks)).simulate(
        opportunity,
        config,
        start_index=start_index,
    )


__all__ = [
    "MarketTick",
    "PreparedTickSeries",
    "ReplayConfig",
    "SimulatedOpeningTrade",
    "expires_at",
    "orderable_at",
    "placement_time",
    "simulate_opportunity",
    "simulate_opportunity_from_sorted_ticks",
]
