"""Append-only execution event journal for broker actions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component


class ExecutionJournal:
    """Write execution events to a symbol-scoped JSONL journal."""

    filename = "mt5_demo_events.jsonl"

    def __init__(self, results_dir: str | Path, symbol: str) -> None:
        self.results_dir = Path(results_dir)
        self.symbol = symbol

    def append(self, event_type: str, payload: dict[str, Any]) -> Path:
        safe_symbol = safe_ticker_component(self.symbol)
        journal_dir = self.results_dir / safe_symbol / "execution_journal"
        journal_dir.mkdir(parents=True, exist_ok=True)
        journal_path = journal_dir / self.filename

        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "symbol": self.symbol,
            "payload": payload,
        }
        with journal_path.open("a", encoding="utf-8") as journal_file:
            journal_file.write(json.dumps(event, sort_keys=True) + "\n")

        return journal_path
