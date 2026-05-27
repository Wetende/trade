"""Append-only execution event journal for broker actions."""

from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component

_CYCLE_MARKER = "<cycle>"
_MAX_NORMALIZE_DEPTH = 64
_EVENT_TYPE_RE = re.compile(r"^[A-Za-z0-9_]+$")


def _normalize_payload_value(
    value: Any,
    seen: set[int] | None = None,
    depth: int = 0,
) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if depth > _MAX_NORMALIZE_DEPTH:
        return _CYCLE_MARKER
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)

    if seen is None:
        seen = set()
    value_id = id(value)
    if value_id in seen:
        return _CYCLE_MARKER
    seen.add(value_id)
    try:
        if isinstance(value, Enum):
            return _normalize_payload_value(value.value, seen, depth + 1)
        if isinstance(value, Mapping):
            return {
                str(key): _normalize_payload_value(item, seen, depth + 1)
                for key, item in value.items()
            }

        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            return _normalize_payload_value(model_dump(mode="python"), seen, depth + 1)

        asdict = getattr(value, "_asdict", None)
        if callable(asdict):
            return _normalize_payload_value(asdict(), seen, depth + 1)

        if isinstance(value, (set, frozenset)):
            normalized = [
                _normalize_payload_value(item, seen, depth + 1)
                for item in value
            ]
            return sorted(
                normalized,
                key=lambda item: json.dumps(item, sort_keys=True, default=str),
            )

        if isinstance(value, (list, tuple)):
            return [
                _normalize_payload_value(item, seen, depth + 1)
                for item in value
            ]

        attributes = getattr(value, "__dict__", None)
        if isinstance(attributes, dict):
            return _normalize_payload_value(attributes, seen, depth + 1)

        return str(value)
    finally:
        seen.remove(value_id)


class ExecutionJournal:
    """Write execution events to a symbol-scoped JSONL journal."""

    filename = "mt5_demo_events.jsonl"

    def __init__(self, results_dir: str | Path, symbol: str) -> None:
        self.results_dir = Path(results_dir)
        self.symbol = symbol

    def append(self, event_type: str, payload: dict[str, Any]) -> Path:
        if not isinstance(event_type, str) or not _EVENT_TYPE_RE.fullmatch(event_type):
            raise ValueError("event_type must contain only letters, digits, or underscores")

        safe_symbol = safe_ticker_component(self.symbol)
        journal_dir = self.results_dir / safe_symbol / "execution_journal"
        self._ensure_contained(journal_dir)
        journal_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        journal_path = journal_dir / self.filename
        self._ensure_contained(journal_path)

        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "symbol": self.symbol,
            "payload": _normalize_payload_value(payload),
        }
        line = (json.dumps(event, sort_keys=True) + "\n").encode("utf-8")
        open_flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        fd = os.open(
            journal_path,
            open_flags,
            0o600,
        )
        try:
            # This is a local containment guard against accidental path escapes,
            # not a complete multi-user sandbox. Re-check after opening to reduce
            # the practical symlink race window for this local results directory.
            self._ensure_contained(journal_path)
            self._write_all(fd, line)
        finally:
            os.close(fd)

        return journal_path

    def _write_all(self, fd: int, data: bytes) -> None:
        offset = 0
        while offset < len(data):
            written = os.write(fd, data[offset:])
            if written == 0:
                raise OSError("execution journal write returned 0 bytes")
            offset += written

    def _ensure_contained(self, journal_path: Path) -> None:
        resolved_results_dir = self.results_dir.resolve()
        resolved_journal_path = journal_path.resolve(strict=False)
        if (
            resolved_journal_path != resolved_results_dir
            and resolved_results_dir not in resolved_journal_path.parents
        ):
            raise ValueError(
                f"execution journal path is outside results_dir: {resolved_journal_path}"
            )
