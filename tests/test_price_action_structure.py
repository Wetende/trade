from tradingagents.agents.price_action.structure import (
    determine_m30_bias,
    evaluate_higher_timeframe_permission,
)


def test_daily_block_rejects_trade():
    result = evaluate_higher_timeframe_permission(
        daily="SELL_ALLOWED",
        h4="BUY_ALLOWED",
        h1="BUY_ALLOWED",
        planned_direction="BUY",
    )

    assert result["permission"] == "NO_TRADE"
    assert "Daily blocks BUY" in result["reason"]


def test_h4_neutral_allows_if_daily_not_blocking_and_h1_agrees():
    result = evaluate_higher_timeframe_permission(
        daily="NEUTRAL",
        h4="NEUTRAL",
        h1="BUY_ALLOWED",
        planned_direction="BUY",
    )

    assert result["permission"] == "BUY_ALLOWED"


def test_h1_must_agree():
    result = evaluate_higher_timeframe_permission(
        daily="NEUTRAL",
        h4="NEUTRAL",
        h1="NEUTRAL",
        planned_direction="BUY",
    )

    assert result["permission"] == "NO_TRADE"


def test_sell_permission_allows_when_higher_timeframes_agree():
    result = evaluate_higher_timeframe_permission(
        daily="SELL_ALLOWED",
        h4="NEUTRAL",
        h1="SELL_ALLOWED",
        planned_direction="SELL",
    )

    assert result["permission"] == "SELL_ALLOWED"


def test_h4_blocks_opposite_sell_direction():
    result = evaluate_higher_timeframe_permission(
        daily="NEUTRAL",
        h4="BUY_ALLOWED",
        h1="SELL_ALLOWED",
        planned_direction="SELL",
    )

    assert result["permission"] == "NO_TRADE"
    assert "H4 blocks SELL" in result["reason"]


def test_permission_normalizes_lowercase_and_whitespace():
    result = evaluate_higher_timeframe_permission(
        daily=" neutral ",
        h4=" neutral ",
        h1=" buy_allowed ",
        planned_direction=" buy ",
    )

    assert result["permission"] == "BUY_ALLOWED"


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
