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


def _two_high_then_impulse_buy_history():
    return [
        _candle(0, 100.0, 100.6, 99.7, 100.3),
        _candle(1, 100.3, 101.0, 100.1, 100.8),
        _candle(2, 100.8, 101.95, 100.4, 101.7),
        _candle(3, 101.7, 101.8, 100.3, 100.6),
        _candle(4, 100.6, 101.9, 100.2, 101.5),
        _candle(5, 101.5, 101.6, 100.7, 100.9),
        _candle(6, 100.9, 102.55, 100.8, 102.45),
    ]


def _two_low_then_impulse_sell_history():
    return [
        _candle(0, 100.0, 100.3, 99.4, 99.7),
        _candle(1, 99.7, 100.1, 98.05, 98.4),
        _candle(2, 98.4, 99.4, 98.2, 99.1),
        _candle(3, 99.1, 99.5, 98.08, 98.7),
        _candle(4, 98.7, 99.2, 98.5, 99.0),
        _candle(5, 99.0, 99.1, 97.45, 97.55),
    ]


def _bullish_pressure_failed_high_sell_history():
    candles = []
    price = 100.0
    for index in range(55):
        open_ = price
        close = price + 0.08
        high = close + 0.12
        low = open_ - 0.08
        candles.append(_candle(index, open_, high, low, close))
        price = close
    candles.extend(
        [
            _candle(55, 104.35, 104.90, 104.10, 104.65),
            _candle(56, 104.62, 104.88, 104.30, 104.55),
            _candle(57, 104.50, 104.92, 104.20, 104.72),
            _candle(58, 104.70, 104.95, 104.45, 104.80),
            _candle(59, 104.85, 105.35, 104.30, 104.60),
        ]
    )
    return candles


def _neutral_pulse_high_impulse_buy_history():
    candles = []
    for index in range(50):
        base = 100.0 + (0.03 if index % 2 else 0.0)
        candles.append(_candle(index, base, base + 0.45, base - 0.35, base + 0.04))
    candles.extend(
        [
            _candle(50, 100.10, 100.65, 99.85, 100.25),
            _candle(51, 100.25, 100.75, 100.00, 100.10),
            _candle(52, 100.10, 100.70, 99.95, 100.30),
            _candle(53, 100.30, 100.78, 100.05, 100.15),
            _candle(54, 100.15, 100.72, 99.90, 100.20),
            _candle(55, 100.20, 101.00, 100.00, 100.80),
            _candle(56, 100.80, 100.92, 100.25, 100.35),
            _candle(57, 100.35, 100.98, 100.15, 100.75),
            _candle(58, 100.75, 100.88, 100.30, 100.45),
            _candle(59, 100.45, 101.35, 100.42, 101.30),
        ]
    )
    return candles


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


def test_one_minute_scalper_journals_high_zone_memory_and_latest_relation():
    payload = _payload(
        _two_high_then_impulse_buy_history(),
        fast_history_window_candles=7,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=102.48,
        current_ask_price=102.68,
    )

    story = payload["market_context"]["one_minute_story"]

    assert story["latest_candle_relation"]["higher_high"] is True
    assert story["latest_candle_relation"]["higher_low"] is True
    assert story["latest_candle_relation"]["broke_high_zone"] is True
    assert story["latest_candle_relation"]["broke_low_zone"] is False
    high_openings = [
        item for item in story["active_openings"] if item["side"] == "high"
    ]
    assert high_openings
    assert high_openings[0]["touch_count"] >= 2
    assert high_openings[0]["state"] == "broken_up"


def test_one_minute_scalper_journals_low_zone_memory_and_latest_relation():
    payload = _payload(
        _two_low_then_impulse_sell_history(),
        fast_history_window_candles=6,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=97.35,
        current_ask_price=97.55,
    )

    story = payload["market_context"]["one_minute_story"]

    assert story["latest_candle_relation"]["lower_low"] is True
    assert story["latest_candle_relation"]["lower_high"] is True
    assert story["latest_candle_relation"]["broke_low_zone"] is True
    assert story["latest_candle_relation"]["broke_high_zone"] is False
    low_openings = [
        item for item in story["active_openings"] if item["side"] == "low"
    ]
    assert low_openings
    assert low_openings[0]["touch_count"] >= 2
    assert low_openings[0]["state"] == "broken_down"


def test_one_minute_scalper_allows_clean_high_impulse_buy_from_remembered_two_highs():
    payload = _payload(
        _two_high_then_impulse_buy_history(),
        fast_history_window_candles=7,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=102.48,
        current_ask_price=102.68,
    )

    candidate = payload["telemetry"]["selected_candidate"]

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "CLEAN_HIGH_IMPULSE_BUY"
    assert candidate["trigger"] == "CLEAN_HIGH_IMPULSE_BUY"
    assert candidate["reaction_type"] == "impulse_break"
    assert "CLEAN_IMPULSE_BREAK" in candidate["score_reasons"]
    assert "RAW_BREAK_EXECUTION_DISABLED" not in candidate["rejection_reasons"]
    assert payload["risk"]["early_loss_exit_points"] > 0
    assert payload["risk"]["scalp_profit_points"] > 0
    assert payload["risk"]["min_stop_update_points"] > 0


def test_one_minute_scalper_allows_clean_low_impulse_sell_from_remembered_two_lows():
    payload = _payload(
        _two_low_then_impulse_sell_history(),
        fast_history_window_candles=6,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=97.35,
        current_ask_price=97.55,
    )

    candidate = payload["telemetry"]["selected_candidate"]

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "CLEAN_LOW_IMPULSE_SELL"
    assert candidate["trigger"] == "CLEAN_LOW_IMPULSE_SELL"
    assert candidate["reaction_type"] == "impulse_break"
    assert "CLEAN_IMPULSE_BREAK" in candidate["score_reasons"]
    assert "RAW_BREAK_EXECUTION_DISABLED" not in candidate["rejection_reasons"]


def test_one_minute_scalper_rejects_sell_against_bullish_sixty_candle_pressure():
    payload = _payload(
        _bullish_pressure_failed_high_sell_history(),
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=104.55,
        current_ask_price=104.75,
    )

    story = payload["market_context"]["one_minute_story"]
    assert story["pressure"]["direction"] == "bullish"
    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    candidate = _candidate_by_trigger(payload, "FAILED_HIGH_BREAK_SELL")
    assert candidate["approved"] is False
    assert "ONE_MINUTE_PRESSURE_CONFLICT" in candidate["rejection_reasons"]
    assert payload["telemetry"]["approved_candidate_count"] == 0


def test_one_minute_scalper_rejects_two_sided_fakeout_memory():
    candles = [
        _candle(0, 102.65, 103.05, 102.82, 102.90),
        _candle(1, 102.90, 103.08, 102.86, 102.96),
        _candle(2, 102.96, 103.02, 102.83, 102.92),
        _candle(3, 103.10, 103.35, 102.75, 102.95),
    ]

    payload = _payload(
        candles,
        fast_history_window_candles=4,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=102.96,
        current_ask_price=103.16,
    )

    relation = payload["market_context"]["one_minute_story"]["latest_candle_relation"]
    assert relation["failed_high_break"] is True
    assert relation["failed_low_break"] is True
    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    candidate = _candidate_by_trigger(payload, "FAILED_HIGH_BREAK_SELL")
    assert candidate["approved"] is False
    assert "CONFLICTED_ONE_MINUTE_MEMORY" in candidate["rejection_reasons"]
    assert "MEMORY_CONFLICT_OVERRIDDEN_BY_STRONG_REVERSAL" not in candidate[
        "score_reasons"
    ]


def test_one_minute_scalper_rejects_default_stop_above_scalp_cap():
    candles = [
        _candle(0, 99.0, 100.0, 97.0, 99.5),
        _candle(1, 99.5, 100.2, 97.2, 99.8),
        _candle(2, 99.8, 100.1, 97.1, 99.2),
        _candle(3, 99.2, 101.6, 99.1, 101.45),
    ]

    payload = _payload(
        candles,
        fast_history_window_candles=4,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
    )

    assert payload["status"] == "NO_SETUP"
    candidate = _candidate_by_trigger(payload, "CLEAN_HIGH_IMPULSE_BUY")
    assert candidate["approved"] is False
    assert any(
        reason.startswith("Stop distance exceeds one-minute maximum")
        for reason in candidate["rejection_reasons"]
    )


def test_one_minute_scalper_rejects_two_touch_fakeout_with_rejection_only():
    candles = [
        _candle(57, 99.8, 101.00, 99.5, 100.3),
        _candle(58, 100.6, 100.95, 99.8, 100.4),
        _candle(59, 100.8, 101.60, 99.3, 100.0),
    ]

    payload = _payload(
        candles,
        fast_history_window_candles=3,
        minimum_stop_distance_price=0.25,
    )

    assert payload["status"] == "NO_SETUP"
    candidate = _candidate_by_trigger(payload, "FAILED_HIGH_BREAK_SELL")
    assert candidate["level_type"] == "two_touch"
    assert candidate["confirmation_type"] == "rejection"
    assert candidate["approved"] is False
    assert "LOW_ONE_MINUTE_SCORE" in candidate["rejection_reasons"]
    assert "RELAXED_FAKEOUT_SCORE_FLOOR" not in candidate["score_reasons"]


def test_one_minute_scalper_clamps_activation_window_to_one_minute():
    payload = _payload(
        _two_high_then_impulse_buy_history(),
        fast_history_window_candles=7,
        fast_activation_window_minutes=6,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=102.48,
        current_ask_price=102.68,
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["activation_window_minutes"] == 1
    assert payload["market_context"]["activation_window_minutes"] == 1


def test_one_minute_scalper_rejects_impulse_without_active_recent_pulse():
    payload = _payload(
        _neutral_pulse_high_impulse_buy_history(),
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=101.25,
        current_ask_price=101.45,
    )

    story = payload["market_context"]["one_minute_story"]
    assert story["active_pulse"]["direction"] == "neutral"
    assert payload["status"] == "NO_SETUP"
    candidate = _candidate_by_trigger(payload, "CLEAN_HIGH_IMPULSE_BUY")
    assert candidate["approved"] is False
    assert "ONE_MINUTE_ACTIVE_PULSE_NOT_ALIGNED" in candidate["rejection_reasons"]


def test_one_minute_scalper_reprices_favorable_impulse_sell_to_continuation_stop():
    payload = _payload(
        _two_low_then_impulse_sell_history(),
        fast_history_window_candles=6,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=97.35,
        current_ask_price=97.55,
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "CLEAN_LOW_IMPULSE_SELL"
    assert payload["risk"]["entry_price"] < 97.35
    assert payload["risk"]["fast_trigger_quality"]["live_repriced"] is True
    assert (
        payload["risk"]["fast_trigger_quality"]["live_reprice_reason"]
        == "favorable_impulse_continuation"
    )


def test_one_minute_scalper_still_rejects_messy_raw_break_without_clean_impulse():
    candles = _base_history() + [
        _candle(57, 99.8, 101.0, 99.5, 100.3),
        _candle(58, 100.2, 100.95, 99.8, 100.5),
        _candle(59, 100.6, 103.8, 100.4, 101.1),
    ]

    payload = _payload(
        candles,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=101.0,
        current_ask_price=101.2,
    )

    assert payload["status"] == "NO_SETUP"
    candidate = _candidate_by_trigger(payload, "HIGH_BREAK_BUY")
    assert "RAW_BREAK_EXECUTION_DISABLED" in candidate["rejection_reasons"]


def test_one_minute_scalper_rejects_clean_impulse_when_live_quote_moved_too_far():
    payload = _payload(
        _two_high_then_impulse_buy_history(),
        fast_history_window_candles=7,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=104.20,
        current_ask_price=104.40,
    )

    assert payload["status"] == "NO_SETUP"
    candidate = _candidate_by_trigger(payload, "CLEAN_HIGH_IMPULSE_BUY")
    assert "IMPULSE_ENTRY_MOVED_AWAY" in candidate["rejection_reasons"]


def test_one_minute_scalper_reprices_clean_impulse_when_quote_still_tight():
    payload = _payload(
        _two_high_then_impulse_buy_history(),
        fast_history_window_candles=7,
        fast_max_stop_distance_price=1.7,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=103.05,
        current_ask_price=103.25,
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "CLEAN_HIGH_IMPULSE_BUY"
    assert payload["risk"]["entry_price"] > 102.45
    assert payload["risk"]["entry_price"] == pytest.approx(103.30)
    assert payload["risk"]["risk_distance"] <= 1.7
    candidate = _candidate_by_trigger(payload, "CLEAN_HIGH_IMPULSE_BUY")
    assert candidate["approved"] is True
    assert "IMPULSE_ENTRY_MOVED_AWAY" not in candidate["rejection_reasons"]
    assert payload["risk"]["fast_trigger_quality"]["live_repriced"] is True


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
                _candle(59, 100.7, 100.9, 99.75, 100.05),
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
                _candle(59, 100.7, 101.6, 99.75, 100.0),
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
                _candle(59, 100.7, 100.9, 99.75, 100.05),
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
                _candle(59, 100.7, 101.6, 99.75, 100.0),
            ],
        ),
    ],
)
def test_high_confidence_reversal_and_fakeout_triggers_use_base_volume(
    trigger_name, candles
):
    payload = _payload(candles)

    assert trigger_name in HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS
    assert payload["setups"][0]["name"] == trigger_name
    assert "volume_multiplier" not in payload["risk"]
    assert payload["telemetry"]["selected_candidate"]["volume_decision"] == "BASE_1_0"
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
def test_raw_breaks_are_rejected_when_entry_is_extended(trigger_name, candles):
    payload = _payload(candles)

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    candidate = _candidate_by_trigger(payload, trigger_name)
    assert "BREAK_ENTRY_TOO_EXTENDED" in candidate["rejection_reasons"]
    assert candidate["volume_decision"] == "REJECTED"


def test_one_minute_scalper_rejects_late_raw_break_entries():
    candles = _base_history() + [
        _candle(57, 99.8, 101.0, 99.5, 100.3),
        _candle(58, 100.2, 100.95, 99.8, 100.5),
        _candle(59, 100.6, 102.1, 100.4, 101.8),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    candidate = _candidate_by_trigger(payload, "HIGH_BREAK_BUY")
    assert "BREAK_ENTRY_TOO_EXTENDED" in candidate["rejection_reasons"]
    assert candidate["volume_decision"] == "REJECTED"


def test_one_minute_scalper_allows_tight_decisive_break_as_clean_impulse():
    candles = [
        _candle(0, 100.0, 100.95, 99.7, 100.2),
        _candle(1, 100.2, 100.90, 99.9, 100.1),
        _candle(2, 100.1, 100.92, 99.8, 100.3),
        _candle(3, 100.3, 101.18, 100.2, 101.12),
    ]

    payload = _payload(
        candles,
        fast_history_window_candles=4,
        minimum_stop_distance_price=0.25,
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "CLEAN_HIGH_IMPULSE_BUY"
    candidate = _candidate_by_trigger(payload, "CLEAN_HIGH_IMPULSE_BUY")
    assert candidate["level_type"] == "three_touch"
    assert "BREAK_ENTRY_TIGHT" in candidate["score_reasons"]
    assert "DECISIVE_CLOSE" in candidate["score_reasons"]
    assert "RAW_BREAK_EXECUTION_DISABLED" not in candidate["rejection_reasons"]
    assert candidate["volume_decision"] == "BASE_1_0"


def test_one_minute_model_respects_configured_minimum_stop_distance():
    payload = _payload(
        _base_history()
        + [
            _candle(57, 99.8, 101.0, 99.4, 100.4),
            _candle(58, 100.2, 100.95, 99.9, 100.6),
            _candle(59, 100.7, 100.9, 99.75, 100.05),
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
        _candle(8, 99.6, 100.5, 98.7, 100.4),
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


def test_one_minute_scalper_allows_clean_two_touch_respect_setup_below_global_score_floor():
    candles = _base_history() + [
        _candle(57, 100.4, 100.8, 99.0, 99.7),
        _candle(58, 99.8, 100.4, 99.05, 99.4),
        _candle(59, 99.3, 100.6, 99.10, 100.2),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"
    candidate = payload["telemetry"]["selected_candidate"]
    assert candidate["trigger"] == "LOW_RESPECT_BUY"
    assert candidate["level_type"] == "two_touch"
    assert candidate["confirmation_type"] in {"engulfing", "rejection"}
    assert "LOW_ONE_MINUTE_SCORE" not in candidate["rejection_reasons"]
    assert "RELAXED_RESPECT_SCORE_FLOOR" in candidate["score_reasons"]
    assert candidate["volume_decision"] == "BASE_1_0"


def test_one_minute_scalper_keeps_strict_high_confidence_candidate_at_base_volume():
    candles = _base_history() + [
        _candle(56, 100.4, 100.8, 99.0, 99.7),
        _candle(57, 99.8, 100.3, 99.05, 99.4),
        _candle(58, 99.5, 100.2, 99.02, 99.3),
        _candle(59, 99.2, 100.25, 98.45, 100.15),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == "FAILED_LOW_BREAK_BUY"
    assert payload["market_context"]["one_minute_story"]["touch_count"] >= 3
    assert "volume_multiplier" not in payload["risk"]
    assert payload["telemetry"]["selected_candidate"]["volume_decision"] == "BASE_1_0"


def test_one_minute_scalper_does_not_boost_without_decisive_close():
    candles = _base_history() + [
        _candle(56, 99.8, 101.0, 99.5, 100.3),
        _candle(57, 100.2, 100.95, 99.8, 100.5),
        _candle(58, 100.4, 101.05, 99.9, 100.8),
        _candle(59, 100.8, 101.6, 99.75, 100.0),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == "FAILED_HIGH_BREAK_SELL"
    assert "DECISIVE_CLOSE" not in payload["telemetry"]["selected_candidate"][
        "score_reasons"
    ]
    assert "volume_multiplier" not in payload["risk"]
    assert payload["telemetry"]["selected_candidate"]["volume_decision"] == "BASE_1_0"


def test_one_minute_scalper_allows_clean_two_touch_fakeout_engulfing_confirmation():
    candles = [
        _candle(57, 99.8, 101.0, 99.5, 100.3),
        _candle(58, 100.2, 100.95, 99.8, 100.5),
        _candle(59, 100.7, 101.6, 99.75, 100.1),
    ]

    payload = _payload(
        candles,
        fast_history_window_candles=3,
        minimum_stop_distance_price=0.25,
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "FAILED_HIGH_BREAK_SELL"
    candidate = payload["telemetry"]["selected_candidate"]
    assert candidate["confirmation_type"] == "engulfing"
    assert candidate["level_type"] == "two_touch"
    assert "DECISIVE_CLOSE" not in candidate["score_reasons"]
    assert "LOW_ONE_MINUTE_SCORE" not in candidate["rejection_reasons"]
    assert "RELAXED_FAKEOUT_SCORE_FLOOR" in candidate["score_reasons"]
    assert candidate["volume_decision"] == "BASE_1_0"


def test_one_minute_scalper_adjusts_respect_fakeout_stop_to_clear_live_spread():
    candles = _base_history() + [
        _candle(57, 100.4, 100.8, 99.0, 99.7),
        _candle(58, 99.8, 100.3, 99.05, 99.4),
        _candle(59, 99.2, 100.55, 98.45, 100.2),
    ]

    payload = _payload(
        candles,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.29,
        minimum_stop_spread_multiple=2.0,
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "FAILED_LOW_BREAK_BUY"
    assert payload["risk"]["risk_distance"] > 0.58
    assert payload["risk"]["risk_distance"] <= 1.2
    assert payload["risk"]["fast_trigger_quality"]["spread_safe_stop_adjusted"] is True
    assert "STOP_TOO_CLOSE_TO_SPREAD" not in payload["telemetry"]["selected_candidate"][
        "rejection_reasons"
    ]


def test_one_minute_scalper_rejects_respect_fakeout_when_spread_safe_stop_is_too_wide():
    candles = _base_history() + [
        _candle(57, 100.4, 100.8, 99.0, 99.7),
        _candle(58, 99.8, 100.3, 99.05, 99.4),
        _candle(59, 99.2, 101.0, 98.45, 100.8),
    ]

    payload = _payload(
        candles,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.75,
        minimum_stop_spread_multiple=2.0,
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    candidate = _candidate_by_trigger(payload, "FAILED_LOW_BREAK_BUY")
    assert candidate["confirmation_type"] in {"engulfing", "rejection"}
    assert "SPREAD_SAFE_STOP_TOO_WIDE" in candidate["rejection_reasons"]


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


def test_one_minute_scalper_rejects_conflicted_two_sided_memory():
    candles = [
        _candle(0, 99.6, 100.15, 99.4, 99.9),
        _candle(1, 99.8, 100.20, 99.5, 100.0),
        _candle(2, 102.4, 103.1, 102.15, 102.8),
        _candle(3, 102.7, 103.0, 102.20, 102.5),
        _candle(4, 102.5, 102.8, 101.2, 101.5),
    ]

    payload = _payload(
        candles,
        fast_history_window_candles=5,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=101.45,
        current_ask_price=101.65,
    )

    relation = payload["market_context"]["one_minute_story"]["latest_candle_relation"]
    assert relation["broke_high_zone"] is True
    assert relation["broke_low_zone"] is True
    assert payload["status"] == "NO_SETUP"
    assert payload["telemetry"]["approved_candidate_count"] == 0
    assert any(
        "CONFLICTED_ONE_MINUTE_MEMORY" in item["rejection_reasons"]
        for item in payload["telemetry"]["candidate_evaluations"]
    )


def test_one_minute_scalper_allows_strong_reversal_when_memory_is_conflicted():
    candles = [
        _candle(0, 99.6, 100.15, 99.4, 99.9),
        _candle(1, 99.8, 100.20, 99.5, 100.0),
        _candle(2, 102.4, 103.1, 102.15, 102.8),
        _candle(3, 102.7, 103.0, 102.20, 102.5),
        _candle(4, 102.65, 102.85, 101.65, 101.75),
    ]

    payload = _payload(
        candles,
        fast_history_window_candles=5,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=101.72,
        current_ask_price=101.92,
    )

    relation = payload["market_context"]["one_minute_story"]["latest_candle_relation"]
    assert relation["broke_high_zone"] is True
    assert relation["broke_low_zone"] is True
    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "CLEAN_LOW_IMPULSE_SELL"
    candidate = _candidate_by_trigger(payload, "CLEAN_LOW_IMPULSE_SELL")
    assert candidate["approved"] is True
    assert "CONFLICTED_ONE_MINUTE_MEMORY" not in candidate["rejection_reasons"]
    assert "MEMORY_CONFLICT_OVERRIDDEN_BY_STRONG_REVERSAL" in candidate["score_reasons"]


def test_one_minute_scalper_rejects_high_respect_sell_into_bullish_pressure():
    candles = _base_history() + [
        _candle(57, 99.8, 101.00, 99.4, 100.4),
        _candle(58, 100.2, 100.92, 99.9, 100.6),
        _candle(59, 100.9, 100.94, 100.2, 100.35),
    ]

    payload = _payload(
        candles,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=100.30,
        current_ask_price=100.50,
    )

    relation = payload["market_context"]["one_minute_story"]["latest_candle_relation"]
    assert relation["higher_high"] is True
    assert relation["higher_low"] is True
    assert payload["status"] == "NO_SETUP"
    candidate = _candidate_by_trigger(payload, "HIGH_RESPECT_SELL")
    assert "RESPECT_ENTRY_CONFLICTS_WITH_LATEST_RELATION" in candidate[
        "rejection_reasons"
    ]


def test_one_minute_scalper_allows_low_respect_buy_when_rejection_confirms():
    candles = _base_history() + [
        _candle(57, 100.4, 100.8, 99.00, 99.7),
        _candle(58, 99.8, 100.4, 99.05, 99.4),
        _candle(59, 99.2, 100.1, 99.03, 99.75),
    ]

    payload = _payload(
        candles,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=98.85,
        current_ask_price=99.05,
    )

    relation = payload["market_context"]["one_minute_story"]["latest_candle_relation"]
    assert relation["lower_high"] is True
    assert relation["lower_low"] is True
    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    candidate = _candidate_by_trigger(payload, "LOW_RESPECT_BUY")
    assert candidate["approved"] is True
    assert "RESPECT_ENTRY_CONFLICTS_WITH_LATEST_RELATION" not in candidate[
        "rejection_reasons"
    ]
