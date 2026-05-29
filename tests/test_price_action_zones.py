from tradingagents.agents.price_action.candles import parse_ohlcv_text
from tradingagents.agents.price_action.zones import (
    calculate_support_resistance,
    classify_range,
    nearest_target_zone,
    zone_to_dict,
)


def _candles():
    return parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 06:00:00,98,100,95.5,97,1000\n"
        "2026-05-18 06:30:00,99,105.0,98.0,104,1000\n"
        "2026-05-18 07:00:00,100,101,95.0,96,1000\n"
        "2026-05-18 07:30:00,100,104.8,97.0,104,1000\n"
        "2026-05-18 08:00:00,99,101,94.9,96,1000\n"
        "2026-05-18 08:30:00,99,103,98.0,102,1000"
    )


def test_detects_support_and_resistance_clusters():
    zones = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)

    assert any(zone.type == "support" and zone.touches == 2 for zone in zones)
    assert any(zone.type == "resistance" and zone.touches == 2 for zone in zones)


def test_scores_higher_timeframe_zones_above_lower_timeframe_zones():
    daily = calculate_support_resistance(_candles(), timeframe="1d", tolerance=0.5)[0]
    m30 = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)[0]

    assert daily.score > m30.score


def test_classifies_sideways_equal_highs_and_lows_as_range():
    zones = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)
    result = classify_range(_candles(), zones)

    assert result["market_type"] == "RANGE"
    assert result["support_zone"]["type"] == "support"
    assert result["resistance_zone"]["type"] == "resistance"


def test_rejects_range_when_intrabar_prices_break_the_box():
    zones = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)
    breakout_candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 06:00:00,98,100,95.5,97,1000\n"
        "2026-05-18 06:30:00,99,108.0,98.0,104,1000\n"
        "2026-05-18 07:00:00,100,101,95.0,96,1000\n"
        "2026-05-18 07:30:00,100,104.8,97.0,104,1000\n"
        "2026-05-18 08:00:00,99,101,94.9,96,1000\n"
        "2026-05-18 08:30:00,99,103,98.0,102,1000"
    )

    result = classify_range(breakout_candles, zones)

    assert result["market_type"] != "RANGE"
    assert result["breakout_count"] == 1


def test_drifting_swing_points_do_not_merge_into_one_large_zone():
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 06:00:00,100,102,98.0,101,1000\n"
        "2026-05-18 06:30:00,100,103,95.0,101,1000\n"
        "2026-05-18 07:00:00,100,102,99.0,101,1000\n"
        "2026-05-18 07:30:00,100,103,95.8,101,1000\n"
        "2026-05-18 08:00:00,100,102,100.0,101,1000\n"
        "2026-05-18 08:30:00,100,103,96.4,101,1000\n"
        "2026-05-18 09:00:00,100,102,101.0,101,1000"
    )

    zones = calculate_support_resistance(candles, timeframe="30m", tolerance=1.0)

    assert not any(zone.type == "support" and zone.touches == 3 for zone in zones)


def test_nearest_target_zone_uses_opposite_zone():
    zones = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)
    target = nearest_target_zone(zones, direction="BUY", entry_price=96.0)

    assert target["type"] == "resistance"
    assert target["midpoint"] > 96.0


def test_empty_and_tiny_inputs_return_no_zones_or_unclear_context():
    assert calculate_support_resistance([], timeframe="30m") == []
    assert calculate_support_resistance(_candles()[:2], timeframe="30m") == []

    result = classify_range(_candles()[:2], [])

    assert result["market_type"] == "UNCLEAR"
    assert result["support_zone"] is None
    assert result["resistance_zone"] is None
    assert nearest_target_zone([], direction="BUY", entry_price=96.0) is None


def test_zone_to_dict_serializes_stable_shape():
    zone = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)[0]

    payload = zone_to_dict(zone)

    assert set(payload) == {
        "type",
        "timeframe",
        "low",
        "high",
        "midpoint",
        "touches",
        "score",
        "source",
        "reactions",
    }
    assert payload["type"] in {"support", "resistance"}
    assert isinstance(payload["reactions"], list)
