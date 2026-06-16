import json
from types import SimpleNamespace

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action import decision
from tradingagents.dataflows.price_action import PriceActionSnapshot


def _healthy_status():
    return {
        "healthy": True,
        "blocking_timeframes": [],
        "trading_timeframe": {"available": True, "fresh": True, "rows": 2},
        "confirmation_timeframe": {"available": True, "fresh": True, "rows": 2},
        "timeframes": {
            "1d": {"available": True, "fresh": True, "rows": 2},
            "4h": {"available": True, "fresh": True, "rows": 2},
            "1h": {"available": True, "fresh": True, "rows": 2},
            "30m": {"available": True, "fresh": True, "rows": 2},
            "15m": {"available": True, "fresh": True, "rows": 2},
        },
    }


def _candles():
    rows = [
        Candle("2026-06-01 08:00:00", 100, 102, 99, 101, 1000),
        Candle("2026-06-01 08:15:00", 101, 104, 100, 103, 1000),
    ]
    return {"1d": rows, "4h": rows, "1h": rows, "30m": rows, "15m": rows}


def test_engine_decision_runs_without_llm_and_writes_payload(monkeypatch, tmp_path):
    calls = {}

    monkeypatch.setattr(
        decision,
        "fetch_price_action_snapshot",
        lambda symbol, as_of, market_timezone: SimpleNamespace(
            candles=_candles(),
            data_status=_healthy_status(),
        ),
    )

    def fake_analyze(symbol, as_of, timeframe_data, market_timezone, session_config):
        calls["analyze"] = {
            "symbol": symbol,
            "as_of": as_of,
            "timeframe_keys": set(timeframe_data),
            "market_timezone": market_timezone,
            "session_config": session_config,
        }
        return {
            "symbol": symbol,
            "as_of": as_of,
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "status": "NO_SETUP",
            "recommendation": "HOLD",
            "message": "No valid M15 setup. Default to HOLD.",
            "checklist": {"playbook_setup": "failed"},
            "risk": {},
            "setups": [],
            "market_context": {"m30_bias": "BULLISH", "m30_context": "BREAKOUT"},
            "telemetry": {
                "decision_stage": "no_m15_setup",
                "primary_hold_reason": "No valid M15 setup. Default to HOLD.",
                "candidate_setup_count": 0,
                "m30_context": {"bias": "BULLISH", "context": "BREAKOUT"},
            },
        }

    monkeypatch.setattr(decision, "analyze_playbook", fake_analyze)

    state = decision.run_engine_decision(
        "GC=F",
        broker_symbol="XAUUSD.vx",
        as_of="2026-06-01 08:15",
        results_dir=tmp_path,
        session_config={"time_filter_mode": "allow"},
    )

    assert calls["analyze"]["symbol"] == "GC=F"
    assert calls["analyze"]["timeframe_keys"] == {"1d", "4h", "1h", "30m", "15m"}
    assert calls["analyze"]["session_config"] == {"time_filter_mode": "allow"}
    assert state["company_of_interest"] == "GC=F"
    assert state["broker_symbol"] == "XAUUSD.vx"
    assert state["engine_payload"]["status"] == "NO_SETUP"
    assert state["engine_telemetry"]["decision_stage"] == "no_m15_setup"
    assert state["data_status"]["healthy"] is True
    assert "Final Action: HOLD" in state["price_action_report"]

    telemetry_path = tmp_path / "GC=F" / "engine_telemetry" / "engine_payload_2026-06-01_08_15.json"
    assert state["telemetry_path"] == str(telemetry_path)
    assert telemetry_path.exists()
    written = json.loads(telemetry_path.read_text(encoding="utf-8"))
    assert written["telemetry"]["decision_stage"] == "no_m15_setup"


def test_engine_decision_preserves_model_timeframes_for_one_minute_profile(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(
        decision,
        "fetch_price_action_snapshot",
        lambda symbol, as_of, market_timezone: SimpleNamespace(
            candles=_candles(),
            data_status=_healthy_status(),
        ),
    )

    def fake_analyze(symbol, as_of, timeframe_data, market_timezone, session_config):
        return {
            "symbol": symbol,
            "as_of": as_of,
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "activation_window_minutes": 1,
            "status": "SETUP_FOUND",
            "recommendation": "SELL",
            "message": "Explicit 1m trigger HIGH_RESPECT_SELL passed.",
            "checklist": {"playbook_setup": "passed"},
            "risk": {"take_profit": 99.4},
            "setups": [
                {
                    "name": "HIGH_RESPECT_SELL",
                    "direction": "SELL",
                    "entry_price": 100.0,
                    "stop_loss": 100.4,
                    "take_profit": 99.4,
                    "setup_grade": "A_PLUS",
                }
            ],
            "market_context": {"one_minute_story": {"classification": "HIGH_RESPECT_SELL"}},
            "telemetry": {
                "decision_stage": "one_minute_setup_found",
                "primary_hold_reason": "Explicit 1m trigger HIGH_RESPECT_SELL passed.",
                "candidate_setup_count": 1,
                "confirmation_timeframe": "1m",
            },
        }

    monkeypatch.setattr(decision, "analyze_playbook", fake_analyze)

    state = decision.run_engine_decision(
        "XAUUSD.vx",
        broker_symbol="XAUUSD.vx",
        as_of="2026-06-10 09:55",
        results_dir=tmp_path,
        timeframe="1m",
        confirmation_timeframe="1m",
        session_config={
            "entry_profile": "fast",
            "activation_window_minutes": 1,
        },
    )

    assert state["timeframe"] == "1m"
    assert state["confirmation_timeframe"] == "1m"
    assert state["engine_payload"]["confirmation_timeframe"] == "1m"
    assert "1m History" in state["price_action_report"]
    assert "3m Context" not in state["price_action_report"]


def test_engine_decision_returns_data_health_hold_when_data_is_unhealthy(
    monkeypatch,
    tmp_path,
):
    unhealthy = _healthy_status()
    unhealthy["healthy"] = False
    unhealthy["blocking_timeframes"] = ["15m"]
    unhealthy["timeframes"]["15m"]["fresh"] = False

    monkeypatch.setattr(
        decision,
        "fetch_price_action_snapshot",
        lambda symbol, as_of, market_timezone: SimpleNamespace(
            candles=_candles(),
            data_status=unhealthy,
        ),
    )

    def fail_analyze(*args, **kwargs):
        raise AssertionError("unhealthy data should not reach analyze_playbook")

    monkeypatch.setattr(decision, "analyze_playbook", fail_analyze)

    state = decision.run_engine_decision(
        "GC=F",
        broker_symbol=None,
        as_of="2026-06-01 08:15",
        results_dir=tmp_path,
    )

    assert state["engine_payload"]["status"] == "NO_SETUP"
    assert state["engine_payload"]["recommendation"] == "HOLD"
    assert state["engine_telemetry"]["decision_stage"] == "data_health"
    assert "Data health failed" in state["price_action_report"]
    assert "15m" in state["price_action_report"]


def test_engine_decision_returns_market_health_hold_for_wide_spread(
    monkeypatch,
    tmp_path,
):
    snapshot = PriceActionSnapshot(
        candles=_candles(),
        data_status=_healthy_status(),
        market_metadata={
            "symbol": {
                "name": "XAUUSD",
                "bid": 4500.0,
                "ask": 4501.0,
                "spread_price": 1.0,
            },
            "tick": {"bid": 4500.0, "ask": 4501.0},
        },
    )

    def fail_analyze(*args, **kwargs):
        raise AssertionError("wide live spread should not reach analyze_playbook")

    monkeypatch.setattr(decision, "analyze_playbook", fail_analyze)

    state = decision.run_engine_decision(
        "XAUUSD",
        broker_symbol="XAUUSD",
        as_of="2026-06-01 08:15",
        results_dir=tmp_path,
        snapshot=snapshot,
        session_config={
            "max_entry_spread_price": 0.5,
            "max_tick_age_seconds": 0,
        },
    )

    payload = state["engine_payload"]
    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["telemetry"]["decision_stage"] == "market_health"
    assert payload["market_health"]["reasons"] == ["spread_too_wide"]


def test_engine_decision_passes_live_bid_ask_into_one_minute_profile(
    monkeypatch,
    tmp_path,
):
    captured_config = {}
    snapshot = PriceActionSnapshot(
        candles={"1m": [Candle("2026-06-10 09:00:00", 1, 2, 0.5, 1.5, 1000)]},
        data_status=_healthy_status(),
        market_metadata={
            "symbol": {
                "name": "XAUUSD.vx",
                "bid": 4339.84,
                "ask": 4340.13,
                "spread_price": 0.29,
            },
            "tick": {"bid": 4339.84, "ask": 4340.13},
        },
    )

    def fake_analyze(symbol, as_of, timeframe_data, market_timezone, session_config):
        captured_config.update(session_config)
        return {
            "symbol": symbol,
            "as_of": as_of,
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "status": "NO_SETUP",
            "recommendation": "HOLD",
            "message": "No one-minute setup.",
            "checklist": {"playbook_setup": "failed"},
            "risk": {},
            "setups": [],
            "market_context": {},
            "telemetry": {"decision_stage": "one_minute_no_trigger"},
        }

    monkeypatch.setattr(decision, "analyze_playbook", fake_analyze)

    decision.run_engine_decision(
        "XAUUSD.vx",
        broker_symbol="XAUUSD.vx",
        as_of="2026-06-10 09:01",
        results_dir=tmp_path,
        timeframe="1m",
        confirmation_timeframe="1m",
        snapshot=snapshot,
        session_config={
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
        },
    )

    assert captured_config["current_spread_price"] == 0.29
    assert captured_config["current_bid_price"] == 4339.84
    assert captured_config["current_ask_price"] == 4340.13


def test_engine_decision_tags_unhealthy_fast_profile_payload(tmp_path):
    unhealthy = _healthy_status()
    unhealthy["healthy"] = False
    unhealthy["blocking_timeframes"] = ["1m"]
    snapshot = PriceActionSnapshot(candles=_candles(), data_status=unhealthy)

    state = decision.run_engine_decision(
        "GC=F",
        broker_symbol="XAUUSD.vx",
        as_of="2026-06-03 08:15",
        results_dir=tmp_path,
        timeframe="1m",
        confirmation_timeframe="1m",
        session_config={
            "entry_profile": "fast",
            "activation_window_minutes": 1,
        },
        snapshot=snapshot,
    )

    telemetry_path = (
        tmp_path
        / "GC=F"
        / "engine_telemetry"
        / "engine_payload_2026-06-03_08_15_fast.json"
    )
    assert state["telemetry_path"] == str(telemetry_path)
    assert state["engine_payload"]["entry_profile"] == "fast"
    assert state["engine_payload"]["activation_window_minutes"] == 1
    assert telemetry_path.exists()


def test_render_engine_decision_report_labels_fast_history_window():
    report = decision.render_engine_decision_report(
        {
            "symbol": "XAUUSD.vx",
            "as_of": "2026-06-11 13:53",
            "status": "SETUP_FOUND",
            "recommendation": "SELL",
            "confirmation_timeframe": "1m",
            "market_context": {"m30_bias": "BEARISH", "m30_context": "BREAKOUT"},
            "telemetry": {
                "candidate_setup_count": 1,
                "m30_context": {"bias": "BEARISH", "context": "BREAKOUT"},
            },
        }
    )

    assert "**1m History:** BEARISH BREAKOUT" in report
    assert "3m Context" not in report
    assert "M30 Context" not in report


def test_run_engine_decision_accepts_prebuilt_snapshot(monkeypatch, tmp_path):
    unhealthy = _healthy_status()
    unhealthy["healthy"] = False
    unhealthy["blocking_timeframes"] = ["15m"]
    unhealthy["timeframes"]["15m"]["fresh"] = False
    snapshot = PriceActionSnapshot(candles=_candles(), data_status=unhealthy)

    def fail_fetch(*args, **kwargs):
        raise AssertionError("prebuilt snapshot should bypass vendor fetch")

    def fail_analyze(*args, **kwargs):
        raise AssertionError("unhealthy data should not reach analyze_playbook")

    monkeypatch.setattr(decision, "fetch_price_action_snapshot", fail_fetch)
    monkeypatch.setattr(decision, "analyze_playbook", fail_analyze)

    state = decision.run_engine_decision(
        "XAUUSD.vx",
        broker_symbol="XAUUSD.vx",
        as_of="2026-06-02T19:16:00-04:00",
        results_dir=tmp_path,
        snapshot=snapshot,
    )

    assert state["company_of_interest"] == "XAUUSD.vx"
    assert state["broker_symbol"] == "XAUUSD.vx"
    assert state["data_status"]["blocking_timeframes"] == ["15m"]
    assert state["engine_telemetry"]["decision_stage"] == "data_health"
