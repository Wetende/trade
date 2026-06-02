# B+ And Fresh Telemetry Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable `B+` setup grading, stop duplicate processed candles from polluting runner summaries, and point the next run at a fresh results directory.

**Architecture:** Extend the deterministic price-action engine so candidate setups are graded as `A_PLUS`, `B_PLUS`, or rejected using the existing checklist plus configurable risk-reward thresholds. Keep runner-cycle audit logs intact, but exclude duplicate processed-candle heartbeats from summary check counts. Use `.env` configuration to send the next trading session to a new isolated results directory instead of mutating or deleting historical logs.

**Tech Stack:** Python, pytest, PowerShell, existing MT5 runner and deterministic price-action engine

---

### Task 1: Add failing engine and config tests for B+

**Files:**
- Modify: `tests/test_price_action_engine.py`
- Modify: `tests/test_env_overrides.py`

- [ ] **Step 1: Write the failing B+ engine tests**
- [ ] **Step 2: Run the targeted engine tests and confirm the new cases fail**
- [ ] **Step 3: Write the failing env override tests for `TRADINGAGENTS_MIN_SETUP_GRADE` and `TRADINGAGENTS_B_PLUS_MIN_RR`**
- [ ] **Step 4: Run the env override tests and confirm the new cases fail**

### Task 2: Add failing proposal and summary tests

**Files:**
- Modify: `tests/test_order_proposal.py`
- Modify: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Write the failing proposal test for `setup_grade` passthrough**
- [ ] **Step 2: Run the proposal test and confirm it fails**
- [ ] **Step 3: Write the failing summary test that excludes `CANDLE_ALREADY_PROCESSED` from check counts**
- [ ] **Step 4: Run the summary test and confirm it fails**

### Task 3: Implement B+ grading and summary behavior

**Files:**
- Modify: `tradingagents/agents/price_action/engine.py`
- Modify: `tradingagents/default_config.py`
- Modify: `tradingagents/agents/price_action/sessions.py`
- Modify: `tradingagents/agents/schemas.py`
- Modify: `tradingagents/agents/execution/order_proposal.py`
- Modify: `tradingagents/brokers/runner_summary.py`

- [ ] **Step 1: Add config defaults and env plumbing for minimum setup grade and B+ minimum R:R**
- [ ] **Step 2: Implement candidate grading in the engine with `A_PLUS`, `B_PLUS`, and rejection states**
- [ ] **Step 3: Prefer A+ over B+ in setup selection and expose grade in telemetry/payload**
- [ ] **Step 4: Carry `setup_grade` into order proposals**
- [ ] **Step 5: Exclude duplicate processed-candle heartbeats from summary totals while still appending cycle logs**

### Task 4: Configure the next run for a fresh telemetry session

**Files:**
- Modify: `.env`

- [ ] **Step 1: Set `TRADINGAGENTS_RESULTS_DIR` to a new overnight session path**
- [ ] **Step 2: Create the session directory if it does not already exist**

### Task 5: Verify the full change set

**Files:**
- Verify: `tests/test_price_action_engine.py`
- Verify: `tests/test_env_overrides.py`
- Verify: `tests/test_order_proposal.py`
- Verify: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Run the targeted pytest command for all touched behaviors**
- [ ] **Step 2: Review the test output and fix any failures**
- [ ] **Step 3: Check git diff to confirm only intended files changed**
