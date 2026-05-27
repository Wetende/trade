"""Append-only execution event journal for broker actions."""

from __future__ import annotations

import json
import math
import os
import re
import stat
import threading
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component

if os.name == "posix":
    import fcntl
else:  # pragma: no cover - only used on platforms without POSIX locking.
    fcntl = None

_CYCLE_MARKER = "<cycle>"
_MAX_NORMALIZE_DEPTH = 64
_EVENT_TYPE_RE = re.compile(r"^[A-Za-z0-9_]+$")
_WRITE_LOCK = threading.Lock()


def _normalize_payload_value(
    value: Any,
    seen: set[int] | None = None,
    depth: int = 0,
) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
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
        journal_path = self.results_dir / safe_symbol / "execution_journal" / self.filename

        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "symbol": self.symbol,
            "payload": _normalize_payload_value(payload),
        }
        line = (json.dumps(event, allow_nan=False, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        self._append_line_descriptor_relative(safe_symbol, line)

        return journal_path

    def _append_line_descriptor_relative(self, safe_symbol: str, line: bytes) -> None:
        self.results_dir.mkdir(mode=0o700, parents=True, exist_ok=True)

        if os.name != "posix" or not hasattr(os, "O_DIRECTORY"):
            # This fallback is weaker than the POSIX dir-fd path and is only
            # used when descriptor-relative directory semantics are unavailable.
            self._append_line_path_fallback(safe_symbol, line)
            return

        # Descriptor-relative opens keep all child lookups anchored under
        # results_dir. This is a local containment guard for execution artifacts,
        # not a complete multi-user sandbox.
        resolved_results_dir = self.results_dir.resolve(strict=True)
        dir_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            dir_flags |= os.O_NOFOLLOW

        results_fd = os.open(resolved_results_dir, dir_flags)
        try:
            self._chmod_owner_only(results_fd, 0o700)
            symbol_fd = self._open_child_dir(results_fd, safe_symbol)
            try:
                self._chmod_owner_only(symbol_fd, 0o700)
                journal_fd = self._open_child_dir(symbol_fd, "execution_journal")
                try:
                    self._chmod_owner_only(journal_fd, 0o700)
                    event_fd = self._open_event_file(journal_fd)
                    try:
                        self._ensure_regular_file(event_fd)
                        self._chmod_owner_only(event_fd, 0o600)
                        self._locked_write_all(event_fd, line)
                    finally:
                        os.close(event_fd)
                finally:
                    os.close(journal_fd)
            finally:
                os.close(symbol_fd)
        finally:
            os.close(results_fd)

    def _append_line_path_fallback(self, safe_symbol: str, line: bytes) -> None:
        journal_dir = self.results_dir / safe_symbol / "execution_journal"
        self._ensure_contained(journal_dir)
        journal_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        journal_path = journal_dir / self.filename
        self._ensure_contained(journal_path)

        open_flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        fd = os.open(
            journal_path,
            open_flags,
            0o600,
        )
        try:
            self._ensure_contained(journal_path)
            self._ensure_regular_file(fd)
            self._chmod_owner_only(fd, 0o600)
            self._locked_write_all(fd, line)
        finally:
            os.close(fd)

    def _open_child_dir(self, parent_fd: int, name: str) -> int:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent_fd)
        except FileExistsError:
            pass

        dir_flags = os.O_RDONLY | os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            dir_flags |= os.O_NOFOLLOW
        try:
            return os.open(name, dir_flags, dir_fd=parent_fd)
        except OSError as exc:
            raise ValueError(
                f"unsafe execution journal directory component: {name!r}"
            ) from exc

    def _open_event_file(self, journal_fd: int) -> int:
        open_flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        try:
            return os.open(self.filename, open_flags, 0o600, dir_fd=journal_fd)
        except OSError as exc:
            raise ValueError("unsafe execution journal file path") from exc

    def _ensure_regular_file(self, fd: int) -> None:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("execution journal target must be a regular file")

    def _chmod_owner_only(self, fd: int, mode: int) -> None:
        try:
            os.fchmod(fd, mode)
        except OSError:
            pass

    def _locked_write_all(self, fd: int, data: bytes) -> None:
        with _WRITE_LOCK:
            if fcntl is None:
                self._write_all(fd, data)
                return
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                self._write_all(fd, data)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)

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
