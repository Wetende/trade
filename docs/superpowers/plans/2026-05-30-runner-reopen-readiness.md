# Runner Reopen Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the MT5 runner reliable before market reopen by fixing proxy pollution, YFinance cache/timezone behavior, data-health false blocks, LLM-runner crash handling, and temporary runtime cleanup.

**Architecture:** Keep the normal `tradingagents mt5-run` path as the main entrypoint. Add small focused helpers at the data/vendor boundary and runner boundary so failures become visible `NO_TRADE`/`RUNNER_ERROR` telemetry instead of dead background processes. Do not loosen trade approval rules; these changes only make scanning and evidence collection reliable.

**Tech Stack:** Python 3.13, Typer CLI, yfinance, MetaTrader5 bridge, pytest, existing `MT5Runner`, `RunnerSummaryStore`, and price-action data-health modules.

---

## File Structure

- Modify: `tradingagents/dataflows/y_finance.py`
  - Owns YFinance fetch behavior, retry behavior, proxy cleanup, timezone formatting, and cache location setup.
- Modify: `tradingagents/dataflows/data_health.py`
  - Owns freshness rules for Daily, 4H, 1H, 30M, and 15M candles.
- Modify: `tradingagents/brokers/mt5_runner.py`
  - Owns unattended loop behavior and heartbeat persistence.
- Modify: `cli/main.py`
  - Owns CLI options and runner construction.
- Modify: `tradingagents/default_config.py`
  - Owns environment-based runner configuration.
- Modify: `tests/test_y_finance_retry.py`
  - Covers YFinance retry, cache, proxy, and timezone behavior.
- Modify: `tests/test_price_action_data_health.py`
  - Covers freshness and timestamp drift behavior.
- Modify: `tests/test_mt5_runner.py`
  - Covers runner exception handling and runtime stop behavior.
- Modify: `tests/test_cli_mt5_execution.py`
  - Covers CLI duration wiring and visible help text.
- Modify: `docs/windows-agent-handoff.md`
  - Documents the clean launch commands and expected telemetry.
- Modify: `docs/mt5-windows-vps.md`
  - Documents market reopen test readiness and duration option.
- Remove or ignore: `runtime/`
  - Runtime artifacts should not be tracked as source code.

---

### Task 1: Clean Temporary Runtime Artifacts

**Files:**
- Modify: `.gitignore`
- Delete: `runtime/deterministic_mt5_runner.py`
- Leave untracked local run logs on disk if needed, but keep them ignored.

- [ ] **Step 1: Inspect runtime artifacts**

Run:

```powershell
git status --short
Get-ChildItem runtime -Force -ErrorAction SilentlyContinue | Select-Object Name,LastWriteTime
```

Expected: `runtime/` is untracked and contains temporary live-run/debug folders.

- [ ] **Step 2: Add runtime ignore rule**

Edit `.gitignore` and add:

```gitignore
# Local live-run logs, temporary runner scripts, and market/debug artifacts.
runtime/
write-test-workspace.txt
```

- [ ] **Step 3: Verify ignored runtime files no longer appear**

Run:

```powershell
git status --short
```

Expected: `runtime/` and `write-test-workspace.txt` do not appear in `git status`.

- [ ] **Step 4: Commit cleanup**

Run:

```powershell
git add .gitignore
git commit -m "chore: ignore local runtime artifacts"
```

Expected: commit succeeds.

---

### Task 2: Configure YFinance Cache and Clear Bad Proxy Vars

**Files:**
- Modify: `tradingagents/dataflows/y_finance.py`
- Test: `tests/test_y_finance_retry.py`

- [ ] **Step 1: Write failing tests**

Add these tests to `tests/test_y_finance_retry.py`:

```python
def test_yfinance_configures_cache_location(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setenv("TRADINGAGENTS_YFINANCE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(y_finance.yf, "set_tz_cache_location", lambda path: calls.append(("tz", path)))
    monkeypatch.setattr(
        y_finance.yf.cache,
        "set_cache_location",
        lambda path: calls.append(("cache", path)),
    )

    y_finance.configure_yfinance_runtime()

    assert ("tz", str(tmp_path)) in calls
    assert ("cache", str(tmp_path)) in calls
```

```python
def test_yfinance_fetch_clears_dead_local_proxy(monkeypatch):
    captured = {}
    fake = FakeTicker([_frame()])

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: fake)
    monkeypatch.setattr(y_finance.time, "sleep", lambda seconds: None)

    def history_with_capture(**kwargs):
        captured["HTTP_PROXY"] = y_finance.os.environ.get("HTTP_PROXY")
        captured["HTTPS_PROXY"] = y_finance.os.environ.get("HTTPS_PROXY")
        captured["ALL_PROXY"] = y_finance.os.environ.get("ALL_PROXY")
        return _frame()

    fake.history = history_with_capture

    text = y_finance.get_YFin_intraday_data("GC=F", period="10d", interval="15m")

    assert "No data found" not in text
    assert captured == {"HTTP_PROXY": None, "HTTPS_PROXY": None, "ALL_PROXY": None}
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_y_finance_retry.py::test_yfinance_configures_cache_location tests/test_y_finance_retry.py::test_yfinance_fetch_clears_dead_local_proxy -q
```

Expected: fail because `configure_yfinance_runtime` does not exist and proxies are not cleared.

- [ ] **Step 3: Implement runtime configuration**

In `tradingagents/dataflows/y_finance.py`, add:

```python
import os
from pathlib import Path
```

Add:

```python
_DEAD_LOCAL_PROXY = "http://127.0.0.1:9"
_PROXY_ENV_VARS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def _default_yfinance_cache_dir() -> Path:
    configured = os.environ.get("TRADINGAGENTS_YFINANCE_CACHE_DIR")
    if configured:
        return Path(configured)
    base = os.environ.get("TRADINGAGENTS_CACHE_DIR")
    if base:
        return Path(base) / "yfinance"
    return Path.home() / ".tradingagents" / "cache" / "yfinance"


def _clear_dead_local_proxies() -> None:
    for name in _PROXY_ENV_VARS:
        if os.environ.get(name) == _DEAD_LOCAL_PROXY:
            os.environ.pop(name, None)


def configure_yfinance_runtime() -> Path:
    _clear_dead_local_proxies()
    cache_dir = _default_yfinance_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache_dir))
    if hasattr(yf, "cache"):
        yf.cache.set_cache_location(str(cache_dir))
    return cache_dir
```

Call `configure_yfinance_runtime()` at the start of `get_YFin_data_online()` and `get_YFin_intraday_data()`.

- [ ] **Step 4: Run YFinance tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_y_finance_retry.py -q
```

Expected: all YFinance tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add tradingagents/dataflows/y_finance.py tests/test_y_finance_retry.py
git commit -m "fix: configure yfinance cache and proxy handling"
```

Expected: commit succeeds.

---

### Task 3: Make Data Freshness Handle Vendor Timestamp Drift Safely

**Files:**
- Modify: `tradingagents/dataflows/data_health.py`
- Test: `tests/test_price_action_data_health.py`

- [ ] **Step 1: Replace broad negative-age test with bounded drift test**

Use this test in `tests/test_price_action_data_health.py`:

```python
def test_data_status_allows_small_source_timestamp_drift_ahead_of_as_of():
    frames = {
        "1d": [_c("2026-05-29")],
        "4h": [_c("2026-05-29 12:00:00")],
        "1h": [_c("2026-05-29 12:00:00")],
        "30m": [_c("2026-05-29 12:30:00")],
        "15m": [_c("2026-05-29 12:45:00")],
    }

    status = build_data_status(frames, "2026-05-29 12:15", "America/New_York")

    assert status["healthy"] is True
    assert status["timeframes"]["15m"]["latest_age_minutes"] == -30
    assert status["timeframes"]["15m"]["fresh"] is True
```

Add this second test:

```python
def test_data_status_blocks_extreme_source_timestamp_drift_ahead_of_as_of():
    frames = {
        "1d": [_c("2026-05-29")],
        "4h": [_c("2026-05-30 12:00:00")],
        "1h": [_c("2026-05-30 12:00:00")],
        "30m": [_c("2026-05-30 12:30:00")],
        "15m": [_c("2026-05-30 12:45:00")],
    }

    status = build_data_status(frames, "2026-05-29 12:15", "America/New_York")

    assert status["healthy"] is False
    assert status["timeframes"]["15m"]["fresh"] is False
    assert "15m" in status["blocking_timeframes"]
```

- [ ] **Step 2: Run tests to verify second test fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_data_health.py -q
```

Expected: extreme future drift test fails with current broad negative-age allowance.

- [ ] **Step 3: Implement bounded drift**

In `tradingagents/dataflows/data_health.py`, add:

```python
MAX_FUTURE_DRIFT_MINUTES = {
    "1d": 1440,
    "4h": 240,
    "1h": 60,
    "30m": 30,
    "15m": 30,
}
```

Replace the freshness assignment with:

```python
future_drift_limit = MAX_FUTURE_DRIFT_MINUTES[timeframe]
fresh = -future_drift_limit <= age_minutes <= MAX_AGE_MINUTES[timeframe]
```

- [ ] **Step 4: Run data-health tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_price_action_data_health.py tests/test_price_action_dataflows.py tests/test_price_action_tools.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add tradingagents/dataflows/data_health.py tests/test_price_action_data_health.py
git commit -m "fix: bound price data timestamp drift"
```

Expected: commit succeeds.

---

### Task 4: Keep MT5 Runner Alive When Analysis Fails

**Files:**
- Modify: `tradingagents/brokers/mt5_runner.py`
- Test: `tests/test_mt5_runner.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_mt5_runner.py`:

```python
def test_runner_records_analysis_error_without_stopping(tmp_path):
    executor = FakeExecutor(active=False)

    def analysis_func():
        raise RuntimeError("OpenRouter connection error")

    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=analysis_func,
    )

    result = runner.run_once()

    assert result["status"] == "RUNNER_ERROR"
    assert result["analysis"]["error_type"] == "RuntimeError"
    assert result["analysis"]["error"] == "OpenRouter connection error"
    assert Path(result["heartbeat_path"]).exists()
    assert Path(result["summary_path"]).exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner.py::test_runner_records_analysis_error_without_stopping -q
```

Expected: fail because `run_once()` raises instead of writing heartbeat.

- [ ] **Step 3: Implement runner error heartbeat**

In `tradingagents/brokers/mt5_runner.py`, wrap analysis parsing:

```python
        try:
            as_of, proposal, analysis = self._parse_analysis_result(self.analysis_func())
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
```

- [ ] **Step 4: Run runner tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner.py tests/test_mt5_runner_summary.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add tradingagents/brokers/mt5_runner.py tests/test_mt5_runner.py
git commit -m "fix: keep mt5 runner alive on analysis errors"
```

Expected: commit succeeds.

---

### Task 5: Finish the Duration-Hours Runner Option

**Files:**
- Modify: `tradingagents/brokers/mt5_runner.py`
- Modify: `cli/main.py`
- Modify: `tradingagents/default_config.py`
- Test: `tests/test_mt5_runner.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Keep the existing CLI test**

Use the existing test in `tests/test_cli_mt5_execution.py`:

```python
def test_mt5_run_duration_hours_sets_runner_runtime_limit(monkeypatch, tmp_path):
    ...
```

It should assert `max_runtime_seconds == 4 * 3600`.

- [ ] **Step 2: Add runner runtime stop test**

Add to `tests/test_mt5_runner.py`:

```python
def test_runner_stops_after_max_runtime_seconds(tmp_path, monkeypatch):
    proposal = proposed_order()
    proposal.status = OrderStatus.NO_TRADE
    executor = FakeExecutor(active=False)
    times = iter([0.0, 0.0, 2.0])
    sleeps = []

    monkeypatch.setattr("tradingagents.brokers.mt5_runner.time.monotonic", lambda: next(times))
    monkeypatch.setattr("tradingagents.brokers.mt5_runner.time.sleep", lambda seconds: sleeps.append(seconds))

    runner = MT5Runner(
        MT5RunnerConfig(
            results_dir=tmp_path,
            poll_seconds=5,
            max_runtime_seconds=1,
        ),
        executor=executor,
        analysis_func=lambda: ("2026-05-28 10:15", proposal),
    )

    result = runner.run_forever()

    assert result["status"] == "STOPPED_MAX_RUNTIME_SECONDS"
    assert result["last_result"]["status"] == "NO_TRADE"
    assert sleeps == []
```

- [ ] **Step 3: Run duration tests to verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_cli_mt5_execution.py::test_mt5_run_duration_hours_sets_runner_runtime_limit tests/test_mt5_runner.py::test_runner_stops_after_max_runtime_seconds -q
```

Expected: fail because config has no `max_runtime_seconds` and CLI has no `--duration-hours`.

- [ ] **Step 4: Implement runtime config**

In `MT5RunnerConfig`, add:

```python
    max_runtime_seconds: int = 0
```

In `__post_init__`:

```python
        max_runtime_seconds = int(self.max_runtime_seconds)
        if max_runtime_seconds < 0:
            raise ValueError("max_runtime_seconds must be non-negative")
        object.__setattr__(self, "max_runtime_seconds", max_runtime_seconds)
```

In `run_forever()`:

```python
        deadline = (
            time.monotonic() + self.config.max_runtime_seconds
            if self.config.max_runtime_seconds
            else None
        )
```

After each `run_once()`:

```python
            if deadline is not None and time.monotonic() >= deadline:
                return {
                    "status": "STOPPED_MAX_RUNTIME_SECONDS",
                    "last_result": last_result,
                }
```

Before sleeping:

```python
            sleep_seconds = self.config.poll_seconds
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return {
                        "status": "STOPPED_MAX_RUNTIME_SECONDS",
                        "last_result": last_result,
                    }
                sleep_seconds = min(sleep_seconds, remaining)
            time.sleep(sleep_seconds)
```

- [ ] **Step 5: Implement CLI option**

In `cli/main.py`, add option:

```python
    duration_hours: float = typer.Option(
        0.0,
        "--duration-hours",
        min=0.0,
        help="Stop the runner after this many wall-clock hours. Zero means no duration limit.",
    ),
```

Set:

```python
                max_runtime_seconds=int(duration_hours * 3600),
```

- [ ] **Step 6: Add env config**

In `tradingagents/default_config.py`, add:

```python
    "TRADINGAGENTS_RUNNER_MAX_RUNTIME_SECONDS": "runner_max_runtime_seconds",
```

and:

```python
    "runner_max_runtime_seconds": 0,
```

Pass it into `MT5RunnerConfig` when `duration_hours` is zero:

```python
max_runtime_seconds=(
    int(duration_hours * 3600)
    if duration_hours
    else int(DEFAULT_CONFIG.get("runner_max_runtime_seconds", 0))
),
```

- [ ] **Step 7: Run duration tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner.py tests/test_cli_mt5_execution.py -q
```

Expected: tests pass.

- [ ] **Step 8: Commit**

Run:

```powershell
git add tradingagents/brokers/mt5_runner.py cli/main.py tradingagents/default_config.py tests/test_mt5_runner.py tests/test_cli_mt5_execution.py
git commit -m "feat: add wall-clock mt5 runner duration"
```

Expected: commit succeeds.

---

### Task 6: Update Runbooks for Reopen Testing

**Files:**
- Modify: `docs/windows-agent-handoff.md`
- Modify: `docs/mt5-windows-vps.md`
- Modify: `docs/mt5-demo-windows.md`

- [ ] **Step 1: Document clean launch**

Add this PowerShell snippet to the runbooks:

```powershell
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
$env:ALL_PROXY=""
$env:GIT_HTTP_PROXY=""
$env:GIT_HTTPS_PROXY=""
$env:TRADINGAGENTS_MT5_ACCOUNT_MODE="demo"
$env:TRADINGAGENTS_MT5_EXECUTION_MODE="broker"
tradingagents mt5-run --poll-seconds 30 --duration-hours 4
```

Mention that `.env` can remain `dry_run`; the process environment controls this one run.

- [ ] **Step 2: Document evidence files**

Ensure runbooks list:

```text
<results_dir>\mt5_runner\summary.json
<results_dir>\mt5_runner\cycles.jsonl
<results_dir>\<analysis-symbol>\engine_telemetry\engine_payload_<as-of>.json
<results_dir>\<broker-symbol>\execution_journal\mt5_events.jsonl
```

- [ ] **Step 3: Document market timing**

Add:

```text
Do not start a setup-validation run after the Friday gold close. For observation, Sunday New York reopen is acceptable. For cleaner strategy validation, prefer London/New York overlap.
```

- [ ] **Step 4: Commit docs**

Run:

```powershell
git add docs/windows-agent-handoff.md docs/mt5-windows-vps.md docs/mt5-demo-windows.md
git commit -m "docs: document clean mt5 reopen test run"
```

Expected: commit succeeds.

---

### Task 7: Final Verification

**Files:**
- No edits expected.

- [ ] **Step 1: Run focused suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_y_finance_retry.py tests/test_price_action_data_health.py tests/test_price_action_dataflows.py tests/test_price_action_tools.py tests/test_mt5_runner.py tests/test_mt5_runner_summary.py tests/test_cli_mt5_execution.py -q
```

Expected: all pass.

- [ ] **Step 2: Run broad safety suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_import_smoke.py tests/test_model_validation.py tests/test_order_proposal.py tests/test_cli_config.py tests/test_mt5_broker.py tests/test_mt5_execution.py tests/test_execution_journal.py tests/test_execution_state.py -q
```

Expected: all pass, with Windows-only skips allowed.

- [ ] **Step 3: Run full suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all pass, with expected live-API or Windows-only skips allowed.

- [ ] **Step 4: Verify no runner processes are still active**

Run:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'mt5-run|deterministic_mt5_runner' } |
  Select-Object ProcessId,Name,CommandLine
```

Expected: no active old runner process.

- [ ] **Step 5: Confirm clean git status**

Run:

```powershell
git status --short
```

Expected: clean, except intentional untracked local files ignored by `.gitignore`.

---

## Self-Review

**Spec coverage:** The plan covers the requested waiting-period fixes: proxy failures, YFinance cache failures, false data-health blocks, OpenRouter/LLM runner crashes, temporary runtime artifacts, and the optional duration-hours feature that was half-started.

**Placeholder scan:** No `TBD`, `TODO`, or vague "add tests" placeholders remain. Each task has exact files, code snippets, commands, expected failures, and commits.

**Type consistency:** The plan consistently uses `max_runtime_seconds` for runner internals and `--duration-hours` for the CLI. Existing status strings remain uppercase runner statuses.
