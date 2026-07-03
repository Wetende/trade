"""Leave-one-day-out opening-state template screening."""

from __future__ import annotations

import hashlib
import json
from bisect import bisect_left
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from tradingagents.agents.price_action.evidence_gate import ScreeningRow
from tradingagents.agents.price_action.evidence_metrics import (
    evaluate_historical_gate,
    summarize_variant,
)
from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
    detect_opening_opportunities,
)
from tradingagents.agents.price_action.opening_tick_replay import (
    MarketTick,
    ReplayConfig,
    simulate_opportunity_from_sorted_ticks,
)


class OpeningResearchFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    candles: tuple[Candle, ...]
    ticks: tuple[MarketTick, ...]


def _day(value: str) -> str:
    return datetime.fromisoformat(value).date().isoformat()


def _group_candles_by_day(candles: tuple[Candle, ...]) -> dict[str, tuple[Candle, ...]]:
    grouped: dict[str, list[Candle]] = defaultdict(list)
    for candle in sorted(candles, key=lambda item: datetime.fromisoformat(item.timestamp)):
        grouped[_day(str(candle.timestamp))].append(candle)
    return {key: tuple(value) for key, value in sorted(grouped.items())}


def _group_ticks_by_day(ticks: tuple[MarketTick, ...]) -> dict[str, tuple[MarketTick, ...]]:
    grouped: dict[str, list[MarketTick]] = defaultdict(list)
    for tick in sorted(ticks, key=lambda item: datetime.fromisoformat(item.time)):
        grouped[_day(tick.time)].append(tick)
    return {key: tuple(value) for key, value in sorted(grouped.items())}


def _tick_times_by_day(
    grouped_ticks: dict[str, tuple[MarketTick, ...]],
) -> dict[str, tuple[datetime, ...]]:
    return {
        day: tuple(datetime.fromisoformat(tick.time) for tick in ticks)
        for day, ticks in grouped_ticks.items()
    }


def _day_opportunities(
    fixture: OpeningResearchFixture,
) -> tuple[tuple[str, OpeningOpportunity], ...]:
    opportunities: list[tuple[str, OpeningOpportunity]] = []
    for day, candles in _group_candles_by_day(fixture.candles).items():
        for opportunity in detect_opening_opportunities(candles):
            opportunities.append((day, opportunity))
    return tuple(opportunities)


def _rows_for_template(
    fixture: OpeningResearchFixture,
    template: OpeningTemplate,
) -> tuple[ScreeningRow, ...]:
    ticks_by_day = _group_ticks_by_day(fixture.ticks)
    tick_times_by_day = _tick_times_by_day(ticks_by_day)
    rows: list[ScreeningRow] = []
    decision_index = 0
    for day, opportunity in _day_opportunities(fixture):
        if opportunity.template != template:
            continue
        day_ticks = ticks_by_day.get(day, ())
        tick_times = tick_times_by_day.get(day, ())
        start_index = bisect_left(
            tick_times,
            datetime.fromisoformat(opportunity.signal_time),
        )
        result = simulate_opportunity_from_sorted_ticks(
            opportunity,
            day_ticks,
            ReplayConfig(),
            start_index=start_index,
        )
        rows.append(
            ScreeningRow(
                session_id=day,
                decision_index=decision_index,
                accepted=True,
                filled=result.status == "CLOSED",
                profit=result.profit if result.status == "CLOSED" else None,
                reasons=(
                    ()
                    if result.status == "CLOSED"
                    else (result.reason or result.status,)
                ),
            )
        )
        decision_index += 1
    return tuple(rows)


def _baseline_rows(fixture: OpeningResearchFixture) -> tuple[ScreeningRow, ...]:
    rows: list[ScreeningRow] = []
    for template in OpeningTemplate:
        rows.extend(_rows_for_template(fixture, template))
    return tuple(rows)


def _source_hash(fixture: OpeningResearchFixture) -> str:
    payload = fixture.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _folds(rows: tuple[ScreeningRow, ...]) -> list[dict[str, Any]]:
    days = sorted({row.session_id for row in rows})
    return [
        {
            "held_out_day": day,
            "metrics": summarize_variant(
                f"held_out_{day}",
                tuple(row for row in rows if row.session_id == day),
                baseline_fill_count=max(
                    1,
                    sum(
                        row.filled and row.profit is not None
                        for row in rows
                    ),
                ),
            ).model_dump(mode="json"),
        }
        for day in days
    ]


def screen_opening_fixture(fixture: OpeningResearchFixture) -> dict[str, Any]:
    baseline_rows = _baseline_rows(fixture)
    baseline_fills = sum(
        row.filled and row.profit is not None for row in baseline_rows
    )
    baseline = summarize_variant(
        "opening_state_baseline",
        baseline_rows,
        baseline_fill_count=max(1, baseline_fills),
    )

    templates: dict[str, Any] = {}
    qualifying: list[str] = []
    for template in OpeningTemplate:
        rows = _rows_for_template(fixture, template)
        metrics = summarize_variant(
            template.value,
            rows,
            baseline_fill_count=max(1, baseline_fills),
        )
        gate = evaluate_historical_gate(metrics, baseline)
        templates[template.value] = {
            "metrics": metrics.model_dump(mode="json"),
            "gate": gate.model_dump(mode="json"),
            "folds": _folds(rows),
        }
        if gate.passed:
            qualifying.append(template.value)

    return {
        "schema_version": 1,
        "broker_mutation_enabled": False,
        "source_fixture_hash": _source_hash(fixture),
        "baseline": baseline.model_dump(mode="json"),
        "templates": templates,
        "qualifying_templates": qualifying,
        "decision": (
            "FREEZE_OPENING_TEMPLATE"
            if qualifying
            else "NO_OPENING_STATE_EDGE"
        ),
    }


def screen_opening_fixture_path(path: str | Path) -> dict[str, Any]:
    fixture = OpeningResearchFixture.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
    return screen_opening_fixture(fixture)


__all__ = [
    "OpeningResearchFixture",
    "screen_opening_fixture",
    "screen_opening_fixture_path",
]
