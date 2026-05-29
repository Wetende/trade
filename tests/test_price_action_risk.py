from tradingagents.agents.price_action.models import Candle, Setup, Zone
from tradingagents.agents.price_action.risk import (
    approve_risk,
    gold_points_to_pips,
    move_to_break_even_allowed,
)


def _setup(direction="BUY"):
    zone = Zone(
        type="support",
        timeframe="1h",
        low=95,
        high=96,
        midpoint=95.5,
        touches=2,
        score=9,
        source="test",
    )
    candle = Candle(
        timestamp="2026-05-18 08:15:00",
        open=100,
        high=101,
        low=98,
        close=100,
        volume=1000,
    )
    return Setup(
        name="Support/Resistance Bounce",
        direction=direction,
        zone=zone,
        entry_price=100,
        stop_loss=98,
        confirmation_candle=candle,
    )


def test_gold_points_to_pips_uses_playbook_conversion():
    assert gold_points_to_pips(5.0) == 50


def test_approve_risk_requires_minimum_clean_range():
    target = {"type": "resistance", "midpoint": 106}

    result = approve_risk(_setup(), target_zone=target, minimum_rr=1.5, preferred_rr=3.0)

    assert result["approved"] is True
    assert result["risk_reward"] == 3.0
    assert result["take_profit"] == 106


def test_approve_risk_rejects_tight_target():
    target = {"type": "resistance", "midpoint": 102}

    result = approve_risk(_setup(), target_zone=target, minimum_rr=1.5, preferred_rr=3.0)

    assert result["approved"] is False
    assert result["reason"] == "Clean range is below minimum risk-to-reward"


def test_break_even_uses_fixed_gold_pips():
    assert (
        move_to_break_even_allowed(
            entry=2350.00,
            current=2355.00,
            direction="BUY",
            threshold_pips=50,
        )
        is True
    )
