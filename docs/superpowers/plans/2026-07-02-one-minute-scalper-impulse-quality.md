# One Minute Scalper Impulse Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reject structurally two-sided and economically weak M1 impulse confirmations while preserving every trigger family and the existing execution and management behavior.

**Architecture:** Extend candidate scoring with two impulse-only deterministic
gates calculated from the latest fully closed M1 candle and the preceding 12
closed candles. Reuse the same quality calculation for telemetry so rejection
logic and diagnostics cannot disagree. Prove behavior with unit tests and a
sanitized MT5 candle replay fixture before deploying a fresh DEMO runner.

**Tech Stack:** Python 3.13, pytest, Pydantic, deterministic JSON replay
fixtures, PowerShell, MetaTrader 5 read-only history and DEMO execution.

---

### Task 1: Preserve the post-change forensic evidence

**Files:**
- Create: `docs/analysis/2026-07-02-one-minute-scalper-impulse-loss-review.md`

- [ ] **Step 1: Write the evidence report**

Record the 18-trade session and two-session comparison:

```text
evidence session: 18 trades, 5 wins, 13 losses, -630.80
combined sessions: 39 trades, 12 wins, 27 losses, -1,234.80
combined impulse: 27 trades, 8 wins, 19 losses, -923.00
combined two-sided impulse: 19 trades, 5 wins, 14 losses, -655.00
rapid later trades: 15 trades, 4 wins, 11 losses, -607.00
evidence-session zero-MFE losses: 12 of 13
intrabar loss saved versus original stops: approximately 160.78
```

Explain that fill drift, broker state, and active management did not produce
the dominant loss. Document that all 23 consumed contexts were unique and the
freshness guard therefore correctly did not fire.

- [ ] **Step 2: Scan the report**

Run:

```powershell
git diff --check
rg -n "account|login|password|server|terminal path" `
  docs/analysis/2026-07-02-one-minute-scalper-impulse-loss-review.md
```

Expected: no private value appears.

- [ ] **Step 3: Commit**

```powershell
git add docs/analysis/2026-07-02-one-minute-scalper-impulse-loss-review.md
git commit -m "docs: analyze post-change impulse losses"
```

### Task 2: Add impulse-only gates with TDD

**Files:**
- Modify: `tests/test_one_minute_entry_model.py`
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`

- [ ] **Step 1: Write failing unit tests**

Add tests that construct 60 closed M1 candles and assert:

```python
assert "IMPULSE_TWO_SIDED_STRUCTURE" in candidate["rejection_reasons"]
assert candidate["approved"] is False
```

for an impulse whose latest relation has both `broke_high_zone` and
`broke_low_zone`.

Add a weak-body impulse test:

```python
assert candidate["signal_quality"]["body_to_recent_median_range"] < 0.50
assert "WEAK_IMPULSE_BODY" in candidate["rejection_reasons"]
assert candidate["approved"] is False
```

Add controls proving a one-sided impulse remains approved and respect/fakeout
candidates never receive either impulse-only rejection.

- [ ] **Step 2: Run RED**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest `
  tests/test_one_minute_entry_model.py -k "two_sided or weak_impulse or one_sided" -q
```

Expected: failures because the new reason codes do not exist.

- [ ] **Step 3: Implement shared quality calculation**

In `one_minute_entry_model.py`, define:

```python
IMPULSE_TWO_SIDED_STRUCTURE = "IMPULSE_TWO_SIDED_STRUCTURE"
WEAK_IMPULSE_BODY = "WEAK_IMPULSE_BODY"
MIN_IMPULSE_BODY_TO_MEDIAN_RANGE = 0.50
```

Extract a helper that returns the existing signal-quality dictionary from a
candidate, history, and spread. Use it in both candidate scoring and telemetry.

- [ ] **Step 4: Implement minimal impulse gates**

Before final candidate approval:

```python
if candidate.reaction_type == "impulse_break":
    quality = _candidate_signal_quality(
        candidate,
        history,
        current_spread_price,
    )
    two_sided = (
        latest_relation.broke_high_zone
        and latest_relation.broke_low_zone
    )
    if two_sided:
        candidate.rejection_reasons.append(
            IMPULSE_TWO_SIDED_STRUCTURE
        )
    if (
        quality["body_to_recent_median_range"]
        < MIN_IMPULSE_BODY_TO_MEDIAN_RANGE
    ):
        candidate.rejection_reasons.append(WEAK_IMPULSE_BODY)
```

Store the quality dictionary under `fast_trigger_quality` and emit:

```python
"impulse_min_body_to_recent_median_range": 0.50
"impulse_one_sided_structure": not two_sided
```

- [ ] **Step 5: Run GREEN and regressions**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest `
  tests/test_one_minute_entry_model.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/agents/price_action/one_minute_entry_model.py `
  tests/test_one_minute_entry_model.py
git commit -m "fix: require clean M1 impulse confirmation"
```

### Task 3: Add sanitized historical replay proof

**Files:**
- Create: `tests/fixtures/one_minute/2026-07-02-impulse-quality-window.json`
- Modify: `tests/test_one_minute_signal_replay.py`

- [ ] **Step 1: Create the sanitized fixture**

Use read-only MT5 M1 history to extract market bars only for windows ending at:

```text
2026-07-02T10:41:00+00:00 losing two-sided impulse
2026-07-02T10:58:00+00:00 winning one-sided impulse
2026-07-02T11:52:00+00:00 losing weak-body impulse
```

Store timestamp, OHLC, spread, and tick volume. Do not store account, order,
deal, login, server, terminal, path, or balance metadata.

- [ ] **Step 2: Write historical replay regression tests**

Assert the two loss patterns are rejected with their exact reason codes and the
one-sided winner remains approved. The unit tests in Task 2 supplied the
mandatory failing tests before production code; these historical tests prove
the same behavior against captured market bars. Update prior replay
expectations only where the newly documented gate intentionally rejects a
previously diagnostic two-sided impulse. Keep a known one-sided impulse as an
approved regression.

- [ ] **Step 3: Run replay regressions**

Run:

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest `
  tests/test_one_minute_signal_replay.py -q
```

Expected: all replay tests pass and at most one candidate is approved per
candle.

- [ ] **Step 4: Commit**

```powershell
git add tests/fixtures/one_minute/2026-07-02-impulse-quality-window.json `
  tests/test_one_minute_signal_replay.py
git commit -m "test: replay impulse quality failures"
```

### Task 4: Verify the complete deterministic system

**Files:**
- Modify: `docs/one-minute-scalper-machine-migration.md`
- Modify: `docs/one-minute-scalper-handoff-2026-07-01.md`

- [ ] **Step 1: Update operator documentation**

Document the two new impulse rejection codes, their closed-M1 inputs, and the
rules deliberately unchanged.

- [ ] **Step 2: Run focused suites**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest `
  tests/test_one_minute_entry_model.py `
  tests/test_one_minute_signal_replay.py `
  tests/test_order_proposal.py `
  tests/test_opening_freshness.py `
  tests/test_execution_state.py `
  tests/test_mt5_broker.py `
  tests/test_mt5_execution.py `
  tests/test_mt5_runner.py `
  tests/test_cli_mt5_execution.py `
  tests/test_portability_artifacts.py -q
```

- [ ] **Step 3: Run the complete suite**

```powershell
& '..\..\.venv\Scripts\python.exe' -m pytest -q
git diff --check
git status --short
```

Expected: zero failures and only intended tracked changes.

- [ ] **Step 4: Commit documentation**

```powershell
git add docs/one-minute-scalper-machine-migration.md `
  docs/one-minute-scalper-handoff-2026-07-01.md
git commit -m "docs: document impulse confirmation gates"
```

### Task 5: Integrate, push, and restart safely

**Files:**
- Merge feature branch into `main`
- Generated and ignored: `results/<timestamp>-one-minute-scalper-impulse-quality`

- [ ] **Step 1: Secret and tracked-file inspection**

Compare tracked text against populated local secret values without printing
those values. Require zero exact matches and zero tracked `.env`, `results/`,
or `runtime/` files.

- [ ] **Step 2: Merge and verify main**

Merge the verified feature branch, run the complete suite again on `main`, and
require a clean tree.

- [ ] **Step 3: Push**

```powershell
git push origin main
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
```

Require identical hashes.

- [ ] **Step 4: Broker preflight**

Run the sanitized probe and require DEMO, trading enabled, a fresh tick, zero
open orders, and zero open positions. Never close broker state automatically.

- [ ] **Step 5: Start one fresh worker**

Run:

```powershell
.\scripts\start-one-minute-demo.ps1
```

Verify one logical process tree, advancing heartbeat, healthy `mt5_tick`,
runner/engine health agreement, empty stderr, and consistent broker counts.
Leave the worker active and do not force a trade.
