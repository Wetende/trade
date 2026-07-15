from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
    HIGH_BREAK_BUY,
    HIGH_RESPECT_SELL,
    LOW_BREAK_SELL,
    LOW_RESPECT_BUY,
)
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_evidence import (
    V8EvidenceCounters,
    V8EvidenceRow,
    evaluate_v8_evidence,
)


FAMILIES = (
    HIGH_BREAK_BUY,
    LOW_BREAK_SELL,
    HIGH_RESPECT_SELL,
    LOW_RESPECT_BUY,
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
)


def _rows(start: datetime, sessions: int, trades_per_session: int):
    rows = []
    for session in range(sessions):
        day = start + timedelta(days=session)
        for trade in range(trades_per_session):
            family = FAMILIES[(session * trades_per_session + trade) % len(FAMILIES)]
            direction = "BUY" if family in {
                HIGH_BREAK_BUY,
                LOW_RESPECT_BUY,
                FAILED_LOW_BREAK_BUY,
            } else "SELL"
            # Two moderate wins then one smaller loss makes every three-trade
            # session profitable without hiding a large loss streak.
            profit = 0.5 if trade % 3 != 2 else -0.2
            moment = day + timedelta(hours=12, minutes=trade)
            rows.append(
                V8EvidenceRow(
                    arm_id=f"{session}-{trade}",
                    session_id=day.date().isoformat(),
                    family=family,
                    direction=direction,
                    armed_at=moment.isoformat(),
                    triggered_at=(moment + timedelta(seconds=1)).isoformat(),
                    placed_at=(moment + timedelta(seconds=6)).isoformat(),
                    filled_at=(moment + timedelta(seconds=7)).isoformat(),
                    closed_at=(moment + timedelta(seconds=20)).isoformat(),
                    outcome="WIN" if profit > 0 else "LOSS",
                    reason="TARGET" if profit > 0 else "STOP",
                    profit_r=profit,
                )
            )
    return rows


def test_discovery_passes_only_when_all_frozen_gates_pass():
    # Ten sessions distributed across all three untouched chronological folds.
    starts = (
        datetime(2026, 6, 22, tzinfo=timezone.utc),
        datetime(2026, 6, 29, tzinfo=timezone.utc),
        datetime(2026, 7, 6, tzinfo=timezone.utc),
    )
    rows = _rows(starts[0], 4, 3) + _rows(starts[1], 3, 3) + _rows(starts[2], 3, 3)
    # Session ids overlap only within each separately seeded range as intended.
    counters = V8EvidenceCounters(
        arms_detected=180,
        valid_triggers=30,
        placements=30,
        fills=30,
    )

    report = evaluate_v8_evidence("DISCOVERY", rows, counters)

    assert report.passed is True
    assert report.retired is False
    assert report.reasons == ()
    assert report.metrics["fills"] == 30
    assert report.metrics["profitable_folds"] == 3
    assert report.metrics["positive_mirrored_categories"] == 3


def test_failed_discovery_retires_candidate_without_promotion_hint():
    rows = _rows(datetime(2026, 6, 22, tzinfo=timezone.utc), 2, 3)
    counters = V8EvidenceCounters(
        arms_detected=100,
        valid_triggers=6,
        placements=3,
        fills=3,
        crossed_rejections=2,
        geometry_rejections=1,
    )

    report = evaluate_v8_evidence("DISCOVERY", rows, counters)

    assert report.status == "FAIL"
    assert report.retired is True
    assert "fills_below_30" in report.reasons
    assert "trigger_rate_below_0.15" in report.reasons
    assert "valid_trigger_placement_fill_rate_below_0.85" in report.reasons


def test_held_out_requires_best_session_and_extra_cost_robustness():
    rows = _rows(datetime(2026, 7, 13, tzinfo=timezone.utc), 5, 3)
    counters = V8EvidenceCounters(arms_detected=50, valid_triggers=15, placements=15, fills=15)

    passing = evaluate_v8_evidence("HELD_OUT", rows, counters)
    fragile = [
        *rows[:-3],
        *[
            V8EvidenceRow(
                **{
                    **row.as_dict(),
                    "profit_r": 3.0,
                    "session_id": "2026-07-19",
                }
            )
            for row in rows[-3:]
        ],
    ]

    assert passing.passed is True
    # Removing the deliberately dominant final session leaves the original
    # four sessions profitable, so force a genuinely fragile distribution.
    loss_rows = [
        V8EvidenceRow(**{**row.as_dict(), "profit_r": -0.2})
        for row in rows[:-3]
    ] + fragile[-3:]
    failed = evaluate_v8_evidence("HELD_OUT", loss_rows, counters)
    assert failed.passed is False
    assert "net_without_best_session_r_not_positive" in failed.reasons


@pytest.mark.parametrize("stage", ["PROSPECTIVE", "DEMO_0_01"])
def test_forward_and_demo_gates_require_zero_safety_lifecycle_failures(stage):
    count = 60 if stage == "PROSPECTIVE" else 30
    sessions = 10 if stage == "PROSPECTIVE" else 5
    rows = _rows(datetime(2026, 7, 20, tzinfo=timezone.utc), sessions, count // sessions)
    clean = V8EvidenceCounters(count * 3, count, count, count)

    assert evaluate_v8_evidence(stage, rows, clean).passed is True

    unsafe = V8EvidenceCounters(
        count * 3,
        count,
        count,
        count,
        safety_failures=1,
    )
    report = evaluate_v8_evidence(stage, rows, unsafe)
    assert report.passed is False
    assert "safety_failures_nonzero" in report.reasons


def test_demo_gate_requires_complete_reconciliation_and_compliant_drift():
    rows = _rows(datetime(2026, 7, 20, tzinfo=timezone.utc), 5, 6)
    counters = V8EvidenceCounters(
        arms_detected=90,
        valid_triggers=30,
        placements=30,
        fills=30,
        reconciliation_failures=1,
        entry_drift_failures=1,
    )

    report = evaluate_v8_evidence("DEMO_0_01", rows, counters)

    assert report.passed is False
    assert "broker_reconciliation_incomplete" in report.reasons
    assert "live_entry_drift_noncompliant" in report.reasons
