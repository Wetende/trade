# MT5 Straddle Breakout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dry-run-first MT5 straddle-breakout sidecar and a small strategy-blocking guard for the current MT5 runner.

**Architecture:** Keep straddle logic outside the price-action engine. Generate paired `BUY_STOP`/`SELL_STOP` proposals from MT5 candles, validate both with the existing MT5 request builder, persist separate straddle state, and expose live placement only behind an explicit CLI flag. Add strategy/side blocking to the existing runner before execution.

**Tech Stack:** Python, pytest, Typer, existing MT5 broker/request-builder/execution journal primitives.

---

### Task 1: Straddle Proposal Engine

**Files:**
- Create: `tradingagents/agents/straddle_breakout.py`
- Test: `tests/test_straddle_breakout.py`

- [ ] Write tests for successful paired proposal generation and spread rejection.
- [ ] Run targeted tests and confirm import/implementation failures.
- [ ] Implement config validation and pair construction.
- [ ] Re-run targeted tests.

### Task 2: Paired MT5 Straddle Executor

**Files:**
- Create: `tradingagents/brokers/straddle_state.py`
- Create: `tradingagents/brokers/mt5_straddle.py`
- Modify: `tradingagents/brokers/__init__.py`
- Test: `tests/test_mt5_straddle.py`

- [ ] Write tests for dry-run validation, request comments, state persistence, and live rollback when the second order fails.
- [ ] Run targeted tests and confirm expected failures.
- [ ] Implement state store and executor.
- [ ] Re-run targeted tests.

### Task 3: Runner Strategy Block Rules

**Files:**
- Modify: `tradingagents/brokers/mt5_runner.py`
- Modify: `tradingagents/default_config.py`
- Modify: `cli/main.py`
- Test: `tests/test_mt5_runner.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] Write tests proving `SUPPORT_RESISTANCE_BOUNCE:SELL` blocks execution and CLI passes configured rules.
- [ ] Run targeted tests and confirm expected failures.
- [ ] Implement block-rule normalization and execution guard.
- [ ] Re-run targeted tests.

### Task 4: Straddle CLI

**Files:**
- Modify: `cli/main.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] Write tests for `mt5-straddle-run --help` and dry-run invocation.
- [ ] Run targeted tests and confirm expected failures.
- [ ] Implement CLI command with default dry-run and explicit `--live`.
- [ ] Re-run targeted tests.

### Task 5: Verification

**Files:**
- Run tests only.

- [ ] Run straddle and runner targeted tests.
- [ ] Run MT5-related test suite.
- [ ] Run full test suite if targeted tests pass.
