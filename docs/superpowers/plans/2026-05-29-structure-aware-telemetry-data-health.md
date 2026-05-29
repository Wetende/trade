# Structure-Aware Telemetry And Data Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build trustworthy live-run observability, data health protection, and playbook-faithful higher-timeframe permission so the bot can explain every HOLD and only approve M15 entries when Daily, 4H, 1H, and M30 context allow them.

**Architecture:** Keep analysis deterministic and observable. The price-action engine emits raw telemetry for every decision, dataflows attach freshness and retry evidence, and the MT5 runner aggregates cycle summaries without changing execution safety. Replace the current first-close-vs-last-close permission shortcut with structure classification that follows `docs/playbook.md`: Daily must not block, 4H must agree or be neutral, 1H must agree, and M30 direction must match the M15 setup.

**Tech Stack:** Python 3.13, Pydantic/dataclasses, Typer, yfinance, MetaTrader5 bridge, pytest, JSON/JSONL artifacts under `~/.tradingagents/logs`.

---

## Ground Rules

- Work on `main`; do not create a branch unless the user later asks for one.
- Keep `.env`, `.env.*`, `.venv`, and local Codex files ignored.
- Use `.venv\Scripts\python.exe -m pytest ...` because `uv` is not currently on this terminal PATH.
- Do not loosen trade approval rules without tests that show the playbook behavior.
- Do not run broker-mode live order tests during this plan unless the user explicitly asks; these tasks are code and dry verification.

## File Structure

- Create `tradingagents/brokers/runner_summary.py`: summary store, HOLD reason categorization, cycle JSONL writer.
- Modify `tradingagents/brokers/mt5_runner.py`: accept optional analysis metadata, write summary after every cycle, include summary path in heartbeat.
- Modify `cli/main.py`: return analysis metadata from `_mt5_runner_analysis_func`, including report/proposal paths and any raw telemetry path available from the graph/tool payload.
- Modify `tradingagents/agents/price_action/engine.py`: emit raw deterministic telemetry in every payload.
- Modify `tradingagents/agents/utils/price_action_tools.py`: persist raw engine payload JSON and attach `telemetry_path`; use richer data health before analysis.
- Create `tradingagents/dataflows/data_health.py`: timestamp parsing, row counts, freshness age, stale/unavailable blockers.
- Modify `tradingagents/dataflows/price_action.py`: add snapshot fetch API that returns candles plus data health while keeping `fetch_price_action_timeframes()` backward compatible.
- Modify `tradingagents/dataflows/y_finance.py`: retry empty/intermittent yfinance responses and record attempt metadata in comments.
- Modify `tradingagents/agents/price_action/structure.py`: classify Daily/4H/1H structure and evaluate permission from structure objects.
- Modify tests:
  - `tests/test_mt5_runner.py`
  - `tests/test_mt5_runner_summary.py`
  - `tests/test_price_action_engine.py`
  - `tests/test_price_action_tools.py`
  - `tests/test_price_action_dataflows.py`
  - `tests/test_price_action_structure.py`
  - `tests/test_y_finance_retry.py`
  - `tests/test_cli_mt5_execution.py`

---

### Task 1: Runner Summary Store

**Files:**
- Create: `tradingagents/brokers/runner_summary.py`
- Create: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Write failing tests for summary counting and reason categorization**

Add this test file:

```python
import json

from tradingagents.brokers.runner_summary import (
    RunnerSummaryStore,
    categorize_hold_reason,
)


def test_categorize_hold_reason_prefers_structured_stage():
    telemetry = {
        "decision_stage": "higher_timeframe_permission",
        "primary_hold_reason": "H4 blocks BUY",
    }

    assert categorize_hold_reason("The text can be noisy.", telemetry) == "higher_timeframe"


def test_categorize_hold_reason_falls_back_to_text():
    assert categorize_hold_reason("Time filter failed. Default to HOLD.", {}) == "time_filter"
    assert categorize_hold_reason("No valid M15 setup. Default to HOLD.", {}) == "no_m15_setup"
    assert categorize_hold_reason("Insufficient closed OHLCV data.", {}) == "data_health"


def test_runner_summary_records_cycle_and_writes_files(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    result = {
        "status": "NO_TRADE",
        "as_of": "2026-05-29 08:15",
        "proposal": {
            "status": "NO_TRADE",
            "reason": "Time filter failed. Default to HOLD.",
        },
        "analysis": {
            "telemetry": {
                "decision_stage": "time_filter",
                "primary_hold_reason": "Time filter failed. Default to HOLD.",
            },
            "data_status": {
                "healthy": True,
                "timeframes": {
                    "15m": {"available": True, "fresh": True, "rows": 745},
                    "30m": {"available": True, "fresh": True, "rows": 373},
                },
            },
        },
    }

    summary = store.record_cycle(result)

    assert summary["total_checks"] == 1
    assert summary["status_counts"]["NO_TRADE"] == 1
    assert summary["hold_reason_counts"]["time_filter"] == 1
    assert summary["data_health"]["healthy_checks"] == 1
    assert summary["data_health"]["unhealthy_checks"] == 0
    assert store.summary_path.exists()
    assert store.cycles_path.exists()

    written = json.loads(store.summary_path.read_text(encoding="utf-8"))
    assert written["total_checks"] == 1
```

- [ ] **Step 2: Run the failing tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner_summary.py -q
```

Expected: fail with `ModuleNotFoundError: No module named 'tradingagents.brokers.runner_summary'`.

- [ ] **Step 3: Implement the summary store**

Create `tradingagents/brokers/runner_summary.py`:

```python
"""Aggregate MT5 runner cycle summaries."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    return json.loads(path.read_text(encoding="utf-8"))


def categorize_hold_reason(reason: str, telemetry: dict[str, Any] | None = None) -> str:
    telemetry = telemetry or {}
    stage = str(telemetry.get("decision_stage") or "").lower()
    text = " ".join(
        [
            str(reason or ""),
            str(telemetry.get("primary_hold_reason") or ""),
            stage,
        ]
    ).lower()

    if "data" in stage or "insufficient" in text or "stale" in text or "no price data" in text:
        return "data_health"
    if "time" in stage or "session" in text or "last 15" in text or "pre-open" in text:
        return "time_filter"
    if "higher" in stage or "daily blocks" in text or "h4 blocks" in text or "h1 must agree" in text:
        return "higher_timeframe"
    if "m15" in text or "no valid" in text or "playbook setup" in text:
        return "no_m15_setup"
    if "risk" in stage or "clean range" in text or "1.5r" in text:
        return "risk_or_range"
    if "wick" in text:
        return "wick_quality"
    if "active trade" in text:
        return "active_trade"
    if "already processed" in text:
        return "duplicate_candle"
    return "other"


class RunnerSummaryStore:
    """Write one JSON summary and one JSONL cycle log for MT5 runner checks."""

    def __init__(self, results_dir: str | Path) -> None:
        self.runner_dir = Path(results_dir) / "mt5_runner"
        self.runner_dir.mkdir(parents=True, exist_ok=True)
        self.summary_path = self.runner_dir / "summary.json"
        self.cycles_path = self.runner_dir / "cycles.jsonl"

    def _empty_summary(self) -> dict[str, Any]:
        now = _utc_now()
        return {
            "started_at_utc": now,
            "updated_at_utc": now,
            "total_checks": 0,
            "status_counts": {},
            "hold_reason_counts": {},
            "orders_placed": 0,
            "orders_rejected": 0,
            "broker_rejections": 0,
            "data_health": {
                "healthy_checks": 0,
                "unhealthy_checks": 0,
                "latest_status": {},
            },
            "latest_cycle": {},
        }

    def record_cycle(self, result: dict[str, Any]) -> dict[str, Any]:
        summary = _read_json(self.summary_path, self._empty_summary())
        status = str(result.get("status") or "UNKNOWN")
        analysis = result.get("analysis") or {}
        telemetry = analysis.get("telemetry") or {}
        proposal = result.get("proposal") or {}
        reason = str(proposal.get("reason") or telemetry.get("primary_hold_reason") or status)

        status_counts = Counter(summary.get("status_counts", {}))
        status_counts[status] += 1
        summary["status_counts"] = dict(status_counts)
        summary["total_checks"] = int(summary.get("total_checks", 0)) + 1
        summary["updated_at_utc"] = _utc_now()

        if status == "NO_TRADE":
            hold_reason = categorize_hold_reason(reason, telemetry)
            hold_counts = Counter(summary.get("hold_reason_counts", {}))
            hold_counts[hold_reason] += 1
            summary["hold_reason_counts"] = dict(hold_counts)

        execution = result.get("execution") or {}
        if status == "ORDER_PLACED":
            summary["orders_placed"] = int(summary.get("orders_placed", 0)) + 1
        if status == "ORDER_NOT_PLACED":
            summary["orders_rejected"] = int(summary.get("orders_rejected", 0)) + 1
        if execution.get("status") == "REJECTED":
            summary["broker_rejections"] = int(summary.get("broker_rejections", 0)) + 1

        data_status = analysis.get("data_status") or {}
        if data_status:
            data_health = summary.setdefault("data_health", {})
            data_health["latest_status"] = data_status
            if data_status.get("healthy", True):
                data_health["healthy_checks"] = int(data_health.get("healthy_checks", 0)) + 1
            else:
                data_health["unhealthy_checks"] = int(data_health.get("unhealthy_checks", 0)) + 1

        summary["latest_cycle"] = {
            "status": status,
            "as_of": result.get("as_of"),
            "heartbeat_utc": result.get("heartbeat_utc"),
            "hold_reason": categorize_hold_reason(reason, telemetry) if status == "NO_TRADE" else None,
        }
        self._append_cycle(result)
        self._write_summary(summary)
        return summary

    def _append_cycle(self, result: dict[str, Any]) -> None:
        line = json.dumps(result, sort_keys=True, default=str) + "\n"
        with self.cycles_path.open("a", encoding="utf-8") as handle:
            handle.write(line)

    def _write_summary(self, summary: dict[str, Any]) -> None:
        temp_path = self.summary_path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(summary, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        temp_path.replace(self.summary_path)
```

- [ ] **Step 4: Verify Task 1**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner_summary.py -q
```

Expected: `3 passed`.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add tradingagents/brokers/runner_summary.py tests/test_mt5_runner_summary.py
git commit -m "feat: add mt5 runner summary store"
```

---

### Task 2: MT5 Runner Summary Integration And Analysis Metadata

**Files:**
- Modify: `tradingagents/brokers/mt5_runner.py`
- Modify: `cli/main.py`
- Modify: `tests/test_mt5_runner.py`
- Modify: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write failing runner metadata tests**

Append to `tests/test_mt5_runner.py`:

```python
def test_runner_records_summary_for_no_trade_with_analysis_metadata(tmp_path):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: (
            "2026-05-28 10:15",
            proposal,
            {
                "telemetry": {
                    "decision_stage": "higher_timeframe_permission",
                    "primary_hold_reason": "H4 blocks BUY",
                },
                "data_status": {"healthy": True, "timeframes": {}},
            },
        ),
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["analysis"]["telemetry"]["decision_stage"] == "higher_timeframe_permission"
    assert Path(result["summary_path"]).exists()
    summary = Path(result["summary_path"]).read_text(encoding="utf-8")
    assert "higher_timeframe" in summary


def test_runner_keeps_two_tuple_analysis_func_backward_compatible(tmp_path):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["analysis"] == {}
```

- [ ] **Step 2: Run failing runner tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner.py -q
```

Expected: fail because `MT5Runner` currently expects only `(as_of, proposal)` and does not write `summary_path`.

- [ ] **Step 3: Implement metadata parsing and summary recording**

Modify `tradingagents/brokers/mt5_runner.py`:

```python
from tradingagents.brokers.runner_summary import RunnerSummaryStore
```

Add in `__init__` after `self.state_path`:

```python
        self.summary_store = RunnerSummaryStore(config.results_dir)
```

Add this helper method:

```python
    def _parse_analysis_result(self, result) -> tuple[str, OrderProposal, dict]:
        if not isinstance(result, tuple):
            raise ValueError("analysis_func must return a tuple")
        if len(result) == 2:
            as_of, proposal = result
            return as_of, proposal, {}
        if len(result) == 3:
            as_of, proposal, analysis = result
            return as_of, proposal, dict(analysis or {})
        raise ValueError("analysis_func must return (as_of, proposal) or (as_of, proposal, analysis)")
```

Change:

```python
        as_of, proposal = self.analysis_func()
```

to:

```python
        as_of, proposal, analysis = self._parse_analysis_result(self.analysis_func())
```

Add `"analysis": analysis` to both `NO_TRADE` and execution heartbeat payloads. Change `_write_heartbeat` to record the summary:

```python
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
```

- [ ] **Step 4: Return metadata from the CLI runner analysis function**

Modify `_mt5_runner_analysis_func()` in `cli/main.py` so `analyze_once()` returns a third item:

```python
        proposal = load_order_proposal(final_state["order_proposal_path"])
        analysis = {
            "order_proposal_path": final_state.get("order_proposal_path"),
            "price_action_report": final_state.get("price_action_report", ""),
            "trade_plan": final_state.get("trade_plan", ""),
        }
        return selections["as_of"], proposal, analysis
```

Task 4 will enrich this metadata with raw telemetry paths after the raw engine payload writer exists.

- [ ] **Step 5: Verify Task 2**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner.py tests/test_cli_mt5_execution.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 2**

Run:

```powershell
git add tradingagents/brokers/mt5_runner.py cli/main.py tests/test_mt5_runner.py tests/test_cli_mt5_execution.py
git commit -m "feat: record mt5 runner summaries"
```

---

### Task 3: Raw Engine Telemetry In Every Decision Payload

**Files:**
- Modify: `tradingagents/agents/price_action/engine.py`
- Modify: `tests/test_price_action_engine.py`

- [ ] **Step 1: Write failing tests for telemetry on HOLD and SETUP_FOUND**

Append to `tests/test_price_action_engine.py`:

```python
from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.engine import analyze_playbook


def _c(ts, open_, high, low, close, volume=1000):
    return Candle(timestamp=ts, open=open_, high=high, low=low, close=close, volume=volume)


def test_engine_payload_contains_raw_telemetry_for_time_filter_hold():
    data = {
        "1d": [_c("2026-05-27", 100, 102, 99, 101), _c("2026-05-28", 101, 103, 100, 102)],
        "4h": [_c("2026-05-28 00:00", 100, 102, 99, 101), _c("2026-05-28 04:00", 101, 103, 100, 102)],
        "1h": [_c("2026-05-28 08:00", 100, 102, 99, 101), _c("2026-05-28 09:00", 101, 103, 100, 102)],
        "30m": [_c("2026-05-28 09:00", 100, 102, 99, 101), _c("2026-05-28 09:30", 101, 103, 100, 102)],
        "15m": [_c("2026-05-28 09:30", 100, 102, 99, 101), _c("2026-05-28 09:45", 101, 103, 100, 102)],
    }

    payload = analyze_playbook("GC=F", "2026-05-28 07:45", data)

    assert payload["status"] == "NO_SETUP"
    assert payload["telemetry"]["decision_stage"] == "time_filter"
    assert payload["telemetry"]["primary_hold_reason"] == "Time filter failed. Default to HOLD."
    assert payload["telemetry"]["timeframe_rows"]["15m"] == 2
    assert payload["telemetry"]["zone_counts"]["4h"] >= 0


def test_engine_payload_contains_permission_telemetry_when_candidate_is_blocked():
    data = {
        "1d": [_c("2026-05-27", 100, 102, 99, 101), _c("2026-05-28", 101, 103, 100, 102)],
        "4h": [
            _c("2026-05-28 00:00", 110, 111, 105, 106),
            _c("2026-05-28 04:00", 106, 107, 100, 101),
            _c("2026-05-28 08:00", 101, 102, 98, 99),
        ],
        "1h": [_c("2026-05-28 08:00", 100, 102, 99, 101), _c("2026-05-28 09:00", 101, 103, 100, 102)],
        "30m": [
            _c("2026-05-28 08:30", 100, 101, 99, 100),
            _c("2026-05-28 09:00", 100, 103, 99, 102),
            _c("2026-05-28 09:30", 102, 106, 101, 105),
        ],
        "15m": [
            _c("2026-05-28 09:15", 103, 104, 101, 103),
            _c("2026-05-28 09:30", 103, 106, 101, 105),
            _c("2026-05-28 09:45", 105, 106, 103, 105.5),
        ],
    }

    payload = analyze_playbook("GC=F", "2026-05-28 08:15", data)

    assert "telemetry" in payload
    assert "timeframe_rows" in payload["telemetry"]
    assert "permissions" in payload["telemetry"]
```

- [ ] **Step 2: Run failing engine telemetry tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_engine.py -q
```

Expected: fail because payloads do not yet include `telemetry`.

- [ ] **Step 3: Add telemetry helpers**

Modify `tradingagents/agents/price_action/engine.py`:

```python
def _rows_by_timeframe(candles_by_tf: dict[str, list[Candle]]) -> dict[str, int]:
    return {tf: len(candles_by_tf.get(tf, [])) for tf in ("1d", "4h", "1h", "30m", "15m")}


def _zone_counts(zones_by_tf: dict[str, list[Zone]]) -> dict[str, int]:
    return {tf: len(zones_by_tf.get(tf, [])) for tf in ("1d", "4h", "1h", "30m")}


def _telemetry(
    *,
    decision_stage: str,
    primary_hold_reason: str,
    candles_by_tf: dict[str, list[Candle]],
    zones_by_tf: dict[str, list[Zone]],
    market_context: dict[str, Any],
    candidate_setups: list[Setup] | None = None,
) -> dict[str, Any]:
    return {
        "decision_stage": decision_stage,
        "primary_hold_reason": primary_hold_reason,
        "timeframe_rows": _rows_by_timeframe(candles_by_tf),
        "zone_counts": _zone_counts(zones_by_tf),
        "permissions": {
            "daily": market_context.get("daily_permission"),
            "h4": market_context.get("h4_permission"),
            "h1": market_context.get("h1_permission"),
            "higher_timeframe": market_context.get("higher_timeframe_permission"),
        },
        "m30_context": {
            "bias": market_context.get("m30_bias"),
            "context": market_context.get("m30_context"),
        },
        "candidate_setup_count": len(candidate_setups or []),
    }
```

Update `_payload(...)` signature to accept `telemetry: dict[str, Any] | None = None`, then include:

```python
        "telemetry": telemetry or {},
```

Pass explicit telemetry in every return:

```python
telemetry=_telemetry(
    decision_stage="time_filter",
    primary_hold_reason="Time filter failed. Default to HOLD.",
    candles_by_tf=candles_by_tf,
    zones_by_tf=zones_by_tf,
    market_context=market_context,
)
```

Use these stage names:

- `time_filter`
- `data_insufficient`
- `no_m15_setup`
- `higher_timeframe_permission`
- `a_plus_checklist`
- `setup_found`

- [ ] **Step 4: Verify Task 3**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_engine.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add tradingagents/agents/price_action/engine.py tests/test_price_action_engine.py
git commit -m "feat: emit raw price action telemetry"
```

---

### Task 4: Persist Raw Engine Payloads And Attach Them To Runner Metadata

**Files:**
- Modify: `tradingagents/agents/utils/price_action_tools.py`
- Modify: `cli/main.py`
- Modify: `tests/test_price_action_tools.py`

- [ ] **Step 1: Write failing telemetry persistence test**

Append to `tests/test_price_action_tools.py`:

```python
import json

from tradingagents.agents.utils import price_action_tools


def test_engine_payload_writer_persists_raw_json(tmp_path):
    payload = {
        "symbol": "GC=F",
        "as_of": "2026-05-29 08:15",
        "status": "NO_SETUP",
        "recommendation": "HOLD",
        "telemetry": {"decision_stage": "time_filter"},
    }

    path = price_action_tools.write_engine_payload(payload, tmp_path)

    assert path.exists()
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["telemetry"]["decision_stage"] == "time_filter"
    assert "GC=F" not in path.name
```

- [ ] **Step 2: Run the failing persistence test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_tools.py::test_engine_payload_writer_persists_raw_json -q
```

Expected: fail because `write_engine_payload` does not exist.

- [ ] **Step 3: Implement raw payload writer**

Add imports in `tradingagents/agents/utils/price_action_tools.py`:

```python
import re
from pathlib import Path

from tradingagents.dataflows.utils import safe_ticker_component
```

Add helper:

```python
def _safe_as_of_component(as_of: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]+", "_", str(as_of)).strip("_") or "unknown"


def write_engine_payload(payload: Dict[str, Any], results_dir: str | Path) -> Path:
    symbol = safe_ticker_component(str(payload["symbol"]))
    safe_as_of = _safe_as_of_component(str(payload.get("as_of", "unknown")))
    directory = Path(results_dir) / symbol / "engine_telemetry"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"engine_payload_{safe_as_of}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path
```

In `get_playbook_setups(...)`, after the engine payload is created and before `return json.dumps(...)`, write the payload:

```python
            from tradingagents.default_config import DEFAULT_CONFIG

            telemetry_path = write_engine_payload(payload, DEFAULT_CONFIG["results_dir"])
            payload["telemetry_path"] = str(telemetry_path)
```

Also write fallback `NO_SETUP` payloads before returning.

- [ ] **Step 4: Attach telemetry path to CLI runner metadata**

Modify `_mt5_runner_analysis_func()` in `cli/main.py`. After `final_state` is available, extract telemetry path from the analyst report if present is not reliable, so read the newest payload matching `selections["as_of"]`:

```python
        from tradingagents.dataflows.utils import safe_ticker_component
        import re

        safe_symbol = safe_ticker_component(selections["ticker"])
        safe_as_of = re.sub(r"[^0-9A-Za-z_-]+", "_", selections["as_of"]).strip("_")
        telemetry_path = (
            Path(DEFAULT_CONFIG["results_dir"])
            / safe_symbol
            / "engine_telemetry"
            / f"engine_payload_{safe_as_of}.json"
        )
        engine_payload = {}
        if telemetry_path.exists():
            engine_payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
        analysis = {
            "order_proposal_path": final_state.get("order_proposal_path"),
            "telemetry_path": str(telemetry_path) if telemetry_path.exists() else None,
            "telemetry": engine_payload.get("telemetry", {}),
            "data_status": engine_payload.get("data_status", {}),
            "price_action_report": final_state.get("price_action_report", ""),
            "trade_plan": final_state.get("trade_plan", ""),
        }
```

- [ ] **Step 5: Verify Task 4**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_tools.py tests/test_cli_mt5_execution.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit Task 4**

Run:

```powershell
git add tradingagents/agents/utils/price_action_tools.py cli/main.py tests/test_price_action_tools.py tests/test_cli_mt5_execution.py
git commit -m "feat: persist raw engine telemetry"
```

---

### Task 5: Data Freshness Health Checks

**Files:**
- Create: `tradingagents/dataflows/data_health.py`
- Modify: `tradingagents/dataflows/price_action.py`
- Modify: `tradingagents/agents/utils/price_action_tools.py`
- Create: `tests/test_price_action_data_health.py`
- Modify: `tests/test_price_action_dataflows.py`

- [ ] **Step 1: Write failing data health tests**

Create `tests/test_price_action_data_health.py`:

```python
from tradingagents.agents.price_action.models import Candle
from tradingagents.dataflows.data_health import build_data_status, data_is_healthy


def _c(ts):
    return Candle(timestamp=ts, open=1, high=2, low=0.5, close=1.5, volume=100)


def test_data_status_marks_required_timeframes_fresh():
    frames = {
        "1d": [_c("2026-05-29")],
        "4h": [_c("2026-05-29 08:00:00")],
        "1h": [_c("2026-05-29 08:00:00")],
        "30m": [_c("2026-05-29 08:00:00")],
        "15m": [_c("2026-05-29 08:00:00")],
    }

    status = build_data_status(frames, "2026-05-29 08:15", "America/New_York")

    assert status["healthy"] is True
    assert status["timeframes"]["15m"]["fresh"] is True
    assert status["timeframes"]["15m"]["latest_age_minutes"] == 15
    assert data_is_healthy(status) is True


def test_data_status_blocks_stale_required_intraday_timeframe():
    frames = {
        "1d": [_c("2026-05-29")],
        "4h": [_c("2026-05-29 04:00:00")],
        "1h": [_c("2026-05-29 07:00:00")],
        "30m": [_c("2026-05-29 07:00:00")],
        "15m": [_c("2026-05-29 06:00:00")],
    }

    status = build_data_status(frames, "2026-05-29 08:15", "America/New_York")

    assert status["healthy"] is False
    assert status["timeframes"]["15m"]["fresh"] is False
    assert "15m" in status["blocking_timeframes"]
```

- [ ] **Step 2: Run failing data health tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_data_health.py -q
```

Expected: fail because `tradingagents.dataflows.data_health` does not exist.

- [ ] **Step 3: Implement data health module**

Create `tradingagents/dataflows/data_health.py`:

```python
"""Data availability and freshness checks for price-action timeframes."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


MAX_AGE_MINUTES = {
    "1d": 4320,
    "4h": 480,
    "1h": 180,
    "30m": 90,
    "15m": 45,
}

REQUIRED_TIMEFRAMES = ("1d", "4h", "1h", "30m", "15m")


def _parse_timestamp(value: Any, market_timezone: str) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip().replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    tz = ZoneInfo(market_timezone)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _latest_timestamp(candles: list[Any], market_timezone: str) -> datetime | None:
    if not candles:
        return None
    latest = getattr(candles[-1], "timestamp", None)
    return _parse_timestamp(latest, market_timezone)


def build_data_status(
    timeframe_data: dict[str, list[Any]],
    as_of: str,
    market_timezone: str,
) -> dict[str, Any]:
    as_of_dt = _parse_timestamp(as_of, market_timezone)
    statuses: dict[str, dict[str, Any]] = {}
    blocking: list[str] = []

    for timeframe in REQUIRED_TIMEFRAMES:
        candles = timeframe_data.get(timeframe, [])
        latest = _latest_timestamp(candles, market_timezone)
        available = bool(candles)
        age_minutes = None
        fresh = False
        if as_of_dt is not None and latest is not None:
            age_minutes = int((as_of_dt - latest).total_seconds() // 60)
            fresh = 0 <= age_minutes <= MAX_AGE_MINUTES[timeframe]
        status = {
            "interval": timeframe,
            "available": available,
            "rows": len(candles),
            "latest_timestamp": latest.isoformat() if latest else None,
            "latest_age_minutes": age_minutes,
            "fresh": fresh,
            "max_age_minutes": MAX_AGE_MINUTES[timeframe],
        }
        statuses[timeframe] = status
        if not available or not fresh:
            blocking.append(timeframe)

    return {
        "healthy": not blocking,
        "blocking_timeframes": blocking,
        "timeframes": statuses,
        "trading_timeframe": statuses["15m"],
        "confirmation_timeframe": statuses["30m"],
    }


def data_is_healthy(status: dict[str, Any]) -> bool:
    return bool(status.get("healthy"))
```

- [ ] **Step 4: Add snapshot fetch while preserving old API**

Modify `tradingagents/dataflows/price_action.py`:

```python
from dataclasses import dataclass
from typing import Any

from tradingagents.dataflows.data_health import build_data_status


@dataclass(frozen=True)
class PriceActionSnapshot:
    candles: dict[str, list[Candle]]
    data_status: dict[str, Any]
```

Add:

```python
def fetch_price_action_snapshot(
    symbol: str,
    *,
    as_of: str,
    market_timezone: str = "America/New_York",
) -> PriceActionSnapshot:
    candles = fetch_price_action_timeframes(symbol)
    return PriceActionSnapshot(
        candles=candles,
        data_status=build_data_status(candles, as_of, market_timezone),
    )
```

Keep existing `fetch_price_action_timeframes(symbol)` returning only the candle dict so current tests and callers stay compatible.

- [ ] **Step 5: Use health status in `get_playbook_setups`**

Modify `tradingagents/agents/utils/price_action_tools.py` to import:

```python
from tradingagents.dataflows.data_health import data_is_healthy
from tradingagents.dataflows.price_action import fetch_price_action_snapshot
```

Inside `get_playbook_setups(...)`, replace direct timeframe fetching with:

```python
        snapshot = fetch_price_action_snapshot(
            symbol,
            as_of=as_of,
            market_timezone=market_timezone,
        )
        timeframe_data = snapshot.candles
        data_status = snapshot.data_status
        if not data_is_healthy(data_status):
            payload = build_no_setup_payload(
                symbol,
                as_of,
                timeframe,
                confirmation_timeframe,
                data_status=data_status,
            )
            payload["message"] = "Data health failed. Default to HOLD."
            telemetry_path = write_engine_payload(payload, DEFAULT_CONFIG["results_dir"])
            payload["telemetry_path"] = str(telemetry_path)
            return json.dumps(payload, indent=2, sort_keys=True)
```

Then run `analyze_top_down_playbook(...)` only when data is healthy.

- [ ] **Step 6: Verify Task 5**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_data_health.py tests/test_price_action_dataflows.py tests/test_price_action_tools.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 5**

Run:

```powershell
git add tradingagents/dataflows/data_health.py tradingagents/dataflows/price_action.py tradingagents/agents/utils/price_action_tools.py tests/test_price_action_data_health.py tests/test_price_action_dataflows.py tests/test_price_action_tools.py
git commit -m "feat: add price action data health checks"
```

---

### Task 6: yfinance Retry Behavior For Intermittent Gaps

**Files:**
- Modify: `tradingagents/dataflows/y_finance.py`
- Create: `tests/test_y_finance_retry.py`

- [ ] **Step 1: Write failing retry tests**

Create `tests/test_y_finance_retry.py`:

```python
import pandas as pd

from tradingagents.dataflows import y_finance


class FakeTicker:
    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0

    def history(self, **kwargs):
        self.calls += 1
        return self.frames.pop(0)


def _frame():
    index = pd.DatetimeIndex(["2026-05-29 08:00:00"])
    return pd.DataFrame(
        {
            "Open": [1.0],
            "High": [2.0],
            "Low": [0.5],
            "Close": [1.5],
            "Volume": [100],
        },
        index=index,
    )


def test_yfinance_intraday_retries_empty_response(monkeypatch):
    fake = FakeTicker([pd.DataFrame(), _frame()])
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: fake)
    monkeypatch.setattr(y_finance.time, "sleep", lambda seconds: None)

    text = y_finance.get_YFin_intraday_data("GC=F", period="10d", interval="15m")

    assert fake.calls == 2
    assert "# yfinance attempts: 2" in text
    assert "No data found" not in text


def test_yfinance_intraday_returns_no_data_after_all_attempts(monkeypatch):
    fake = FakeTicker([pd.DataFrame(), pd.DataFrame(), pd.DataFrame()])
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: fake)
    monkeypatch.setattr(y_finance.time, "sleep", lambda seconds: None)

    text = y_finance.get_YFin_intraday_data("GC=F", period="10d", interval="15m")

    assert fake.calls == 3
    assert "No data found for symbol 'GC=F'" in text
    assert "attempts=3" in text
```

- [ ] **Step 2: Run failing retry tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_y_finance_retry.py -q
```

Expected: fail because `y_finance` does not retry and does not import `time`.

- [ ] **Step 3: Implement retry loop**

Modify `tradingagents/dataflows/y_finance.py`:

```python
import time
```

Add:

```python
def _history_with_retries(ticker, *, attempts: int = 3, delay_seconds: float = 0.5, **kwargs):
    last_data = None
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            data = ticker.history(**kwargs)
            last_data = data
            if not data.empty:
                return data, attempt, None
        except Exception as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(delay_seconds)
    if last_error is not None and last_data is None:
        raise last_error
    return last_data, attempts, last_error
```

Change `_format_history(...)` signature:

```python
def _format_history(symbol: str, data, source_note: str, attempts: int = 1) -> str:
```

Change empty response:

```python
        return f"No data found for symbol '{symbol}' ({source_note}, attempts={attempts})"
```

Add attempt comment before CSV:

```python
    header += f"# yfinance attempts: {attempts}\n"
```

Modify `get_YFin_data_online(...)` and `get_YFin_intraday_data(...)` to call `_history_with_retries(...)` and pass `attempts=attempts`.

- [ ] **Step 4: Verify Task 6**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_y_finance_retry.py tests/test_price_action_dataflows.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 6**

Run:

```powershell
git add tradingagents/dataflows/y_finance.py tests/test_y_finance_retry.py
git commit -m "feat: retry intermittent yfinance gaps"
```

---

### Task 7: Structure-Aware Daily, 4H, And 1H Classification

**Files:**
- Modify: `tradingagents/agents/price_action/structure.py`
- Modify: `tests/test_price_action_structure.py`

- [ ] **Step 1: Write failing structure tests**

Append to `tests/test_price_action_structure.py`:

```python
from tradingagents.agents.price_action.models import Candle, Zone
from tradingagents.agents.price_action.structure import (
    classify_timeframe_structure,
    evaluate_higher_timeframe_permission,
)


def _c(ts, open_, high, low, close):
    return Candle(timestamp=ts, open=open_, high=high, low=low, close=close, volume=100)


def _zone(kind, low, high, score=20):
    return Zone(
        type=kind,
        timeframe="4h",
        low=low,
        high=high,
        midpoint=(low + high) / 2,
        touches=3,
        score=score,
        source="test",
        reactions=[],
    )


def test_classify_timeframe_structure_detects_bullish_higher_highs_and_lows():
    candles = [
        _c("1", 100, 105, 99, 104),
        _c("2", 104, 106, 101, 102),
        _c("3", 102, 110, 101, 109),
        _c("4", 109, 111, 104, 105),
        _c("5", 105, 114, 105, 113),
    ]

    result = classify_timeframe_structure(candles, [], "4h")

    assert result["classification"] == "BULLISH_STRUCTURE"
    assert result["permission"] == "BUY_ALLOWED"


def test_classify_timeframe_structure_detects_bearish_structure():
    candles = [
        _c("1", 120, 121, 115, 116),
        _c("2", 116, 118, 112, 117),
        _c("3", 117, 118, 109, 110),
        _c("4", 110, 113, 106, 112),
        _c("5", 112, 113, 101, 102),
    ]

    result = classify_timeframe_structure(candles, [], "4h")

    assert result["classification"] == "BEARISH_STRUCTURE"
    assert result["permission"] == "SELL_ALLOWED"


def test_classify_timeframe_structure_marks_near_major_support_as_neutral_buy_context():
    candles = [
        _c("1", 105, 108, 101, 106),
        _c("2", 106, 109, 100, 102),
        _c("3", 102, 107, 99.5, 106),
    ]
    zones = [_zone("support", 99, 101)]

    result = classify_timeframe_structure(candles, zones, "4h")

    assert result["classification"] == "NEAR_MAJOR_SUPPORT"
    assert result["permission"] == "NEUTRAL"


def test_higher_timeframe_permission_allows_buy_when_4h_neutral_and_1h_agrees():
    daily = {"permission": "NEUTRAL", "classification": "RANGE", "reason": "Daily neutral"}
    h4 = {"permission": "NEUTRAL", "classification": "NEAR_MAJOR_SUPPORT", "reason": "4H support"}
    h1 = {"permission": "BUY_ALLOWED", "classification": "BULLISH_STRUCTURE", "reason": "1H bullish"}

    result = evaluate_higher_timeframe_permission(daily, h4, h1, "BUY")

    assert result["permission"] == "BUY_ALLOWED"
    assert result["reason"] == "Higher timeframes permit BUY"


def test_higher_timeframe_permission_blocks_buy_when_4h_clearly_bearish():
    daily = {"permission": "NEUTRAL", "classification": "RANGE", "reason": "Daily neutral"}
    h4 = {"permission": "SELL_ALLOWED", "classification": "BEARISH_STRUCTURE", "reason": "4H bearish"}
    h1 = {"permission": "BUY_ALLOWED", "classification": "BULLISH_STRUCTURE", "reason": "1H bullish"}

    result = evaluate_higher_timeframe_permission(daily, h4, h1, "BUY")

    assert result["permission"] == "NO_TRADE"
    assert result["reason"] == "4H blocks BUY"


def test_higher_timeframe_permission_blocks_when_1h_is_unclear():
    daily = {"permission": "NEUTRAL", "classification": "RANGE", "reason": "Daily neutral"}
    h4 = {"permission": "NEUTRAL", "classification": "RANGE", "reason": "4H neutral"}
    h1 = {"permission": "NEUTRAL", "classification": "UNCLEAR", "reason": "1H unclear"}

    result = evaluate_higher_timeframe_permission(daily, h4, h1, "SELL")

    assert result["permission"] == "NO_TRADE"
    assert result["reason"] == "1H must agree with SELL"
```

- [ ] **Step 2: Run failing structure tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_structure.py -q
```

Expected: fail because `classify_timeframe_structure` does not exist and `evaluate_higher_timeframe_permission` only accepts strings.

- [ ] **Step 3: Implement structure classifier**

Modify `tradingagents/agents/price_action/structure.py` with these helpers while keeping existing `determine_m30_bias`:

```python
from tradingagents.agents.price_action.models import Candle, Zone


STRUCTURE_CLASSIFICATIONS = {
    "BULLISH_STRUCTURE",
    "BEARISH_STRUCTURE",
    "RANGE",
    "NEAR_MAJOR_SUPPORT",
    "NEAR_MAJOR_RESISTANCE",
    "BREAK_OF_STRUCTURE_UP",
    "BREAK_OF_STRUCTURE_DOWN",
    "UNCLEAR",
}


def _permission_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("permission") or "NEUTRAL").upper()
    return str(value or "NEUTRAL").upper()


def _classification_value(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("classification") or "UNCLEAR").upper()
    return str(value or "UNCLEAR").upper()


def _recent_direction(candles: list[Candle]) -> str:
    if len(candles) < 3:
        return "UNCLEAR"
    recent = candles[-5:]
    highs = [float(candle.high) for candle in recent]
    lows = [float(candle.low) for candle in recent]
    closes = [float(candle.close) for candle in recent]
    higher_highs = highs[-1] > highs[0] and max(highs[-2:]) > max(highs[:2])
    higher_lows = lows[-1] > lows[0] and min(lows[-2:]) > min(lows[:2])
    lower_highs = highs[-1] < highs[0] and max(highs[-2:]) < max(highs[:2])
    lower_lows = lows[-1] < lows[0] and min(lows[-2:]) < min(lows[:2])
    if higher_highs and higher_lows and closes[-1] > closes[0]:
        return "BULLISH_STRUCTURE"
    if lower_highs and lower_lows and closes[-1] < closes[0]:
        return "BEARISH_STRUCTURE"
    return "UNCLEAR"


def _near_zone(candle: Candle, zones: list[Zone], zone_type: str) -> Zone | None:
    if not zones:
        return None
    price = float(candle.close)
    candidates = [zone for zone in zones if zone.type == zone_type]
    for zone in sorted(candidates, key=lambda item: item.score, reverse=True):
        width = max(float(zone.high) - float(zone.low), 0.01)
        tolerance = max(width, abs(price) * 0.001)
        if float(zone.low) - tolerance <= price <= float(zone.high) + tolerance:
            return zone
    return None


def _permission_for_classification(classification: str) -> str:
    if classification in {"BULLISH_STRUCTURE", "BREAK_OF_STRUCTURE_UP"}:
        return "BUY_ALLOWED"
    if classification in {"BEARISH_STRUCTURE", "BREAK_OF_STRUCTURE_DOWN"}:
        return "SELL_ALLOWED"
    return "NEUTRAL"


def classify_timeframe_structure(
    candles: list[Candle],
    zones: list[Zone],
    timeframe: str,
) -> dict[str, Any]:
    if len(candles) < 2:
        return {
            "timeframe": timeframe,
            "classification": "UNCLEAR",
            "permission": "NEUTRAL",
            "reason": f"{timeframe} has insufficient structure candles",
        }

    latest = candles[-1]
    resistance = _near_zone(latest, zones, "resistance")
    support = _near_zone(latest, zones, "support")
    if resistance is not None:
        classification = "NEAR_MAJOR_RESISTANCE"
    elif support is not None:
        classification = "NEAR_MAJOR_SUPPORT"
    else:
        classification = _recent_direction(candles)

    if classification == "UNCLEAR" and zones:
        classification = "RANGE"

    permission = _permission_for_classification(classification)
    return {
        "timeframe": timeframe,
        "classification": classification,
        "permission": permission,
        "reason": f"{timeframe} classified as {classification}",
        "latest_close": float(latest.close),
    }
```

Replace `evaluate_higher_timeframe_permission(...)` with a backward-compatible version:

```python
def evaluate_higher_timeframe_permission(
    daily: Any,
    h4: Any,
    h1: Any,
    planned_direction: str,
) -> dict[str, str]:
    direction = str(planned_direction).strip().upper()
    opposite = _opposite(direction)

    daily_permission = _permission_value(daily)
    h4_permission = _permission_value(h4)
    h1_permission = _permission_value(h1)

    if daily_permission == _allowed(opposite):
        return {"permission": "NO_TRADE", "reason": f"Daily blocks {direction}"}
    if h4_permission == _allowed(opposite):
        return {"permission": "NO_TRADE", "reason": f"4H blocks {direction}"}
    if h1_permission != _allowed(direction):
        return {"permission": "NO_TRADE", "reason": f"1H must agree with {direction}"}
    return {"permission": _allowed(direction), "reason": f"Higher timeframes permit {direction}"}
```

- [ ] **Step 4: Verify Task 7**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_structure.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 7**

Run:

```powershell
git add tradingagents/agents/price_action/structure.py tests/test_price_action_structure.py
git commit -m "feat: classify higher timeframe structure"
```

---

### Task 8: Integrate Structure-Aware Permission Into The Engine

**Files:**
- Modify: `tradingagents/agents/price_action/engine.py`
- Modify: `tests/test_price_action_engine.py`

- [ ] **Step 1: Write failing engine integration tests**

Append to `tests/test_price_action_engine.py`:

```python
def test_engine_market_context_includes_structure_objects():
    data = {
        "1d": [_c("2026-05-27", 100, 103, 99, 102), _c("2026-05-28", 102, 104, 100, 103)],
        "4h": [
            _c("2026-05-28 00:00", 100, 105, 99, 104),
            _c("2026-05-28 04:00", 104, 106, 101, 102),
            _c("2026-05-28 08:00", 102, 110, 101, 109),
            _c("2026-05-28 12:00", 109, 111, 104, 105),
            _c("2026-05-28 16:00", 105, 114, 105, 113),
        ],
        "1h": [
            _c("2026-05-28 12:00", 100, 105, 99, 104),
            _c("2026-05-28 13:00", 104, 106, 101, 102),
            _c("2026-05-28 14:00", 102, 110, 101, 109),
            _c("2026-05-28 15:00", 109, 111, 104, 105),
            _c("2026-05-28 16:00", 105, 114, 105, 113),
        ],
        "30m": [_c("2026-05-28 15:30", 100, 102, 99, 101), _c("2026-05-28 16:00", 101, 103, 100, 102)],
        "15m": [_c("2026-05-28 15:45", 100, 102, 99, 101), _c("2026-05-28 16:00", 101, 103, 100, 102)],
    }

    payload = analyze_playbook("GC=F", "2026-05-28 08:15", data)

    assert "daily_structure" in payload["market_context"]
    assert "h4_structure" in payload["market_context"]
    assert "h1_structure" in payload["market_context"]
    assert payload["market_context"]["h4_structure"]["classification"] in {
        "BULLISH_STRUCTURE",
        "BEARISH_STRUCTURE",
        "RANGE",
        "NEAR_MAJOR_SUPPORT",
        "NEAR_MAJOR_RESISTANCE",
        "UNCLEAR",
    }
```

- [ ] **Step 2: Run failing engine integration test**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_engine.py::test_engine_market_context_includes_structure_objects -q
```

Expected: fail because market context only includes string permissions.

- [ ] **Step 3: Replace permission proxy in engine**

Modify imports in `tradingagents/agents/price_action/engine.py`:

```python
from tradingagents.agents.price_action.structure import (
    classify_timeframe_structure,
    determine_m30_bias,
    evaluate_higher_timeframe_permission,
)
```

Remove `_permission_from_candles(...)`.

Before `market_context = {...}`, compute:

```python
    daily_structure = classify_timeframe_structure(
        candles_by_tf.get("1d", []),
        zones_by_tf.get("1d", []),
        "Daily",
    )
    h4_structure = classify_timeframe_structure(
        candles_by_tf.get("4h", []),
        zones_by_tf.get("4h", []),
        "4H",
    )
    h1_structure = classify_timeframe_structure(
        candles_by_tf.get("1h", []),
        zones_by_tf.get("1h", []),
        "1H",
    )
```

Set market context:

```python
    market_context = {
        **m30_context,
        "daily_structure": daily_structure,
        "h4_structure": h4_structure,
        "h1_structure": h1_structure,
        "daily_permission": daily_structure["permission"],
        "h4_permission": h4_structure["permission"],
        "h1_permission": h1_structure["permission"],
        "range": classify_range(m30, m30_zones),
    }
```

Change permission evaluation:

```python
    higher_permission = evaluate_higher_timeframe_permission(
        daily_structure,
        h4_structure,
        h1_structure,
        setup.direction,
    )
```

- [ ] **Step 4: Verify Task 8**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_engine.py tests/test_price_action_structure.py tests/test_price_action_tools.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 8**

Run:

```powershell
git add tradingagents/agents/price_action/engine.py tests/test_price_action_engine.py
git commit -m "feat: use structure-aware higher timeframe permission"
```

---

### Task 9: Documentation And Final Verification

**Files:**
- Modify: `docs/playbook.md`
- Modify: `docs/mt5-demo-windows.md`
- Modify: `docs/windows-agent-handoff.md`

- [ ] **Step 1: Document the implemented runtime behavior**

Add a short section to `docs/windows-agent-handoff.md` after the runner section:

```markdown
## Runner Observability

Each `tradingagents mt5-run` cycle writes:

- `~/.tradingagents/logs/mt5_runner/heartbeat.json`
- `~/.tradingagents/logs/mt5_runner/summary.json`
- `~/.tradingagents/logs/mt5_runner/cycles.jsonl`
- `~/.tradingagents/logs/<analysis-symbol>/engine_telemetry/engine_payload_<as-of>.json`

Use `summary.json` after a live demo test to review total checks, HOLD reasons, order placement/rejection counts, and data health.
```

Add a short section to `docs/playbook.md` under `4-Hour Chart`:

```markdown
Implementation note:

The bot should classify 4H structure before granting permission. 4H can agree, be neutral, or block. Neutral/ranging 4H does not automatically block a trade, but 1H must agree and M30/M15 must align before entry.
```

- [ ] **Step 2: Run focused verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner_summary.py tests/test_mt5_runner.py tests/test_price_action_engine.py tests/test_price_action_structure.py tests/test_price_action_data_health.py tests/test_price_action_dataflows.py tests/test_price_action_tools.py tests/test_y_finance_retry.py tests/test_cli_mt5_execution.py -q
```

Expected: all listed tests pass.

- [ ] **Step 3: Run broader safe verification**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_import_smoke.py tests/test_model_validation.py tests/test_order_proposal.py tests/test_cli_config.py tests/test_mt5_broker.py tests/test_mt5_execution.py -q
```

Expected: all listed tests pass.

- [ ] **Step 4: Run one dry MT5 runner cycle**

Run with `.env` still set to dry run:

```powershell
.\.venv\Scripts\tradingagents.exe mt5-run --once
```

Expected:

- The command exits with code `0`.
- `~/.tradingagents/logs/mt5_runner/heartbeat.json` exists.
- `~/.tradingagents/logs/mt5_runner/summary.json` exists.
- If the cycle is `NO_TRADE`, `summary.json` includes a categorized HOLD reason.
- No broker order is sent unless `.env` has `TRADINGAGENTS_MT5_EXECUTION_MODE=broker` and the proposal is `PROPOSED`.

- [ ] **Step 5: Commit Task 9**

Run:

```powershell
git add docs/playbook.md docs/mt5-demo-windows.md docs/windows-agent-handoff.md
git commit -m "docs: document runner telemetry and structure permission"
```

---

## Final Acceptance Checklist

- [ ] Runner writes `summary.json` and `cycles.jsonl` for every cycle.
- [ ] Heartbeat includes `summary_path`.
- [ ] `NO_TRADE` cycles are grouped into readable HOLD reason categories.
- [ ] Engine payload includes `telemetry` on every decision path.
- [ ] Raw engine payload JSON is persisted under the analysis symbol logs.
- [ ] Data health marks unavailable or stale 15m/30m data as blocking.
- [ ] yfinance retries empty intermittent responses before returning `No data found`.
- [ ] Daily, 4H, and 1H market context includes structure objects.
- [ ] 4H can agree, be neutral, or block; it does not block merely because it is neutral.
- [ ] 1H must agree with the planned direction.
- [ ] M30/M15 correlation remains mandatory.
- [ ] Existing dry-run and broker guards still pass.

## Self-Review Notes

Spec coverage:

- Runner summary reporting is covered by Tasks 1 and 2.
- Raw engine telemetry is covered by Tasks 3 and 4.
- Data freshness checks are covered by Task 5.
- yfinance retry behavior is covered by Task 6.
- Structure-aware higher-timeframe permission is covered by Tasks 7 and 8.
- Documentation and verification are covered by Task 9.

Placeholder scan:

- This plan contains exact file targets, test names, expected failures, implementation snippets, and verification commands.
- No step requires an unspecified design decision during implementation.

Type consistency:

- `analysis_func` stays backward compatible with the existing `(as_of, proposal)` tuple and adds optional `(as_of, proposal, analysis)`.
- `evaluate_higher_timeframe_permission` stays backward compatible with existing string permissions and adds dict-based structure support.
- `fetch_price_action_timeframes(symbol)` remains backward compatible; `fetch_price_action_snapshot(...)` is additive.
