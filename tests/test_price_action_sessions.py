from tradingagents.agents.price_action.sessions import evaluate_time_filters
from tradingagents.default_config import DEFAULT_CONFIG


def test_london_window_passes_on_monday():
    result = evaluate_time_filters("2026-05-18 04:00", "America/New_York")

    assert result["volume_time"] == "passed"
    assert result["not_sunday_asian_session"] == "passed"


def test_monday_early_asian_is_blocked():
    result = evaluate_time_filters("2026-05-18 01:00", "America/New_York")

    assert result["volume_time"] == "failed"


def test_exactly_15_minutes_before_new_york_open_is_blocked():
    result = evaluate_time_filters("2026-05-18 07:45", "America/New_York")

    assert result["not_15_min_before_open"] == "failed"
    assert result["volume_time"] == "failed"


def test_last_15_minutes_of_4h_candle_is_blocked():
    result = evaluate_time_filters("2026-05-18 07:50", "America/New_York")

    assert result["not_last_15_of_4h"] == "failed"


def test_sunday_asian_session_is_blocked():
    result = evaluate_time_filters("2026-05-17 19:30", "America/New_York")

    assert result["not_sunday_asian_session"] == "failed"
    assert result["volume_time"] == "failed"


def test_default_config_price_action_shape_can_change_session_window():
    config = {
        **DEFAULT_CONFIG["price_action"],
        "london_session_start": "04:30",
    }

    result = evaluate_time_filters(
        "2026-05-18 04:00",
        "America/New_York",
        config=config,
    )

    assert result["volume_time"] == "failed"


def test_custom_pre_open_block_setting_affects_behavior():
    config = {
        **DEFAULT_CONFIG["price_action"],
        "pre_open_block_minutes": 30,
    }

    result = evaluate_time_filters(
        "2026-05-18 07:35",
        "America/New_York",
        config=config,
    )

    assert result["not_15_min_before_open"] == "failed"
    assert result["volume_time"] == "failed"


def test_next_day_session_open_blocks_previous_day_pre_open():
    config = {
        **DEFAULT_CONFIG["price_action"],
        "asian_session_start": "00:05",
        "asian_session_end": "02:00",
    }

    result = evaluate_time_filters(
        "2026-05-18 23:55",
        "America/New_York",
        config=config,
    )

    assert result["not_15_min_before_open"] == "failed"
    assert result["volume_time"] == "failed"


def test_invalid_timestamp_returns_all_unknown():
    result = evaluate_time_filters("not-a-time", "America/New_York")

    assert set(result.values()) == {"unknown"}


def test_invalid_timezone_returns_all_unknown():
    result = evaluate_time_filters("2026-05-18 04:00", "Etc/Nope")

    assert set(result.values()) == {"unknown"}


def test_timezone_aware_timestamp_is_converted_to_market_timezone():
    result = evaluate_time_filters("2026-05-18 11:00:00+00:00", "America/New_York")

    assert result["volume_time"] == "passed"
    assert result["not_15_min_before_open"] == "passed"


def test_pre_open_boundary_seconds():
    before_block = evaluate_time_filters("2026-05-18 07:44:59", "America/New_York")
    starts_block = evaluate_time_filters("2026-05-18 07:45:00", "America/New_York")
    end_of_block = evaluate_time_filters("2026-05-18 07:59:59", "America/New_York")
    at_open = evaluate_time_filters("2026-05-18 08:00:00", "America/New_York")

    assert before_block["not_15_min_before_open"] == "passed"
    assert starts_block["not_15_min_before_open"] == "failed"
    assert end_of_block["not_15_min_before_open"] == "failed"
    assert at_open["not_15_min_before_open"] == "passed"


def test_session_boundary_seconds():
    config = {
        **DEFAULT_CONFIG["price_action"],
        "four_hour_candle_block_minutes": 0,
    }
    before_london = evaluate_time_filters("2026-05-18 02:44:59", "America/New_York")
    london_open = evaluate_time_filters("2026-05-18 03:00:00", "America/New_York")
    asian_last_second = evaluate_time_filters(
        "2026-05-18 23:59:59",
        "America/New_York",
        config=config,
    )

    assert before_london["volume_time"] == "failed"
    assert london_open["volume_time"] == "passed"
    assert asian_last_second["volume_time"] == "passed"


def test_four_hour_boundary_seconds():
    before_block = evaluate_time_filters("2026-05-18 03:44:59", "America/New_York")
    starts_block = evaluate_time_filters("2026-05-18 03:45:00", "America/New_York")
    end_of_block = evaluate_time_filters("2026-05-18 03:59:59", "America/New_York")
    after_block = evaluate_time_filters("2026-05-18 04:00:00", "America/New_York")

    assert before_block["not_last_15_of_4h"] == "passed"
    assert starts_block["not_last_15_of_4h"] == "failed"
    assert end_of_block["not_last_15_of_4h"] == "failed"
    assert after_block["not_last_15_of_4h"] == "passed"
