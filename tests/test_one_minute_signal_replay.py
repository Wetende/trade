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


def _decision_at(timestamp: str):
    bars = _bars()
    index = next(
        index for index, bar in enumerate(bars) if bar["timestamp"] == timestamp
    )
    current = bars[index]
    spread = max(0.01, float(current["spread"]) * 0.01)
    config = {
        **DEFAULT_CONFIG["price_action"],
        "current_spread_price": spread,
        "current_bid_price": float(current["close"]),
        "current_ask_price": float(current["close"]) + spread,
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
