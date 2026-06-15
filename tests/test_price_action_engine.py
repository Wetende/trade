from tradingagents.agents.price_action.candles import parse_ohlcv_text
from tradingagents.agents.price_action import normal_entry_model as engine
from tradingagents.agents.price_action.engine import analyze_playbook
from tradingagents.agents.price_action.models import Candle, Setup, Zone


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


def aligned_buy_setup_data():
    return {
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


def test_engine_approves_buy_when_top_down_and_m15_retest_align():
    data = aligned_buy_setup_data()

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


def test_engine_approves_m30_m15_setup_when_higher_timeframe_is_only_context():
    data = aligned_buy_setup_data()
    data["1d"] = candles(
        "2026-05-15 00:00:00,120,122,116,118,1000\n"
        "2026-05-16 00:00:00,118,119,112,114,1000\n"
        "2026-05-17 00:00:00,114,115,108,110,1000"
    )

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["checklist"]["timeframe_correlation"] == "passed"
    assert payload["telemetry"]["decision_stage"] == "setup_found"
    assert payload["market_context"]["daily_structure"]["permission"] == "SELL_ALLOWED"
    assert payload["telemetry"]["permissions"]["higher_timeframe"]["permission"] == "CONTEXT_ONLY"


def test_engine_treats_m15_breakout_as_core_entry_model(monkeypatch):
    breakout_zone = Zone(
        type="resistance",
        timeframe="30m",
        low=100.0,
        high=101.0,
        midpoint=100.5,
        touches=3,
        score=30.0,
        source="test",
    )
    target_zone = Zone(
        type="resistance",
        timeframe="30m",
        low=105.5,
        high=106.5,
        midpoint=106.0,
        touches=2,
        score=24.0,
        source="test",
    )

    def fake_zones(_candles, timeframe):
        return [breakout_zone, target_zone] if timeframe == "30m" else []

    monkeypatch.setattr(engine, "calculate_support_resistance", fake_zones)
    data = {
        "1d": candles("2026-05-18 00:00:00,99,103,98,102,1000"),
        "4h": candles("2026-05-18 04:00:00,99,103,98,102,1000"),
        "1h": candles("2026-05-18 08:00:00,99,103,98,102,1000"),
        "30m": candles("2026-05-18 08:00:00,100.8,102.6,100.6,102.0,1000"),
        "15m": candles("2026-05-18 08:15:00,101.2,102.8,100.8,102.2,1000"),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
        session_config={"time_filter_mode": "allow"},
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "Breakout"
    assert any(
        item["setup"]["name"] == "Breakout" and item["approved"]
        for item in payload["telemetry"]["candidate_evaluations"]
    )


def test_engine_evaluates_next_candidate_when_first_candidate_fails(monkeypatch):
    data = aligned_buy_setup_data()
    zone = Zone(
        type="resistance",
        timeframe="30m",
        low=105.0,
        high=106.0,
        midpoint=105.5,
        touches=3,
        score=30.0,
        source="test",
    )
    candle = Candle(
        timestamp="2026-05-18 08:15:00",
        open=106.0,
        high=108.5,
        low=105.5,
        close=108.0,
        volume=1000,
    )
    m30_context = Setup(
        name="Breakout",
        direction="BUY",
        zone=zone,
        entry_price=106.0,
        stop_loss=105.0,
        confirmation_candle=data["30m"][-1],
    )
    failing_setup = Setup(
        name="Break and Retest",
        direction="BUY",
        zone=zone,
        entry_price=106.0,
        stop_loss=105.0,
        confirmation_candle=candle,
    )
    passing_setup = Setup(
        name="Breakout",
        direction="BUY",
        zone=zone,
        entry_price=107.0,
        stop_loss=106.0,
        confirmation_candle=candle,
    )

    def fake_breakouts(raw_candles, _zones):
        latest = list(raw_candles)[-1]
        return [m30_context] if latest.timestamp.endswith("08:00:00") else []

    def fake_target(_zones, _direction, entry_price):
        midpoint = 106.4 if float(entry_price) == 106.0 else 110.5
        return {"type": "resistance", "timeframe": "30m", "midpoint": midpoint}

    monkeypatch.setattr(engine, "detect_breakouts", fake_breakouts)
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [failing_setup, passing_setup])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "nearest_target_zone", fake_target)

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["entry_price"] == 107.0
    assert payload["telemetry"]["candidate_setup_count"] == 2
    assert payload["telemetry"]["candidate_evaluations"][0]["approved"] is False
    assert payload["telemetry"]["candidate_evaluations"][1]["approved"] is True


def test_engine_allows_b_plus_candidate_when_minimum_setup_grade_is_b_plus(monkeypatch):
    data = aligned_buy_setup_data()
    zone = Zone(
        type="resistance",
        timeframe="30m",
        low=105.0,
        high=106.0,
        midpoint=105.5,
        touches=3,
        score=30.0,
        source="test",
    )
    candle = Candle(
        timestamp="2026-05-18 08:15:00",
        open=106.0,
        high=108.0,
        low=105.5,
        close=107.0,
        volume=1000,
    )
    m30_context = Setup(
        name="Breakout",
        direction="BUY",
        zone=zone,
        entry_price=106.0,
        stop_loss=105.0,
        confirmation_candle=data["30m"][-1],
    )
    candidate = Setup(
        name="Break and Retest",
        direction="BUY",
        zone=zone,
        entry_price=106.0,
        stop_loss=105.0,
        confirmation_candle=candle,
    )

    def fake_breakouts(raw_candles, _zones):
        latest = list(raw_candles)[-1]
        return [m30_context] if latest.timestamp.endswith("08:00:00") else []

    def fake_approve_risk(setup, target_zone, minimum_rr=1.5, preferred_rr=3.0):
        available_rr = 1.3
        if available_rr < minimum_rr:
            return {
                "approved": False,
                "reason": "Clean range is below minimum risk-to-reward",
                "risk_reward": available_rr,
            }
        return {
            "approved": True,
            "entry_price": setup.entry_price,
            "stop_loss": setup.stop_loss,
            "take_profit": 107.3,
            "risk_distance": 1.0,
            "reward_distance": 1.3,
            "risk_reward": available_rr,
            "available_risk_reward": available_rr,
        }

    monkeypatch.setattr(engine, "detect_breakouts", fake_breakouts)
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [candidate])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 107.3})
    monkeypatch.setattr(engine, "approve_risk", fake_approve_risk)

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
        session_config={"minimum_setup_grade": "B_PLUS", "b_plus_min_rr": 1.2},
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["setup_grade"] == "B_PLUS"
    assert payload["telemetry"]["candidate_evaluations"][0]["setup_grade"] == "B_PLUS"
    assert payload["telemetry"]["decision_stage"] == "setup_found"


def test_engine_holds_b_plus_candidate_when_minimum_setup_grade_is_a_plus(monkeypatch):
    data = aligned_buy_setup_data()
    zone = Zone(
        type="resistance",
        timeframe="30m",
        low=105.0,
        high=106.0,
        midpoint=105.5,
        touches=3,
        score=30.0,
        source="test",
    )
    candle = Candle(
        timestamp="2026-05-18 08:15:00",
        open=106.0,
        high=108.0,
        low=105.5,
        close=107.0,
        volume=1000,
    )
    m30_context = Setup(
        name="Breakout",
        direction="BUY",
        zone=zone,
        entry_price=106.0,
        stop_loss=105.0,
        confirmation_candle=data["30m"][-1],
    )
    candidate = Setup(
        name="Break and Retest",
        direction="BUY",
        zone=zone,
        entry_price=106.0,
        stop_loss=105.0,
        confirmation_candle=candle,
    )

    def fake_breakouts(raw_candles, _zones):
        latest = list(raw_candles)[-1]
        return [m30_context] if latest.timestamp.endswith("08:00:00") else []

    def fake_approve_risk(setup, target_zone, minimum_rr=1.5, preferred_rr=3.0):
        available_rr = 1.3
        if available_rr < minimum_rr:
            return {
                "approved": False,
                "reason": "Clean range is below minimum risk-to-reward",
                "risk_reward": available_rr,
            }
        return {
            "approved": True,
            "entry_price": setup.entry_price,
            "stop_loss": setup.stop_loss,
            "take_profit": 107.3,
            "risk_distance": 1.0,
            "reward_distance": 1.3,
            "risk_reward": available_rr,
            "available_risk_reward": available_rr,
        }

    monkeypatch.setattr(engine, "detect_breakouts", fake_breakouts)
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [candidate])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 107.3})
    monkeypatch.setattr(engine, "approve_risk", fake_approve_risk)

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
        session_config={"minimum_setup_grade": "A_PLUS", "b_plus_min_rr": 1.2},
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["setups"][0]["setup_grade"] == "B_PLUS"
    assert payload["telemetry"]["candidate_evaluations"][0]["setup_grade"] == "B_PLUS"
    assert payload["telemetry"]["decision_stage"] == "setup_grade_filter"


def test_engine_routes_fast_profile_to_one_minute_entry_model():
    data = {
        "3m": candles(
            "2026-06-10 09:39:00,1996.0,1998.0,1995.5,1997.0,1000\n"
            "2026-06-10 09:42:00,1997.0,1999.0,1996.5,1998.5,1000\n"
            "2026-06-10 09:45:00,1998.5,2000.8,1998.0,2000.0,1000\n"
            "2026-06-10 09:48:00,2000.0,2001.2,1999.4,2000.8,1000\n"
            "2026-06-10 09:51:00,2000.8,2002.0,2000.0,2001.4,1000"
        ),
        "1m": candles(
            "2026-06-10 09:50:00,2000.0,2000.8,1998.6,1999.4,1000\n"
            "2026-06-10 09:51:00,1999.4,2001.0,1998.0,2000.7,1000\n"
            "2026-06-10 09:52:00,2000.7,2001.4,1999.7,2001.0,1000\n"
            "2026-06-10 09:53:00,2001.0,2001.2,1999.2,1999.8,1000\n"
            "2026-06-10 09:54:00,1999.8,2000.7,1998.1,2000.4,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("3m",),
            "governing_timeframes": ("3m",),
            "context_timeframes": ("3m",),
            "activation_window_minutes": 6,
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["entry_profile"] == "fast"
    assert payload["timeframe"] == "1m"
    assert payload["confirmation_timeframe"] == "1m"
    assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"
    assert payload["activation_window_minutes"] == 6
    assert payload["telemetry"]["timeframe_rows"]["1m"] == 5
    assert payload["telemetry"]["zone_counts"]["1m"] == 1
    assert "3m" not in payload["telemetry"]["zone_counts"]


def test_one_minute_low_respect_buy_from_equal_lows():
    data = {
        "3m": candles(
            "2026-06-10 09:39:00,1996.0,1998.0,1995.5,1997.0,1000\n"
            "2026-06-10 09:42:00,1997.0,1999.0,1996.5,1998.5,1000\n"
            "2026-06-10 09:45:00,1998.5,2000.8,1998.0,2000.0,1000\n"
            "2026-06-10 09:48:00,2000.0,2001.2,1999.4,2000.8,1000\n"
            "2026-06-10 09:51:00,2000.8,2002.0,2000.0,2001.4,1000"
        ),
        "1m": candles(
            "2026-06-10 09:50:00,2000.0,2000.8,1998.6,1999.4,1000\n"
            "2026-06-10 09:51:00,1999.4,2001.0,1998.0,2000.7,1000\n"
            "2026-06-10 09:52:00,2000.7,2001.4,1999.7,2001.0,1000\n"
            "2026-06-10 09:53:00,2001.0,2001.2,1999.2,1999.8,1000\n"
            "2026-06-10 09:54:00,1999.8,2000.7,1998.1,2000.4,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("3m",),
            "context_timeframes": ("3m",),
            "governing_timeframes": ("3m",),
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"
    assert payload["setups"][0]["setup_grade"] == "A_PLUS"
    assert payload["risk"]["approved"] is True
    assert payload["risk"]["risk_reward"] >= 1.1
    assert payload["risk"]["volume_multiplier"] == 1.5
    assert payload["risk"]["position_lifecycle"] == "FAST_PARTIAL_SCALE"
    assert payload["checklist"]["confirmation_context_clear"] == "passed"
    assert payload["market_context"]["fast_microstructure"]["window_timeframe"] == "1m"


def test_one_minute_low_break_sell_after_recent_support_fails():
    data = {
        "3m": candles(
            "2026-06-10 10:00:00,2003.0,2005.4,2001.6,2002.2,1000\n"
            "2026-06-10 10:03:00,2002.2,2005.0,2001.4,2002.0,1000\n"
            "2026-06-10 10:06:00,2002.0,2003.0,1999.0,1999.6,1000"
        ),
        "1m": candles(
            "2026-06-10 10:02:00,2002.0,2005.0,2001.0,2002.1,1000\n"
            "2026-06-10 10:03:00,2002.1,2003.0,2000.7,2001.0,1000\n"
            "2026-06-10 10:04:00,2001.0,2004.9,2000.9,2001.7,1000\n"
            "2026-06-10 10:05:00,2001.7,2002.2,2000.8,2001.0,1000\n"
            "2026-06-10 10:06:00,2001.0,2001.2,1999.4,1999.7,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 10:07",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("3m",),
            "context_timeframes": ("3m",),
            "governing_timeframes": ("3m",),
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "LOW_BREAK_SELL"
    assert payload["risk"]["approved"] is True
    assert payload["risk"]["risk_reward"] >= 1.4
    assert payload["checklist"]["confirmation_context_clear"] == "passed"


def test_one_minute_low_break_sell_when_two_lows_fail():
    data = {
        "3m": candles(
            "2026-06-10 10:15:00,2000.0,2002.0,1998.0,2000.4,1000\n"
            "2026-06-10 10:18:00,2000.4,2001.2,1998.1,1999.6,1000\n"
            "2026-06-10 10:21:00,1999.6,2000.1,1997.1,1997.5,1000"
        ),
        "1m": candles(
            "2026-06-10 10:17:00,2000.0,2000.8,1998.0,1999.5,1000\n"
            "2026-06-10 10:18:00,1999.5,2001.0,1998.0,2000.4,1000\n"
            "2026-06-10 10:19:00,2000.4,2001.1,1999.0,1999.4,1000\n"
            "2026-06-10 10:20:00,1999.4,2000.2,1998.1,1998.5,1000\n"
            "2026-06-10 10:21:00,1998.5,1999.0,1997.2,1997.5,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 10:22",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("3m",),
            "context_timeframes": ("3m",),
            "governing_timeframes": ("3m",),
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "LOW_BREAK_SELL"
    assert payload["setups"][0]["zone"]["type"] == "support"
    assert payload["risk"]["approved"] is True


def test_one_minute_high_rejection_switches_to_sell_trigger():
    data = {
        "3m": candles(
            "2026-06-10 10:00:00,100.0,102.0,99.0,100.8,1000\n"
            "2026-06-10 10:03:00,100.8,102.4,99.4,101.0,1000\n"
            "2026-06-10 10:06:00,101.0,103.2,100.0,101.2,1000"
        ),
        "1m": candles(
            "2026-06-10 10:02:00,100.1,101.00,99.0,100.2,1000\n"
            "2026-06-10 10:03:00,100.2,101.05,99.4,100.0,1000\n"
            "2026-06-10 10:04:00,100.0,101.0,99.3,100.4,1000\n"
            "2026-06-10 10:05:00,100.4,102.8,100.2,102.4,1000\n"
            "2026-06-10 10:06:00,102.4,103.0,101.1,101.2,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 10:07",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("3m",),
            "context_timeframes": ("3m",),
            "governing_timeframes": ("3m",),
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "HIGH_RESPECT_SELL"
    assert payload["market_context"]["one_minute_story"]["classification"] == "HIGH_RESPECT_SELL"


def test_one_minute_low_break_sell_uses_latest_breaking_candle():
    data = {
        "3m": candles(
            "2026-06-10 11:00:00,100.0,101.5,98.8,99.9,1000\n"
            "2026-06-10 11:03:00,99.9,101.0,98.6,99.7,1000\n"
            "2026-06-10 11:06:00,99.7,100.5,97.2,99.0,1000"
        ),
        "1m": candles(
            "2026-06-10 11:02:00,100.2,101.0,99.00,99.6,1000\n"
            "2026-06-10 11:03:00,99.6,100.4,98.95,100.0,1000\n"
            "2026-06-10 11:04:00,100.0,100.7,99.2,99.5,1000\n"
            "2026-06-10 11:05:00,99.5,100.0,98.4,98.6,1000\n"
            "2026-06-10 11:06:00,98.2,99.3,96.8,98.8,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 11:07",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("3m",),
            "context_timeframes": ("3m",),
            "governing_timeframes": ("3m",),
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "LOW_BREAK_SELL"
    assert payload["market_context"]["one_minute_story"]["classification"] == "LOW_BREAK_SELL"


def test_one_minute_profile_ignores_opposing_extra_history(monkeypatch):
    data = {
        "3m": candles(
            "2026-06-10 09:45:00,2000.0,2002.0,1998.6,2000.4,1000\n"
            "2026-06-10 09:48:00,2000.4,2001.2,1998.4,1999.7,1000\n"
            "2026-06-10 09:51:00,1999.7,2001.4,1998.0,2000.2,1000"
        ),
        "1m": candles(
            "2026-06-10 09:50:00,2000.0,2000.8,1998.6,1999.4,1000\n"
            "2026-06-10 09:51:00,1999.4,2001.0,1998.0,2000.7,1000\n"
            "2026-06-10 09:52:00,2000.7,2001.4,1999.7,2001.0,1000\n"
            "2026-06-10 09:53:00,2001.0,2001.2,1999.2,1999.8,1000\n"
            "2026-06-10 09:54:00,1999.8,2000.7,1998.1,2000.4,1000"
        ),
    }

    def fake_market_state(raw_candles, zones, timeframe):
        direction = "SELL" if timeframe == "3m" else "BUY"
        return {
            "timeframe": timeframe,
            "trend_state": "TRENDING",
            "direction": direction,
            "structure": {
                "classification": "BEARISH_STRUCTURE"
                if direction == "SELL"
                else "BULLISH_STRUCTURE",
                "permission": "SELL_ALLOWED"
                if direction == "SELL"
                else "BUY_ALLOWED",
            },
            "volatility_state": "NORMAL",
            "latest_close": raw_candles[-1].close if raw_candles else None,
            "rows": 6,
        }

    monkeypatch.setattr(engine, "classify_market_state", fake_market_state)

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("3m",),
            "context_timeframes": ("3m",),
            "governing_timeframes": ("3m",),
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["confirmation_timeframe"] == "1m"
    assert payload["checklist"]["timeframe_correlation"] == "passed"
    assert payload["market_context"]["fast_microstructure"]["window_timeframe"] == "1m"
    assert payload["market_context"]["fast_microstructure"]["history_window_candles"] == 60
    assert payload["market_context"]["one_minute_story"]["classification"] == "LOW_RESPECT_BUY"
    assert payload["telemetry"]["market_state"] == {}


def test_one_minute_profile_uses_one_minute_history_window_without_extra_data():
    data = {
        "1m": candles(
            "2026-06-10 09:50:00,2000.0,2000.8,1998.6,1999.4,1000\n"
            "2026-06-10 09:51:00,1999.4,2001.0,1998.0,2000.7,1000\n"
            "2026-06-10 09:52:00,2000.7,2001.4,1999.7,2001.0,1000\n"
            "2026-06-10 09:53:00,2001.0,2001.2,1999.2,1999.8,1000\n"
            "2026-06-10 09:54:00,1999.8,2000.7,1998.1,2000.4,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "zone_timeframes": ("1m",),
            "context_timeframes": ("1m",),
            "governing_timeframes": ("1m",),
            "fast_history_window_candles": 60,
            "fast_min_trigger_candles": 3,
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    fast_meta = payload["market_context"]["fast_microstructure"]
    assert fast_meta["window_timeframe"] == "1m"
    assert fast_meta["history_window_candles"] == 60
    assert fast_meta["trigger_window_min_candles"] == 3
    assert fast_meta["trigger_selection"] == "cleanest_recent_story"


def test_fast_one_minute_profile_does_not_call_generic_setup_detectors(monkeypatch):
    data = {
        "1m": candles(
            "2026-06-10 09:50:00,100.0,100.6,99.8,100.2,1000\n"
            "2026-06-10 09:51:00,100.2,100.8,100.0,100.4,1000\n"
            "2026-06-10 09:52:00,100.4,101.0,100.2,100.7,1000\n"
            "2026-06-10 09:53:00,100.7,101.2,100.5,101.0,1000\n"
            "2026-06-10 09:54:00,101.0,101.5,100.8,101.3,1000"
        )
    }

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("fast 1m model must not call generic setup detectors")

    monkeypatch.setattr(engine, "detect_breakouts", fail_if_called, raising=False)
    monkeypatch.setattr(engine, "detect_break_and_retest", fail_if_called, raising=False)
    monkeypatch.setattr(engine, "detect_sr_bounce", fail_if_called, raising=False)

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "zone_timeframes": ("1m",),
            "context_timeframes": ("1m",),
            "governing_timeframes": ("1m",),
            "fast_history_window_candles": 60,
            "fast_min_trigger_candles": 3,
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["telemetry"]["decision_stage"] == "one_minute_no_trigger"


def test_fast_one_minute_profile_holds_when_story_is_unclear():
    data = {
        "1m": candles(
            "2026-06-10 10:00:00,100.0,100.7,99.7,100.1,1000\n"
            "2026-06-10 10:01:00,100.1,100.8,99.8,100.3,1000\n"
            "2026-06-10 10:02:00,100.3,101.0,100.0,100.5,1000\n"
            "2026-06-10 10:03:00,100.5,101.1,100.2,100.6,1000\n"
            "2026-06-10 10:04:00,100.6,101.2,100.4,100.8,1000"
        )
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 10:05",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "zone_timeframes": ("1m",),
            "context_timeframes": ("1m",),
            "governing_timeframes": ("1m",),
            "fast_history_window_candles": 60,
            "fast_min_trigger_candles": 3,
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["market_context"]["one_minute_story"]["classification"] == "UNCLEAR"


def test_fast_microstructure_can_trigger_from_clean_story_beyond_ten_candles():
    data = {
        "1m": candles(
            "2026-06-10 09:40:00,100.0,100.8,99.00,100.0,1000\n"
            "2026-06-10 09:41:00,100.0,100.7,99.60,100.2,1000\n"
            "2026-06-10 09:42:00,100.2,100.9,99.70,100.3,1000\n"
            "2026-06-10 09:43:00,100.3,101.0,99.80,100.4,1000\n"
            "2026-06-10 09:44:00,100.4,101.1,99.90,100.5,1000\n"
            "2026-06-10 09:45:00,100.5,101.2,100.0,100.6,1000\n"
            "2026-06-10 09:46:00,100.6,101.3,100.1,100.7,1000\n"
            "2026-06-10 09:47:00,100.7,101.4,100.2,100.8,1000\n"
            "2026-06-10 09:48:00,100.8,101.5,100.3,100.9,1000\n"
            "2026-06-10 09:49:00,100.9,101.6,100.4,101.0,1000\n"
            "2026-06-10 09:50:00,101.0,101.7,100.5,101.1,1000\n"
            "2026-06-10 09:51:00,101.1,101.8,100.6,101.2,1000\n"
            "2026-06-10 09:52:00,101.2,101.9,100.7,101.3,1000\n"
            "2026-06-10 09:53:00,101.3,102.0,100.8,101.4,1000\n"
            "2026-06-10 09:54:00,100.0,100.8,99.05,100.6,1000"
        )
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "zone_timeframes": ("1m",),
            "context_timeframes": ("1m",),
            "governing_timeframes": ("1m",),
            "fast_history_window_candles": 60,
            "fast_min_trigger_candles": 3,
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"


def test_one_minute_profile_holds_when_latest_candle_has_no_equal_level_trigger():
    data = {
        "1m": candles(
            "2026-06-10 10:00:00,100.0,100.7,99.7,100.1,1000\n"
            "2026-06-10 10:01:00,100.1,100.8,99.8,100.3,1000\n"
            "2026-06-10 10:02:00,100.3,101.0,100.0,100.5,1000\n"
            "2026-06-10 10:03:00,100.5,101.1,100.2,100.6,1000\n"
            "2026-06-10 10:04:00,100.6,101.2,100.4,100.8,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 10:05",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "fast_history_window_candles": 60,
            "fast_min_trigger_candles": 3,
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["checklist"]["entry_market_state_aligned"] == "passed"
    assert payload["telemetry"]["decision_stage"] == "one_minute_no_trigger"
    assert payload["market_context"]["one_minute_story"]["classification"] == "UNCLEAR"


def test_one_minute_profile_does_not_require_extra_confirmation_context():
    data = {
        "3m": candles(
            "2026-06-10 09:45:00,2000.0,2002.0,1998.6,2000.4,1000\n"
            "2026-06-10 09:48:00,2000.4,2001.2,1998.4,1999.7,1000\n"
            "2026-06-10 09:51:00,1999.7,2001.4,1998.0,2000.2,1000"
        ),
        "1m": candles(
            "2026-06-10 09:50:00,2000.0,2000.8,1998.6,1999.4,1000\n"
            "2026-06-10 09:51:00,1999.4,2001.0,1998.0,2000.7,1000\n"
            "2026-06-10 09:52:00,2000.7,2001.4,1999.7,2001.0,1000\n"
            "2026-06-10 09:53:00,2001.0,2001.2,1999.2,1999.8,1000\n"
            "2026-06-10 09:54:00,1999.8,2000.7,1998.1,2000.4,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("3m",),
            "governing_timeframes": ("3m",),
            "context_timeframes": ("3m",),
            "activation_window_minutes": 6,
            "minimum_stop_distance_price": 2.5,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["confirmation_timeframe"] == "1m"
    assert payload["checklist"]["timeframe_correlation"] == "passed"
    assert payload["market_context"]["one_minute_story"]["classification"] == "LOW_RESPECT_BUY"


def test_one_minute_profile_does_not_use_higher_timeframe_bias_filter():
    data = {
        "1m": candles(
            "2026-06-10 09:50:00,2000.0,2000.8,1998.6,1999.4,1000\n"
            "2026-06-10 09:51:00,1999.4,2001.0,1998.0,2000.7,1000\n"
            "2026-06-10 09:52:00,2000.7,2001.4,1999.7,2001.0,1000\n"
            "2026-06-10 09:53:00,2001.0,2001.2,1999.2,1999.8,1000\n"
            "2026-06-10 09:54:00,1999.8,2000.7,1998.1,2000.4,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "activation_window_minutes": 6,
            "minimum_setup_grade": "B_PLUS",
            "b_plus_min_rr": 1.2,
            "higher_timeframe_bias": "SELL",
            "fast_counter_bias_minimum_grade": "A_PLUS",
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"
    assert payload["telemetry"]["decision_stage"] == "one_minute_setup_found"


def test_engine_uses_state_aware_confirmation_when_no_event_context(monkeypatch):
    data = {
        **aligned_buy_setup_data(),
        "30m": candles(
            "2026-06-09 12:00:00,100,103,99,102,1000\n"
            "2026-06-09 12:30:00,102,105,101,104,1000\n"
            "2026-06-09 13:00:00,104,107,103,106,1000\n"
            "2026-06-09 13:30:00,106,109,105,108,1000\n"
            "2026-06-09 14:00:00,108,112,107,111,1000"
        ),
        "15m": candles(
            "2026-06-09 13:30:00,108,109,107,108.5,1000\n"
            "2026-06-09 13:45:00,108.5,110,108,109.5,1000\n"
            "2026-06-09 14:00:00,109.5,113,109,112,1000"
        ),
    }
    zone = Zone("resistance", "30m", 100.0, 101.0, 100.5, 3, 20, "test")
    setup = Setup("Breakout", "BUY", zone, 112.0, 109.0, data["15m"][-1])

    monkeypatch.setattr(
        engine,
        "calculate_support_resistance",
        lambda _candles, timeframe: [zone] if timeframe == "30m" else [],
    )
    monkeypatch.setattr(
        engine,
        "detect_breakouts",
        lambda raw_candles, _zones: [setup] if raw_candles == data["15m"] else [],
    )
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "_is_overextended", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 118.0})
    monkeypatch.setattr(
        engine,
        "approve_risk",
        lambda *_args, **_kwargs: {
            "approved": True,
            "take_profit": 118.0,
            "risk_distance": 3.0,
            "reward_distance": 6.0,
            "risk_reward": 2.0,
            "available_risk_reward": 2.0,
        },
    )

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-09 14:15",
        data,
        market_timezone="America/New_York",
        session_config={"time_filter_mode": "allow"},
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["market_context"]["m30_context"] == "STRUCTURE"
    assert payload["market_context"]["market_state"]["30m"]["direction"] == "BUY"
    assert payload["checklist"]["confirmation_context_clear"] == "passed"


def test_engine_uses_profile_zones_for_entry_triggers_not_context_zones(monkeypatch):
    data = aligned_buy_setup_data()
    captured_entry_zone_timeframes = []
    m30_zone = Zone("support", "30m", 100.0, 101.0, 100.5, 3, 20, "m30")
    daily_zone = Zone("support", "1d", 90.0, 91.0, 90.5, 3, 30, "daily")

    def fake_zones(_candles, timeframe):
        if timeframe == "30m":
            return [m30_zone]
        if timeframe == "1d":
            return [daily_zone]
        return []

    def fake_sr_bounce(raw_candles, zones):
        if raw_candles == data["15m"]:
            captured_entry_zone_timeframes.extend(zone.timeframe for zone in zones)
        return []

    monkeypatch.setattr(engine, "calculate_support_resistance", fake_zones)
    monkeypatch.setattr(engine, "detect_breakouts", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", fake_sr_bounce)

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "zone_timeframes": ("30m",),
            "context_timeframes": ("1d", "4h", "1h"),
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert captured_entry_zone_timeframes == ["30m"]
    assert payload["market_context"]["context_timeframes"] == ("1d", "4h", "1h")


def test_engine_rejects_candidate_below_minimum_stop_distance(monkeypatch):
    data = aligned_buy_setup_data()
    zone = Zone(
        type="resistance",
        timeframe="30m",
        low=105.0,
        high=106.0,
        midpoint=105.5,
        touches=3,
        score=30.0,
        source="test",
    )
    setup = Setup(
        name="Breakout",
        direction="BUY",
        zone=zone,
        entry_price=106.0,
        stop_loss=105.4,
        confirmation_candle=data["15m"][-1],
    )

    monkeypatch.setattr(engine, "detect_breakouts", lambda raw_candles, zones: [setup])
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 110})
    monkeypatch.setattr(
        engine,
        "approve_risk",
        lambda *_args, **_kwargs: {
            "approved": True,
            "take_profit": 110,
            "risk_distance": 0.6,
            "reward_distance": 4,
            "risk_reward": 6.67,
            "available_risk_reward": 6.67,
        },
    )

    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-18 08:30",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "minimum_stop_distance_price": 2.5,
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["checklist"]["clean_range_to_fill"] == "failed"
    assert "Stop distance is below minimum" in payload["risk"]["reason"]


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


def test_engine_time_filter_allow_mode_can_continue_to_setup():
    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-17 19:30",
        aligned_buy_setup_data(),
        market_timezone="America/New_York",
        session_config={"time_filter_mode": "allow"},
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["checklist"]["volume_time"] == "passed"
    assert payload["checklist"]["not_sunday_asian_session"] == "passed"
    assert payload["market_context"]["time_filter_mode"] == "allow"


def test_engine_time_filter_observe_mode_records_candidates_but_blocks_order():
    payload = analyze_playbook(
        "XAUUSD",
        "2026-05-17 19:30",
        aligned_buy_setup_data(),
        market_timezone="America/New_York",
        session_config={"time_filter_mode": "observe"},
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["checklist"]["volume_time"] == "failed"
    assert payload["checklist"]["not_sunday_asian_session"] == "failed"
    assert payload["telemetry"]["decision_stage"] == "a_plus_checklist"
    assert payload["telemetry"]["candidate_setup_count"] >= 1
    assert payload["telemetry"]["candidate_evaluations"]
    assert payload["market_context"]["time_filter_mode"] == "observe"


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
    assert payload["market_context"]["daily_structure"]["classification"] in {
        "BULLISH_STRUCTURE",
        "BEARISH_STRUCTURE",
        "RANGE",
        "NEAR_MAJOR_SUPPORT",
        "NEAR_MAJOR_RESISTANCE",
        "BREAK_OF_STRUCTURE_UP",
        "BREAK_OF_STRUCTURE_DOWN",
        "UNCLEAR",
    }
    assert payload["market_context"]["h4_structure"]["permission"] in {
        "BUY_ALLOWED",
        "SELL_ALLOWED",
        "NEUTRAL",
    }
    assert payload["market_context"]["h1_structure"]["timeframe"] == "1H"


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
