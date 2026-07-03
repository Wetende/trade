# One Minute Opening-State Prospective Shadow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and run a read-only prospective shadow collector for the frozen `OPENING_STATE_QUEUE_TARGET_GRID_V1` candidate.

**Architecture:** Add a read-only MT5 tick-range method, implement a pure shadow report module that can work with fake brokers in tests and real MT5 in CLI, then add a CLI that writes atomic ignored runtime reports. Keep broker execution runner stopped and never import execution/order mutation classes.

**Tech Stack:** Python 3.13, Pydantic, existing MT5 broker read APIs, existing opening-state replay modules, Typer CLI, pytest.

---

## File structure

- Modify `tradingagents/brokers/mt5.py`
  - Add read-only `fetch_ticks_range(start_utc, end_utc)`.
- Create `tradingagents/agents/price_action/opening_state_shadow.py`
  - Own manifest loading, broker safety inspection, shadow replay, prospective
    metrics, and gate state.
- Modify `cli/main.py`
  - Add `one-minute-opening-target-grid-shadow-step`.
- Create `tests/test_one_minute_opening_state_shadow.py`
  - Unit tests for gate logic, frozen target replay, broker safety, and
    opportunity start filtering.
- Create `tests/test_one_minute_opening_state_shadow_cli.py`
  - CLI deterministic-output test with a fixture mode or fake broker path.
- Modify `tests/test_mt5_broker.py`
  - Add read-only tick normalization test.

---

### Task 1: Read-only MT5 tick range

- [ ] Write failing `tests/test_mt5_broker.py` test for
  `MT5Broker.fetch_ticks_range()`.
- [ ] Verify RED because method is missing.
- [ ] Implement `fetch_ticks_range()` using `copy_ticks_range` and
  `COPY_TICKS_ALL`, normalizing `time_msc`/`time`, bid, and ask to UTC.
- [ ] Verify focused MT5 broker test passes.
- [ ] Commit: `feat: read mt5 tick ranges`.

### Task 2: Prospective shadow module

- [ ] Write failing tests for:
  - refusing `allow_real_orders`;
  - refusing open orders/positions;
  - excluding pre-start opportunities;
  - using `risk_reward=0.75`;
  - `COLLECTING`, `PASS`, and `FAIL` gate states.
- [ ] Verify RED because module is missing.
- [ ] Implement `opening_state_shadow.py` with:
  - `load_frozen_manifest(path)`;
  - `build_shadow_report(...)`;
  - `evaluate_shadow_gate(candidate_metrics, baseline_metrics, session_count)`;
  - sanitized safety snapshot.
- [ ] Verify focused shadow tests pass.
- [ ] Commit: `feat: evaluate opening-state shadow reports`.

### Task 3: CLI shadow step

- [ ] Write failing CLI test for
  `one-minute-opening-target-grid-shadow-step`.
- [ ] Verify RED because command is missing.
- [ ] Add CLI command that:
  - accepts `--manifest`, `--prospective-start`, and `--output`;
  - connects using `MT5ConnectionConfig.from_env()`;
  - writes atomic JSON;
  - performs only read-only broker calls.
- [ ] Verify CLI test and focused opening/MT5 tests pass.
- [ ] Commit: `feat: add opening-state shadow cli`.

### Task 4: Launch read-only shadow

- [ ] Run full verification.
- [ ] Push feature branch and main.
- [ ] Re-check no execution runner is active.
- [ ] Run the shadow CLI once against live MT5 with prospective start equal to
  the frozen manifest creation time or later.
- [ ] If the report is not yet evaluable, leave only the ignored runtime report
  and do not claim prospective success.
- [ ] If evaluable, track a sanitized aggregate report under `docs/analysis/`.

## Self-review

- Spec coverage: read-only MT5 safety, frozen target, gate states, output
  handling, and no broker mutation are covered.
- Placeholder scan: no TBD values remain.
- Type consistency: method, module, and CLI names are consistent.
