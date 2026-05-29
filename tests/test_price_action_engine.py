from tradingagents.agents.price_action.candles import parse_ohlcv_text
from tradingagents.agents.price_action.engine import analyze_playbook


def candles(raw_rows: str):
    return parse_ohlcv_text("Datetime,Open,High,Low,Close,Volume\n" + raw_rows)


def target_candles():
    return candles(
        "2026-05-18 04:00:00,100,108,99,104,1000\n"
        "2026-05-18 05:00:00,104,112,103,106,1000\n"
        "2026-05-18 06:00:00,106,108,104,105,1000\n"
        "2026-05-18 07:00:00,105,112.2,104,108,1000\n"
        "2026-05-18 08:00:00,108,109,106,111,1000"
    )


def test_engine_approves_buy_when_top_down_and_m15_retest_align():
    data = {
        "1d": candles(
            "2026-05-15 00:00:00,90,110,89,106,1000\n"
            "2026-05-16 00:00:00,106,112,101,110,1000\n"
            "2026-05-17 00:00:00,110,115,105,114,1000"
        ),
        "4h": candles(
            "2026-05-18 00:00:00,98,105,95,104,1000\n"
            "2026-05-18 04:00:00,104,108,102,107,1000\n"
            "2026-05-18 08:00:00,107,112,105,111,1000"
        ),
        "1h": target_candles(),
        "30m": candles(
            "2026-05-18 05:30:00,98,100,95.5,97,1000\n"
            "2026-05-18 06:00:00,99,105,98,104,1000\n"
            "2026-05-18 06:30:00,100,101,95,96,1000\n"
            "2026-05-18 07:00:00,100,104.8,97,104,1000\n"
            "2026-05-18 07:30:00,99,101,94.9,96,1000\n"
            "2026-05-18 08:00:00,101,107.2,100.5,106.8,1000"
        ),
        "15m": candles(
            "2026-05-18 07:45:00,105.5,106.1,104.7,105.4,1000\n"
            "2026-05-18 08:00:00,105.9,106.5,104.8,106.2,1000\n"
            "2026-05-18 08:15:00,106,107.2,104.9,106.9,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["checklist"]["timeframe_correlation"] == "passed"
    assert payload["checklist"]["clean_range_to_fill"] == "passed"
    assert payload["risk"]["approved"] is True
    assert payload["risk"]["available_risk_reward"] >= 1.5


def test_engine_rejects_setup_without_real_target_zone():
    data = {
        "1d": candles(
            "2026-05-15 00:00:00,90,110,89,106,1000\n"
            "2026-05-16 00:00:00,106,112,101,110,1000\n"
            "2026-05-17 00:00:00,110,115,105,114,1000"
        ),
        "4h": candles(
            "2026-05-18 00:00:00,98,105,95,104,1000\n"
            "2026-05-18 04:00:00,104,108,102,107,1000\n"
            "2026-05-18 08:00:00,107,112,105,111,1000"
        ),
        "1h": candles(
            "2026-05-18 06:00:00,100,105,99,104,1000\n"
            "2026-05-18 07:00:00,104,108,103,107,1000\n"
            "2026-05-18 08:00:00,107,112,105,111,1000"
        ),
        "30m": candles(
            "2026-05-18 05:30:00,98,100,95.5,97,1000\n"
            "2026-05-18 06:00:00,99,105,98,104,1000\n"
            "2026-05-18 06:30:00,100,101,95,96,1000\n"
            "2026-05-18 07:00:00,100,104.8,97,104,1000\n"
            "2026-05-18 07:30:00,99,101,94.9,96,1000\n"
            "2026-05-18 08:00:00,101,107.2,100.5,106.8,1000"
        ),
        "15m": candles(
            "2026-05-18 07:45:00,105.5,106.1,104.7,105.4,1000\n"
            "2026-05-18 08:00:00,105.9,106.5,104.8,106.2,1000\n"
            "2026-05-18 08:15:00,106,107.2,104.9,106.9,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["checklist"]["clean_range_to_fill"] == "failed"
    assert payload["risk"]["reason"] == "No target zone available"


def test_engine_accepts_m30_rejection_plus_m15_rejection_correlation():
    data = {
        "1d": candles(
            "2026-05-15 00:00:00,90,110,89,106,1000\n"
            "2026-05-16 00:00:00,106,112,101,110,1000\n"
            "2026-05-17 00:00:00,110,115,105,114,1000"
        ),
        "4h": candles(
            "2026-05-18 00:00:00,98,105,95,104,1000\n"
            "2026-05-18 04:00:00,104,108,102,107,1000\n"
            "2026-05-18 08:00:00,107,112,105,111,1000"
        ),
        "1h": target_candles(),
        "30m": candles(
            "2026-05-18 05:30:00,98,100,95.5,97,1000\n"
            "2026-05-18 06:00:00,99,105,98,104,1000\n"
            "2026-05-18 06:30:00,100,101,95.0,96,1000\n"
            "2026-05-18 07:00:00,100,104.8,97,104,1000\n"
            "2026-05-18 07:30:00,99,101,94.9,96,1000\n"
            "2026-05-18 08:00:00,98,101,95.2,100,1000"
        ),
        "15m": candles(
            "2026-05-18 07:45:00,100,104,98,99,1000\n"
            "2026-05-18 08:00:00,99,103,97,98.5,1000\n"
            "2026-05-18 08:15:00,97.2,100,95.4,99,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["market_context"]["m30_context"] == "REJECTION"
    assert payload["checklist"]["timeframe_correlation"] == "passed"


def test_engine_rejects_when_time_filter_fails():
    data = {"1d": [], "4h": [], "1h": [], "30m": [], "15m": []}

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-17 19:30",
        data,
        market_timezone="America/New_York",
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["checklist"]["not_sunday_asian_session"] == "failed"


def test_engine_payload_contains_raw_telemetry_for_time_filter_hold():
    data = {
        "1d": candles(
            "2026-05-27 00:00:00,100,102,99,101,1000\n"
            "2026-05-28 00:00:00,101,103,100,102,1000"
        ),
        "4h": candles(
            "2026-05-28 00:00:00,100,102,99,101,1000\n"
            "2026-05-28 04:00:00,101,103,100,102,1000"
        ),
        "1h": candles(
            "2026-05-28 08:00:00,100,102,99,101,1000\n"
            "2026-05-28 09:00:00,101,103,100,102,1000"
        ),
        "30m": candles(
            "2026-05-28 09:00:00,100,102,99,101,1000\n"
            "2026-05-28 09:30:00,101,103,100,102,1000"
        ),
        "15m": candles(
            "2026-05-28 09:30:00,100,102,99,101,1000\n"
            "2026-05-28 09:45:00,101,103,100,102,1000"
        ),
    }

    payload = analyze_playbook("GC=F", "2026-05-28 07:45", data)

    assert payload["status"] == "NO_SETUP"
    assert payload["telemetry"]["decision_stage"] == "time_filter"
    assert payload["telemetry"]["primary_hold_reason"] == "Time filter failed. Default to HOLD."
    assert payload["telemetry"]["timeframe_rows"]["15m"] == 2
    assert payload["telemetry"]["zone_counts"]["4h"] >= 0


def test_engine_payload_contains_permission_telemetry_when_candidate_is_blocked():
    data = {
        "1d": candles(
            "2026-05-27 00:00:00,100,102,99,101,1000\n"
            "2026-05-28 00:00:00,101,103,100,102,1000"
        ),
        "4h": candles(
            "2026-05-28 00:00:00,110,111,105,106,1000\n"
            "2026-05-28 04:00:00,106,107,100,101,1000\n"
            "2026-05-28 08:00:00,101,102,98,99,1000"
        ),
        "1h": candles(
            "2026-05-28 08:00:00,100,102,99,101,1000\n"
            "2026-05-28 09:00:00,101,103,100,102,1000"
        ),
        "30m": candles(
            "2026-05-28 08:30:00,100,101,99,100,1000\n"
            "2026-05-28 09:00:00,100,103,99,102,1000\n"
            "2026-05-28 09:30:00,102,106,101,105,1000"
        ),
        "15m": candles(
            "2026-05-28 09:15:00,103,104,101,103,1000\n"
            "2026-05-28 09:30:00,103,106,101,105,1000\n"
            "2026-05-28 09:45:00,105,106,103,105.5,1000"
        ),
    }

    payload = analyze_playbook("GC=F", "2026-05-28 08:15", data)

    assert "telemetry" in payload
    assert "timeframe_rows" in payload["telemetry"]
    assert "permissions" in payload["telemetry"]
