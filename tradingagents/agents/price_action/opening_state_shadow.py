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
from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
)
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
FROZEN_BUY_CONTINUATION_CANDIDATE = "OPENING_STATE_BUY_CONTINUATION_EXTENDED_V1"
SUPPORTED_FROZEN_CANDIDATES = frozenset(
    {FROZEN_TARGET_GRID_CANDIDATE, FROZEN_BUY_CONTINUATION_CANDIDATE}
)
BUY_CONTINUATION_TEMPLATES = frozenset(
    {OpeningTemplate.BREAK_HOLD, OpeningTemplate.BREAK_RETEST_HOLD}
)
SHADOW_MIN_FILLS = 30
SHADOW_MIN_SESSIONS = 3
SHADOW_MIN_PROFIT_FACTOR = 1.10
SHADOW_MIN_WIN_RATE = 0.60
SHADOW_DEFAULT_CANDLE_COUNT = SHADOW_MIN_SESSIONS * 24 * 60
SHADOW_DEFAULT_CANDLE_CLOSE_DELAY_SECONDS = 60.0
SHADOW_DEFAULT_PLACEMENT_DELAY_SECONDS = 5.0


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_frozen_manifest(path: str | Path) -> dict[str, Any]:
    manifest = json.loads(Path(path).read_text(encoding="utf-8"))
    if manifest.get("candidate") not in SUPPORTED_FROZEN_CANDIDATES:
        raise ValueError("unsupported frozen opening-state candidate")
    if manifest.get("broker_mutation_enabled") is not False:
        raise ValueError("frozen manifest must disable broker mutation")
    return manifest


def _candidate_name(manifest: dict[str, Any]) -> str:
    candidate = str(manifest.get("candidate") or "")
    if candidate not in SUPPORTED_FROZEN_CANDIDATES:
        raise ValueError("unsupported frozen opening-state candidate")
    return candidate


def _manifest_replay_config(
    manifest: dict[str, Any],
    config: ReplayConfig | None = None,
) -> ReplayConfig:
    updates: dict[str, Any] = {"risk_reward": float(manifest["final_target"])}
    for key in ("reaction_expiry_seconds", "continuation_expiry_seconds"):
        if manifest.get(key) is not None:
            updates[key] = int(manifest[key])
    return (config or ReplayConfig()).model_copy(update=updates)


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
        win_rate = candidate.wins / candidate.fills if candidate.fills else 0.0
        if win_rate < SHADOW_MIN_WIN_RATE:
            reasons.append("WIN_RATE_BELOW_0_60")
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


def buy_continuation_opportunities(
    fixture: OpeningResearchFixture,
) -> tuple[OpeningOpportunity, ...]:
    """Return the frozen post-close BUY continuation shadow candidates."""
    return tuple(
        opportunity
        for opportunity in detected_candidate_opportunities(fixture)
        if opportunity.direction == "BUY"
        and opportunity.template in BUY_CONTINUATION_TEMPLATES
    )


def _candidate_opportunities_for_manifest(
    fixture: OpeningResearchFixture,
    manifest: dict[str, Any],
) -> tuple[OpeningOpportunity, ...]:
    candidate = _candidate_name(manifest)
    if candidate == FROZEN_BUY_CONTINUATION_CANDIDATE:
        return buy_continuation_opportunities(fixture)
    return detected_candidate_opportunities(fixture)


def _session_count(rows: tuple[ScreeningRow, ...]) -> int:
    return len(
        {
            row.session_id
            for row in rows
            if row.accepted and row.filled and row.profit is not None
        }
    )


def realistic_replay_config_from_broker(
    config: Any,
    manifest: dict[str, Any],
    *,
    candle_close_delay_seconds: float = SHADOW_DEFAULT_CANDLE_CLOSE_DELAY_SECONDS,
    placement_delay_seconds: float = SHADOW_DEFAULT_PLACEMENT_DELAY_SECONDS,
    skip_if_entry_crossed_at_placement: bool = True,
) -> ReplayConfig:
    """Build the replay policy intended to match the future DEMO executor."""
    return _manifest_replay_config(
        manifest,
        ReplayConfig(
            minimum_stop_distance=float(
                getattr(config, "min_stop_distance_price", 0.30) or 0.30
            ),
            minimum_stop_spread_multiple=float(
                getattr(config, "min_stop_spread_multiple", 0.0) or 0.0
            ),
            max_entry_distance=float(
                getattr(config, "max_entry_distance_points", 0.0) or 0.0
            ),
            candle_close_delay_seconds=float(candle_close_delay_seconds),
            placement_delay_seconds=float(placement_delay_seconds),
            absolute_pending_expiry=True,
            skip_if_entry_crossed_at_placement=skip_if_entry_crossed_at_placement,
        ),
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
    replay_config: ReplayConfig | None = None,
) -> dict[str, Any]:
    candidate_name = _candidate_name(manifest)
    if manifest.get("broker_mutation_enabled") is not False:
        raise ValueError("frozen manifest must disable broker mutation")
    target = float(manifest["final_target"])
    config = _manifest_replay_config(manifest, replay_config)
    raw = _filter_opportunities(
        raw_opportunities
        if raw_opportunities is not None
        else detected_raw_opportunities(fixture),
        prospective_start,
    )
    candidate = _filter_opportunities(
        candidate_opportunities
        if candidate_opportunities is not None
        else _candidate_opportunities_for_manifest(fixture, manifest),
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
        f"{candidate_name}_shadow_baseline",
        baseline_rows,
        baseline_fill_count=max(1, baseline_fills),
    )
    candidate_metrics = summarize_variant(
        candidate_name,
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
        "candidate": candidate_name,
        "broker_mutation_enabled": False,
        "prospective_start": prospective_start,
        "replay_config": config.model_dump(mode="json"),
        "manifest": {
            "candidate": manifest.get("candidate"),
            "final_target": target,
            "target_grid_version": manifest.get("target_grid_version"),
            "queue_policy_version": manifest.get("queue_policy_version"),
            "buy_continuation_policy_version": manifest.get(
                "buy_continuation_policy_version"
            ),
            "template_filter": manifest.get("template_filter"),
            "direction_filter": manifest.get("direction_filter"),
            "entry_policy": manifest.get("entry_policy"),
            "continuation_expiry_seconds": manifest.get(
                "continuation_expiry_seconds"
            ),
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
    candidate_name = _candidate_name(manifest)
    empty = VariantMetrics(
        name=candidate_name,
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
        "candidate": candidate_name,
        "broker_mutation_enabled": False,
        "prospective_start": prospective_start,
        "replay_config": _manifest_replay_config(manifest).model_dump(mode="json"),
        "manifest": {
            "candidate": manifest.get("candidate"),
            "final_target": float(manifest["final_target"]),
            "target_grid_version": manifest.get("target_grid_version"),
            "queue_policy_version": manifest.get("queue_policy_version"),
            "buy_continuation_policy_version": manifest.get(
                "buy_continuation_policy_version"
            ),
            "template_filter": manifest.get("template_filter"),
            "direction_filter": manifest.get("direction_filter"),
            "entry_policy": manifest.get("entry_policy"),
            "continuation_expiry_seconds": manifest.get(
                "continuation_expiry_seconds"
            ),
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
    candle_count: int = SHADOW_DEFAULT_CANDLE_COUNT,
    candle_close_delay_seconds: float = SHADOW_DEFAULT_CANDLE_CLOSE_DELAY_SECONDS,
    placement_delay_seconds: float = SHADOW_DEFAULT_PLACEMENT_DELAY_SECONDS,
    skip_if_entry_crossed_at_placement: bool = True,
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
    replay_config = realistic_replay_config_from_broker(
        config,
        manifest,
        candle_close_delay_seconds=candle_close_delay_seconds,
        placement_delay_seconds=placement_delay_seconds,
        skip_if_entry_crossed_at_placement=skip_if_entry_crossed_at_placement,
    )
    latest_open = max(_parse(str(candle.timestamp)) for candle in candles)
    latest_closed_boundary = latest_open + timedelta(minutes=1)
    tick_end = latest_closed_boundary
    tick_time = ((safety.get("symbol") or {}).get("tick_time_utc"))
    if tick_time:
        try:
            tick_end = max(tick_end, _parse(str(tick_time)))
        except ValueError:
            pass
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
        replay_config=replay_config,
    )


__all__ = [
    "BUY_CONTINUATION_TEMPLATES",
    "FROZEN_BUY_CONTINUATION_CANDIDATE",
    "FROZEN_TARGET_GRID_CANDIDATE",
    "SHADOW_MIN_FILLS",
    "SHADOW_MIN_PROFIT_FACTOR",
    "SHADOW_MIN_SESSIONS",
    "SHADOW_MIN_WIN_RATE",
    "SHADOW_DEFAULT_CANDLE_COUNT",
    "SHADOW_DEFAULT_CANDLE_CLOSE_DELAY_SECONDS",
    "SHADOW_DEFAULT_PLACEMENT_DELAY_SECONDS",
    "build_shadow_report",
    "build_shadow_report_from_broker",
    "buy_continuation_opportunities",
    "evaluate_shadow_gate",
    "load_frozen_manifest",
    "realistic_replay_config_from_broker",
]
