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
