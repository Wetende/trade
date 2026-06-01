from tradingagents.agents.price_action.models import Candle, Zone
from tradingagents.agents.price_action.structure import (
    classify_timeframe_structure,
    determine_m30_bias,
    evaluate_higher_timeframe_permission,
)


def _c(ts, open_, high, low, close):
    return Candle(timestamp=ts, open=open_, high=high, low=low, close=close, volume=100)


def _zone(kind, low, high, score=20):
    return Zone(
        type=kind,
        timeframe="4h",
        low=low,
        high=high,
        midpoint=(low + high) / 2,
        touches=3,
        score=score,
        source="test",
        reactions=[],
    )


def test_higher_timeframe_context_records_opposing_daily_without_blocking():
    result = evaluate_higher_timeframe_permission(
        daily="SELL_ALLOWED",
        h4="BUY_ALLOWED",
        h1="BUY_ALLOWED",
        planned_direction="BUY",
    )

    assert result["permission"] == "CONTEXT_ONLY"
    assert result["planned_direction"] == "BUY"
    assert result["daily_permission"] == "SELL_ALLOWED"


def test_higher_timeframe_context_records_neutral_h4_and_aligned_h1():
    result = evaluate_higher_timeframe_permission(
        daily="NEUTRAL",
        h4="NEUTRAL",
        h1="BUY_ALLOWED",
        planned_direction="BUY",
    )

    assert result["permission"] == "CONTEXT_ONLY"
    assert result["h4_permission"] == "NEUTRAL"
    assert result["h1_permission"] == "BUY_ALLOWED"


def test_higher_timeframe_context_records_unclear_1h_without_blocking():
    result = evaluate_higher_timeframe_permission(
        daily="NEUTRAL",
        h4="NEUTRAL",
        h1="NEUTRAL",
        planned_direction="BUY",
    )

    assert result["permission"] == "CONTEXT_ONLY"
    assert result["h1_permission"] == "NEUTRAL"


def test_higher_timeframe_context_records_sell_plan():
    result = evaluate_higher_timeframe_permission(
        daily="SELL_ALLOWED",
        h4="NEUTRAL",
        h1="SELL_ALLOWED",
        planned_direction="SELL",
    )

    assert result["permission"] == "CONTEXT_ONLY"
    assert result["planned_direction"] == "SELL"


def test_higher_timeframe_context_records_opposing_h4_without_blocking():
    result = evaluate_higher_timeframe_permission(
        daily="NEUTRAL",
        h4="BUY_ALLOWED",
        h1="SELL_ALLOWED",
        planned_direction="SELL",
    )

    assert result["permission"] == "CONTEXT_ONLY"
    assert result["h4_permission"] == "BUY_ALLOWED"


def test_permission_normalizes_lowercase_and_whitespace():
    result = evaluate_higher_timeframe_permission(
        daily=" neutral ",
        h4=" neutral ",
        h1=" buy_allowed ",
        planned_direction=" buy ",
    )

    assert result["permission"] == "CONTEXT_ONLY"
    assert result["planned_direction"] == "BUY"
    assert result["h1_permission"] == "BUY_ALLOWED"


def test_m30_bias_comes_from_breakout_direction():
    result = determine_m30_bias([{"direction": "BUY", "name": "Breakout"}])

    assert result["m30_bias"] == "BULLISH"
    assert result["m30_context"] == "BREAKOUT"


def test_m30_bias_comes_from_sell_breakout_direction():
    result = determine_m30_bias([{"direction": "SELL", "name": "Breakout"}])

    assert result["m30_bias"] == "BEARISH"
    assert result["m30_context"] == "BREAKOUT"


def test_m30_bias_is_unclear_for_empty_breakouts():
    result = determine_m30_bias([])

    assert result == {"m30_bias": "UNCLEAR", "m30_context": "UNCLEAR"}


def test_m30_bias_is_unclear_for_missing_direction():
    result = determine_m30_bias([{"name": "Breakout"}])

    assert result["m30_bias"] == "UNCLEAR"
    assert result["m30_context"] == "UNCLEAR"
    assert result["m30_breakout"] == {"name": "Breakout"}


def test_m30_bias_is_unclear_for_invalid_direction():
    result = determine_m30_bias([{"direction": "SIDEWAYS", "name": "Breakout"}])

    assert result["m30_bias"] == "UNCLEAR"
    assert result["m30_context"] == "UNCLEAR"
    assert result["m30_breakout"] == {"direction": "SIDEWAYS", "name": "Breakout"}


def test_m30_bias_is_unclear_for_non_dict_first_entry():
    result = determine_m30_bias(["bad"])

    assert result == {"m30_bias": "UNCLEAR", "m30_context": "UNCLEAR"}


def test_classify_timeframe_structure_detects_bullish_higher_highs_and_lows():
    candles = [
        _c("1", 100, 105, 99, 104),
        _c("2", 104, 106, 101, 102),
        _c("3", 102, 110, 101, 109),
        _c("4", 109, 111, 104, 105),
        _c("5", 105, 114, 105, 113),
    ]

    result = classify_timeframe_structure(candles, [], "4h")

    assert result["classification"] == "BULLISH_STRUCTURE"
    assert result["permission"] == "BUY_ALLOWED"


def test_classify_timeframe_structure_detects_bearish_structure():
    candles = [
        _c("1", 120, 121, 115, 116),
        _c("2", 116, 118, 112, 117),
        _c("3", 117, 118, 109, 110),
        _c("4", 110, 113, 106, 112),
        _c("5", 112, 113, 101, 102),
    ]

    result = classify_timeframe_structure(candles, [], "4h")

    assert result["classification"] == "BEARISH_STRUCTURE"
    assert result["permission"] == "SELL_ALLOWED"


def test_classify_timeframe_structure_uses_three_candle_momentum_when_clean():
    candles = [
        _c("1", 100, 105, 99, 104),
        _c("2", 104, 108, 103, 107),
        _c("3", 107, 112, 105, 111),
    ]

    result = classify_timeframe_structure(candles, [], "1h")

    assert result["classification"] == "BULLISH_STRUCTURE"
    assert result["permission"] == "BUY_ALLOWED"


def test_classify_timeframe_structure_marks_near_major_support_as_neutral_buy_context():
    candles = [
        _c("1", 105, 108, 101, 106),
        _c("2", 106, 109, 100, 102),
        _c("3", 102, 107, 99.5, 106),
    ]
    zones = [_zone("support", 99, 101)]

    result = classify_timeframe_structure(candles, zones, "4h")

    assert result["classification"] == "NEAR_MAJOR_SUPPORT"
    assert result["permission"] == "NEUTRAL"


def test_higher_timeframe_context_allows_buy_when_4h_neutral_and_1h_agrees():
    daily = {"permission": "NEUTRAL", "classification": "RANGE", "reason": "Daily neutral"}
    h4 = {"permission": "NEUTRAL", "classification": "NEAR_MAJOR_SUPPORT", "reason": "4H support"}
    h1 = {"permission": "BUY_ALLOWED", "classification": "BULLISH_STRUCTURE", "reason": "1H bullish"}

    result = evaluate_higher_timeframe_permission(daily, h4, h1, "BUY")

    assert result["permission"] == "CONTEXT_ONLY"
    assert result["daily_classification"] == "RANGE"
    assert result["h4_classification"] == "NEAR_MAJOR_SUPPORT"


def test_higher_timeframe_context_records_bearish_4h_without_blocking():
    daily = {"permission": "NEUTRAL", "classification": "RANGE", "reason": "Daily neutral"}
    h4 = {"permission": "SELL_ALLOWED", "classification": "BEARISH_STRUCTURE", "reason": "4H bearish"}
    h1 = {"permission": "BUY_ALLOWED", "classification": "BULLISH_STRUCTURE", "reason": "1H bullish"}

    result = evaluate_higher_timeframe_permission(daily, h4, h1, "BUY")

    assert result["permission"] == "CONTEXT_ONLY"
    assert result["h4_permission"] == "SELL_ALLOWED"
    assert result["h4_classification"] == "BEARISH_STRUCTURE"


def test_higher_timeframe_context_records_unclear_1h():
    daily = {"permission": "NEUTRAL", "classification": "RANGE", "reason": "Daily neutral"}
    h4 = {"permission": "NEUTRAL", "classification": "RANGE", "reason": "4H neutral"}
    h1 = {"permission": "NEUTRAL", "classification": "UNCLEAR", "reason": "1H unclear"}

    result = evaluate_higher_timeframe_permission(daily, h4, h1, "SELL")

    assert result["permission"] == "CONTEXT_ONLY"
    assert result["h1_classification"] == "UNCLEAR"
