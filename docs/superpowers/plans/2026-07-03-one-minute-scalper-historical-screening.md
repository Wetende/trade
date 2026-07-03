# One Minute Scalper Historical Screening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic, sanitized historical screening gate that compares the unchanged One Minute Scalper baseline with the three pre-registered restrictive variants and identifies whether any candidate qualifies for prospective shadow validation.

**Architecture:** Keep strategy production code unchanged. Export sanitized decision/trade evidence into a stable schema, apply restrictive variants to the baseline-selected candidate without fallback, then calculate session and aggregate metrics through a pure evaluation module. A CLI command produces a sanitized report and machine-readable candidate manifest; no broker or execution class is imported.

**Tech Stack:** Python 3.13, Pydantic, Typer, pytest, JSON fixtures, existing One Minute Scalper telemetry.

---

## Scope boundary

This plan implements the historical screening subsystem from the approved
design. Prospective MT5 shadow collection is a separate subsystem and receives
its own plan only if a frozen candidate passes this historical gate.

The execution runner remains stopped. No task in this plan starts a runner or
calls an MT5 order mutation.

### Task 1: Define sanitized evidence models

**Files:**
- Create: `tradingagents/agents/price_action/evidence_gate.py`
- Create: `tests/test_one_minute_evidence_gate.py`

- [ ] **Step 1: Write failing schema tests**

```python
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from tradingagents.agents.price_action.evidence_gate import (
    EvidenceDecision,
    EvidenceSession,
    EvidenceTrade,
)


def test_evidence_session_accepts_market_and_strategy_fields_only():
    session = EvidenceSession(
        session_id="session-a",
        decisions=[
            EvidenceDecision(
                as_of=datetime(2026, 7, 2, 20, 0, tzinfo=timezone.utc),
                trigger="CLEAN_HIGH_IMPULSE_BUY",
                direction="BUY",
                reaction_type="impulse_break",
                approved=True,
                touch_count=3,
                body_ratio=0.75,
            )
        ],
        trades=[
            EvidenceTrade(
                decision_index=0,
                filled=True,
                placed_at=datetime(2026, 7, 2, 20, 0, tzinfo=timezone.utc),
                filled_at=datetime(2026, 7, 2, 20, 0, 1, tzinfo=timezone.utc),
                closed_at=datetime(2026, 7, 2, 20, 0, 30, tzinfo=timezone.utc),
                profit=50.0,
                spread=0.33,
                mfe=0.80,
                mae=-0.20,
            )
        ],
    )
    assert session.trades[0].decision_index == 0


def test_evidence_schema_rejects_broker_identifiers():
    with pytest.raises(ValidationError):
        EvidenceTrade(
            decision_index=0,
            filled=True,
            placed_at=datetime(2026, 7, 2, 20, 0, tzinfo=timezone.utc),
            filled_at=datetime(2026, 7, 2, 20, 0, 1, tzinfo=timezone.utc),
            closed_at=datetime(2026, 7, 2, 20, 0, 30, tzinfo=timezone.utc),
            profit=-50.0,
            spread=0.33,
            mfe=0.0,
            mae=-0.5,
            ticket=123,
        )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_evidence_gate.py -q
```

Expected: collection fails because `evidence_gate` does not exist.

- [ ] **Step 3: Implement strict models**

Create frozen Pydantic models with `extra="forbid"`:

```python
class EvidenceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    as_of: datetime
    trigger: str
    direction: Literal["BUY", "SELL"]
    reaction_type: Literal["impulse_break", "respect", "fakeout"]
    approved: bool
    touch_count: int = Field(ge=2)
    body_ratio: float = Field(ge=0)


class EvidenceTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision_index: int = Field(ge=0)
    filled: bool
    placed_at: datetime
    filled_at: datetime | None
    closed_at: datetime | None
    profit: float | None
    spread: float = Field(ge=0)
    mfe: float | None
    mae: float | None


class EvidenceSession(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    session_id: str
    decisions: tuple[EvidenceDecision, ...]
    trades: tuple[EvidenceTrade, ...]
```

Add model validation requiring unfilled trades to have `filled_at`,
`closed_at`, `profit`, `mfe`, and `mae` set to `None`. Filled trades require
all five values, `filled_at >= placed_at`, and `closed_at >= filled_at`.

- [ ] **Step 4: Run GREEN**

Run the Task 1 test file. Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/price_action/evidence_gate.py tests/test_one_minute_evidence_gate.py
git commit -m "feat: define sanitized scalper evidence"
```

### Task 2: Implement isolated restrictive variants

**Files:**
- Modify: `tradingagents/agents/price_action/evidence_gate.py`
- Modify: `tests/test_one_minute_evidence_gate.py`

- [ ] **Step 1: Add failing variant tests**

Test these exact rules:

```python
assert evaluate_variant(two_touch_impulse, "baseline").accepted is True
assert evaluate_variant(two_touch_impulse, "h1_touch_maturity").reason == (
    "SHADOW_IMPULSE_REQUIRES_THIRD_TOUCH"
)
assert evaluate_variant(large_body_impulse, "h2_exhaustion").reason == (
    "SHADOW_IMPULSE_BODY_EXHAUSTED"
)
assert evaluate_variant(large_body_respect, "h2_exhaustion").accepted is True
```

Add boundary controls proving body ratio `1.20` is accepted and `1.2001` is
rejected. Add a control proving a rejected primary candidate produces HOLD;
the evaluator must never select a lower-ranked fallback.

- [ ] **Step 2: Run RED**

Expected: imports or assertions fail because variant evaluation is absent.

- [ ] **Step 3: Implement variant configuration and evaluation**

```python
class VariantName(StrEnum):
    BASELINE = "baseline"
    H1_TOUCH_MATURITY = "h1_touch_maturity"
    H2_EXHAUSTION = "h2_exhaustion"
    H3_POST_LOSS_CLUSTER = "h3_post_loss_cluster"


class VariantDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    accepted: bool
    reason: str | None = None


def evaluate_variant(
    decision: EvidenceDecision,
    variant: VariantName | str,
) -> VariantDecision:
    selected = VariantName(variant)
    if not decision.approved:
        return VariantDecision(accepted=False, reason="BASELINE_REJECTED")
    if decision.reaction_type != "impulse_break":
        return VariantDecision(accepted=True)
    if selected == VariantName.H1_TOUCH_MATURITY and decision.touch_count < 3:
        return VariantDecision(
            accepted=False,
            reason="SHADOW_IMPULSE_REQUIRES_THIRD_TOUCH",
        )
    if selected == VariantName.H2_EXHAUSTION and decision.body_ratio > 1.20:
        return VariantDecision(
            accepted=False,
            reason="SHADOW_IMPULSE_BODY_EXHAUSTED",
        )
    return VariantDecision(accepted=True)
```

- [ ] **Step 4: Run GREEN and the current signal tests**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_evidence_gate.py tests/test_one_minute_entry_model.py tests/test_one_minute_signal_replay.py -q
```

Expected: pass; production engine behavior is unchanged.

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/price_action/evidence_gate.py tests/test_one_minute_evidence_gate.py
git commit -m "feat: add scalper screening variants"
```

### Task 3: Add stateful post-loss screening and combinations

**Files:**
- Modify: `tradingagents/agents/price_action/evidence_gate.py`
- Modify: `tests/test_one_minute_evidence_gate.py`

- [ ] **Step 1: Write failing H3 timeline tests**

Create decisions at `12:00`, `12:04:59`, and `12:05:00` UTC after a loss
closed at `12:00`. Assert that `12:04:59` is suppressed and `12:05:00` is
accepted.
Assert that a prior win does not start suppression.

- [ ] **Step 2: Write failing combination tests**

Assert that pairwise combinations apply both constituent rules and return
ordered reason codes. Assert that three-way combinations are rejected by
configuration validation during historical screening.

- [ ] **Step 3: Run RED**

Expected: H3 and combination tests fail.

- [ ] **Step 4: Implement chronological evaluation**

Add `evaluate_session(session, variants)` which:

- sorts decisions by `as_of`;
- tracks the most recent simulated filled loss `closed_at` per variant;
- applies H3 until `loss_time + timedelta(minutes=5)`;
- never allows more than one trade for the same `decision_index`;
- evaluates singles first and only the pairwise combinations
  `h1+h2`, `h1+h3`, and `h2+h3`.

Return immutable rows containing session, decision index, variant, accepted,
filled, profit, and reason codes.

- [ ] **Step 5: Run GREEN**

Run `tests/test_one_minute_evidence_gate.py -q`. Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/agents/price_action/evidence_gate.py tests/test_one_minute_evidence_gate.py
git commit -m "feat: evaluate stateful scalper variants"
```

### Task 4: Calculate qualification metrics

**Files:**
- Create: `tradingagents/agents/price_action/evidence_metrics.py`
- Create: `tests/test_one_minute_evidence_metrics.py`

- [ ] **Step 1: Write failing metric tests**

Use a fixed trade sequence to assert wins, losses, net P/L, profit factor,
expectancy, fill retention, maximum loss streak, and maximum drawdown. Include
zero-gross-loss handling without infinity or NaN.

- [ ] **Step 2: Write failing gate tests**

Assert a variant passes only with:

```python
expectancy > 0
profit_factor >= 1.15
profitable_session_count >= 2
fill_retention >= 0.60
max_loss_streak <= baseline.max_loss_streak
max_session_drawdown <= baseline.max_session_drawdown
```

- [ ] **Step 3: Run RED**

Expected: module import fails.

- [ ] **Step 4: Implement pure metrics and gate evaluation**

Define strict `VariantMetrics` and `HistoricalGateResult` models. Calculate
drawdown from chronological cumulative realized P/L. Represent a no-loss
profit factor as `None` plus `no_gross_loss=True`, and treat it as satisfying
the numeric threshold only when net P/L and expectancy are positive.

- [ ] **Step 5: Run GREEN**

Run both evidence test files. Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/agents/price_action/evidence_metrics.py tests/test_one_minute_evidence_metrics.py
git commit -m "feat: score scalper evidence candidates"
```

### Task 5: Export safe historical evidence

**Files:**
- Create: `scripts/export-one-minute-evidence.py`
- Create: `tests/test_one_minute_evidence_export.py`
- Create: `tests/fixtures/one_minute/evidence_sessions/.gitkeep`

- [ ] **Step 1: Write failing export tests**

Build a temporary result session containing candidate telemetry and closed
trade summaries with synthetic broker identifiers. Assert the exported JSON
validates as `EvidenceSession` and recursively contains none of:

```text
account, login, password, server, terminal, ticket, order, deal, position_id
```

- [ ] **Step 2: Run RED**

Expected: exporter does not exist.

- [ ] **Step 3: Implement deterministic export**

The script accepts explicit `--session` arguments and `--output-dir`. It joins
trades to their selected candidate in memory, writes only the Task 1 schema,
sorts by UTC timestamp, hashes no private identifiers, and refuses incomplete
joins rather than guessing.

- [ ] **Step 4: Run GREEN**

Run the export tests. Expected: pass.

- [ ] **Step 5: Export the three reviewed sessions**

Export the 21-, 18-, and 32-trade sessions to
`tests/fixtures/one_minute/evidence_sessions/`. Validate each fixture with the
strict model and scan added lines for secrets before staging.

- [ ] **Step 6: Commit**

```powershell
git add scripts/export-one-minute-evidence.py tests/test_one_minute_evidence_export.py tests/fixtures/one_minute/evidence_sessions
git commit -m "test: add sanitized scalper evidence sessions"
```

### Task 6: Add the historical-screening CLI

**Files:**
- Modify: `cli/main.py`
- Modify: `tests/test_cli_mt5_execution.py`
- Create: `tests/test_one_minute_historical_screening.py`

- [ ] **Step 1: Write failing CLI safety test**

Invoke:

```text
one-minute-screen --evidence-dir <fixtures> --output <report.json>
```

Monkeypatch `MT5Executor`, `MT5Broker`, and order mutation methods to raise if
constructed or called. Assert the command succeeds without touching them.

- [ ] **Step 2: Write failing deterministic report test**

Run screening twice and assert byte-identical JSON. Assert the report includes
baseline, each single hypothesis, permitted pairs, qualification reasons,
source fixture hashes, and `broker_mutation_enabled: false`.

- [ ] **Step 3: Run RED**

Expected: Typer reports that `one-minute-screen` is unknown.

- [ ] **Step 4: Implement the command**

The command loads only sanitized fixtures, evaluates all variants, writes
sorted JSON atomically, and exits:

- `0` when evaluation completed, regardless of whether a candidate qualifies;
- `2` for invalid or incomplete evidence;
- `3` for nondeterministic duplicate evidence.

It must not import modules from `tradingagents.brokers`.

- [ ] **Step 5: Run GREEN**

Run the CLI and screening tests. Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add cli/main.py tests/test_cli_mt5_execution.py tests/test_one_minute_historical_screening.py
git commit -m "feat: add scalper historical screening command"
```

### Task 7: Run screening and publish the sanitized decision report

**Files:**
- Create: `docs/analysis/2026-07-03-one-minute-scalper-historical-screening.md`
- Create only if a candidate qualifies: `docs/analysis/2026-07-03-one-minute-scalper-frozen-candidate.json`

- [ ] **Step 1: Run the deterministic screen**

```powershell
.\.venv\Scripts\python.exe -m cli.main one-minute-screen `
  --evidence-dir tests/fixtures/one_minute/evidence_sessions `
  --output test-artifacts/one-minute-historical-screening.json
```

- [ ] **Step 2: Verify reproducibility**

Run again to a second file and compare SHA-256 hashes. Expected: equal.

- [ ] **Step 3: Write the report**

Document every variant's sample size, wins, losses, net P/L, profit factor,
expectancy, session profitability, retention, loss streak, drawdown, and exact
pass/fail reasons. State explicitly that historical qualification does not
authorize broker orders.

- [ ] **Step 4: Freeze only a qualifying candidate**

If one or more variants pass, choose the simplest passing variant in this
order: single hypothesis, then two-rule combination. Write its exact rules,
fixture hashes, source commit, and metrics to the frozen manifest.

If none passes, do not create a manifest and do not proceed to prospective
shadow implementation. Record `NO_HISTORICAL_CANDIDATE`.

- [ ] **Step 5: Commit the report**

```powershell
git add docs/analysis/2026-07-03-one-minute-scalper-historical-screening.md
git add docs/analysis/2026-07-03-one-minute-scalper-frozen-candidate.json 2>$null
git commit -m "docs: report scalper historical screening"
```

### Task 8: Complete verification and safe push

**Files:**
- Modify if needed: `docs/one-minute-scalper-handoff-2026-07-01.md`
- Modify if needed: `docs/one-minute-scalper-machine-migration.md`

- [ ] **Step 1: Run focused suites**

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests/test_one_minute_evidence_gate.py `
  tests/test_one_minute_evidence_metrics.py `
  tests/test_one_minute_evidence_export.py `
  tests/test_one_minute_historical_screening.py `
  tests/test_cli_mt5_execution.py -q
```

- [ ] **Step 2: Run full verification**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
git status --short
```

Expected: all required tests pass and only intentional tracked files differ.

- [ ] **Step 3: Inspect staged content**

Scan every staged added line for credentials, tokens, numeric login values,
broker identifiers, and private paths. Verify fixture keys recursively against
the strict evidence schema.

- [ ] **Step 4: Verify safety state**

Confirm zero `mt5-run` processes and use the read-only broker probe to confirm
DEMO mode, zero open orders, and zero open positions. Do not start execution.

- [ ] **Step 5: Commit any handoff updates and push**

```powershell
git push origin main
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
```

Expected: local HEAD equals `origin/main`.

## Terminal outcomes

- The production strategy remains unchanged.
- No broker order is placed.
- All three pre-registered hypotheses and allowed pairs are evaluated.
- Historical evidence and reports are sanitized and deterministic.
- A frozen candidate exists only if every historical gate passes.
- Prospective shadow work begins only from that frozen candidate.
