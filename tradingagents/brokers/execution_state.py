"""JSON state file for the active MT5 order."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.schemas import OrderProposal
from tradingagents.dataflows.utils import safe_ticker_component


class ExecutionStateStore:
    """Persist one-symbol MT5 execution state."""

    filename = "mt5_state.json"

    def __init__(self, results_dir: str | Path, symbol: str) -> None:
        self.symbol = symbol
        safe_symbol = safe_ticker_component(symbol)
        self.directory = Path(results_dir) / safe_symbol / "execution_state"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / self.filename

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {
                "symbol": self.symbol,
                "active_order_ticket": None,
                "active_position_ticket": None,
            }
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

    def record_pending_order(
        self,
        ticket: int,
        proposal: OrderProposal,
        placed_at_utc: datetime | None = None,
        cancel_after_utc: datetime | None = None,
        pending_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        placed_at = placed_at_utc or datetime.now(timezone.utc)
        if placed_at.tzinfo is None:
            placed_at = placed_at.replace(tzinfo=timezone.utc)
        placed_at = placed_at.astimezone(timezone.utc)
        if cancel_after_utc is None:
            activation_window = proposal.activation_window_minutes or 10
            cancel_after = placed_at + timedelta(minutes=activation_window)
        else:
            cancel_after = cancel_after_utc
            if cancel_after.tzinfo is None:
                cancel_after = cancel_after.replace(tzinfo=timezone.utc)
            cancel_after = cancel_after.astimezone(timezone.utc)
        return self.save(
            {
                "symbol": self.symbol,
                "active_order_ticket": int(ticket),
                "active_position_ticket": None,
                "placed_at_utc": placed_at.isoformat(),
                "cancel_after_utc": cancel_after.isoformat(),
                "pending_policy": dict(pending_policy or {}),
                "proposal": proposal.model_dump(mode="json"),
            }
        )

    def clear_pending_order(self) -> dict[str, Any]:
        state = self.load()
        state["active_order_ticket"] = None
        return self.save(state)

    def mark_position_active(self, ticket: int) -> dict[str, Any]:
        state = self.load()
        state["active_order_ticket"] = None
        state["active_position_ticket"] = int(ticket)
        return self.save(state)

    def clear_trade(self) -> dict[str, Any]:
        return self.save(
            {
                "symbol": self.symbol,
                "active_order_ticket": None,
                "active_position_ticket": None,
            }
        )
