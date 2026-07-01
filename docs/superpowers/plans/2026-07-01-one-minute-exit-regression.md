# One-Minute Exit Regression Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve one-minute pending expiry while removing aggressive transient-price exits introduced by fast maintenance.

**Architecture:** Keep one-second maintenance focused on pending cancellation and leave position management in normal runner cycles. Suppress price-only early-loss closure for `FAST_PARTIAL_SCALE` M1 proposals while retaining broker SL/TP and closed-candle rejection.

**Tech Stack:** Python 3.13, MetaTrader5 adapter, pytest, Typer.

---

### Task 1: Lock The Correct Position Behavior

**Files:**
- Modify: `tests/test_mt5_execution.py`
- Modify: `tradingagents/brokers/mt5_execution.py`

- [ ] **Step 1: Replace the grace-period expectation with a regression test**

Create a test that loads an M1 `FAST_PARTIAL_SCALE` proposal, supplies an
adverse position older than five seconds, calls `manage_open_positions`, and
asserts `NO_POSITION_ACTION` with no broker close.

- [ ] **Step 2: Verify the test fails**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py -k "one_minute_ignores_price_only_early_loss" -q
```

Expected: failure because the current executor closes the position.

- [ ] **Step 3: Implement minimal lifecycle gating**

Gate the `EARLY_LOSS_EXIT` branch so it does not run when the saved proposal is
an M1 `FAST_PARTIAL_SCALE` proposal. Do not alter rejection, partial, scalp,
break-even, trailing, or broker stop behavior.

- [ ] **Step 4: Verify focused execution tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py -k "early_loss or rejection" -q
```

Expected: all selected tests pass.

### Task 2: Separate Fast Cancellation From Position Management

**Files:**
- Modify: `tests/test_mt5_runner.py`
- Modify: `tradingagents/brokers/mt5_runner.py`

- [ ] **Step 1: Change the scheduler regression expectation**

Assert that two full runner cycles call position management twice while stale
order cancellation runs six times across the five one-second waits.

- [ ] **Step 2: Verify the test fails**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_runner.py -k "maintains_active_trade_each_second" -q
```

Expected: failure because maintenance currently calls position management.

- [ ] **Step 3: Make lightweight maintenance cancellation-only**

Change `run_maintenance_once` to call only `cancel_stale_pending_orders` and
return cancellation metadata. Keep `run_once` position management unchanged.

- [ ] **Step 4: Verify runner tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_runner.py -q
```

Expected: all runner tests pass.

### Task 3: Remove Obsolete Grace Configuration

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tradingagents/default_config.py`
- Modify: `cli/main.py`
- Modify: `tests/test_env_overrides.py`
- Modify: `tests/test_cli_mt5_execution.py`
- Modify: `tests/test_mt5_broker.py`

- [ ] **Step 1: Remove grace-specific tests and expectations**

Delete assertions for `fast_early_loss_grace_seconds` and replace broker
timestamp tests only if no remaining behavior consumes normalized position
open time.

- [ ] **Step 2: Remove dead production configuration**

Remove `early_loss_grace_seconds`, its environment mapping, CLI propagation,
position-age helper, and grace-only `opened_at_utc` normalization.

- [ ] **Step 3: Run affected suites**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py tests\test_mt5_broker.py tests\test_mt5_runner.py tests\test_env_overrides.py tests\test_cli_mt5_execution.py -q
```

Expected: all selected tests pass.

### Task 4: Replay, Verify, And Integrate

**Files:**
- Modify: `.env` locally to remove the obsolete grace setting.

- [ ] **Step 1: Re-run broker-history counterfactual**

Confirm the pending-expiry policy retains all nine previous winners and removes
the four stale losses.

- [ ] **Step 2: Re-run the post-change M1-bar review**

Confirm the session contained three early exits whose subsequent bars reached
TP, establishing why price-only early loss must remain disabled.

- [ ] **Step 3: Run the full suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest
```

Expected: no test failures.

- [ ] **Step 4: Review and integrate**

Run `git diff --check`, stage only source, tests, and documentation, commit the
correction, and push `main`. Leave telemetry, reports, screenshots, and
credentials untracked.
