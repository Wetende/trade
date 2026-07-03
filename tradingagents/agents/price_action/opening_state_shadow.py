"""Read-only prospective shadow evaluation for frozen opening-state candidates."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.price_action.evidence_gate import ScreeningRow
from tradingagents.agents.price_action.evidence_metrics import (
    VariantMetrics,
    summarize_variant,
)
from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_state import OpeningOpportunity
from tradingagents.agents.price_action.opening_state_queue_fast_target import (
    baseline_rows_with_config,
    candidate_opportunities as detected_candidate_opportunities,
    raw_opportunities as detected_raw_opportunities,
    replay_queue_fast_target_fixture,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
)
from tradingagents.agents.price_action.opening_tick_replay import (
    MarketTick,
    ReplayConfig,
)
from tradingagents.brokers.mode_gate import account_safety_from_connection
from tradingagents.brokers.mt5 import safe_mt5_connection_status


FROZEN_TARGET_GRID_CANDIDATE = "OPENING_STATE_QUEUE_TARGET_GRID_V1"
SHADOW_MIN_FILLS = 30
SHADOW_MIN_SESSIONS = 3
SHADOW_MIN_PROFIT_FACTOR = 1.10


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_frozen_manifest(path: str | Path) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("candidate") != FROZEN_TARGET_GRID_CANDIDATE:
        raise ValueError("unsupported frozen opening-state candidate")
    if manifest.get("broker_mutation_enabled") is not False:
        raise ValueError("frozen manifest must disable broker mutation")
    return manifest


def _profit_factor_passes(candidate: VariantMetrics) -> bool:
    if candidate.no_gross_loss:
        return candidate.net_profit > 0 and candidate.expectancy > 0
    return (
        candidate.profit_factor is not None
        and candidate.profit_factor >= SHADOW_MIN_PROFIT_FACTOR
    )


def evaluate_shadow_gate(
    *,
    candidate: VariantMetrics,
    baseline: VariantMetrics,
    candidate_session_count: int,
    safety_reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    reasons: list[str] = list(safety_reasons)
    if candidate.fills < SHADOW_MIN_FILLS:
        reasons.append("FEWER_THAN_30_CANDIDATE_FILLS")
    if candidate_session_count < SHADOW_MIN_SESSIONS:
        reasons.append("FEWER_THAN_3_CANDIDATE_SESSIONS")
    evaluable = not any(
        reason
        in {
            "FEWER_THAN_30_CANDIDATE_FILLS",
            "FEWER_THAN_3_CANDIDATE_SESSIONS",
        }
        for reason in reasons
    )
    if evaluable:
        if not _profit_factor_passes(candidate):
            reasons.append("PROFIT_FACTOR_BELOW_1_10")
        if candidate.expectancy <= 0:
            reasons.append("NON_POSITIVE_EXPECTANCY")
        if candidate.net_profit <= 0:
            reasons.append("NON_POSITIVE_NET_PROFIT")
        if candidate.max_loss_streak > baseline.max_loss_streak:
            reasons.append("MAX_LOSS_STREAK_WORSE_THAN_BASELINE")

    unique_reasons = list(dict.fromkeys(reasons))
    if safety_reasons:
        decision = "FAIL_PROSPECTIVE_SHADOW"
    elif not evaluable:
        decision = "COLLECTING_PROSPECTIVE_SHADOW"
    elif unique_reasons:
        decision = "FAIL_PROSPECTIVE_SHADOW"
    else:
        decision = "PASS_PROSPECTIVE_SHADOW"
    return {
        "passed": decision == "PASS_PROSPECTIVE_SHADOW",
        "evaluable": evaluable and not safety_reasons,
        "decision": decision,
        "reasons": unique_reasons,
    }


def _filter_opportunities(
    opportunities: tuple[OpeningOpportunity, ...],
    prospective_start: str,
) -> tuple[OpeningOpportunity, ...]:
    start = _parse(prospective_start)
    return tuple(
        opportunity
        for opportunity in opportunities
        if _parse(opportunity.signal_time) >= start
    )


def _session_count(rows: tuple[ScreeningRow, ...]) -> int:
    return len(
        {
            row.session_id
            for row in rows
            if row.accepted and row.filled and row.profit is not None
        }
    )


def _same_target_baseline_rows(
    fixture: OpeningResearchFixture,
    opportunities: tuple[OpeningOpportunity, ...],
    config: ReplayConfig,
) -> tuple[ScreeningRow, ...]:
    if not opportunities:
        return ()
    filtered_fixture = OpeningResearchFixture(
        schema_version=fixture.schema_version,
        candles=fixture.candles,
        ticks=fixture.ticks,
    )
    all_rows = baseline_rows_with_config(filtered_fixture, config)
    allowed_times = {opportunity.signal_time for opportunity in opportunities}
    allowed_indexes: list[int] = []
    for index, opportunity in enumerate(detected_raw_opportunities(fixture)):
        if opportunity.signal_time in allowed_times:
            allowed_indexes.append(index)
    allowed = set(allowed_indexes)
    return tuple(row for index, row in enumerate(all_rows) if index in allowed)


def build_shadow_report(
    fixture: OpeningResearchFixture,
    *,
    manifest: dict[str, Any],
    prospective_start: str,
    raw_opportunities: tuple[OpeningOpportunity, ...] | None = None,
    candidate_opportunities: tuple[OpeningOpportunity, ...] | None = None,
    safety: dict[str, Any] | None = None,
    safety_reasons: tuple[str, ...] = (),
) -> dict[str, Any]:
    if manifest.get("candidate") != FROZEN_TARGET_GRID_CANDIDATE:
        raise ValueError("unsupported frozen opening-state candidate")
    if manifest.get("broker_mutation_enabled") is not False:
        raise ValueError("frozen manifest must disable broker mutation")
    target = float(manifest["final_target"])
    config = ReplayConfig(risk_reward=target)
    raw = _filter_opportunities(
        raw_opportunities
        if raw_opportunities is not None
        else detected_raw_opportunities(fixture),
        prospective_start,
    )
    candidate = _filter_opportunities(
        candidate_opportunities
        if candidate_opportunities is not None
        else detected_candidate_opportunities(fixture),
        prospective_start,
    )
    baseline_rows = _same_target_baseline_rows(fixture, raw, config)
    candidate_rows = replay_queue_fast_target_fixture(
        fixture,
        opportunities=candidate,
        config=config,
    )
    baseline_fills = sum(
        row.accepted and row.filled and row.profit is not None
        for row in baseline_rows
    )
    baseline_metrics = summarize_variant(
        f"{FROZEN_TARGET_GRID_CANDIDATE}_shadow_baseline",
        baseline_rows,
        baseline_fill_count=max(1, baseline_fills),
    )
    candidate_metrics = summarize_variant(
        FROZEN_TARGET_GRID_CANDIDATE,
        candidate_rows,
        baseline_fill_count=max(1, baseline_fills),
    )
    candidate_session_count = _session_count(candidate_rows)
    gate = evaluate_shadow_gate(
        candidate=candidate_metrics,
        baseline=baseline_metrics,
        candidate_session_count=candidate_session_count,
        safety_reasons=safety_reasons,
    )
    return {
        "schema_version": 1,
        "candidate": FROZEN_TARGET_GRID_CANDIDATE,
        "broker_mutation_enabled": False,
        "prospective_start": prospective_start,
        "replay_config": config.model_dump(mode="json"),
        "manifest": {
            "candidate": manifest.get("candidate"),
            "final_target": target,
            "target_grid_version": manifest.get("target_grid_version"),
            "queue_policy_version": manifest.get("queue_policy_version"),
            "source_fixture_hash": manifest.get("source_fixture_hash"),
        },
        "safety": dict(safety or {}),
        "raw_opportunities_after_start": len(raw),
        "candidate_opportunities_after_start": len(candidate),
        "candidate_session_count": candidate_session_count,
        "baseline": baseline_metrics.model_dump(mode="json"),
        "metrics": candidate_metrics.model_dump(mode="json"),
        "gate": gate,
        "decision": gate["decision"],
    }


def _to_candle(row: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=str(row["timestamp"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0)),
    )


def _to_tick(row: dict[str, Any]) -> MarketTick:
    return MarketTick(
        time=str(row["time"]),
        bid=float(row["bid"]),
        ask=float(row["ask"]),
    )


def _empty_safety_failure(
    *,
    manifest: dict[str, Any],
    prospective_start: str,
    safety: dict[str, Any],
    reasons: tuple[str, ...],
) -> dict[str, Any]:
    empty = VariantMetrics(
        name=FROZEN_TARGET_GRID_CANDIDATE,
        fills=0,
        wins=0,
        losses=0,
        net_profit=0.0,
        gross_profit=0.0,
        gross_loss=0.0,
        profit_factor=None,
        no_gross_loss=True,
        expectancy=0.0,
        fill_retention=0.0,
        max_loss_streak=0,
        max_session_drawdown=0.0,
        profitable_session_count=0,
    )
    gate = evaluate_shadow_gate(
        candidate=empty,
        baseline=empty,
        candidate_session_count=0,
        safety_reasons=reasons,
    )
    return {
        "schema_version": 1,
        "candidate": FROZEN_TARGET_GRID_CANDIDATE,
        "broker_mutation_enabled": False,
        "prospective_start": prospective_start,
        "replay_config": ReplayConfig(
            risk_reward=float(manifest["final_target"])
        ).model_dump(mode="json"),
        "manifest": {
            "candidate": manifest.get("candidate"),
            "final_target": float(manifest["final_target"]),
            "target_grid_version": manifest.get("target_grid_version"),
            "queue_policy_version": manifest.get("queue_policy_version"),
            "source_fixture_hash": manifest.get("source_fixture_hash"),
        },
        "safety": safety,
        "raw_opportunities_after_start": 0,
        "candidate_opportunities_after_start": 0,
        "candidate_session_count": 0,
        "baseline": empty.model_dump(mode="json"),
        "metrics": empty.model_dump(mode="json"),
        "gate": gate,
        "decision": gate["decision"],
    }


def build_shadow_report_from_broker(
    broker: Any,
    *,
    config: Any,
    manifest: dict[str, Any],
    prospective_start: str,
    candle_count: int = 1500,
) -> dict[str, Any]:
    if bool(getattr(config, "allow_real_orders", False)):
        return _empty_safety_failure(
            manifest=manifest,
            prospective_start=prospective_start,
            safety={"broker_mutation_enabled": False},
            reasons=("REAL_ORDER_CONFIGURATION_ENABLED",),
        )

    connection = broker.connect()
    snapshot = broker.current_symbol_snapshot()
    orders = broker.open_orders(config.symbol)
    positions = broker.open_positions(config.symbol)
    account_safety = account_safety_from_connection(
        connection,
        require_demo=bool(getattr(config, "require_demo_account", True)),
    )
    safety = safe_mt5_connection_status(
        connection,
        account_safety=account_safety,
        symbol_snapshot=snapshot,
        open_order_count=len(orders),
        open_position_count=len(positions),
    )
    safety_reasons: list[str] = []
    if not account_safety.get("passed"):
        safety_reasons.append("ACCOUNT_SAFETY_FAILED")
    if orders or positions:
        safety_reasons.append("OPEN_BROKER_STATE_PRESENT")
    if safety_reasons:
        return _empty_safety_failure(
            manifest=manifest,
            prospective_start=prospective_start,
            safety=safety,
            reasons=tuple(safety_reasons),
        )

    candle_rows = broker.fetch_closed_rates("1m", int(candle_count))
    candles = tuple(_to_candle(row) for row in candle_rows)
    if not candles:
        return _empty_safety_failure(
            manifest=manifest,
            prospective_start=prospective_start,
            safety=safety,
            reasons=("NO_CLOSED_M1_CANDLES",),
        )
    latest_open = max(_parse(str(candle.timestamp)) for candle in candles)
    tick_end = latest_open + timedelta(minutes=1)
    tick_rows = broker.fetch_ticks_range(_parse(prospective_start), tick_end)
    fixture = OpeningResearchFixture(
        schema_version=1,
        candles=candles,
        ticks=tuple(_to_tick(row) for row in tick_rows),
    )
    return build_shadow_report(
        fixture,
        manifest=manifest,
        prospective_start=prospective_start,
        safety=safety,
    )


__all__ = [
    "FROZEN_TARGET_GRID_CANDIDATE",
    "SHADOW_MIN_FILLS",
    "SHADOW_MIN_PROFIT_FACTOR",
    "SHADOW_MIN_SESSIONS",
    "build_shadow_report",
    "build_shadow_report_from_broker",
    "evaluate_shadow_gate",
    "load_frozen_manifest",
]
