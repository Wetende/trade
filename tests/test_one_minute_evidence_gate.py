from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from tradingagents.agents.price_action.evidence_gate import (
    EvidenceDecision,
    EvidenceSession,
    EvidenceTrade,
    VariantName,
    evaluate_session,
    evaluate_variant,
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


def _decision(**updates):
    values = {
        "as_of": UTC_NOW,
        "trigger": "CLEAN_HIGH_IMPULSE_BUY",
        "direction": "BUY",
        "reaction_type": "impulse_break",
        "approved": True,
        "touch_count": 2,
        "body_ratio": 0.75,
    }
    values.update(updates)
    return EvidenceDecision(**values)


def test_touch_maturity_rejects_only_two_touch_impulses():
    impulse = _decision()

    assert evaluate_variant(impulse, VariantName.BASELINE).accepted is True
    result = evaluate_variant(impulse, VariantName.H1_TOUCH_MATURITY)
    assert result.accepted is False
    assert result.reason == "SHADOW_IMPULSE_REQUIRES_THIRD_TOUCH"


@pytest.mark.parametrize(
    ("body_ratio", "accepted"),
    [(1.20, True), (1.2001, False)],
)
def test_exhaustion_has_an_inclusive_upper_boundary(body_ratio, accepted):
    result = evaluate_variant(
        _decision(body_ratio=body_ratio),
        VariantName.H2_EXHAUSTION,
    )

    assert result.accepted is accepted


def test_exhaustion_does_not_change_respect_candidates():
    result = evaluate_variant(
        _decision(
            trigger="LOW_RESPECT_BUY",
            reaction_type="respect",
            body_ratio=2.0,
        ),
        VariantName.H2_EXHAUSTION,
    )

    assert result.accepted is True


def test_variant_never_revives_a_baseline_rejection():
    result = evaluate_variant(
        _decision(approved=False),
        VariantName.H1_TOUCH_MATURITY,
    )

    assert result.accepted is False
    assert result.reason == "BASELINE_REJECTED"


def test_post_loss_cluster_suppresses_until_five_minutes_have_elapsed():
    decisions = tuple(
        _decision(as_of=UTC_NOW + offset)
        for offset in (
            timedelta(seconds=0),
            timedelta(minutes=4, seconds=59),
            timedelta(minutes=5),
        )
    )
    session = EvidenceSession(
        session_id="cluster",
        decisions=decisions,
        trades=[
            _filled_trade(
                profit=-50.0,
                closed_at=UTC_NOW,
            )
        ],
    )

    rows = evaluate_session(session, (VariantName.H3_POST_LOSS_CLUSTER,))

    assert [row.accepted for row in rows] == [True, False, True]
    assert rows[1].reasons == ("SHADOW_POST_LOSS_CLUSTER",)


def test_post_loss_cluster_is_not_started_by_a_win():
    session = EvidenceSession(
        session_id="winning",
        decisions=(
            _decision(as_of=UTC_NOW),
            _decision(as_of=UTC_NOW + timedelta(minutes=1)),
        ),
        trades=[_filled_trade(profit=50.0)],
    )

    rows = evaluate_session(session, (VariantName.H3_POST_LOSS_CLUSTER,))

    assert [row.accepted for row in rows] == [True, True]


def test_pairwise_variants_return_stable_ordered_reasons():
    session = EvidenceSession(
        session_id="pair",
        decisions=(_decision(touch_count=2, body_ratio=1.3),),
        trades=[],
    )

    rows = evaluate_session(
        session,
        (VariantName.H1_TOUCH_MATURITY, VariantName.H2_EXHAUSTION),
    )

    assert rows[0].reasons == (
        "SHADOW_IMPULSE_REQUIRES_THIRD_TOUCH",
        "SHADOW_IMPULSE_BODY_EXHAUSTED",
    )


def test_three_way_variant_is_not_part_of_historical_screening():
    session = EvidenceSession(session_id="three-way", decisions=(), trades=())

    with pytest.raises(ValueError, match="at most two"):
        evaluate_session(
            session,
            (
                VariantName.H1_TOUCH_MATURITY,
                VariantName.H2_EXHAUSTION,
                VariantName.H3_POST_LOSS_CLUSTER,
            ),
        )
