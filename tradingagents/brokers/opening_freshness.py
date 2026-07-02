"""Pure candidate-local freshness rules for consumed M1 openings."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any


def _text(value: Any) -> str:
    return str(value or "").strip()


def _token(value: Any) -> str:
    return _text(value).upper()


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _nonnegative_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _timestamp(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _valid_context(context: Mapping[str, Any] | None) -> bool:
    if not isinstance(context, Mapping):
        return False
    return bool(
        _token(context.get("direction"))
        and _token(context.get("level_side"))
        and _token(context.get("trigger"))
        and _token(context.get("reaction_type"))
        and _finite_float(context.get("level")) is not None
        and _finite_float(context.get("tolerance")) is not None
        and _nonnegative_int(context.get("touch_count")) is not None
        and _timestamp(context.get("last_touch_timestamp")) is not None
        and _timestamp(context.get("confirmation_timestamp")) is not None
    )


def same_opening_zone(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
) -> bool:
    """Return whether two valid contexts describe the same local price zone."""
    if not _valid_context(current) or not _valid_context(previous):
        return False
    if _token(current.get("direction")) != _token(previous.get("direction")):
        return False
    if _token(current.get("level_side")) != _token(previous.get("level_side")):
        return False
    current_level = _finite_float(current.get("level"))
    previous_level = _finite_float(previous.get("level"))
    current_tolerance = _finite_float(current.get("tolerance"))
    previous_tolerance = _finite_float(previous.get("tolerance"))
    assert current_level is not None
    assert previous_level is not None
    assert current_tolerance is not None
    assert previous_tolerance is not None
    return abs(current_level - previous_level) <= max(
        0.0,
        current_tolerance,
        previous_tolerance,
    )


def _opening_context(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    nested = record.get("opening_context")
    if isinstance(nested, Mapping):
        return nested
    return record if _valid_context(record) else None


def _is_stale_match(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
) -> bool:
    if not same_opening_zone(current, previous):
        return False
    if _token(current.get("trigger")) != _token(previous.get("trigger")):
        return False
    if _token(current.get("reaction_type")) != _token(
        previous.get("reaction_type")
    ):
        return False
    current_confirmation = _timestamp(current.get("confirmation_timestamp"))
    previous_confirmation = _timestamp(previous.get("confirmation_timestamp"))
    current_touch = _timestamp(current.get("last_touch_timestamp"))
    previous_touch = _timestamp(previous.get("last_touch_timestamp"))
    current_count = _nonnegative_int(current.get("touch_count"))
    previous_count = _nonnegative_int(previous.get("touch_count"))
    if None in (
        current_confirmation,
        previous_confirmation,
        current_touch,
        previous_touch,
        current_count,
        previous_count,
    ):
        return False
    return bool(
        current_confirmation <= previous_confirmation
        and current_touch <= previous_touch
        and current_count <= previous_count
    )


def stale_consumed_opening(
    current: Mapping[str, Any] | None,
    consumed: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    """Return the newest consumed record that makes ``current`` stale."""
    if not _valid_context(current):
        return None
    matches: list[tuple[datetime, int, dict[str, Any]]] = []
    for index, raw_record in enumerate(consumed):
        if not isinstance(raw_record, Mapping):
            continue
        previous = _opening_context(raw_record)
        if previous is None or not _is_stale_match(current, previous):
            continue
        record = dict(raw_record)
        consumed_at = _timestamp(record.get("consumed_at_utc"))
        matches.append(
            (
                consumed_at or datetime.min.replace(tzinfo=timezone.utc),
                index,
                record,
            )
        )
    if not matches:
        return None
    return max(matches, key=lambda item: (item[0], item[1]))[2]


__all__ = ["same_opening_zone", "stale_consumed_opening"]
