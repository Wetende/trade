# One Minute History Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the fast 1m entry model use a 60-candle 1m working history without requiring a 3m confirmation/history gate.

**Architecture:** Keep the existing price-action engine and MT5 runner. Add small 1m window helpers inside `tradingagents/agents/price_action/engine.py`, adjust fast profile config in `cli/main.py`, and update tests to prove 3m no longer approves or rejects 1m entries.

**Tech Stack:** Python, pytest, existing deterministic price-action engine, MT5 runner.

---

### Task 1: Add Failing Engine Tests

**Files:**
- Modify: `tests/test_price_action_engine.py`

- [ ] Add a test proving a valid 1m micro setup passes with only 1m candles.
- [ ] Add a test proving old opposing 3m history does not block the 1m setup.
- [ ] Add a test proving telemetry records a 60-candle 1m history window.
- [ ] Run the focused tests and confirm they fail before implementation.

### Task 2: Implement 1m History Window

**Files:**
- Modify: `tradingagents/agents/price_action/engine.py`

- [ ] Add fast window defaults: history `60`, minimum trigger `3`, maximum trigger `10`.
- [ ] Limit micro setup detection to the last 60 closed 1m candles.
- [ ] Record `history_window_candles`, `trigger_window_min_candles`, and `trigger_window_max_candles` in `market_context["fast_microstructure"]`.
- [ ] Remove the 3m confirmation/history requirement for fast micro setups.
- [ ] Keep latest 1m candle quality checks, stop checks, risk checks, and active-trade execution guards unchanged.

### Task 3: Wire CLI Fast Profile

**Files:**
- Modify: `cli/main.py`
- Modify: `tradingagents/default_config.py`
- Modify: `tests/test_cli_mt5_execution.py`
- Modify: `tests/test_env_overrides.py`

- [ ] Add optional config/env values for fast history window defaults.
- [ ] Pass the fast history window values into the fast profile session config.
- [ ] Update CLI tests to assert the fast profile uses 1m governing/history configuration.

### Task 4: Verify and Restart

**Files:**
- Modify as needed from previous tasks

- [ ] Run focused engine/CLI tests.
- [ ] Run the full pytest suite.
- [ ] Commit and push only the relevant files.
- [ ] Restart a fresh `ENTRY_ONLY` runner with fast entries enabled.
- [ ] Confirm first heartbeat, demo guard, and zero unexpected exposure.
