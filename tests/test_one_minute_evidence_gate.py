from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.agents.price_action.evidence_gate import (
    EvidenceDecision,
    EvidenceSession,
    EvidenceTrade,
)


UTC_NOW = datetime(2026, 7, 2, 20, 0, tzinfo=timezone.utc)


def _filled_trade(**updates):
    values = {
        "decision_index": 0,
        "filled": True,
        "placed_at": UTC_NOW,
        "filled_at": UTC_NOW,
        "closed_at": UTC_NOW,
        "profit": 50.0,
        "spread": 0.33,
        "mfe": 0.80,
        "mae": -0.20,
    }
    values.update(updates)
    return EvidenceTrade(**values)


def test_evidence_session_accepts_market_and_strategy_fields_only():
    session = EvidenceSession(
        session_id="session-a",
        decisions=[
            EvidenceDecision(
                as_of=UTC_NOW,
                trigger="CLEAN_HIGH_IMPULSE_BUY",
                direction="BUY",
                reaction_type="impulse_break",
                approved=True,
                touch_count=3,
                body_ratio=0.75,
            )
        ],
        trades=[_filled_trade()],
    )

    assert session.trades[0].decision_index == 0


def test_evidence_schema_rejects_broker_identifiers():
    with pytest.raises(ValidationError):
        _filled_trade(ticket=123)


def test_evidence_trade_rejects_out_of_order_timestamps():
    with pytest.raises(ValidationError):
        _filled_trade(
            filled_at=datetime(2026, 7, 2, 19, 59, tzinfo=timezone.utc)
        )


def test_unfilled_evidence_trade_rejects_outcome_values():
    with pytest.raises(ValidationError):
        EvidenceTrade(
            decision_index=0,
            filled=False,
            placed_at=UTC_NOW,
            filled_at=None,
            closed_at=None,
            profit=50.0,
            spread=0.33,
            mfe=None,
            mae=None,
        )
