import json

import pytest

from tradingagents.agents.utils.price_action_tools import (
    analyze_playbook,
    build_no_setup_payload,
    calculate_support_resistance,
    detect_break_and_retest,
    detect_breakouts,
    detect_sr_bounce,
    evaluate_time_filters,
    get_playbook_setups,
)


def _c(timestamp, open_, high, low, close, volume=1000):
    return {
        "timestamp": timestamp,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }


@pytest.mark.unit
def test_support_resistance_clusters_repeated_swing_reactions():
    candles = [
        _c("2026-05-18 06:00", 98, 100, 95.5, 97),
        _c("2026-05-18 06:30", 99, 105.0, 98.0, 104),
        _c("2026-05-18 07:00", 100, 101, 95.0, 96),
        _c("2026-05-18 07:30", 100, 104.8, 97.0, 104),
        _c("2026-05-18 08:00", 99, 101, 94.9, 96),
        _c("2026-05-18 08:30", 99, 103, 98.0, 102),
    ]

    zones = calculate_support_resistance(candles, timeframe="30m", tolerance=0.5)

    support = next(zone for zone in zones if zone["type"] == "support")
    resistance = next(zone for zone in zones if zone["type"] == "resistance")
    assert support["touches"] == 2
    assert resistance["touches"] == 2
    assert support["low"] <= 95.0 <= support["high"]
    assert resistance["low"] <= 105.0 <= resistance["high"]


@pytest.mark.unit
def test_sr_bounce_requires_rejection_wick_for_trade_direction():
    support_zone = {
        "type": "support",
        "low": 94.5,
        "high": 95.5,
        "midpoint": 95.0,
        "touches": 2,
        "score": 7,
    }
    buy_candle = _c("2026-05-18 08:15", 95.8, 99.0, 94.4, 98.3)

    setups = detect_sr_bounce([buy_candle], [support_zone])

    assert setups[0]["direction"] == "BUY"
    assert setups[0]["entry_price"] == pytest.approx(95.5)
    assert setups[0]["stop_loss"] < 94.7


@pytest.mark.unit
def test_break_and_retest_accepts_half_wick_depth_and_rejects_close_back_inside_zone():
    broken_resistance = {
        "type": "resistance",
        "low": 100.0,
        "high": 102.0,
        "midpoint": 101.0,
        "touches": 2,
        "score": 9,
    }
    valid_retest = _c("2026-05-18 08:15", 103.0, 103.5, 100.8, 102.8)
    shallow_retest = _c("2026-05-18 08:15", 103.0, 103.5, 101.6, 102.8)
    close_inside = _c("2026-05-18 08:15", 103.0, 103.5, 100.8, 101.7)

    valid = detect_break_and_retest([valid_retest], [broken_resistance], direction="BUY")
    shallow = detect_break_and_retest([shallow_retest], [broken_resistance], direction="BUY")
    invalid = detect_break_and_retest([close_inside], [broken_resistance], direction="BUY")

    assert valid[0]["direction"] == "BUY"
    assert valid[0]["retest_depth"] >= 0.5
    assert shallow == []
    assert invalid == []


@pytest.mark.unit
def test_time_filter_blocks_15_minutes_before_new_york_open():
    checklist = evaluate_time_filters("2026-05-18 07:45", "America/New_York")

    assert checklist["not_15_min_before_open"] == "failed"
    assert checklist["volume_time"] == "failed"


@pytest.mark.unit
def test_analyze_playbook_approves_buy_break_and_retest_when_rules_pass():
    confirmation_candles = [
        _c("2026-05-18 05:30", 98, 100, 95.5, 97),
        _c("2026-05-18 06:00", 99, 105.0, 98.0, 104),
        _c("2026-05-18 06:30", 100, 101, 95.0, 96),
        _c("2026-05-18 07:00", 100, 104.8, 97.0, 104),
        _c("2026-05-18 07:30", 99, 101, 94.9, 96),
        _c("2026-05-18 08:00", 101, 107.2, 100.5, 106.8),
    ]
    trading_candles = [
        _c("2026-05-18 07:45", 105.5, 106.1, 104.7, 105.4),
        _c("2026-05-18 08:00", 105.9, 106.5, 104.8, 106.2),
        _c("2026-05-18 08:15", 106.0, 107.2, 104.9, 106.9),
    ]

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        trading_candles,
        confirmation_candles,
        timeframe="15m",
        confirmation_timeframe="30m",
        market_timezone="America/New_York",
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "Break and Retest"
    assert payload["checklist"]["timeframe_correlation"] == "passed"
    assert payload["checklist"]["clean_range_to_fill"] == "passed"


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
    def fake_fetch(symbol):
        return {"1d": [], "4h": [], "1h": [], "30m": [], "15m": []}

    monkeypatch.setattr(
        "tradingagents.agents.utils.price_action_tools.fetch_price_action_timeframes",
        fake_fetch,
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
def test_get_playbook_setups_reports_top_down_data_status(monkeypatch):
    def fake_fetch(symbol):
        from tradingagents.agents.price_action.candles import parse_ohlcv_text

        candles = parse_ohlcv_text(
            "Datetime,Open,High,Low,Close,Volume\n"
            "2026-05-17 10:15:00,100,101,99,100.5,1000"
        )
        return {"1d": candles, "4h": candles, "1h": candles, "30m": candles, "15m": candles}

    monkeypatch.setattr(
        "tradingagents.agents.utils.price_action_tools.fetch_price_action_timeframes",
        fake_fetch,
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
    assert payload["data_status"]["trading_timeframe"]["available"] is True
    assert payload["data_status"]["confirmation_timeframe"]["available"] is True
    assert payload["data_status"]["timeframes"]["1d"]["available"] is True
    assert payload["data_status"]["timeframes"]["4h"]["rows"] == 1


@pytest.mark.unit
def test_get_playbook_setups_keeps_hold_when_intraday_data_is_empty(monkeypatch):
    def fake_fetch(symbol):
        return {"1d": [], "4h": [], "1h": [], "30m": [], "15m": []}

    monkeypatch.setattr(
        "tradingagents.agents.utils.price_action_tools.fetch_price_action_timeframes",
        fake_fetch,
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


@pytest.mark.unit
def test_get_playbook_setups_payload_contains_engine_sections(monkeypatch):
    def fake_fetch(symbol):
        from tradingagents.agents.price_action.candles import parse_ohlcv_text

        candles = parse_ohlcv_text(
            "Datetime,Open,High,Low,Close,Volume\n"
            "2026-05-18 08:00:00,100,105,99,104,1000\n"
            "2026-05-18 08:15:00,104,108,103,107,1000"
        )
        return {"1d": candles, "4h": candles, "1h": candles, "30m": candles, "15m": candles}

    monkeypatch.setattr(
        "tradingagents.agents.utils.price_action_tools.fetch_price_action_timeframes",
        fake_fetch,
    )

    raw = get_playbook_setups.invoke(
        {
            "symbol": "XAUUSD",
            "as_of": "2026-05-18 08:30",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
        }
    )
    payload = json.loads(raw)

    assert "checklist" in payload
    assert "market_context" in payload
    assert "zones" in payload
    assert "setups" in payload


@pytest.mark.unit
def test_get_playbook_setups_uses_configured_session_windows(monkeypatch):
    def fake_fetch(symbol):
        from tradingagents.agents.price_action.candles import parse_ohlcv_text

        candles = parse_ohlcv_text(
            "Datetime,Open,High,Low,Close,Volume\n"
            "2026-05-18 08:00:00,100,105,99,104,1000\n"
            "2026-05-18 08:15:00,104,108,103,107,1000"
        )
        return {"1d": candles, "4h": candles, "1h": candles, "30m": candles, "15m": candles}

    custom_config = {
        "price_action": {
            "asian_session_start": "19:00",
            "asian_session_end": "19:30",
            "london_session_start": "03:00",
            "london_session_end": "03:30",
            "new_york_session_start": "09:00",
            "new_york_session_end": "09:30",
            "pre_open_block_minutes": 0,
            "four_hour_candle_block_minutes": 0,
            "sunday_asian_block_start": "17:00",
            "monday_early_asian_cutoff": "00:00",
        }
    }

    monkeypatch.setattr(
        "tradingagents.agents.utils.price_action_tools.fetch_price_action_timeframes",
        fake_fetch,
    )
    monkeypatch.setattr(
        "tradingagents.agents.utils.price_action_tools._default_price_action_session_config",
        lambda: custom_config["price_action"],
    )

    raw = get_playbook_setups.invoke(
        {
            "symbol": "XAUUSD",
            "as_of": "2026-05-18 08:30",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
        }
    )
    payload = json.loads(raw)

    assert payload["checklist"]["volume_time"] == "failed"
