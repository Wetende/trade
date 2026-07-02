import json
from pathlib import Path

import pytest

from tradingagents.agents.price_action.one_minute_entry_model import (
    analyze_one_minute_entry,
)
from tradingagents.default_config import DEFAULT_CONFIG


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "one_minute"
    / "2026-07-01-signal-window.json"
)


def _bars():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["bars"]


def _decision_at(
    timestamp: str,
    *,
    current_bid_price: float | None = None,
    current_spread_price: float | None = None,
):
    bars = _bars()
    index = next(
        index for index, bar in enumerate(bars) if bar["timestamp"] == timestamp
    )
    current = bars[index]
    spread = (
        max(0.01, float(current["spread"]) * 0.01)
        if current_spread_price is None
        else current_spread_price
    )
    bid = (
        float(current["close"])
        if current_bid_price is None
        else current_bid_price
    )
    config = {
        **DEFAULT_CONFIG["price_action"],
        "current_spread_price": spread,
        "current_bid_price": bid,
        "current_ask_price": bid + spread,
    }
    return analyze_one_minute_entry(
        "XAUUSD.vx",
        timestamp,
        {"1m": bars[: index + 1]},
        session_config=config,
    )


@pytest.mark.parametrize(
    ("timestamp", "expected_trigger"),
    [
        ("2026-07-01T21:03:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:17:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:22:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:34:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:40:00+00:00", "FAILED_HIGH_BREAK_SELL"),
        ("2026-07-01T21:44:00+00:00", "HIGH_RESPECT_SELL"),
        ("2026-07-01T21:50:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
    ],
)
def test_replay_exposes_clean_current_opening(timestamp, expected_trigger):
    payload = _decision_at(timestamp)
    matching = [
        candidate
        for candidate in payload["telemetry"]["candidate_evaluations"]
        if candidate["trigger"] == expected_trigger
    ]
    assert matching
    assert matching[0]["confirmation_type"] in {
        "rejection",
        "engulfing",
        "strong_close",
    }


@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-07-01T21:07:00+00:00",
        "2026-07-01T21:13:00+00:00",
        "2026-07-01T21:36:00+00:00",
    ],
)
def test_replay_does_not_approve_mixed_confirmation(timestamp):
    payload = _decision_at(timestamp)
    approved = [
        candidate
        for candidate in payload["telemetry"]["candidate_evaluations"]
        if candidate["approved"]
    ]
    assert approved == []


@pytest.mark.parametrize(
    ("timestamp", "expected_trigger"),
    [
        ("2026-07-01T21:34:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:40:00+00:00", "FAILED_HIGH_BREAK_SELL"),
        ("2026-07-01T21:44:00+00:00", "HIGH_RESPECT_SELL"),
    ],
)
def test_remote_memory_does_not_veto_clean_local_opening(
    timestamp,
    expected_trigger,
):
    payload = _decision_at(timestamp)
    candidate = next(
        item
        for item in payload["telemetry"]["candidate_evaluations"]
        if item["trigger"] == expected_trigger
    )
    assert "CONFLICTED_ONE_MINUTE_MEMORY" not in candidate["rejection_reasons"]


@pytest.mark.parametrize(
    ("timestamp", "expected_trigger"),
    [
        ("2026-07-01T21:17:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:22:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:50:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
    ],
)
def test_clean_current_impulse_can_reverse_old_pressure(
    timestamp,
    expected_trigger,
):
    payload = _decision_at(timestamp)
    candidate = next(
        item
        for item in payload["telemetry"]["candidate_evaluations"]
        if item["trigger"] == expected_trigger
    )
    assert "ONE_MINUTE_PRESSURE_CONFLICT" not in candidate["rejection_reasons"]
    assert "CONFLICTED_LOCAL_ONE_MINUTE_ZONE" not in candidate["rejection_reasons"]
    assert (
        "ONE_MINUTE_ACTIVE_PULSE_NOT_ALIGNED"
        not in candidate["rejection_reasons"]
    )


def test_confirmed_high_respect_sell_is_repriced_near_live_quote():
    payload = _decision_at(
        "2026-07-01T21:44:00+00:00",
        current_bid_price=4033.87,
        current_spread_price=0.29,
    )
    candidate = next(
        item
        for item in payload["telemetry"]["candidate_evaluations"]
        if item["trigger"] == "HIGH_RESPECT_SELL"
    )

    assert candidate["approved"] is True
    assert candidate["entry_price"] < 4034.78
    assert abs(candidate["entry_price"] - 4033.87) <= 0.35
    assert candidate["stop_loss"] > candidate["entry_price"]
    assert candidate["risk_distance"] <= 1.0
    quality = payload["risk"]["fast_trigger_quality"]
    assert quality["live_repriced"] is True
    assert quality["live_reprice_reason"] == "confirmed_reaction"
    assert quality["live_reference_close"] == 4033.89
    assert quality["live_quote"] == 4033.87
    assert quality["live_entry_drift"] == 0.02


def test_confirmed_reaction_rejects_live_quote_that_moved_from_confirmation():
    payload = _decision_at(
        "2026-07-01T21:44:00+00:00",
        current_bid_price=4032.50,
        current_spread_price=0.29,
    )
    candidate = next(
        item
        for item in payload["telemetry"]["candidate_evaluations"]
        if item["trigger"] == "HIGH_RESPECT_SELL"
    )

    assert candidate["approved"] is False
    assert "LIVE_ENTRY_MOVED_AWAY" in candidate["rejection_reasons"]


@pytest.mark.parametrize(
    ("timestamp", "expected_trigger"),
    [
        ("2026-07-01T21:03:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:17:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:34:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:44:00+00:00", "HIGH_RESPECT_SELL"),
        ("2026-07-01T21:50:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
    ],
)
def test_replay_approves_clean_current_opening(timestamp, expected_trigger):
    payload = _decision_at(timestamp)
    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == expected_trigger


def test_replay_selects_at_most_one_approved_candidate_per_candle():
    for bar in _bars()[60:]:
        payload = _decision_at(bar["timestamp"])
        approved = [
            candidate
            for candidate in payload["telemetry"]["candidate_evaluations"]
            if candidate["approved"]
        ]
        assert len(approved) <= 1


def test_late_impulse_remains_diagnostic_without_exhaustion_filter():
    timestamp = "2026-07-01T21:45:00+00:00"
    payload = _decision_at(timestamp)
    candidate = next(
        item
        for item in payload["telemetry"]["candidate_evaluations"]
        if item["trigger"] == "CLEAN_LOW_IMPULSE_SELL"
    )
    candle = next(item for item in _bars() if item["timestamp"] == timestamp)
    quality = candidate["signal_quality"]
    body_to_median_range = quality["body_to_recent_median_range"]
    distance_from_level = quality["entry_distance_from_level"]

    assert body_to_median_range > 0
    assert distance_from_level > 0
    assert 0 < candidate["risk_distance"] <= 1.0
    assert candidate["active_pulse"]["direction"] == "bearish"
    assert candidate["approved"] is True
    assert candidate["opening_context"]["confirmation_timestamp"] == candle["timestamp"]
