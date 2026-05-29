"""Session and time-of-day filters for the price-action playbook."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


PASS = "passed"
FAIL = "failed"
UNKNOWN = "unknown"

DEFAULT_SESSION_CONFIG = {
    "asian_session_start": "19:00",
    "asian_session_end": "23:59:59",
    "london_session_start": "03:00",
    "london_session_end": "11:00",
    "new_york_session_start": "08:00",
    "new_york_session_end": "12:00",
    "pre_open_block_minutes": 15,
    "four_hour_candle_block_minutes": 15,
    "sunday_asian_block_start": "17:00",
    "monday_early_asian_cutoff": "03:00",
}

_UNKNOWN_FILTERS = {
    "volume_time": UNKNOWN,
    "not_last_15_of_4h": UNKNOWN,
    "not_15_min_before_open": UNKNOWN,
    "not_sunday_asian_session": UNKNOWN,
}


def _parse_time(value: Any) -> time:
    parts = [int(part) for part in str(value).split(":")]
    if len(parts) == 2:
        hour, minute = parts
        second = 0
    elif len(parts) == 3:
        hour, minute, second = parts
    else:
        raise ValueError("time must be HH:MM or HH:MM:SS")
    return time(hour, minute, second)


def _parse_as_of(as_of: str, market_timezone: str) -> datetime | None:
    try:
        tz = ZoneInfo(market_timezone)
        parsed = datetime.fromisoformat(str(as_of).strip().replace(" ", "T"))
    except (TypeError, ValueError, ZoneInfoNotFoundError):
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _in_window(current: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _in_pre_open_block(dt: datetime, session_open: time, minutes: int) -> bool:
    open_at = dt.replace(
        hour=session_open.hour,
        minute=session_open.minute,
        second=session_open.second,
        microsecond=0,
    )
    if open_at <= dt:
        open_at += timedelta(days=1)
    block_starts_at = open_at - timedelta(minutes=minutes)
    return block_starts_at <= dt < open_at


def _is_last_minutes_of_4h_cycle(dt: datetime, minutes: int) -> bool:
    if minutes <= 0:
        return False
    cycle_hour = dt.hour % 4
    cutoff_minute = 60 - minutes
    return cycle_hour == 3 and dt.minute >= cutoff_minute


def _merged_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    return {
        **DEFAULT_SESSION_CONFIG,
        **dict(config or {}),
    }


def evaluate_time_filters(
    as_of: str,
    market_timezone: str = "America/New_York",
    config: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Evaluate configured session gates in market-local time."""
    dt = _parse_as_of(as_of, market_timezone)
    if dt is None:
        return dict(_UNKNOWN_FILTERS)

    session_config = _merged_config(config)
    try:
        current = dt.time().replace(microsecond=0)
        asian_start = _parse_time(session_config["asian_session_start"])
        asian_end = _parse_time(session_config["asian_session_end"])
        london_start = _parse_time(session_config["london_session_start"])
        london_end = _parse_time(session_config["london_session_end"])
        new_york_start = _parse_time(session_config["new_york_session_start"])
        new_york_end = _parse_time(session_config["new_york_session_end"])
        pre_open_block_minutes = int(session_config["pre_open_block_minutes"])
        four_hour_block_minutes = int(session_config["four_hour_candle_block_minutes"])
        sunday_asian_block_start = _parse_time(session_config["sunday_asian_block_start"])
        monday_early_cutoff = _parse_time(session_config["monday_early_asian_cutoff"])
    except (KeyError, TypeError, ValueError):
        return dict(_UNKNOWN_FILTERS)

    in_session = (
        _in_window(current, asian_start, asian_end)
        or _in_window(current, london_start, london_end)
        or _in_window(current, new_york_start, new_york_end)
    )

    session_opens = (asian_start, london_start, new_york_start)
    in_pre_open = any(
        _in_pre_open_block(dt, session_open, pre_open_block_minutes)
        for session_open in session_opens
    )
    in_last_15_of_4h = _is_last_minutes_of_4h_cycle(
        dt,
        four_hour_block_minutes,
    )
    is_sunday_asian = dt.weekday() == 6 and current >= sunday_asian_block_start
    is_monday_early_asian = dt.weekday() == 0 and current < monday_early_cutoff

    hard_block = (
        in_pre_open
        or in_last_15_of_4h
        or is_sunday_asian
        or is_monday_early_asian
    )

    return {
        "volume_time": PASS if in_session and not hard_block else FAIL,
        "not_last_15_of_4h": FAIL if in_last_15_of_4h else PASS,
        "not_15_min_before_open": FAIL if in_pre_open else PASS,
        "not_sunday_asian_session": FAIL if is_sunday_asian else PASS,
    }
