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


def _candidate_by_trigger(payload, trigger_name):
    candidates = payload["telemetry"]["candidate_evaluations"]
    matches = [item for item in candidates if item["trigger"] == trigger_name]
    assert matches, f"Missing candidate {trigger_name}: {candidates}"
    return matches[0]


def _assert_candidate_journal_shape(candidate):
    assert candidate["model_name"] == "One Minute Scalper"
    assert candidate["trigger"]
    assert candidate["direction"] in {"BUY", "SELL"}
    assert candidate["reaction_type"] in {"respect", "break", "fakeout"}
    assert candidate["confirmation_type"] in {
        "rejection",
        "engulfing",
        "strong_close",
        "mixed",
    }
    assert candidate["level_type"] in {"two_touch", "three_touch"}
    assert candidate["touch_count"] >= 2
    assert isinstance(candidate["score"], (int, float))
    assert isinstance(candidate["score_reasons"], list)
    assert isinstance(candidate["rejection_reasons"], list)
    assert candidate["volume_decision"] in {"BASE_1_0", "BOOST_1_5", "REJECTED"}


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
    assert payload["risk"]["risk_distance"] > 0.4
    assert (
        payload["setups"][0]["stop_loss"] - payload["setups"][0]["entry_price"]
    ) == pytest.approx(0.45)


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


def test_one_minute_scalper_journals_multiple_candidates_and_selects_best_valid_opening():
    candles = [
        _candle(0, 100.0, 100.8, 99.7, 100.1),
        _candle(1, 100.1, 101.0, 99.8, 100.8),
        _candle(2, 100.8, 101.1, 100.1, 100.3),
        _candle(3, 100.3, 101.05, 100.0, 100.6),
        _candle(4, 100.6, 101.0, 99.8, 100.4),
        _candle(5, 100.4, 100.9, 99.2, 99.8),
        _candle(6, 99.8, 100.5, 99.15, 100.0),
        _candle(7, 100.0, 100.4, 99.1, 99.6),
        _candle(8, 99.6, 100.7, 98.7, 100.4),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert (
        payload["market_context"]["one_minute_story"]["model_name"]
        == "One Minute Scalper"
    )
    assert payload["setups"][0]["name"] == "FAILED_LOW_BREAK_BUY"
    assert payload["telemetry"]["candidate_setup_count"] >= 2
    assert payload["telemetry"]["approved_candidate_count"] >= 1
    assert payload["telemetry"]["selected_candidate"]["trigger"] == "FAILED_LOW_BREAK_BUY"
    for candidate in payload["telemetry"]["candidate_evaluations"]:
        _assert_candidate_journal_shape(candidate)


def test_one_minute_scalper_rejects_overlapping_chop_candidates():
    candles = [
        _candle(
            index,
            100.0 if index % 2 == 0 else 100.15,
            100.45,
            99.85,
            100.15 if index % 2 == 0 else 100.0,
        )
        for index in range(60)
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["telemetry"]["decision_stage"] == "one_minute_no_approved_candidate"
    assert payload["telemetry"]["candidate_setup_count"] >= 1
    assert any(
        "OVERLAPPING_CHOP" in item["rejection_reasons"]
        for item in payload["telemetry"]["candidate_evaluations"]
    )


def test_one_minute_scalper_uses_base_volume_for_medium_two_touch_setup():
    candles = _base_history() + [
        _candle(57, 100.4, 100.8, 99.0, 99.7),
        _candle(58, 99.8, 100.4, 99.05, 99.4),
        _candle(59, 99.3, 100.6, 99.10, 100.2),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"
    assert "volume_multiplier" not in payload["risk"]
    assert payload["telemetry"]["selected_candidate"]["volume_decision"] == "BASE_1_0"


def test_one_minute_scalper_allows_boost_only_for_strict_high_confidence_candidate():
    candles = _base_history() + [
        _candle(56, 100.4, 100.8, 99.0, 99.7),
        _candle(57, 99.8, 100.3, 99.05, 99.4),
        _candle(58, 99.5, 100.2, 99.02, 99.3),
        _candle(59, 99.2, 101.0, 98.45, 100.8),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == "FAILED_LOW_BREAK_BUY"
    assert payload["market_context"]["one_minute_story"]["touch_count"] >= 3
    assert payload["risk"]["volume_multiplier"] == 1.5
    assert payload["telemetry"]["selected_candidate"]["volume_decision"] == "BOOST_1_5"


def test_one_minute_scalper_does_not_boost_without_decisive_close():
    candles = _base_history() + [
        _candle(56, 99.8, 101.0, 99.5, 100.3),
        _candle(57, 100.2, 100.95, 99.8, 100.5),
        _candle(58, 100.4, 101.05, 99.9, 100.8),
        _candle(59, 100.8, 101.6, 99.3, 100.0),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == "FAILED_HIGH_BREAK_SELL"
    assert "DECISIVE_CLOSE" not in payload["telemetry"]["selected_candidate"][
        "score_reasons"
    ]
    assert "volume_multiplier" not in payload["risk"]
    assert payload["telemetry"]["selected_candidate"]["volume_decision"] == "BASE_1_0"


def test_one_minute_scalper_only_executes_when_latest_closed_candle_confirms_candidate():
    candles = _base_history() + [
        _candle(57, 99.8, 101.0, 99.4, 100.4),
        _candle(58, 100.2, 100.95, 99.9, 100.6),
        _candle(59, 100.5, 101.05, 99.9, 100.55),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["telemetry"]["candidate_setup_count"] >= 1
    assert payload["telemetry"]["approved_candidate_count"] == 0
    assert all(
        "LATEST_CANDLE_NOT_CONFIRMING" in item["rejection_reasons"]
        or "MIXED_CONFIRMATION" in item["rejection_reasons"]
        for item in payload["telemetry"]["candidate_evaluations"]
    )
