# One-Minute Lifecycle Guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add trigger-aware pending-order expiry, early-loss grace, and independent one-second MT5 maintenance for the One Minute Scalper.

**Architecture:** Keep strategy detection unchanged. Add an execution lifecycle configuration consumed by `MT5Executor`, persist the effective pending policy in execution state, normalize position-open timestamps in the broker adapter, and schedule lightweight maintenance between normal runner analysis cycles.

**Tech Stack:** Python 3.13, Pydantic, MetaTrader5 Python integration, pytest, Typer.

---

### Task 1: Trigger-Aware Pending Expiry

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tradingagents/brokers/execution_state.py`
- Modify: `tradingagents/default_config.py`
- Modify: `cli/main.py`
- Test: `tests/test_mt5_execution.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write failing tests**

Add tests proving fakeout/respect proposals expire after 20 seconds, impulse
proposals expire after 45 seconds, one-minute expiry is clamped before the next
candle boundary, and normal proposals retain activation-window expiry.

- [ ] **Step 2: Verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py -k "pending_policy or trigger_aware" -q
```

Expected: failures because lifecycle policy configuration and metadata do not
exist.

- [ ] **Step 3: Implement minimal policy**

Add `MT5OneMinuteLifecycleConfig`, compute effective expiry in
`MT5Executor.execute_proposal`, and pass explicit expiry/policy metadata to
`ExecutionStateStore.record_pending_order`.

- [ ] **Step 4: Verify GREEN**

Run the focused command again and expect all selected tests to pass.

### Task 2: Early-Loss Grace

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tradingagents/brokers/mt5_execution.py`
- Test: `tests/test_mt5_broker.py`
- Test: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing tests**

Add tests proving broker positions expose normalized `opened_at_utc`, a fresh
one-minute position is not closed by discretionary early loss before five
seconds, and the same adverse position may close after the grace period.

- [ ] **Step 2: Verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_broker.py tests\test_mt5_execution.py -k "opened_at_utc or early_loss_grace" -q
```

Expected: failures because position age is not yet available or enforced.

- [ ] **Step 3: Implement minimal grace**

Normalize broker position time using the existing server-offset detection and
gate only one-minute `FAST_PARTIAL_SCALE` discretionary early-loss actions.

- [ ] **Step 4: Verify GREEN**

Run the focused command again and expect all selected tests to pass.

### Task 3: Independent Maintenance Cadence

**Files:**
- Modify: `tradingagents/brokers/mt5_runner.py`
- Modify: `tradingagents/default_config.py`
- Modify: `cli/main.py`
- Test: `tests/test_mt5_runner.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write failing tests**

Add tests proving maintenance runs between analysis cycles, does not increment
analysis-cycle count, and respects runtime and risk-limit termination.

- [ ] **Step 2: Verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_runner.py tests\test_cli_mt5_execution.py -k "maintenance" -q
```

Expected: failures because the runner only performs work at `poll_seconds`.

- [ ] **Step 3: Implement minimal scheduler**

Add `maintenance_poll_seconds` to `MT5RunnerConfig`, run cancellation and
position management between full cycles, and leave heartbeat/summary analysis
cadence unchanged.

- [ ] **Step 4: Verify GREEN**

Run the focused command again and expect all selected tests to pass.

### Task 4: Integration Verification And Deployment

**Files:**
- Modify: `.env` only for local runtime values; do not commit credentials.

- [ ] **Step 1: Run focused suites**

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py tests\test_mt5_broker.py tests\test_mt5_runner.py tests\test_cli_mt5_execution.py -q
```

- [ ] **Step 2: Run full suite**

```powershell
.venv\Scripts\python.exe -m pytest
```

- [ ] **Step 3: Commit and push**

Stage only source, tests, and design documentation. Exclude results, reports,
screenshots, and credentials.

- [ ] **Step 4: Restart**

Start `mt5-run` in `ENTRY_ONLY` and `fast_only` mode with fresh telemetry,
confirm demo-account safety, healthy data, first heartbeat, and one-second
maintenance configuration.
