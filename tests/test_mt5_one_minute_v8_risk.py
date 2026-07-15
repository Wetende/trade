import pytest

from tradingagents.brokers.mt5_one_minute_v8_risk import (
    V8RiskBudget,
    calculate_reserved_exposure_currency,
    calculate_v8_unit_risk_currency,
    evaluate_v8_risk_budget,
)


class FakeRiskBroker:
    def estimate_stop_loss_account_currency(self, side, volume, entry, stop):
        return abs(float(entry) - float(stop)) * 100.0 * float(volume)


def test_unit_risk_uses_configured_volume_and_maximum_one_unit_stop():
    risk = calculate_v8_unit_risk_currency(
        FakeRiskBroker(),
        volume=1.0,
        bid=4500.0,
        ask=4500.2,
        maximum_stop_distance=1.0,
    )

    assert risk == pytest.approx(100.0)


def test_exact_budget_boundary_is_accepted_and_one_cent_over_is_blocked():
    budget = V8RiskBudget(unit_risk_currency=100.0, max_session_r=2.0)

    exact = evaluate_v8_risk_budget(
        budget,
        realized_net_currency=-50.0,
        reserved_exposure_currency=25.0,
        proposed_stop_risk_currency=120.0,
    )
    over = evaluate_v8_risk_budget(
        budget,
        realized_net_currency=-50.0,
        reserved_exposure_currency=25.0,
        proposed_stop_risk_currency=120.01,
    )

    assert exact.cost_buffer_currency == 5.0
    assert exact.required_currency == 200.0
    assert exact.accepted is True
    assert over.accepted is False
    assert over.reason == "SESSION_RISK_BUDGET_EXCEEDED"


def test_positive_realized_profit_does_not_create_negative_loss_reservation():
    decision = evaluate_v8_risk_budget(
        V8RiskBudget(unit_risk_currency=100.0),
        realized_net_currency=20.0,
        reserved_exposure_currency=0.0,
        proposed_stop_risk_currency=100.0,
    )

    assert decision.realized_loss_currency == 0.0
    assert decision.required_currency == 105.0
    assert decision.accepted is True


def test_reserved_orders_and_positions_are_estimated_in_account_currency():
    reserved, missing = calculate_reserved_exposure_currency(
        FakeRiskBroker(),
        [
            {
                "side": "BUY",
                "price_open": 4500.0,
                "sl": 4499.5,
                "volume": 1.0,
            }
        ],
        [
            {
                "side": "SELL",
                "price_open": 4500.0,
                "sl": 4500.25,
                "volume": 1.0,
            }
        ],
    )

    assert reserved == pytest.approx(75.0)
    assert missing == 0


def test_unpriced_exposure_fails_closed_even_below_budget():
    reserved, missing = calculate_reserved_exposure_currency(
        FakeRiskBroker(),
        [{"side": "BUY", "price_open": 4500.0, "volume": 1.0}],
        [],
    )
    decision = evaluate_v8_risk_budget(
        V8RiskBudget(unit_risk_currency=100.0),
        realized_net_currency=0.0,
        reserved_exposure_currency=reserved,
        proposed_stop_risk_currency=10.0,
        unpriced_exposure_count=missing,
    )

    assert decision.accepted is False
    assert decision.reason == "UNPRICED_EXPOSURE"
