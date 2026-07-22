"""Sanitize recorded runner sessions into deterministic evidence fixtures."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

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


def _export_session(
    session_root: str | Path,
    *,
    closed_by_order_override: Mapping[int, dict[str, Any]] | None = None,
    unmatched_closed_trade_count: int | None = None,
) -> EvidenceSession:
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
    if closed_by_order_override is None:
        closed_by_order: dict[int, dict[str, Any]] = {}
        for trade in summary["trade_history"]["closed_trades"]:
            try:
                order = int(trade["entry_order"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("closed trade is missing an entry-order join") from exc
            if order in closed_by_order:
                raise ValueError("closed trades require unique entry-order joins")
            closed_by_order[order] = trade
    else:
        closed_by_order = dict(closed_by_order_override)

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
    if unmatched_closed_trade_count is not None:
        if unmatched:
            raise ValueError("reconciled session contains a foreign closed trade")
        unmatched_count = unmatched_closed_trade_count
    else:
        unmatched_count = len(unmatched)
    return EvidenceSession(
        session_id=root.name,
        decisions=tuple(decisions),
        trades=tuple(trades),
        unmatched_closed_trade_count=unmatched_count,
    )


def export_session(session_root: str | Path) -> EvidenceSession:
    """Export one session without making cross-session ownership assumptions."""
    return _export_session(session_root)


def _trade_identity(trade: Mapping[str, Any]) -> tuple[Any, ...]:
    """Return broker/economic fields that must agree across repeated snapshots."""
    return tuple(
        trade.get(field)
        for field in (
            "entry_order",
            "entry_deal_ticket",
            "exit_order",
            "exit_deal_ticket",
            "position_id",
            "side",
            "volume",
            "entry_price",
            "exit_price",
            "profit",
        )
    )


def _as_datetime(value: Any, *, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"trade row has invalid {field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"trade row has naive {field}")
    return parsed


def export_sessions_reconciled(
    session_roots: Iterable[str | Path],
) -> list[EvidenceSession]:
    """Export completed sessions with global broker-ticket ownership.

    Runner summaries intentionally use overlapping broker-history lookbacks.  A
    close can therefore be repeated in the next session and broker-local clock
    inference can shift that repeated row by an hour.  Learning evidence must
    assign the trade to the session that placed the broker order, exactly once.
    """
    roots = [Path(root) for root in session_roots]
    placements: dict[int, tuple[Path, datetime]] = {}
    closed_candidates: dict[int, list[dict[str, Any]]] = {}
    filled_orders: set[int] = set()

    for root in roots:
        runner = root / "mt5_runner"
        summary = json.loads((runner / "summary.json").read_text(encoding="utf-8"))
        for cycle in _json_lines(runner / "cycles.jsonl"):
            if cycle.get("status") != "ORDER_PLACED":
                continue
            execution = cycle.get("execution") or {}
            try:
                order = int(execution.get("order") or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError("placed cycle is missing a broker order join") from exc
            if not order:
                raise ValueError("placed cycle is missing a broker order join")
            timeline = execution.get("execution_timeline") or {}
            submitted = timeline.get("submitted_at_utc") or cycle.get("heartbeat_utc")
            submitted_at = _as_datetime(submitted, field="submission time")
            previous = placements.get(order)
            if previous is not None and previous[0] != root:
                raise ValueError("broker order is placed by more than one session")
            if previous is not None:
                raise ValueError("placed cycles require globally unique broker orders")
            placements[order] = (root, submitted_at)

        history = summary.get("trade_history") or {}
        for trade in history.get("filled_trades") or []:
            try:
                filled_orders.add(int(trade["entry_order"]))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("filled trade is missing an entry-order join") from exc
        for trade in history.get("closed_trades") or []:
            try:
                order = int(trade["entry_order"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("closed trade is missing an entry-order join") from exc
            closed_candidates.setdefault(order, []).append(dict(trade))

    foreign_closed = sorted(set(closed_candidates) - set(placements))
    foreign_filled = sorted(filled_orders - set(placements))
    if foreign_closed or foreign_filled:
        raise ValueError(
            "learning sources contain broker trades without an owning placement"
        )

    canonical_closed: dict[int, dict[str, Any]] = {}
    for order, candidates in closed_candidates.items():
        identities = {_trade_identity(candidate) for candidate in candidates}
        if len(identities) != 1:
            raise ValueError("repeated broker trade rows disagree on immutable fields")
        submitted_at = placements[order][1]
        canonical_closed[order] = min(
            candidates,
            key=lambda candidate: abs(
                (
                    _as_datetime(
                        candidate.get("opened_at_utc"),
                        field="opened_at_utc",
                    )
                    - submitted_at
                ).total_seconds()
            ),
        )

    unclosed_fills = sorted(filled_orders - set(canonical_closed))
    if unclosed_fills:
        raise ValueError("completed learning sources contain filled trades without closes")

    closed_by_root: dict[Path, dict[int, dict[str, Any]]] = {
        root: {} for root in roots
    }
    for order, trade in canonical_closed.items():
        owner = placements[order][0]
        closed_by_root[owner][order] = trade

    return [
        _export_session(
            root,
            closed_by_order_override=closed_by_root[root],
            unmatched_closed_trade_count=0,
        )
        for root in roots
    ]
