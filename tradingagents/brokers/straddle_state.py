"""JSON state file for active MT5 straddle pairs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.straddle_breakout import StraddlePairProposal
from tradingagents.dataflows.utils import safe_ticker_component


class StraddleStateStore:
    """Persist one-symbol MT5 straddle execution state."""

    filename = "mt5_straddle_state.json"

    def __init__(self, results_dir: str | Path, symbol: str) -> None:
        self.symbol = symbol
        safe_symbol = safe_ticker_component(symbol)
        self.directory = Path(results_dir) / safe_symbol / "execution_state"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / self.filename

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"symbol": self.symbol, "active_pair": None}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        self.directory.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
        return state

    def record_pair(
        self,
        pair: StraddlePairProposal,
        *,
        dry_run: bool,
        buy_ticket: int | None = None,
        sell_ticket: int | None = None,
        placed_at_utc: datetime | None = None,
        requests: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        placed_at = placed_at_utc or datetime.now(timezone.utc)
        if placed_at.tzinfo is None:
            placed_at = placed_at.replace(tzinfo=timezone.utc)
        placed_at = placed_at.astimezone(timezone.utc)
        cancel_after = None
        if pair.buy_stop is not None:
            cancel_after = pair.buy_stop.cancel_if_not_triggered_after
        return self.save(
            {
                "symbol": self.symbol,
                "active_pair": {
                    "dry_run": bool(dry_run),
                    "buy_ticket": buy_ticket,
                    "sell_ticket": sell_ticket,
                    "placed_at_utc": placed_at.isoformat(),
                    "cancel_after_utc": cancel_after,
                    "pair": pair.model_dump(mode="json"),
                    "requests": requests or [],
                },
            }
        )

    def clear_pair(self) -> dict[str, Any]:
        state = self.load()
        state["active_pair"] = None
        return self.save(state)
