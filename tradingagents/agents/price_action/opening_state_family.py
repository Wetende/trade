"""Deterministic all-template opening-state family candidate screening."""

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
    _baseline_rows,
    _day,
    _group_candles_by_day,
    _group_ticks_by_day,
    _source_hash,
)
from tradingagents.agents.price_action.opening_tick_replay import (
    PreparedTickSeries,
    ReplayConfig,
)


FAMILY_CANDIDATE_NAME = "OPENING_STATE_FAMILY_V1"
RANKING_VERSION = 1

_TEMPLATE_PRIORITY = {
    OpeningTemplate.BREAK_RETEST_HOLD: 0,
    OpeningTemplate.FAILED_BREAK: 1,
    OpeningTemplate.BREAK_HOLD: 2,
    OpeningTemplate.REJECTION: 3,
}
_SIDE_ORDER = {"high": 0, "low": 1}


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
    return (datetime.fromisoformat(opportunity.signal_time), *_rank_key(opportunity))


def _minute_key(opportunity: OpeningOpportunity) -> str:
    current = datetime.fromisoformat(opportunity.signal_time)
    return current.replace(second=0, microsecond=0).isoformat()


def rank_family_opportunities(
    opportunities: tuple[OpeningOpportunity, ...] | list[OpeningOpportunity],
) -> tuple[OpeningOpportunity, ...]:
    """Rank opportunities by the pre-registered family rules."""
    return tuple(sorted(opportunities, key=_rank_key))


def select_family_opportunities(
    opportunities: tuple[OpeningOpportunity, ...] | list[OpeningOpportunity],
) -> tuple[OpeningOpportunity, ...]:
    """Select at most one deterministic family opportunity per UTC minute."""
    by_minute: dict[str, list[OpeningOpportunity]] = {}
    for opportunity in opportunities:
        by_minute.setdefault(_minute_key(opportunity), []).append(opportunity)

    selected: list[OpeningOpportunity] = []
    for minute in sorted(by_minute):
        retained: list[OpeningOpportunity] = []
        for opportunity in rank_family_opportunities(tuple(by_minute[minute])):
            same_local_zone = any(
                existing.level_side == opportunity.level_side
                and abs(float(existing.level) - float(opportunity.level))
                <= max(float(existing.tolerance), float(opportunity.tolerance))
                for existing in retained
            )
            if not same_local_zone:
                retained.append(opportunity)
        if retained:
            selected.append(retained[0])
    return tuple(sorted(selected, key=_time_key))


def _fixture(value: str | Path | OpeningResearchFixture) -> OpeningResearchFixture:
    if isinstance(value, OpeningResearchFixture):
        return value
    return OpeningResearchFixture.model_validate_json(
        Path(value).read_text(encoding="utf-8")
    )


def _detected_family_opportunities(
    fixture: OpeningResearchFixture,
) -> tuple[OpeningOpportunity, ...]:
    opportunities: list[OpeningOpportunity] = []
    for candles in _group_candles_by_day(fixture.candles).values():
        opportunities.extend(detect_opening_opportunities(candles))
    return select_family_opportunities(tuple(opportunities))


def _series_by_day(
    fixture: OpeningResearchFixture,
) -> dict[str, PreparedTickSeries]:
    return {
        day: PreparedTickSeries.from_ticks(ticks)
        for day, ticks in _group_ticks_by_day(fixture.ticks).items()
    }


def replay_family_fixture(
    fixture: OpeningResearchFixture,
    *,
    opportunities: tuple[OpeningOpportunity, ...] | None = None,
) -> tuple[ScreeningRow, ...]:
    """Replay family opportunities with one active simulated order or position."""
    selected = (
        tuple(sorted(opportunities, key=_time_key))
        if opportunities is not None
        else _detected_family_opportunities(fixture)
    )
    series_by_day = _series_by_day(fixture)
    rows: list[ScreeningRow] = []
    active_until: datetime | None = None
    for index, opportunity in enumerate(selected):
        signal_time = datetime.fromisoformat(opportunity.signal_time)
        if active_until is not None and signal_time < active_until:
            rows.append(
                ScreeningRow(
                    session_id=_day(opportunity.signal_time),
                    decision_index=index,
                    accepted=False,
                    filled=False,
                    profit=None,
                    reasons=("ONE_ACTIVE_FAMILY_POSITION",),
                )
            )
            continue

        series = series_by_day.get(_day(opportunity.signal_time))
        result = (
            series.simulate(opportunity, ReplayConfig())
            if series is not None
            else PreparedTickSeries.from_ticks(()).simulate(
                opportunity,
                ReplayConfig(),
            )
        )
        has_active_lifecycle = result.status in {"CLOSED", "EXPIRED"} or (
            result.filled_at is not None
        )
        if has_active_lifecycle and result.completed_at is not None:
            active_until = datetime.fromisoformat(result.completed_at)

        filled = result.status == "CLOSED" and result.profit is not None
        accepted = has_active_lifecycle
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


def screen_family_fixture(
    fixture_or_path: str | Path | OpeningResearchFixture,
) -> dict[str, Any]:
    fixture = _fixture(fixture_or_path)
    baseline_rows = _baseline_rows(fixture)
    baseline_fills = sum(
        row.filled and row.profit is not None for row in baseline_rows
    )
    baseline = summarize_variant(
        "opening_state_family_baseline",
        baseline_rows,
        baseline_fill_count=max(1, baseline_fills),
    )
    rows = replay_family_fixture(fixture)
    metrics = summarize_variant(
        FAMILY_CANDIDATE_NAME,
        rows,
        baseline_fill_count=max(1, baseline_fills),
    )
    gate = evaluate_historical_gate(metrics, baseline)
    source_hash = _source_hash(fixture)
    frozen_manifest = None
    if gate.passed:
        frozen_manifest = {
            "candidate": FAMILY_CANDIDATE_NAME,
            "ranking_version": RANKING_VERSION,
            "source_fixture_hash": source_hash,
            "historical_metrics": metrics.model_dump(mode="json"),
            "broker_mutation_enabled": False,
            "next_stage": "READ_ONLY_PROSPECTIVE_SHADOW",
        }
    return {
        "schema_version": 1,
        "candidate": FAMILY_CANDIDATE_NAME,
        "ranking_version": RANKING_VERSION,
        "broker_mutation_enabled": False,
        "source_fixture_hash": source_hash,
        "baseline": baseline.model_dump(mode="json"),
        "metrics": metrics.model_dump(mode="json"),
        "gate": gate.model_dump(mode="json"),
        "decision": (
            "FREEZE_OPENING_STATE_FAMILY"
            if gate.passed
            else "NO_OPENING_STATE_FAMILY_EDGE"
        ),
        "frozen_manifest": frozen_manifest,
    }


__all__ = [
    "FAMILY_CANDIDATE_NAME",
    "RANKING_VERSION",
    "rank_family_opportunities",
    "replay_family_fixture",
    "screen_family_fixture",
    "select_family_opportunities",
]
