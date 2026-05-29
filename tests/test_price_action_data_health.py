from tradingagents.agents.price_action.models import Candle
from tradingagents.dataflows.data_health import build_data_status, data_is_healthy


def _c(ts):
    return Candle(timestamp=ts, open=1, high=2, low=0.5, close=1.5, volume=100)


def test_data_status_marks_required_timeframes_fresh():
    frames = {
        "1d": [_c("2026-05-29")],
        "4h": [_c("2026-05-29 08:00:00")],
        "1h": [_c("2026-05-29 08:00:00")],
        "30m": [_c("2026-05-29 08:00:00")],
        "15m": [_c("2026-05-29 08:00:00")],
    }

    status = build_data_status(frames, "2026-05-29 08:15", "America/New_York")

    assert status["healthy"] is True
    assert status["timeframes"]["15m"]["fresh"] is True
    assert status["timeframes"]["15m"]["latest_age_minutes"] == 15
    assert data_is_healthy(status) is True


def test_data_status_blocks_stale_required_intraday_timeframe():
    frames = {
        "1d": [_c("2026-05-29")],
        "4h": [_c("2026-05-29 04:00:00")],
        "1h": [_c("2026-05-29 07:00:00")],
        "30m": [_c("2026-05-29 07:00:00")],
        "15m": [_c("2026-05-29 06:00:00")],
    }

    status = build_data_status(frames, "2026-05-29 08:15", "America/New_York")

    assert status["healthy"] is False
    assert status["timeframes"]["15m"]["fresh"] is False
    assert "15m" in status["blocking_timeframes"]


def test_data_status_allows_small_source_timestamp_drift_ahead_of_as_of():
    frames = {
        "1d": [_c("2026-05-29")],
        "4h": [_c("2026-05-29 12:00:00")],
        "1h": [_c("2026-05-29 12:00:00")],
        "30m": [_c("2026-05-29 12:30:00")],
        "15m": [_c("2026-05-29 12:45:00")],
    }

    status = build_data_status(frames, "2026-05-29 12:15", "America/New_York")

    assert status["healthy"] is True
    assert status["timeframes"]["15m"]["latest_age_minutes"] == -30
    assert status["timeframes"]["15m"]["fresh"] is True


def test_data_status_blocks_extreme_source_timestamp_drift_ahead_of_as_of():
    frames = {
        "1d": [_c("2026-05-29")],
        "4h": [_c("2026-05-30 12:00:00")],
        "1h": [_c("2026-05-30 12:00:00")],
        "30m": [_c("2026-05-30 12:30:00")],
        "15m": [_c("2026-05-30 12:45:00")],
    }

    status = build_data_status(frames, "2026-05-29 12:15", "America/New_York")

    assert status["healthy"] is False
    assert status["timeframes"]["15m"]["fresh"] is False
    assert "15m" in status["blocking_timeframes"]
