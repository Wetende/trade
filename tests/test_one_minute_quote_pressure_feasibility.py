from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.one_minute_quote_pressure_feasibility import (
    FeasibilityConfig,
    analyze_feasibility_fixture,
)


START = datetime(2026, 7, 26, 22, 0, tzinfo=timezone.utc)


def _fixture(*, complete=True):
    candles = [
        {
            "timestamp": (START + timedelta(minutes=minute)).isoformat(),
            "open": 100.0,
            "high": 100.2,
            "low": 99.8,
            "close": 100.0,
        }
        for minute in range(5)
    ]
    ticks = []
    for minute in range(4):
        candle_time = START + timedelta(minutes=minute)
        closed_at = candle_time + timedelta(minutes=1)
        count = 21 if complete else 4
        for index in range(count):
            mid = 100.0 + index * 0.02
            ticks.append(
                {
                    "time": (closed_at + timedelta(seconds=index * 0.1)).isoformat(),
                    "bid": mid - 0.01,
                    "ask": mid + 0.01,
                }
            )
    return {
        "evidence_start": START.isoformat(),
        "evidence_end": (START + timedelta(minutes=5)).isoformat(),
        "candles": candles,
        "ticks": ticks,
    }


def _config():
    return FeasibilityConfig(
        minimum_windows=3,
        minimum_sample_complete_rate=0.50,
        minimum_strict_feasible_rate=0.50,
        minimum_strict_events=2,
        minimum_session_coverage=1.0,
    )


def test_feasibility_probe_passes_directional_twenty_change_windows():
    report = analyze_feasibility_fixture(_fixture(), config=_config())
    assert report["status"] == "PASS"
    assert report["order_capability"] is False
    assert report["metrics"]["eligible_windows"] == 4
    assert report["metrics"]["sample_complete_windows"] == 4
    assert report["metrics"]["strict_feasible_windows"] == 4
    assert report["metrics"]["buy_strict_windows"] == 4


def test_feasibility_probe_fails_when_feed_cannot_supply_twenty_changes():
    report = analyze_feasibility_fixture(_fixture(complete=False), config=_config())
    assert report["status"] == "FAIL"
    assert report["decision"] == "FEED_INFEASIBLE"
    assert "SAMPLE_COMPLETE_RATE_BELOW_MINIMUM" in report["reasons"]
    assert "STRICT_EVENTS_BELOW_MINIMUM" in report["reasons"]


def test_feasibility_probe_rejects_incomplete_candle_partition():
    fixture = _fixture()
    fixture["candles"] = fixture["candles"][:1]
    report = analyze_feasibility_fixture(fixture, config=_config())
    assert report["data_quality"]["passed"] is False
    assert "DATA_QUALITY_FAILED" in report["reasons"]
