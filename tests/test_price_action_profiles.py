import pytest


@pytest.mark.unit
def test_entry_profiles_use_configured_timeframes_and_windows():
    from tradingagents.agents.price_action.profiles import fast_profile, normal_profile

    config = {
        "timeframe": "15m",
        "confirmation_timeframe": "30m",
        "fast_timeframe": "1m",
        "fast_confirmation_timeframe": "3m",
        "normal_activation_window_minutes": 30,
        "fast_activation_window_minutes": 6,
        "fast_counter_bias_minimum_grade": "A_PLUS",
    }

    normal = normal_profile(config)
    fast = fast_profile(config)

    assert normal.name == "normal"
    assert normal.timeframe == "15m"
    assert normal.confirmation_timeframe == "30m"
    assert normal.zone_timeframes == ("1d", "4h", "1h", "30m")
    assert normal.governing_timeframes == ("30m",)
    assert normal.activation_window_minutes == 30
    assert normal.independent_direction is False
    assert fast.name == "fast"
    assert fast.timeframe == "1m"
    assert fast.confirmation_timeframe == "3m"
    assert fast.zone_timeframes == ("30m", "15m")
    assert fast.governing_timeframes == ("30m", "15m")
    assert fast.activation_window_minutes == 6
    assert fast.independent_direction is True
    assert fast.counter_bias_minimum_grade == "A_PLUS"
