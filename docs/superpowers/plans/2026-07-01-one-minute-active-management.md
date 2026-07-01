# One-Minute Active Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Manage active M1 positions every second with spread-aware protection, confirmed intrabar exits, and durable excursion telemetry.

**Architecture:** Extend the existing runner maintenance path instead of adding another worker. Keep proposal thresholds deterministic and store per-ticket observations in the durable execution state.

**Tech Stack:** Python 3.14, pytest, MT5 executor/runner, JSON execution state.

---

### Task 1: Active maintenance

**Files:**
- Modify: `tradingagents/brokers/mt5_runner.py`
- Test: `tests/test_mt5_runner.py`

- [ ] Add a failing test asserting `run_maintenance_once()` invokes both
  `cancel_stale_pending_orders()` and `manage_open_positions()`.
- [ ] Run the focused test and verify it fails because position management is
  absent.
- [ ] Add `position_management` to the maintenance result.
- [ ] Run all runner tests.

### Task 2: Spread-aware proposal thresholds

**Files:**
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Test: `tests/test_one_minute_entry_model.py`

- [ ] Add failing tests for break-even, partial, and scalp thresholds calculated
  from risk and spread.
- [ ] Run the focused tests and verify the old risk-only values fail.
- [ ] Pass spread into `_dynamic_fast_exit_settings()` and implement the formulas
  from the design.
- [ ] Run all one-minute model tests.

### Task 3: Intrabar emergency protection and telemetry

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Test: `tests/test_mt5_execution.py`

- [ ] Add failing tests proving one adverse observation holds, recovery resets,
  and two consecutive observations close an M1 position.
- [ ] Add a failing test for MFE/MAE, spread, and threshold telemetry persistence.
- [ ] Extend `MT5ExitManagementConfig` with a validated `0.65` adverse fraction
  and `2` confirmation observations.
- [ ] Record per-ticket excursion state in `position_excursion_state`.
- [ ] Execute the emergency close only for ticket-bound
  `FAST_PARTIAL_SCALE` positions and only after confirmation.
- [ ] Run all executor tests.

### Task 4: Verification and restart

**Files:**
- Modify only if verification finds a scoped defect.

- [ ] Run all MT5 and CLI suites.
- [ ] Run the complete pytest suite.
- [ ] Review `git diff --check` and the complete source diff.
- [ ] Commit and push `main`.
- [ ] Start a fresh telemetry session and confirm process, heartbeat, demo safety,
  health gate, and empty stderr while leaving the runner active.
