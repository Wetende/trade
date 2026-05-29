"""Unattended MT5 automation loop."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from tradingagents.agents.schemas import OrderProposal
from tradingagents.brokers.runner_summary import RunnerSummaryStore


@dataclass(frozen=True)
class MT5RunnerConfig:
    results_dir: str | Path
    poll_seconds: int = 30
    max_cycles: int = 0

    def __post_init__(self) -> None:
        poll_seconds = int(self.poll_seconds)
        max_cycles = int(self.max_cycles)
        if poll_seconds < 5:
            raise ValueError("poll_seconds must be at least 5")
        if max_cycles < 0:
            raise ValueError("max_cycles must be non-negative")
        object.__setattr__(self, "poll_seconds", poll_seconds)
        object.__setattr__(self, "max_cycles", max_cycles)


class MT5Runner:
    """Run analysis and guarded MT5 execution on a repeating cadence."""

    def __init__(
        self,
        config: MT5RunnerConfig,
        *,
        executor,
        analysis_func: Callable[[], tuple[str, OrderProposal]],
    ) -> None:
        self.config = config
        self.executor = executor
        self.analysis_func = analysis_func
        self.runner_dir = Path(config.results_dir) / "mt5_runner"
        self.runner_dir.mkdir(parents=True, exist_ok=True)
        self.heartbeat_path = self.runner_dir / "heartbeat.json"
        self.state_path = self.runner_dir / "state.json"
        self.summary_store = RunnerSummaryStore(config.results_dir)

    def run_once(self) -> dict:
        started_at = datetime.now(timezone.utc).isoformat()
        snapshot = self.executor.snapshot_state()
        self.executor.cancel_stale_pending_orders()
        self.executor.manage_open_positions()

        if snapshot.get("orders") or snapshot.get("positions"):
            return self._write_heartbeat(
                {
                    "status": "ACTIVE_TRADE_MONITORED",
                    "started_at_utc": started_at,
                }
            )

        as_of, proposal, analysis = self._parse_analysis_result(self.analysis_func())
        state = self._load_state()
        if state.get("last_processed_as_of") == as_of:
            return self._write_heartbeat(
                {
                    "status": "CANDLE_ALREADY_PROCESSED",
                    "started_at_utc": started_at,
                    "as_of": as_of,
                    "analysis": analysis,
                }
            )

        status = str(getattr(proposal.status, "value", proposal.status)).upper()
        if status != "PROPOSED":
            self._save_state({"last_processed_as_of": as_of})
            return self._write_heartbeat(
                {
                    "status": "NO_TRADE",
                    "started_at_utc": started_at,
                    "as_of": as_of,
                    "proposal": proposal.model_dump(mode="json"),
                    "analysis": analysis,
                }
            )

        execution = self.executor.execute_proposal(proposal)
        self._save_state({"last_processed_as_of": as_of})
        return self._write_heartbeat(
            {
                "status": (
                    "ORDER_PLACED"
                    if execution.get("status") == "PLACED"
                    else "ORDER_NOT_PLACED"
                ),
                "started_at_utc": started_at,
                "as_of": as_of,
                "execution": execution,
                "analysis": analysis,
            }
        )

    def run_forever(self) -> dict:
        cycles = 0
        last_result = {"status": "NOT_STARTED"}
        while True:
            last_result = self.run_once()
            cycles += 1
            if self.config.max_cycles and cycles >= self.config.max_cycles:
                return {"status": "STOPPED_MAX_CYCLES", "last_result": last_result}
            time.sleep(self.config.poll_seconds)

    def _write_heartbeat(self, result: dict) -> dict:
        payload = {
            **result,
            "heartbeat_utc": datetime.now(timezone.utc).isoformat(),
            "heartbeat_path": str(self.heartbeat_path),
        }
        summary = self.summary_store.record_cycle(payload)
        payload["summary_path"] = str(self.summary_store.summary_path)
        payload["summary"] = summary
        self.heartbeat_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return payload

    def _parse_analysis_result(self, result) -> tuple[str, OrderProposal, dict]:
        if not isinstance(result, tuple):
            raise ValueError("analysis_func must return a tuple")
        if len(result) == 2:
            as_of, proposal = result
            return as_of, proposal, {}
        if len(result) == 3:
            as_of, proposal, analysis = result
            return as_of, proposal, dict(analysis or {})
        raise ValueError(
            "analysis_func must return (as_of, proposal) or (as_of, proposal, analysis)"
        )

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def _save_state(self, state: dict) -> dict:
        self.state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return state
