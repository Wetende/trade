from tradingagents.agents.price_action.candles import parse_ohlcv_text
from tradingagents.agents.price_action import engine
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


def test_engine_can_run_fast_profile_with_one_minute_entries(monkeypatch):
    data = {
        **aligned_buy_setup_data(),
        "3m": candles(
            "2026-06-03 08:06:00,100,103,99,102,1000\n"
            "2026-06-03 08:09:00,102,106,101,105,1000"
        ),
        "1m": candles(
            "2026-06-03 08:10:00,104,105,103,104.5,1000\n"
            "2026-06-03 08:11:00,104.5,106.5,104,106,1000"
        ),
    }
    zone = Zone(
        type="resistance",
        timeframe="3m",
        low=104.0,
        high=105.0,
        midpoint=104.5,
        touches=3,
        score=20.0,
        source="test",
    )
    setup = Setup(
        name="Breakout",
        direction="BUY",
        zone=zone,
        entry_price=106.0,
        stop_loss=103.0,
        confirmation_candle=data["1m"][-1],
    )
    confirmation_setup = Setup(
        name="Breakout",
        direction="BUY",
        zone=zone,
        entry_price=105.0,
        stop_loss=102.0,
        confirmation_candle=data["3m"][-1],
    )

    monkeypatch.setattr(
        engine,
        "calculate_support_resistance",
        lambda raw_candles, timeframe: [zone] if timeframe == "3m" else [],
    )
    monkeypatch.setattr(
        engine,
        "detect_breakouts",
        lambda raw_candles, zones: (
            [setup]
            if raw_candles == data["1m"]
            else [confirmation_setup]
            if raw_candles == data["3m"]
            else []
        ),
    )
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 112.0})
    monkeypatch.setattr(
        engine,
        "approve_risk",
        lambda *_args, **_kwargs: {
            "approved": True,
            "take_profit": 112.0,
            "risk_distance": 3.0,
            "reward_distance": 6.0,
            "risk_reward": 2.0,
            "available_risk_reward": 2.0,
        },
    )

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-03 08:12",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("1d", "4h", "1h", "30m", "15m", "3m"),
            "activation_window_minutes": 6,
            "minimum_stop_distance_price": 2.5,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["entry_profile"] == "fast"
    assert payload["timeframe"] == "1m"
    assert payload["confirmation_timeframe"] == "3m"
    assert payload["activation_window_minutes"] == 6
    assert payload["telemetry"]["timeframe_rows"]["1m"] == 2
    assert payload["telemetry"]["zone_counts"]["3m"] == 1


def test_fast_microstructure_aggressive_respect_buy_from_two_lows():
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
            "context_timeframes": ("3m",),
            "governing_timeframes": ("3m",),
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "Aggressive Respect"
    assert payload["setups"][0]["setup_grade"] == "B_PLUS"
    assert payload["risk"]["approved"] is True
    assert payload["risk"]["risk_reward"] >= 1.1
    assert payload["checklist"]["confirmation_context_clear"] == "passed"
    assert payload["market_context"]["fast_microstructure"]["window_timeframe"] == "3m"


def test_fast_microstructure_confirmed_break_sell_from_two_highs():
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
    assert payload["setups"][0]["name"] == "Confirmed Break"
    assert payload["risk"]["approved"] is True
    assert payload["risk"]["risk_reward"] >= 1.4
    assert payload["checklist"]["confirmation_context_clear"] == "passed"


def test_fast_microstructure_confirmed_break_sell_when_two_lows_fail():
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
    assert payload["setups"][0]["name"] == "Confirmed Break"
    assert payload["setups"][0]["zone"]["type"] == "support"
    assert payload["risk"]["approved"] is True


def test_fast_microstructure_blocks_when_three_minute_window_opposes(monkeypatch):
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

    assert payload["status"] == "NO_SETUP"
    assert payload["checklist"]["timeframe_correlation"] == "failed"
    assert "3m window opposes" in payload["telemetry"]["primary_hold_reason"]


def test_fast_engine_uses_governing_context_separate_from_three_minute_timing(
    monkeypatch,
):
    data = {
        **aligned_buy_setup_data(),
        "30m": candles(
            "2026-06-09 14:00:00,100,102,98,101,1000\n"
            "2026-06-09 14:30:00,101,102,96,97,1000"
        ),
        "15m": candles(
            "2026-06-09 14:15:00,101,102,98,100,1000\n"
            "2026-06-09 14:30:00,100,101,96,97,1000"
        ),
        "3m": candles(
            "2026-06-09 14:54:00,98,99,97,98.5,1000\n"
            "2026-06-09 14:57:00,98.5,99.5,97.5,98.4,1000"
        ),
        "1m": candles(
            "2026-06-09 14:58:00,98.4,99.0,97.8,98.1,1000\n"
            "2026-06-09 14:59:00,98.1,98.8,96.8,97.2,1000"
        ),
    }
    context_zone = Zone("support", "30m", 96.0, 97.0, 96.5, 3, 20, "test")
    entry_zone = Zone("support", "15m", 96.0, 97.0, 96.5, 3, 20, "test")
    context_setup = Setup(
        "Breakout",
        "SELL",
        context_zone,
        97.0,
        99.0,
        data["30m"][-1],
    )
    entry_setup = Setup(
        "Breakout",
        "SELL",
        entry_zone,
        97.2,
        98.9,
        data["1m"][-1],
    )

    monkeypatch.setattr(
        engine,
        "calculate_support_resistance",
        lambda raw_candles, timeframe: (
            [context_zone]
            if timeframe == "30m"
            else [entry_zone]
            if timeframe == "15m"
            else []
        ),
    )
    monkeypatch.setattr(
        engine,
        "detect_breakouts",
        lambda raw_candles, zones: (
            [context_setup]
            if raw_candles == data["30m"]
            else [entry_setup]
            if raw_candles == data["1m"]
            else []
        ),
    )
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "_is_overextended", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 92.0})
    monkeypatch.setattr(
        engine,
        "approve_risk",
        lambda *_args, **_kwargs: {
            "approved": True,
            "take_profit": 92.0,
            "risk_distance": 1.7,
            "reward_distance": 5.2,
            "risk_reward": 3.0,
            "available_risk_reward": 3.0,
        },
    )

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-09 15:00",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "governing_timeframes": ("30m", "15m"),
            "zone_timeframes": ("30m", "15m"),
            "activation_window_minutes": 6,
            "minimum_stop_distance_price": 0.5,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["confirmation_timeframe"] == "3m"
    assert payload["market_context"]["governing_timeframes"] == ("30m", "15m")
    assert payload["checklist"]["timeframe_correlation"] == "passed"
    assert payload["checklist"]["confirmation_context_clear"] == "passed"


def test_fast_engine_rejects_entry_against_one_minute_market_state(monkeypatch):
    data = {
        **aligned_buy_setup_data(),
        "30m": candles(
            "2026-06-09 14:00:00,100,102,98,101,1000\n"
            "2026-06-09 14:30:00,101,102,96,97,1000"
        ),
        "15m": candles(
            "2026-06-09 14:15:00,101,102,98,100,1000\n"
            "2026-06-09 14:30:00,100,101,96,97,1000"
        ),
        "3m": candles(
            "2026-06-09 14:54:00,98,99,97,98.5,1000\n"
            "2026-06-09 14:57:00,98.5,99.5,97.5,98.4,1000"
        ),
        "1m": candles(
            "2026-06-09 14:58:00,98.4,99.0,97.8,98.1,1000\n"
            "2026-06-09 14:59:00,98.1,98.8,96.8,97.2,1000"
        ),
    }
    context_zone = Zone("support", "30m", 96.0, 97.0, 96.5, 3, 20, "test")
    entry_zone = Zone("support", "15m", 96.0, 97.0, 96.5, 3, 20, "test")
    context_setup = Setup(
        "Breakout",
        "SELL",
        context_zone,
        97.0,
        99.0,
        data["30m"][-1],
    )
    entry_setup = Setup(
        "Breakout",
        "SELL",
        entry_zone,
        97.2,
        98.9,
        data["1m"][-1],
    )

    monkeypatch.setattr(
        engine,
        "calculate_support_resistance",
        lambda raw_candles, timeframe: (
            [context_zone]
            if timeframe == "30m"
            else [entry_zone]
            if timeframe == "15m"
            else []
        ),
    )
    monkeypatch.setattr(
        engine,
        "detect_breakouts",
        lambda raw_candles, zones: (
            [context_setup]
            if raw_candles == data["30m"]
            else [entry_setup]
            if raw_candles == data["1m"]
            else []
        ),
    )
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "_is_overextended", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 92.0})
    monkeypatch.setattr(
        engine,
        "approve_risk",
        lambda *_args, **_kwargs: {
            "approved": True,
            "take_profit": 92.0,
            "risk_distance": 1.7,
            "reward_distance": 5.2,
            "risk_reward": 3.0,
            "available_risk_reward": 3.0,
        },
    )
    monkeypatch.setattr(
        engine,
        "classify_market_state",
        lambda raw_candles, zones, timeframe: {
            "timeframe": timeframe,
            "trend_state": "TRENDING",
            "direction": "BUY" if timeframe == "1m" else None,
            "structure": {
                "classification": (
                    "BULLISH_STRUCTURE" if timeframe == "1m" else "RANGE"
                ),
                "permission": "BUY_ALLOWED" if timeframe == "1m" else "NEUTRAL",
            },
            "volatility_state": "NORMAL",
            "latest_close": raw_candles[-1].close if raw_candles else None,
            "rows": len(raw_candles),
        },
    )

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-09 15:00",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "governing_timeframes": ("30m", "15m"),
            "zone_timeframes": ("30m", "15m"),
            "activation_window_minutes": 6,
            "minimum_stop_distance_price": 0.5,
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["checklist"]["entry_market_state_aligned"] == "failed"
    assert payload["telemetry"]["decision_stage"] == "a_plus_checklist"
    assert "entry market state opposes" in payload["telemetry"]["primary_hold_reason"]


def test_fast_engine_rejects_entries_when_confirmation_context_is_unclear(monkeypatch):
    data = {
        **aligned_buy_setup_data(),
        "3m": candles(
            "2026-06-03 08:06:00,100,103,99,102,1000\n"
            "2026-06-03 08:09:00,102,106,101,105,1000"
        ),
        "1m": candles(
            "2026-06-03 08:10:00,104,105,103,104.5,1000\n"
            "2026-06-03 08:11:00,104.5,106.5,104,106,1000"
        ),
    }
    zone = Zone("resistance", "3m", 104, 105, 104.5, 3, 20, "test")
    setup = Setup("Breakout", "BUY", zone, 106.0, 103.0, data["1m"][-1])

    monkeypatch.setattr(
        engine,
        "calculate_support_resistance",
        lambda raw_candles, timeframe: [zone] if timeframe == "3m" else [],
    )
    monkeypatch.setattr(
        engine,
        "detect_breakouts",
        lambda raw_candles, zones: [setup] if raw_candles == data["1m"] else [],
    )
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 112.0})
    monkeypatch.setattr(
        engine,
        "approve_risk",
        lambda *_args, **_kwargs: {
            "approved": True,
            "take_profit": 112.0,
            "risk_distance": 3.0,
            "reward_distance": 6.0,
            "risk_reward": 2.0,
            "available_risk_reward": 2.0,
        },
    )

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-03 08:12",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("1h", "30m", "15m", "3m"),
            "activation_window_minutes": 6,
            "minimum_stop_distance_price": 2.5,
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["checklist"]["timeframe_correlation"] == "failed"
    assert payload["telemetry"]["decision_stage"] == "a_plus_checklist"
    assert "confirmation context is unclear" in payload["telemetry"]["primary_hold_reason"]


def test_fast_engine_requires_a_plus_when_counter_higher_timeframe_bias(monkeypatch):
    data = {
        **aligned_buy_setup_data(),
        "3m": candles(
            "2026-06-03 08:06:00,100,103,99,102,1000\n"
            "2026-06-03 08:09:00,102,106,101,105,1000"
        ),
        "1m": candles(
            "2026-06-03 08:10:00,104,105,103,104.5,1000\n"
            "2026-06-03 08:11:00,104.5,106.5,104,106,1000"
        ),
    }
    zone = Zone("resistance", "3m", 104, 105, 104.5, 3, 20, "test")
    setup = Setup("Breakout", "BUY", zone, 106.0, 103.0, data["1m"][-1])

    monkeypatch.setattr(engine, "calculate_support_resistance", lambda raw_candles, timeframe: [zone])
    monkeypatch.setattr(engine, "detect_breakouts", lambda raw_candles, zones: [setup])
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 110})
    def fake_approve_risk(_setup, _target_zone, minimum_rr=1.5, preferred_rr=3.0):
        available_rr = 1.33
        if available_rr < minimum_rr:
            return {
                "approved": False,
                "reason": "Clean range is below minimum risk-to-reward",
                "risk_reward": available_rr,
            }
        return {
            "approved": True,
            "take_profit": 110,
            "risk_distance": 3,
            "reward_distance": 4,
            "risk_reward": available_rr,
            "available_risk_reward": available_rr,
        }

    monkeypatch.setattr(engine, "approve_risk", fake_approve_risk)

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-03 08:12",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "activation_window_minutes": 6,
            "minimum_setup_grade": "B_PLUS",
            "b_plus_min_rr": 1.2,
            "higher_timeframe_bias": "SELL",
            "fast_counter_bias_minimum_grade": "A_PLUS",
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["telemetry"]["decision_stage"] == "counter_bias_grade_filter"
    assert payload["telemetry"]["candidate_evaluations"][0]["setup_grade"] == "B_PLUS"


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
