from pathlib import Path

import pytest

from tradingagents.agents.price_action.one_minute_entry_model import (
    HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS,
    analyze_one_minute_entry,
)


def _candle(index, open_, high, low, close):
    return {
        "timestamp": f"2026-06-10 09:{index:02d}:00",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": 1000,
    }


def _base_history(count=57):
    return [
        _candle(index, 100.0, 100.9, 99.8, 100.2)
        for index in range(count)
    ]


def _payload(candles, **config):
    return analyze_one_minute_entry(
        "XAUUSD",
        "2026-06-10 10:00",
        {"1m": candles},
        session_config=config or None,
    )


@pytest.mark.parametrize(
    ("trigger_name", "direction", "candles"),
    [
        (
            "LOW_RESPECT_BUY",
            "BUY",
            _base_history()
            + [
                _candle(57, 100.4, 100.8, 99.0, 99.7),
                _candle(58, 99.8, 100.4, 99.05, 99.4),
                _candle(59, 99.3, 100.9, 99.10, 100.7),
            ],
        ),
        (
            "HIGH_RESPECT_SELL",
            "SELL",
            _base_history()
            + [
                _candle(57, 99.8, 101.0, 99.4, 100.4),
                _candle(58, 100.2, 100.95, 99.9, 100.6),
                _candle(59, 100.7, 100.9, 99.2, 99.5),
            ],
        ),
        (
            "LOW_BREAK_SELL",
            "SELL",
            _base_history()
            + [
                _candle(57, 100.4, 100.8, 99.0, 99.6),
                _candle(58, 99.8, 100.2, 99.05, 99.4),
                _candle(59, 99.3, 99.5, 98.1, 98.3),
            ],
        ),
        (
            "HIGH_BREAK_BUY",
            "BUY",
            _base_history()
            + [
                _candle(57, 99.8, 101.0, 99.5, 100.3),
                _candle(58, 100.2, 100.95, 99.8, 100.5),
                _candle(59, 100.6, 102.1, 100.4, 101.8),
            ],
        ),
        (
            "FAILED_LOW_BREAK_BUY",
            "BUY",
            _base_history()
            + [
                _candle(57, 100.4, 100.8, 99.0, 99.6),
                _candle(58, 99.8, 100.2, 99.05, 99.4),
                _candle(59, 99.2, 100.7, 98.4, 100.4),
            ],
        ),
        (
            "FAILED_HIGH_BREAK_SELL",
            "SELL",
            _base_history()
            + [
                _candle(57, 99.8, 101.0, 99.5, 100.3),
                _candle(58, 100.2, 100.95, 99.8, 100.5),
                _candle(59, 100.7, 101.6, 99.3, 99.6),
            ],
        ),
    ],
)
def test_one_minute_model_emits_explicit_trigger_name_and_direction(
    trigger_name, direction, candles
):
    payload = _payload(candles)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == direction
    assert payload["setups"][0]["name"] == trigger_name
    assert payload["setups"][0]["direction"] == direction


@pytest.mark.parametrize(
    "trigger_name,candles",
    [
        (
            "LOW_RESPECT_BUY",
            _base_history()
            + [
                _candle(57, 100.4, 100.8, 99.0, 99.7),
                _candle(58, 99.8, 100.4, 99.05, 99.4),
                _candle(59, 99.3, 100.9, 99.10, 100.7),
            ],
        ),
        (
            "HIGH_RESPECT_SELL",
            _base_history()
            + [
                _candle(57, 99.8, 101.0, 99.4, 100.4),
                _candle(58, 100.2, 100.95, 99.9, 100.6),
                _candle(59, 100.7, 100.9, 99.2, 99.5),
            ],
        ),
        (
            "FAILED_LOW_BREAK_BUY",
            _base_history()
            + [
                _candle(57, 100.4, 100.8, 99.0, 99.6),
                _candle(58, 99.8, 100.2, 99.05, 99.4),
                _candle(59, 99.2, 100.7, 98.4, 100.4),
            ],
        ),
        (
            "FAILED_HIGH_BREAK_SELL",
            _base_history()
            + [
                _candle(57, 99.8, 101.0, 99.5, 100.3),
                _candle(58, 100.2, 100.95, 99.8, 100.5),
                _candle(59, 100.7, 101.6, 99.3, 99.6),
            ],
        ),
    ],
)
def test_high_confidence_reversal_and_fakeout_triggers_get_volume_multiplier(
    trigger_name, candles
):
    payload = _payload(candles)

    assert trigger_name in HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS
    assert payload["setups"][0]["name"] == trigger_name
    assert payload["risk"]["volume_multiplier"] == 1.5
    assert payload["risk"]["position_lifecycle"] == "FAST_PARTIAL_SCALE"


@pytest.mark.parametrize(
    "trigger_name,candles",
    [
        (
            "LOW_BREAK_SELL",
            _base_history()
            + [
                _candle(57, 100.4, 100.8, 99.0, 99.6),
                _candle(58, 99.8, 100.2, 99.05, 99.4),
                _candle(59, 99.3, 99.5, 98.1, 98.3),
            ],
        ),
        (
            "HIGH_BREAK_BUY",
            _base_history()
            + [
                _candle(57, 99.8, 101.0, 99.5, 100.3),
                _candle(58, 100.2, 100.95, 99.8, 100.5),
                _candle(59, 100.6, 102.1, 100.4, 101.8),
            ],
        ),
    ],
)
def test_raw_breaks_use_base_volume_without_multiplier(trigger_name, candles):
    payload = _payload(candles)

    assert payload["setups"][0]["name"] == trigger_name
    assert "volume_multiplier" not in payload["risk"]
    assert payload["risk"]["position_lifecycle"] == "FAST_PARTIAL_SCALE"


def test_one_minute_model_respects_configured_minimum_stop_distance():
    payload = _payload(
        _base_history()
        + [
            _candle(57, 99.8, 101.0, 99.4, 100.4),
            _candle(58, 100.2, 100.95, 99.9, 100.6),
            _candle(59, 100.7, 100.9, 99.2, 99.5),
        ],
        minimum_stop_distance_price=0.4,
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == "HIGH_RESPECT_SELL"
    assert payload["risk"]["risk_distance"] >= 0.4
    assert (
        payload["setups"][0]["stop_loss"] - payload["setups"][0]["entry_price"]
    ) == pytest.approx(0.4)


def test_unclear_one_minute_story_returns_hold():
    candles = _base_history(60)

    payload = _payload(candles)

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["market_context"]["one_minute_story"]["classification"] == "UNCLEAR"


def test_one_minute_model_uses_last_configured_history_window_only():
    candles = [
        _candle(0, 100.4, 100.8, 99.0, 99.7),
        _candle(1, 99.8, 100.4, 99.05, 99.4),
    ] + _base_history(60)

    payload = _payload(candles, fast_history_window_candles=60)

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["market_context"]["one_minute_story"]["history_candles"] == 60


def test_one_minute_entry_model_has_no_generic_detector_imports_or_names():
    source = Path(
        "tradingagents/agents/price_action/one_minute_entry_model.py"
    ).read_text(encoding="utf-8")

    forbidden = [
        "detect_breakouts",
        "detect_break_and_retest",
        "detect_sr_bounce",
        "Breakout",
        "Support/Resistance Bounce",
        "Aggressive Respect",
        "Confirmed Break",
    ]
    assert not any(term in source for term in forbidden)
