"""Offline failure learning reports for the deterministic One Minute Scalper."""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable

from tradingagents.agents.price_action.evidence_export import export_session
from tradingagents.agents.price_action.evidence_gate import (
    EvidenceDecision,
    EvidenceSession,
    EvidenceTrade,
)

LOSS_ONLY_TAG = "UNCLASSIFIED_RULE_EXECUTION_FAILURE"


def _load_evidence_dir(evidence_dir: str | Path) -> tuple[EvidenceSession, ...]:
    root = Path(evidence_dir)
    return tuple(
        EvidenceSession.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(root.glob("*.json"))
    )


def _trade_latency_seconds(trade: EvidenceTrade) -> float | None:
    if trade.filled_at is None:
        return None
    return round((trade.filled_at - trade.placed_at).total_seconds(), 4)


def _profit_factor(gross_profit: float, gross_loss: float) -> float | None:
    if gross_loss == 0:
        return None
    return round(gross_profit / abs(gross_loss), 4)


def _empty_stats() -> dict[str, Any]:
    return {
        "fills": 0,
        "wins": 0,
        "losses": 0,
        "net_profit": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "profit_factor": None,
        "expectancy": 0.0,
        "win_rate": 0.0,
        "avg_mfe": None,
        "avg_mae": None,
        "avg_fill_latency_seconds": None,
    }


def _add_trade(stats: dict[str, Any], trade: EvidenceTrade) -> None:
    if not trade.filled or trade.profit is None:
        return
    profit = float(trade.profit)
    stats["fills"] += 1
    stats["net_profit"] = round(float(stats["net_profit"]) + profit, 2)
    if profit > 0:
        stats["wins"] += 1
        stats["gross_profit"] = round(float(stats["gross_profit"]) + profit, 2)
    elif profit < 0:
        stats["losses"] += 1
        stats["gross_loss"] = round(float(stats["gross_loss"]) + profit, 2)
    mfe_values = stats.setdefault("_mfe_values", [])
    mae_values = stats.setdefault("_mae_values", [])
    latency_values = stats.setdefault("_latency_values", [])
    if trade.mfe is not None:
        mfe_values.append(float(trade.mfe))
    if trade.mae is not None:
        mae_values.append(float(trade.mae))
    latency = _trade_latency_seconds(trade)
    if latency is not None:
        latency_values.append(latency)


def _finalize_stats(stats: dict[str, Any]) -> dict[str, Any]:
    fills = int(stats["fills"])
    gross_profit = float(stats["gross_profit"])
    gross_loss = float(stats["gross_loss"])
    mfe_values = stats.pop("_mfe_values", [])
    mae_values = stats.pop("_mae_values", [])
    latency_values = stats.pop("_latency_values", [])
    stats["profit_factor"] = _profit_factor(gross_profit, gross_loss)
    stats["expectancy"] = round(float(stats["net_profit"]) / fills, 4) if fills else 0.0
    stats["win_rate"] = round(float(stats["wins"]) / fills, 4) if fills else 0.0
    stats["avg_mfe"] = (
        round(sum(mfe_values) / len(mfe_values), 4) if mfe_values else None
    )
    stats["avg_mae"] = (
        round(sum(mae_values) / len(mae_values), 4) if mae_values else None
    )
    stats["avg_fill_latency_seconds"] = (
        round(sum(latency_values) / len(latency_values), 4)
        if latency_values
        else None
    )
    return stats


def _summarize_pairs(
    pairs: Iterable[tuple[EvidenceSession, int, EvidenceDecision, EvidenceTrade]],
) -> dict[str, Any]:
    stats = _empty_stats()
    for _session, _index, _decision, trade in pairs:
        _add_trade(stats, trade)
    return _finalize_stats(stats)


def classify_trade_features(
    decision: EvidenceDecision,
    trade: EvidenceTrade,
) -> tuple[str, ...]:
    """Return deterministic feature tags that may explain a trade outcome."""
    tags: list[str] = []
    latency = _trade_latency_seconds(trade)
    if latency is not None:
        if latency > 10:
            tags.append("VERY_LATE_FILL_AFTER_SIGNAL")
        elif latency > 5:
            tags.append("LATE_FILL_AFTER_SIGNAL")
    if decision.score is not None and decision.score < 8:
        tags.append("LOW_APPROVAL_SCORE")
    if (
        decision.stop_to_spread_ratio is not None
        and decision.stop_to_spread_ratio <= 2.2
    ):
        tags.append("TIGHT_STOP_TO_SPREAD")
    if decision.touch_count < 3:
        tags.append("TWO_TOUCH_ONLY")
    if decision.touch_age is not None and decision.touch_age > 3:
        tags.append("STALE_LEVEL_TOUCH")
    if decision.pressure_relation == "opposed":
        tags.append("LONG_PRESSURE_OPPOSED")
    if decision.pulse_relation == "opposed":
        tags.append("ACTIVE_PULSE_OPPOSED")
    if decision.reaction_type == "impulse_break":
        if decision.body_ratio is None:
            tags.append("IMPULSE_BODY_UNMEASURED")
        elif decision.body_ratio < 0.65:
            tags.append("WEAK_IMPULSE_BODY")
        elif decision.body_ratio > 1.20:
            tags.append("EXHAUSTED_IMPULSE_BODY")
    if trade.mfe is not None:
        if trade.mfe <= 0.05:
            tags.append("ZERO_MFE_REVERSAL")
        elif trade.mfe < 0.20:
            tags.append("LOW_FAVORABLE_EXCURSION")
    return tuple(dict.fromkeys(tags))


def classify_failure(
    decision: EvidenceDecision,
    trade: EvidenceTrade,
) -> tuple[str, ...]:
    if trade.profit is None or trade.profit >= 0:
        return ()
    tags = list(classify_trade_features(decision, trade))
    if not tags:
        tags.append(LOSS_ONLY_TAG)
    return tuple(tags)


def _filled_pairs(
    sessions: Iterable[EvidenceSession],
) -> list[tuple[EvidenceSession, int, EvidenceDecision, EvidenceTrade]]:
    pairs: list[tuple[EvidenceSession, int, EvidenceDecision, EvidenceTrade]] = []
    for session in sessions:
        decisions = tuple(session.decisions)
        for trade in session.trades:
            if not trade.filled or trade.profit is None:
                continue
            pairs.append((session, trade.decision_index, decisions[trade.decision_index], trade))
    return sorted(
        pairs,
        key=lambda item: (
            item[0].session_id,
            item[3].placed_at,
            item[1],
        ),
    )


def _stats_by_key(
    pairs: Iterable[tuple[EvidenceSession, int, EvidenceDecision, EvidenceTrade]],
    key_func: Callable[[EvidenceDecision, EvidenceTrade], Iterable[str]],
) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = defaultdict(_empty_stats)
    for _session, _index, decision, trade in pairs:
        for key in key_func(decision, trade):
            _add_trade(grouped[str(key)], trade)
    return {
        key: _finalize_stats(grouped[key])
        for key in sorted(grouped)
    }


def _loss_examples(
    pairs: Iterable[tuple[EvidenceSession, int, EvidenceDecision, EvidenceTrade]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    losses = [
        (session, index, decision, trade)
        for session, index, decision, trade in pairs
        if trade.profit is not None and trade.profit < 0
    ]
    losses.sort(key=lambda item: (float(item[3].profit or 0.0), item[3].placed_at))
    examples: list[dict[str, Any]] = []
    for session, index, decision, trade in losses[:limit]:
        examples.append(
            {
                "session_id": session.session_id,
                "decision_index": index,
                "placed_at": trade.placed_at.isoformat(),
                "trigger": decision.trigger,
                "direction": decision.direction,
                "reaction_type": decision.reaction_type,
                "profit": trade.profit,
                "mfe": trade.mfe,
                "mae": trade.mae,
                "fill_latency_seconds": _trade_latency_seconds(trade),
                "failure_tags": list(classify_failure(decision, trade)),
                "rule_inputs": {
                    "score": decision.score,
                    "touch_count": decision.touch_count,
                    "touch_age": decision.touch_age,
                    "body_ratio": decision.body_ratio,
                    "entry_distance": decision.entry_distance,
                    "opposing_wick_ratio": decision.opposing_wick_ratio,
                    "stop_to_spread_ratio": decision.stop_to_spread_ratio,
                    "pressure_relation": decision.pressure_relation,
                    "pulse_relation": decision.pulse_relation,
                },
            }
        )
    return examples


def _what_if_remove(
    pairs: list[tuple[EvidenceSession, int, EvidenceDecision, EvidenceTrade]],
    predicate: Callable[[EvidenceDecision, EvidenceTrade], bool],
) -> dict[str, Any]:
    kept = [pair for pair in pairs if not predicate(pair[2], pair[3])]
    removed = [pair for pair in pairs if predicate(pair[2], pair[3])]
    current = _summarize_pairs(pairs)
    kept_stats = _summarize_pairs(kept)
    removed_stats = _summarize_pairs(removed)
    return {
        "current": current,
        "kept_if_removed": kept_stats,
        "removed": removed_stats,
        "net_improvement": round(
            float(kept_stats["net_profit"]) - float(current["net_profit"]),
            2,
        ),
    }


def _trigger_hypotheses(
    pairs: list[tuple[EvidenceSession, int, EvidenceDecision, EvidenceTrade]],
    *,
    min_samples: int,
) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    triggers = sorted({decision.trigger for _s, _i, decision, _t in pairs})
    for trigger in triggers:
        what_if = _what_if_remove(
            pairs,
            lambda decision, _trade, selected=trigger: decision.trigger == selected,
        )
        removed = what_if["removed"]
        if (
            removed["fills"] >= min_samples
            and removed["losses"] > removed["wins"]
            and removed["net_profit"] < 0
        ):
            hypotheses.append(
                {
                    "key": f"BLOCK_TRIGGER:{trigger}:*",
                    "type": "blocked_strategy_rule_candidate",
                    "status": "SHADOW_ONLY_NOT_AUTOPROMOTED",
                    "candidate_rule": f"{trigger}:*",
                    "reason": (
                        "This trigger family has negative net outcome in the "
                        "observed evidence and should be blocked only after "
                        "replay or prospective shadow confirms the improvement."
                    ),
                    "what_if": what_if,
                    "promotion_gate": {
                        "passed": False,
                        "reasons": ["REQUIRES_REPLAY_OR_SHADOW_VALIDATION"],
                    },
                }
            )
    return hypotheses


def _feature_hypotheses(
    pairs: list[tuple[EvidenceSession, int, EvidenceDecision, EvidenceTrade]],
    *,
    min_samples: int,
) -> list[dict[str, Any]]:
    features = sorted(
        {
            tag
            for _session, _index, decision, trade in pairs
            for tag in classify_trade_features(decision, trade)
        }
    )
    hypotheses: list[dict[str, Any]] = []
    for feature in features:
        what_if = _what_if_remove(
            pairs,
            lambda decision, trade, selected=feature: selected
            in classify_trade_features(decision, trade),
        )
        removed = what_if["removed"]
        if (
            removed["fills"] >= min_samples
            and removed["losses"] >= 2
            and removed["win_rate"] <= 0.4
            and removed["net_profit"] < 0
        ):
            hypotheses.append(
                {
                    "key": f"FILTER_FEATURE:{feature}",
                    "type": "rule_threshold_candidate",
                    "status": "SHADOW_ONLY_NOT_AUTOPROMOTED",
                    "candidate_filter": feature,
                    "reason": (
                        "This feature appears on a losing cluster. Convert it "
                        "to an entry rule only after replay or prospective "
                        "shadow confirms that retention and profit factor hold."
                    ),
                    "what_if": what_if,
                    "promotion_gate": {
                        "passed": False,
                        "reasons": ["REQUIRES_REPLAY_OR_SHADOW_VALIDATION"],
                    },
                }
            )
    return hypotheses


def build_learning_report(
    sessions: Iterable[EvidenceSession],
    *,
    min_samples: int = 2,
    loss_example_limit: int = 20,
) -> dict[str, Any]:
    selected_sessions = tuple(sessions)
    pairs = _filled_pairs(selected_sessions)
    failure_counts: Counter[str] = Counter()
    for _session, _index, decision, trade in pairs:
        for tag in classify_failure(decision, trade):
            failure_counts[tag] += 1

    hypotheses = [
        *_trigger_hypotheses(pairs, min_samples=min_samples),
        *_feature_hypotheses(pairs, min_samples=min_samples),
    ]
    hypotheses.sort(
        key=lambda item: (
            -float(item["what_if"]["net_improvement"]),
            item["key"],
        )
    )

    return {
        "schema_version": 1,
        "broker_mutation_enabled": False,
        "strategy_scope": "one_minute_scalper",
        "learning_mode": "offline_failure_report_only",
        "source_sessions": [session.session_id for session in selected_sessions],
        "summary": _summarize_pairs(pairs),
        "by_trigger": _stats_by_key(
            pairs,
            lambda decision, _trade: (decision.trigger,),
        ),
        "by_failure_tag": _stats_by_key(
            pairs,
            lambda decision, trade: classify_failure(decision, trade),
        ),
        "by_feature_tag": _stats_by_key(
            pairs,
            lambda decision, trade: classify_trade_features(decision, trade),
        ),
        "failure_taxonomy_counts": dict(sorted(failure_counts.items())),
        "loss_examples": _loss_examples(pairs, limit=loss_example_limit),
        "candidate_rule_hypotheses": hypotheses,
        "guardrails": [
            "report is read-only and broker-free",
            "do not mutate live rules during an active session",
            "promote candidates only through replay or prospective shadow gates",
            "no martingale, recovery sizing, or LLM live decisions",
        ],
    }


def build_session_learning_report(
    session_root: str | Path,
    *,
    min_samples: int = 2,
) -> dict[str, Any]:
    return build_learning_report(
        (export_session(session_root),),
        min_samples=min_samples,
    )


def build_evidence_dir_learning_report(
    evidence_dir: str | Path,
    *,
    min_samples: int = 2,
) -> dict[str, Any]:
    root = Path(evidence_dir)
    files = sorted(root.glob("*.json"))
    report = build_learning_report(
        _load_evidence_dir(root),
        min_samples=min_samples,
    )
    report["source_fixture_hashes"] = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in files
    }
    return report
