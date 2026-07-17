"""Sanitize recorded runner sessions into deterministic evidence fixtures."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tradingagents.agents.price_action.evidence_gate import (
    EvidenceDecision,
    EvidenceSession,
    EvidenceTrade,
)


def _json_lines(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _relationship(direction: str, context: str | None) -> str:
    if context not in {"bullish", "bearish"}:
        return "neutral"
    aligned = (direction == "BUY" and context == "bullish") or (
        direction == "SELL" and context == "bearish"
    )
    return "aligned" if aligned else "opposed"


def export_session(session_root: str | Path) -> EvidenceSession:
    root = Path(session_root)
    runner = root / "mt5_runner"
    cycles = [
        cycle
        for cycle in _json_lines(runner / "cycles.jsonl")
        if cycle.get("status") == "ORDER_PLACED"
    ]
    summary = json.loads(
        (runner / "summary.json").read_text(encoding="utf-8")
    )
    closed_by_order: dict[int, dict[str, Any]] = {}
    for trade in summary["trade_history"]["closed_trades"]:
        try:
            order = int(trade["entry_order"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("closed trade is missing an entry-order join") from exc
        if order in closed_by_order:
            raise ValueError("closed trades require unique entry-order joins")
        closed_by_order[order] = trade

    decisions: list[EvidenceDecision] = []
    trades: list[EvidenceTrade] = []
    seen_orders: set[int] = set()
    for cycle in cycles:
        execution = cycle.get("execution") or {}
        order = int(execution.get("order") or 0)
        if not order or order in seen_orders:
            raise ValueError("placed cycles require unique broker order joins")
        seen_orders.add(order)
        proposal = cycle.get("proposal") or {}
        closed = closed_by_order.get(order)
        selected = (
            (cycle.get("analysis") or {})
            .get("telemetry", {})
            .get("selected_candidate", {})
        )
        quality = selected.get("signal_quality") or {}
        decision_index = len(decisions)
        timeline = execution.get("execution_timeline") or {}
        placed_at = timeline.get("submitted_at_utc") or (
            closed.get("opened_at_utc")
            if closed is not None
            else cycle["heartbeat_utc"]
        )
        direction = selected.get("direction") or proposal.get("side")
        decisions.append(
            EvidenceDecision(
                as_of=placed_at,
                trigger=selected.get("trigger")
                or proposal.get("trigger_name"),
                direction=direction,
                reaction_type=selected.get("reaction_type")
                or proposal.get("reaction_type"),
                approved=bool(selected.get("approved", True)),
                touch_count=int(
                    selected.get("touch_count")
                    or proposal.get("touch_count")
                ),
                body_ratio=quality.get(
                    "body_to_recent_median_range"
                ),
                confirmation_type=selected.get("confirmation_type"),
                score=selected.get("score"),
                level_type=selected.get("level_type"),
                touch_age=quality.get("touch_age_closed_bars"),
                entry_distance=quality.get("entry_distance_from_level"),
                opposing_wick_ratio=quality.get(
                    "opposing_wick_to_range"
                ),
                stop_to_spread_ratio=quality.get("stop_to_spread_ratio"),
                pressure_relation=_relationship(
                    direction,
                    (selected.get("pressure") or {}).get("direction"),
                ),
                pulse_relation=_relationship(
                    direction,
                    (selected.get("active_pulse") or {}).get("direction"),
                ),
                utc_hour=datetime.fromisoformat(placed_at).hour,
            )
        )
        quote = proposal.get("decision_quote") or {}
        if closed is None:
            trades.append(
                EvidenceTrade(
                    decision_index=decision_index,
                    filled=False,
                    placed_at=placed_at,
                    filled_at=None,
                    closed_at=None,
                    profit=None,
                    spread=quote.get("spread_price"),
                    mfe=None,
                    mae=None,
                )
            )
            continue
        filled_at = closed["opened_at_utc"]
        placed_time = datetime.fromisoformat(placed_at)
        filled_time = datetime.fromisoformat(filled_at)
        if filled_time < placed_time:
            if (placed_time - filled_time).total_seconds() > 1.0:
                raise ValueError("fill time materially precedes submission")
            filled_at = placed_at
        trades.append(
            EvidenceTrade(
                decision_index=decision_index,
                filled=True,
                placed_at=placed_at,
                filled_at=filled_at,
                closed_at=closed["closed_at_utc"],
                profit=float(closed["profit"]),
                spread=quote.get("spread_price"),
                mfe=closed.get("mfe_points"),
                mae=closed.get("mae_points"),
            )
        )

    # A runner can see an earlier bot close in the broker history when a
    # terminal reports deal timestamps in broker-local time.  It is not
    # evidence for this session unless this session recorded the placement.
    # Keep the raw summary hash in the source registry and expose the count,
    # but never invent a decision or attach that outcome to a later cycle.
    unmatched = set(closed_by_order) - seen_orders
    return EvidenceSession(
        session_id=root.name,
        decisions=tuple(decisions),
        trades=tuple(trades),
        unmatched_closed_trade_count=len(unmatched),
    )
