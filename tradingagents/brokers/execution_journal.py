"""Append-only execution event journal for broker actions."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component


def _normalize_payload_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Enum):
        return _normalize_payload_value(value.value)
    if isinstance(value, Mapping):
        return {
            str(key): _normalize_payload_value(item)
            for key, item in value.items()
        }

    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _normalize_payload_value(model_dump(mode="python"))

    asdict = getattr(value, "_asdict", None)
    if callable(asdict):
        return _normalize_payload_value(asdict())

    if isinstance(value, (list, tuple, set, frozenset)):
        return [_normalize_payload_value(item) for item in value]

    attributes = getattr(value, "__dict__", None)
    if isinstance(attributes, dict):
        return _normalize_payload_value(attributes)

    return str(value)


class ExecutionJournal:
    """Write execution events to a symbol-scoped JSONL journal."""

    filename = "mt5_demo_events.jsonl"

    def __init__(self, results_dir: str | Path, symbol: str) -> None:
        self.results_dir = Path(results_dir)
        self.symbol = symbol

    def append(self, event_type: str, payload: dict[str, Any]) -> Path:
        if not isinstance(event_type, str) or not event_type.strip():
            raise ValueError("event_type must be a non-empty string")

        safe_symbol = safe_ticker_component(self.symbol)
        journal_dir = self.results_dir / safe_symbol / "execution_journal"
        self._ensure_contained(journal_dir)
        journal_dir.mkdir(parents=True, exist_ok=True)
        journal_path = journal_dir / self.filename
        self._ensure_contained(journal_path)

        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "symbol": self.symbol,
            "payload": _normalize_payload_value(payload),
        }
        line = (json.dumps(event, sort_keys=True) + "\n").encode("utf-8")
        fd = os.open(
            journal_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY,
            0o600,
        )
        try:
            bytes_written = os.write(fd, line)
            if bytes_written != len(line):
                raise OSError("incomplete execution journal write")
        finally:
            os.close(fd)

        return journal_path

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
