import json

import pytest

from tradingagents.agents.utils.price_action_tools import (
    build_no_setup_payload,
    calculate_support_resistance,
    detect_break_and_retest,
    detect_breakouts,
    detect_sr_bounce,
    get_playbook_setups,
)


@pytest.mark.unit
def test_stub_detectors_return_no_setups():
    assert calculate_support_resistance() == []
    assert detect_breakouts() == []
    assert detect_sr_bounce() == []
    assert detect_break_and_retest() == []


@pytest.mark.unit
def test_no_setup_payload_defaults_to_hold():
    payload = build_no_setup_payload("spy", "2026-05-17 10:15")
    assert payload["symbol"] == "SPY"
    assert payload["timeframe"] == "15m"
    assert payload["confirmation_timeframe"] == "30m"
    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["setups"] == []


@pytest.mark.unit
def test_get_playbook_setups_tool_returns_json_hold_payload(monkeypatch):
    def fake_route_to_vendor(method, symbol, period, interval):
        return "No data found for symbol 'SPY'"

    monkeypatch.setattr(
        "tradingagents.agents.utils.price_action_tools.route_to_vendor",
        fake_route_to_vendor,
    )

    raw = get_playbook_setups.invoke(
        {
            "symbol": "SPY",
            "as_of": "2026-05-17 10:15",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
        }
    )
    payload = json.loads(raw)
    assert payload["recommendation"] == "HOLD"
    assert payload["status"] == "NO_SETUP"


@pytest.mark.unit
def test_get_playbook_setups_fetches_trading_and_confirmation_data(monkeypatch):
    calls = []

    def fake_route_to_vendor(method, symbol, period, interval):
        calls.append((method, symbol, period, interval))
        return "\n".join(
            [
                "# OHLCV data for SPY",
                "Datetime,Open,High,Low,Close,Volume",
                "2026-05-17 10:15:00,100,101,99,100.5,1000",
            ]
        )

    monkeypatch.setattr(
        "tradingagents.agents.utils.price_action_tools.route_to_vendor",
        fake_route_to_vendor,
    )

    raw = get_playbook_setups.invoke(
        {
            "symbol": "SPY",
            "as_of": "2026-05-17 10:15",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
        }
    )

    payload = json.loads(raw)
    assert calls == [
        ("get_intraday_price_data", "SPY", "5d", "15m"),
        ("get_intraday_price_data", "SPY", "5d", "30m"),
    ]
    assert payload["recommendation"] == "HOLD"
    assert payload["data_status"]["trading_timeframe"]["available"] is True
    assert payload["data_status"]["confirmation_timeframe"]["available"] is True


@pytest.mark.unit
def test_get_playbook_setups_keeps_hold_when_intraday_data_is_empty(monkeypatch):
    def fake_route_to_vendor(method, symbol, period, interval):
        return f"No data found for symbol '{symbol}'"

    monkeypatch.setattr(
        "tradingagents.agents.utils.price_action_tools.route_to_vendor",
        fake_route_to_vendor,
    )

    raw = get_playbook_setups.invoke(
        {
            "symbol": "SPY",
            "as_of": "2026-05-17 10:15",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
        }
    )

    payload = json.loads(raw)
    assert payload["recommendation"] == "HOLD"
    assert payload["status"] == "NO_SETUP"
    assert payload["data_status"]["trading_timeframe"]["available"] is False
    assert payload["data_status"]["confirmation_timeframe"]["available"] is False
