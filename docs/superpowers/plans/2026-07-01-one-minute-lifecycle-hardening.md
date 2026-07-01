# One-Minute Lifecycle Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix reviewed timing, restart-safety, expiry, telemetry, and partial-close defects in the One Minute Scalper lifecycle.

**Architecture:** Keep entry detection unchanged. Harden `MT5Executor` around broker-facing lifecycle identity and timing, adjust only M1 exit metadata in the isolated entry model, and retain all normal-profile behavior.

**Tech Stack:** Python 3.13, MetaTrader5 adapter, Pydantic, pytest.

---

### Task 1: Correct Rejection Candle Timing

**Files:**
- Modify: `tests/test_mt5_execution.py`
- Modify: `tradingagents/brokers/mt5_execution.py`

- [ ] Add a failing test where a position opens at `12:00:05`, an adverse M1
  candle has timestamp `12:00:00`, and management must close after that candle
  completes.
- [ ] Add a control test proving a candle whose derived close time is not after
  position open remains ignored.
- [ ] Derive candle duration from the configured rejection timeframe and pass
  broker position-open time into rejection selection.
- [ ] Run the focused rejection tests and confirm they pass.

### Task 2: Persist Lifecycle Through Broker State

**Files:**
- Modify: `tests/test_mt5_execution.py`
- Modify: `tradingagents/brokers/mt5_execution.py`

- [ ] Add a failing request test proving M1 orders use `TA|M1|FAST` while
  normal orders retain `TradingAgents`.
- [ ] Add a failing management test with empty local state and an M1-tagged
  broker position; assert price-only early loss remains disabled.
- [ ] Add centralized lifecycle detection using proposal metadata or the exact
  broker comment.
- [ ] Run focused request and management tests.

### Task 3: Reject Expired Orders Before Submission

**Files:**
- Modify: `tests/test_mt5_execution.py`
- Modify: `tradingagents/brokers/mt5_execution.py`

- [ ] Add a failing test with a deterministic executor clock at
  `14:00:59.500`; assert no broker check or placement occurs.
- [ ] Compute pending policy before broker submission and skip M1 requests with
  one second or less remaining.
- [ ] Persist the precomputed policy after successful placement.
- [ ] Run pending-policy and executor placement tests.

### Task 4: Align Telemetry And Base Partial Behavior

**Files:**
- Modify: `tests/test_one_minute_entry_model.py`
- Modify: `tests/test_mt5_execution.py`
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Modify: `tradingagents/brokers/mt5_execution.py`

- [ ] Change the existing telemetry test to require
  `early_loss_exit_points == 0.0` and verify it fails.
- [ ] Add a failing first-partial test proving base 1.0 closes 0.5 and leaves
  0.5.
- [ ] Emit zero M1 early-loss points.
- [ ] Derive a half-volume first-stage target only when current volume is not
  above the configured absolute target.
- [ ] Confirm boosted 1.5 behavior remains 1.0.

### Task 5: Full Verification And Integration

**Files:**
- No additional production files.

- [ ] Run affected executor, runner, broker, CLI, environment, and one-minute
  model test modules.
- [ ] Run `.venv\Scripts\python.exe -m pytest`.
- [ ] Run `git diff --check` and review the complete diff.
- [ ] Commit source, tests, and documentation only.
- [ ] Push `main`; leave the runner stopped until results are reviewed.
