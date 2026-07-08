"""Queued fast-target opening-state family candidate screening."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from tradingagents.agents.price_action.evidence_gate import ScreeningRow
from tradingagents.agents.price_action.evidence_metrics import (
    evaluate_historical_gate,
    summarize_variant,
)
from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
    detect_opening_opportunities,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
    _day,
    _group_candles_by_day,
    _group_ticks_by_day,
    _source_hash,
)
from tradingagents.agents.price_action.opening_tick_replay import (
    PreparedTickSeries,
    ReplayConfig,
    expires_at as replay_expires_at,
)


QUEUE_FAST_TARGET_CANDIDATE_NAME = "OPENING_STATE_QUEUE_FAST_TARGET_V1"
QUEUE_POLICY_VERSION = 1
FAST_TARGET_REPLAY_CONFIG = ReplayConfig(risk_reward=1.0)

_TEMPLATE_PRIORITY = {
    OpeningTemplate.BREAK_RETEST_HOLD: 0,
    OpeningTemplate.FAILED_BREAK: 1,
    OpeningTemplate.BREAK_HOLD: 2,
    OpeningTemplate.REJECTION: 3,
}
_SIDE_ORDER = {"high": 0, "low": 1}


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _expires_at(opportunity: OpeningOpportunity, config: ReplayConfig) -> datetime:
    return replay_expires_at(opportunity, config)


def _rank_key(opportunity: OpeningOpportunity) -> tuple[Any, ...]:
    return (
        -int(opportunity.touch_count),
        _TEMPLATE_PRIORITY[opportunity.template],
        -max(opportunity.used_candle_indexes or (0,)),
        float(opportunity.tolerance),
        _SIDE_ORDER[opportunity.level_side],
        round(float(opportunity.level), 4),
        opportunity.direction,
    )


def _time_key(opportunity: OpeningOpportunity) -> tuple[Any, ...]:
    return (_parse(opportunity.signal_time), *_rank_key(opportunity))


def _queue_key(
    opportunity: OpeningOpportunity,
    config: ReplayConfig,
) -> tuple[Any, ...]:
    return (_expires_at(opportunity, config), *_rank_key(opportunity))


def dedupe_signal_zone_opportunities(
    opportunities: tuple[OpeningOpportunity, ...] | list[OpeningOpportunity],
) -> tuple[OpeningOpportunity, ...]:
    """Remove duplicate local-zone opportunities at the same signal timestamp."""
    by_signal: dict[str, list[OpeningOpportunity]] = {}
    for opportunity in opportunities:
        by_signal.setdefault(opportunity.signal_time, []).append(opportunity)

    retained: list[OpeningOpportunity] = []
    for signal_time in sorted(by_signal):
        local: list[OpeningOpportunity] = []
        for opportunity in sorted(by_signal[signal_time], key=_rank_key):
            same_zone = any(
                existing.level_side == opportunity.level_side
                and abs(float(existing.level) - float(opportunity.level))
                <= max(float(existing.tolerance), float(opportunity.tolerance))
                for existing in local
            )
            if not same_zone:
                local.append(opportunity)
        retained.extend(local)
    return tuple(sorted(retained, key=_time_key))


def _fixture(value: str | Path | OpeningResearchFixture) -> OpeningResearchFixture:
    if isinstance(value, OpeningResearchFixture):
        return value
    return OpeningResearchFixture.model_validate_json(
        Path(value).read_text(encoding="utf-8")
    )


def _raw_opportunities(
    fixture: OpeningResearchFixture,
) -> tuple[OpeningOpportunity, ...]:
    opportunities: list[OpeningOpportunity] = []
    for candles in _group_candles_by_day(fixture.candles).values():
        opportunities.extend(detect_opening_opportunities(candles))
    return tuple(sorted(opportunities, key=_time_key))


def _candidate_opportunities(
    fixture: OpeningResearchFixture,
) -> tuple[OpeningOpportunity, ...]:
    return dedupe_signal_zone_opportunities(_raw_opportunities(fixture))


def raw_opportunities(
    fixture: OpeningResearchFixture,
) -> tuple[OpeningOpportunity, ...]:
    """Return all detected opening-state opportunities before queue selection."""
    return _raw_opportunities(fixture)


def candidate_opportunities(
    fixture: OpeningResearchFixture,
) -> tuple[OpeningOpportunity, ...]:
    """Return signal-zone deduplicated opportunities for queue selection."""
    return _candidate_opportunities(fixture)


def _series_by_day(
    fixture: OpeningResearchFixture,
) -> dict[str, PreparedTickSeries]:
    return {
        day: PreparedTickSeries.from_ticks(ticks)
        for day, ticks in _group_ticks_by_day(fixture.ticks).items()
    }


def _baseline_rows_with_config(
    fixture: OpeningResearchFixture,
    config: ReplayConfig,
) -> tuple[ScreeningRow, ...]:
    series_by_day = _series_by_day(fixture)
    rows: list[ScreeningRow] = []
    for index, opportunity in enumerate(_raw_opportunities(fixture)):
        series = series_by_day.get(_day(opportunity.signal_time))
        result = (
            series.simulate(opportunity, config)
            if series is not None
            else PreparedTickSeries.from_ticks(()).simulate(opportunity, config)
        )
        filled = result.status == "CLOSED" and result.profit is not None
        accepted = result.status in {"CLOSED", "EXPIRED"} or result.filled_at is not None
        rows.append(
            ScreeningRow(
                session_id=_day(opportunity.signal_time),
                decision_index=index,
                accepted=accepted,
                filled=filled,
                profit=result.profit if filled else None,
                reasons=(() if filled else (result.reason or result.status,)),
            )
        )
    return tuple(rows)


def baseline_rows_with_config(
    fixture: OpeningResearchFixture,
    config: ReplayConfig,
) -> tuple[ScreeningRow, ...]:
    """Replay the all-template baseline with the supplied replay config."""
    return _baseline_rows_with_config(fixture, config)


def replay_queue_fast_target_fixture(
    fixture: OpeningResearchFixture,
    *,
    opportunities: tuple[OpeningOpportunity, ...] | None = None,
    config: ReplayConfig = FAST_TARGET_REPLAY_CONFIG,
) -> tuple[ScreeningRow, ...]:
    """Replay queued opening opportunities with one active simulated lifecycle."""
    selected = (
        tuple(sorted(opportunities, key=_time_key))
        if opportunities is not None
        else _candidate_opportunities(fixture)
    )
    series_by_day = _series_by_day(fixture)
    rows: list[ScreeningRow] = []
    pending: list[OpeningOpportunity] = []
    cursor = 0
    clock: datetime | None = None
    decision_index = 0

    while cursor < len(selected) or pending:
        if not pending:
            next_signal = _parse(selected[cursor].signal_time)
            clock = next_signal if clock is None else max(clock, next_signal)
        if clock is None:
            break

        while cursor < len(selected) and _parse(selected[cursor].signal_time) <= clock:
            pending.append(selected[cursor])
            cursor += 1

        fresh: list[OpeningOpportunity] = []
        for opportunity in pending:
            if _expires_at(opportunity, config) <= clock:
                rows.append(
                    ScreeningRow(
                        session_id=_day(opportunity.signal_time),
                        decision_index=decision_index,
                        accepted=False,
                        filled=False,
                        profit=None,
                        reasons=("QUEUE_EXPIRED_BEFORE_AVAILABLE",),
                    )
                )
                decision_index += 1
            else:
                fresh.append(opportunity)
        pending = fresh
        if not pending:
            continue

        opportunity = min(pending, key=lambda item: _queue_key(item, config))
        pending.remove(opportunity)
        series = series_by_day.get(_day(opportunity.signal_time))
        result = (
            series.simulate_window(
                opportunity,
                config,
                available_at=clock,
                expires_at=_expires_at(opportunity, config),
            )
            if series is not None
            else PreparedTickSeries.from_ticks(()).simulate_window(
                opportunity,
                config,
                available_at=clock,
                expires_at=_expires_at(opportunity, config),
            )
        )
        filled = result.status == "CLOSED" and result.profit is not None
        accepted = result.status in {"CLOSED", "EXPIRED"} or result.filled_at is not None
        rows.append(
            ScreeningRow(
                session_id=_day(opportunity.signal_time),
                decision_index=decision_index,
                accepted=accepted,
                filled=filled,
                profit=result.profit if filled else None,
                reasons=(() if filled else (result.reason or result.status,)),
            )
        )
        decision_index += 1
        if accepted and result.completed_at is not None:
            clock = _parse(result.completed_at)
        else:
            clock = max(clock, _parse(opportunity.signal_time))

    return tuple(rows)


def screen_queue_fast_target_fixture(
    fixture_or_path: str | Path | OpeningResearchFixture,
) -> dict[str, Any]:
    fixture = _fixture(fixture_or_path)
    baseline_rows = _baseline_rows_with_config(fixture, FAST_TARGET_REPLAY_CONFIG)
    baseline_fills = sum(
        row.accepted and row.filled and row.profit is not None
        for row in baseline_rows
    )
    baseline = summarize_variant(
        "opening_state_queue_fast_target_baseline",
        baseline_rows,
        baseline_fill_count=max(1, baseline_fills),
    )
    rows = replay_queue_fast_target_fixture(fixture)
    metrics = summarize_variant(
        QUEUE_FAST_TARGET_CANDIDATE_NAME,
        rows,
        baseline_fill_count=max(1, baseline_fills),
    )
    gate = evaluate_historical_gate(metrics, baseline)
    source_hash = _source_hash(fixture)
    frozen_manifest = None
    if gate.passed:
        frozen_manifest = {
            "candidate": QUEUE_FAST_TARGET_CANDIDATE_NAME,
            "queue_policy_version": QUEUE_POLICY_VERSION,
            "source_fixture_hash": source_hash,
            "replay_config": FAST_TARGET_REPLAY_CONFIG.model_dump(mode="json"),
            "historical_metrics": metrics.model_dump(mode="json"),
            "broker_mutation_enabled": False,
            "next_stage": "READ_ONLY_PROSPECTIVE_SHADOW",
        }
    return {
        "schema_version": 1,
        "candidate": QUEUE_FAST_TARGET_CANDIDATE_NAME,
        "queue_policy_version": QUEUE_POLICY_VERSION,
        "broker_mutation_enabled": False,
        "source_fixture_hash": source_hash,
        "replay_config": FAST_TARGET_REPLAY_CONFIG.model_dump(mode="json"),
        "baseline": baseline.model_dump(mode="json"),
        "metrics": metrics.model_dump(mode="json"),
        "gate": gate.model_dump(mode="json"),
        "decision": (
            "FREEZE_OPENING_STATE_QUEUE_FAST_TARGET"
            if gate.passed
            else "NO_OPENING_STATE_QUEUE_FAST_TARGET_EDGE"
        ),
        "frozen_manifest": frozen_manifest,
    }


__all__ = [
    "FAST_TARGET_REPLAY_CONFIG",
    "QUEUE_FAST_TARGET_CANDIDATE_NAME",
    "QUEUE_POLICY_VERSION",
    "baseline_rows_with_config",
    "candidate_opportunities",
    "dedupe_signal_zone_opportunities",
    "raw_opportunities",
    "replay_queue_fast_target_fixture",
    "screen_queue_fast_target_fixture",
]
