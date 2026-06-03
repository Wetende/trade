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
    max_runtime_seconds: int = 0

    def __post_init__(self) -> None:
        poll_seconds = int(self.poll_seconds)
        max_cycles = int(self.max_cycles)
        max_runtime_seconds = int(self.max_runtime_seconds)
        if poll_seconds < 5:
            raise ValueError("poll_seconds must be at least 5")
        if max_cycles < 0:
            raise ValueError("max_cycles must be non-negative")
        if max_runtime_seconds < 0:
            raise ValueError("max_runtime_seconds must be non-negative")
        object.__setattr__(self, "poll_seconds", poll_seconds)
        object.__setattr__(self, "max_cycles", max_cycles)
        object.__setattr__(self, "max_runtime_seconds", max_runtime_seconds)


class MT5Runner:
    """Run analysis and guarded MT5 execution on a repeating cadence."""

    def __init__(
        self,
        config: MT5RunnerConfig,
        *,
        executor,
        analysis_func: Callable[[], tuple[str, OrderProposal] | list],
        current_as_of_func: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.executor = executor
        self.analysis_func = analysis_func
        self.current_as_of_func = current_as_of_func
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

        state = self._load_state()
        if self.current_as_of_func is not None:
            current_as_of = self.current_as_of_func()
            if state.get("last_processed_as_of") == current_as_of:
                return self._write_heartbeat(
                    {
                        "status": "CANDLE_ALREADY_PROCESSED",
                        "started_at_utc": started_at,
                        "as_of": current_as_of,
                    }
                )

        try:
            analysis_result = self.analysis_func()
            analysis_rows = self._parse_analysis_results(analysis_result)
        except Exception as exc:
            return self._write_heartbeat(
                {
                    "status": "RUNNER_ERROR",
                    "started_at_utc": started_at,
                    "analysis": {
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                }
            )

        multi_profile_result = isinstance(analysis_result, list)
        last_processed_by_profile = dict(state.get("last_processed_by_profile") or {})
        processed_rows = []
        selected = None
        legacy_last_processed = state.get("last_processed_as_of")

        for profile, as_of, proposal, analysis in analysis_rows:
            if last_processed_by_profile.get(profile) == as_of or (
                profile == "normal" and legacy_last_processed == as_of
            ):
                continue

            status = str(getattr(proposal.status, "value", proposal.status)).upper()
            processed_rows.append((profile, as_of, proposal, analysis, status))
            last_processed_by_profile[profile] = as_of
            if selected is None and status == "PROPOSED":
                selected = (profile, as_of, proposal, analysis)

        if not processed_rows:
            return self._write_heartbeat(
                {
                    "status": "CANDLE_ALREADY_PROCESSED",
                    "started_at_utc": started_at,
                    "profiles": [],
                }
            )

        latest_as_of = processed_rows[-1][1]
        self._save_state(
            {
                "last_processed_as_of": latest_as_of,
                "last_processed_by_profile": last_processed_by_profile,
            }
        )

        if selected is None:
            if not multi_profile_result and len(processed_rows) == 1:
                profile, as_of, proposal, analysis, _status = processed_rows[0]
                return self._write_heartbeat(
                    {
                        "status": "NO_TRADE",
                        "started_at_utc": started_at,
                        "as_of": as_of,
                        "proposal": proposal.model_dump(mode="json"),
                        "analysis": analysis,
                    }
                )
            return self._write_heartbeat(
                {
                    "status": "NO_TRADE",
                    "started_at_utc": started_at,
                    "profiles": [
                        {
                            "entry_profile": profile,
                            "as_of": as_of,
                            "proposal": proposal.model_dump(mode="json"),
                            "analysis": analysis,
                            "status": status,
                        }
                        for profile, as_of, proposal, analysis, status in processed_rows
                    ],
                }
            )

        profile, as_of, proposal, analysis = selected
        execution = self.executor.execute_proposal(proposal)
        payload = {
            "status": (
                "ORDER_PLACED"
                if execution.get("status") == "PLACED"
                else "ORDER_NOT_PLACED"
            ),
            "started_at_utc": started_at,
            "entry_profile": profile,
            "as_of": as_of,
            "proposal": proposal.model_dump(mode="json"),
            "execution": execution,
            "analysis": analysis,
        }
        if not multi_profile_result:
            payload.pop("entry_profile", None)
        return self._write_heartbeat(payload)

    def run_forever(self) -> dict:
        cycles = 0
        last_result = {"status": "NOT_STARTED"}
        deadline = (
            time.monotonic() + self.config.max_runtime_seconds
            if self.config.max_runtime_seconds
            else None
        )
        while True:
            last_result = self.run_once()
            cycles += 1
            if (
                deadline is None
                and self.config.max_cycles
                and cycles >= self.config.max_cycles
            ):
                return {"status": "STOPPED_MAX_CYCLES", "last_result": last_result}
            if deadline is not None:
                if time.monotonic() >= deadline:
                    return {
                        "status": "STOPPED_MAX_RUNTIME_SECONDS",
                        "last_result": last_result,
                    }
                remaining_seconds = deadline - time.monotonic()
                if remaining_seconds <= 0:
                    return {
                        "status": "STOPPED_MAX_RUNTIME_SECONDS",
                        "last_result": last_result,
                    }
                time.sleep(min(self.config.poll_seconds, remaining_seconds))
            else:
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

    def _parse_analysis_results(self, result) -> list[tuple[str, str, OrderProposal, dict]]:
        if isinstance(result, list):
            rows = []
            for item in result:
                if not isinstance(item, tuple):
                    raise ValueError("analysis profile rows must be tuples")
                if len(item) == 4:
                    profile, as_of, proposal, analysis = item
                    rows.append((str(profile), as_of, proposal, dict(analysis or {})))
                else:
                    as_of, proposal, analysis = self._parse_analysis_result(item)
                    rows.append(("normal", as_of, proposal, analysis))
            return rows

        as_of, proposal, analysis = self._parse_analysis_result(result)
        return [("normal", as_of, proposal, analysis)]

    def _load_state(self) -> dict:
        if not self.state_path.exists():
            return {"last_processed_by_profile": {}}
        return {
            "last_processed_by_profile": {},
            **json.loads(self.state_path.read_text(encoding="utf-8")),
        }

    def _save_state(self, state: dict) -> dict:
        self.state_path.write_text(
            json.dumps(state, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return state
