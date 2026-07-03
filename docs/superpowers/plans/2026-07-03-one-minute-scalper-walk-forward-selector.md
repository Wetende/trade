# One Minute Scalper Walk-Forward Selector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Determine with deterministic leave-one-session-out evaluation whether a shallow pre-entry selector can meet the existing historical acceptance gates.

**Architecture:** Enrich the strict sanitized evidence schema from recorded candidate telemetry, generate only rules allowed by the pre-registered grammar, select rules on two sessions, and score them once on the held-out session. Keep production strategy and broker modules untouched.

**Tech Stack:** Python 3.13, Pydantic, pytest, Typer, JSON fixtures.

---

### Task 1: Enrich sanitized decision evidence

**Files:**
- Modify: `tradingagents/agents/price_action/evidence_gate.py`
- Modify: `tradingagents/agents/price_action/evidence_export.py`
- Modify: `tests/test_one_minute_evidence_gate.py`
- Modify: `tests/test_one_minute_evidence_export.py`
- Regenerate: `tests/fixtures/one_minute/evidence_sessions/*.json`

- [ ] Add failing tests for optional score, confirmation, level type, touch age,
  entry distance, wick ratio, stop/spread ratio, pressure relationship, pulse
  relationship, and UTC hour.
- [ ] Verify RED.
- [ ] Add strict optional fields and deterministic aligned/opposed/neutral
  relationship derivation.
- [ ] Run GREEN.
- [ ] Regenerate all three fixtures and verify forbidden-key scan.
- [ ] Commit with `feat: enrich scalper screening evidence`.

### Task 2: Implement canonical rule grammar

**Files:**
- Create: `tradingagents/agents/price_action/walk_forward_selector.py`
- Create: `tests/test_one_minute_walk_forward_selector.py`

- [ ] Write failing tests proving one-clause and two-clause evaluation, missing
  evidence rejection, stable canonical text, deduplication, and fixed-grid
  enforcement.
- [ ] Verify RED.
- [ ] Implement frozen `RuleClause` and `SelectorRule` models with operators
  `eq`, `ne`, `ge`, and `le`.
- [ ] Implement `generate_rules()` from only the spec's categorical values and
  numeric grid.
- [ ] Run GREEN.
- [ ] Commit with `feat: define deterministic scalper selector rules`.

### Task 3: Implement leave-one-session-out selection

**Files:**
- Modify: `tradingagents/agents/price_action/walk_forward_selector.py`
- Modify: `tests/test_one_minute_walk_forward_selector.py`

- [ ] Write failing tests using three synthetic sessions where training selects
  a known simple rule and held-out P/L is counted only once.
- [ ] Add controls for 60% training retention, positive training expectancy,
  simplest-rule tie breaking, and a fold with no candidate.
- [ ] Verify RED.
- [ ] Implement fold selection and aggregate out-of-sample rows using existing
  `summarize_variant` and `evaluate_historical_gate`.
- [ ] Run GREEN.
- [ ] Commit with `feat: add scalper walk-forward selection`.

### Task 4: Run the pre-registered screen

**Files:**
- Modify: `cli/main.py`
- Create: `tests/test_one_minute_walk_forward_cli.py`
- Create: `docs/analysis/2026-07-03-one-minute-scalper-walk-forward-screening.md`
- Create only on pass: `docs/analysis/2026-07-03-one-minute-scalper-walk-forward-candidate.json`

- [ ] Write a failing CLI test for `one-minute-walk-forward` and broker-free,
  byte-identical output.
- [ ] Verify RED.
- [ ] Implement the command without importing `tradingagents.brokers`.
- [ ] Run GREEN.
- [ ] Run twice and compare SHA-256.
- [ ] Record every fold rule, train metrics, held-out metrics, combined gate,
  and exact failure reasons.
- [ ] Create a frozen candidate only if every approved gate passes.
- [ ] Commit with `docs: report scalper walk-forward screening`.

### Task 5: Verify, merge, and push

- [ ] Run all evidence and selector tests.
- [ ] Run the complete pytest suite.
- [ ] Run `git diff --check`.
- [ ] Secret-scan all outgoing added lines and recursively validate fixture
  keys.
- [ ] Confirm zero `mt5-run` processes and read-only DEMO broker state with zero
  orders and positions.
- [ ] Merge verified work to `main`, rerun the complete suite, push, fetch, and
  prove local HEAD equals `origin/main`.

## Terminal decision

If no selector passes, publish `NO_WALK_FORWARD_CANDIDATE`, keep execution and
prospective candidate shadowing stopped, and move to a new architecture
hypothesis without weakening any gate.
