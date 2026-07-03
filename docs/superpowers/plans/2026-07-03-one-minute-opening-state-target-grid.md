# One Minute Opening-State Target Grid Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and evaluate `OPENING_STATE_QUEUE_TARGET_GRID_V1`, a fixed-grid walk-forward target selector for the queued opening-state family.

**Architecture:** Reuse `opening_state_queue_fast_target` for queue replay and same-config baseline rows. Add a target-grid module that computes rows once per target, performs leave-one-day-out target selection, gates combined held-out rows, and emits a manifest only when all gates pass.

**Tech Stack:** Python 3.13, Pydantic metrics, pytest, Typer CLI, existing broker-free opening-state replay modules.

---

## File structure

- Modify `tradingagents/agents/price_action/opening_state_queue_fast_target.py`
  - Expose same-config baseline rows and raw/candidate opportunity helpers for reuse.
- Create `tradingagents/agents/price_action/opening_state_target_grid.py`
  - Own fixed grid, fold selection, combined held-out metrics, gate, and manifest.
- Create `tests/test_one_minute_opening_state_target_grid.py`
  - Unit tests for ranking, fold failure, held-out report, and manifest branch.
- Modify `cli/main.py`
  - Add `one-minute-opening-target-grid-screen --fixture --output`.
- Create `tests/test_one_minute_opening_state_target_grid_cli.py`
  - CLI determinism test.
- Create `docs/analysis/2026-07-03-one-minute-opening-state-target-grid-screening.md`
  - Sanitized historical result.

---

### Task 1: Reusable queue replay helpers

**Files:**
- Modify: `tradingagents/agents/price_action/opening_state_queue_fast_target.py`
- Modify: `tests/test_one_minute_opening_state_queue_fast_target.py`

- [ ] Add tests that import `baseline_rows_with_config`,
  `candidate_opportunities`, and `raw_opportunities`.
- [ ] Verify RED if helpers are not exported.
- [ ] Rename private helpers to public wrappers while keeping existing behavior.
- [ ] Run queue fast-target tests.
- [ ] Commit: `refactor: expose opening queue replay helpers`.

### Task 2: Target-grid module

**Files:**
- Create: `tradingagents/agents/price_action/opening_state_target_grid.py`
- Create: `tests/test_one_minute_opening_state_target_grid.py`

- [ ] Write tests for:
  - `TARGET_GRID == (0.60, 0.75, 0.90, 1.00)`;
  - training ranking prefers higher PF, expectancy, fills, then target;
  - no eligible target records `NO_ELIGIBLE_TARGET_FOR_FOLD`;
  - passing forced gate creates manifest;
  - failing gate returns `NO_OPENING_STATE_QUEUE_TARGET_GRID_EDGE`.
- [ ] Verify RED because module is missing.
- [ ] Implement:
  - `TargetFoldResult` Pydantic model or plain dict payload;
  - `rank_training_targets(candidates)`;
  - `screen_target_grid_fixture(fixture_or_path)`;
  - deterministic same-target baseline aggregation.
- [ ] Run target-grid tests.
- [ ] Commit: `feat: screen opening-state target grid`.

### Task 3: CLI and historical report

**Files:**
- Modify: `cli/main.py`
- Create: `tests/test_one_minute_opening_state_target_grid_cli.py`
- Create: `docs/analysis/2026-07-03-one-minute-opening-state-target-grid-screening.md`

- [ ] Write CLI determinism test for
  `one-minute-opening-target-grid-screen`.
- [ ] Verify RED because command is missing.
- [ ] Add CLI command with atomic JSON output.
- [ ] Run focused target-grid and opening suites.
- [ ] Run historical screen against
  `test-artifacts/opening-state/read-only-mt5-opening-fixture.json`.
- [ ] Write sanitized tracked report with baseline, held-out metrics, fold
  targets, gate, decision, and safety notes.
- [ ] Commit: `docs: report opening-state target grid`.

### Task 4: Verification and push

- [ ] Run focused opening suites.
- [ ] Run related one-minute/evidence suites.
- [ ] Run full `pytest -q`.
- [ ] Run `git diff --check`.
- [ ] Run changed-file secret scan that prints filenames only.
- [ ] Confirm no Python/trading runner processes are active.
- [ ] Push feature branch, fast-forward main, rerun full tests on main, push
  main, and verify local HEAD equals `origin/main`.

## Self-review

- Spec coverage: fixed grid, walk-forward selection, same-target baseline,
  held-out gate, failure behavior, manifest, and safety are covered.
- Placeholder scan: no TBD values remain.
- Type consistency: helper, module, CLI, and report names are consistent.
