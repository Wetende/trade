# One Minute Scalper Evidence Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add durable candidate-local reset enforcement, complete execution evidence, idempotent management reconciliation, and account-safe portability without adding unproven entry filters.

**Architecture:** The M1 engine emits immutable opening and shadow-quality context into `OrderProposal`. A small pure opening-freshness module compares that context with bounded durable execution state, and `MT5Executor` consumes an opening only after successful broker placement. Execution state archives first/final observations and excursions; output-bound connection data passes through a single sanitizer while internal broker guards retain the full connection object.

**Tech Stack:** Python 3.10-3.13, Pydantic 2, pytest, MetaTrader5 adapter, append-only JSONL journal, atomic JSON execution state.

---

## File structure

| File | Responsibility |
|---|---|
| `tradingagents/agents/price_action/one_minute_entry_model.py` | Derive opening context and shadow metrics from 60 closed M1 candles. |
| `tradingagents/agents/schemas.py` | Carry optional opening and signal-quality context in proposals. |
| `tradingagents/agents/execution/order_proposal.py` | Transfer selected engine context into the execution proposal. |
| `tradingagents/brokers/opening_freshness.py` | Pure same-zone and stale-opening comparison. |
| `tradingagents/brokers/execution_state.py` | Preserve consumed openings and completed execution telemetry atomically. |
| `tradingagents/brokers/mt5_execution.py` | Enforce stale-opening reset, capture execution timeline, archive excursions, and reconcile close races. |
| `tradingagents/brokers/mt5.py` | Produce safe output representations and identifier-free guard errors. |
| `cli/main.py` | Print only sanitized broker-probe output. |
| `tests/test_one_minute_entry_model.py` | Closed-candle opening and shadow-metric tests. |
| `tests/test_order_proposal.py` | Engine-to-proposal context transfer tests. |
| `tests/test_opening_freshness.py` | Pure reset-semantics matrix. |
| `tests/test_execution_state.py` | Persistent-state preservation and bounded archive tests. |
| `tests/test_mt5_execution.py` | Stale guard, timeline, excursion, race, and safe-journal tests. |
| `tests/test_mt5_broker.py` | Safe connection and identifier-free mismatch tests. |
| `tests/test_cli_mt5_execution.py` | Sanitized probe-output test. |
| `tests/test_one_minute_signal_replay.py` | Winner/control replay regressions and ranking stability. |

### Task 1: Emit opening context and shadow measurements

**Files:**
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Modify: `tests/test_one_minute_entry_model.py`
- Modify: `tests/test_one_minute_signal_replay.py`

- [ ] **Step 1: Write failing engine tests**

Add tests that assert selected and evaluated candidates include context derived
from closed candles:

```python
def test_selected_candidate_emits_closed_m1_opening_context():
    payload = analyze_one_minute_entry(
        "XAUUSD",
        "2026-07-01 19:44",
        {"1m": replay_candles},
        session_config=fast_config,
    )
    context = payload["telemetry"]["selected_candidate"]["opening_context"]
    assert context["confirmation_timestamp"] == replay_candles[-1]["timestamp"]
    assert context["last_touch_timestamp"] in {
        candle["timestamp"] for candle in replay_candles
    }
    assert context["level"] == payload["market_context"]["one_minute_story"]["level"]
    assert context["touch_count"] >= 2


def test_signal_quality_metrics_are_shadow_only():
    payload = analyze_one_minute_entry(...)
    selected = payload["telemetry"]["selected_candidate"]
    metrics = selected["signal_quality"]
    assert metrics["confirmation_body"] >= 0
    assert metrics["confirmation_range"] >= metrics["confirmation_body"]
    assert metrics["body_to_recent_median_range"] >= 0
    assert metrics["entry_distance_from_level"] >= 0
    assert selected["approved"] is True
```

Add a replay assertion that candidate ordering and the known winning trigger
remain unchanged when shadow fields are emitted.

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_one_minute_entry_model.py `
  tests/test_one_minute_signal_replay.py -k "opening_context or shadow" -v
```

Expected: FAIL because `opening_context` and `signal_quality` do not exist.

- [ ] **Step 3: Add deterministic context helpers**

Add helpers equivalent to:

```python
def _history_timestamp(history: list[Candle], index: int) -> str | None:
    if 0 <= index < len(history):
        return str(history[index].timestamp)
    return None


def _candidate_opening_context(
    candidate: OneMinuteCandidate,
    history: list[Candle],
    tolerance: float,
) -> dict[str, Any]:
    return {
        "model_name": MODEL_NAME,
        "direction": candidate.direction,
        "trigger": candidate.trigger,
        "reaction_type": candidate.reaction_type,
        "confirmation_type": candidate.confirmation_type,
        "level": round(candidate.level.level, 4),
        "level_side": candidate.level.side,
        "level_type": candidate.level.level_type,
        "tolerance": round(tolerance, 4),
        "touch_count": candidate.level.touch_count,
        "first_touch_timestamp": _history_timestamp(
            history, candidate.level.first_touch_index
        ),
        "last_touch_timestamp": _history_timestamp(
            history, candidate.level.last_touch_index
        ),
        "confirmation_timestamp": str(history[-1].timestamp),
    }
```

Compute shadow metrics from `history[-1]`, the preceding 12 closed bars,
candidate entry/stop/level, and decision spread. Attach both dictionaries in
`_candidate_to_telemetry`. Do not read or modify the forming candle and do not
use the metrics in `_score_candidate`.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 1 command. Expected: PASS.

- [ ] **Step 5: Run entry-model regressions**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_one_minute_entry_model.py `
  tests/test_one_minute_signal_replay.py -q
```

Expected: all pass with unchanged trigger/ranking expectations.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/agents/price_action/one_minute_entry_model.py `
  tests/test_one_minute_entry_model.py tests/test_one_minute_signal_replay.py
git commit -m "feat: emit one-minute opening evidence"
```

### Task 2: Carry context through order proposals

**Files:**
- Modify: `tradingagents/agents/schemas.py`
- Modify: `tradingagents/agents/execution/order_proposal.py`
- Modify: `tests/test_order_proposal.py`

- [ ] **Step 1: Write a failing proposal-transfer test**

```python
def test_engine_order_proposal_carries_opening_and_signal_context(tmp_path):
    state = engine_state_with_selected_candidate(
        opening_context={
            "model_name": "One Minute Scalper",
            "direction": "SELL",
            "trigger": "HIGH_RESPECT_SELL",
            "reaction_type": "respect",
            "confirmation_type": "rejection",
            "level": 4039.1,
            "level_side": "high",
            "level_type": "three_touch",
            "tolerance": 0.24,
            "touch_count": 4,
            "first_touch_timestamp": "2026-07-01T22:30:00+00:00",
            "last_touch_timestamp": "2026-07-01T23:20:00+00:00",
            "confirmation_timestamp": "2026-07-01T23:21:00+00:00",
        },
        signal_quality={"body_to_recent_median_range": 0.43},
    )
    proposal = build_order_proposal(state)
    assert proposal.opening_context["level"] == 4039.1
    assert proposal.signal_quality["body_to_recent_median_range"] == 0.43
```

- [ ] **Step 2: Run and verify RED**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_order_proposal.py::test_engine_order_proposal_carries_opening_and_signal_context -v
```

Expected: FAIL because the schema fields do not exist.

- [ ] **Step 3: Add optional schema fields and transfer**

Add:

```python
opening_context: Optional[dict] = None
signal_quality: Optional[dict] = None
decision_quote: Optional[dict] = None
```

In `_proposal_from_engine_payload`, copy only dictionaries from
`telemetry.selected_candidate` and build `decision_quote` from the engine
payload's safe bid, ask, spread, and reference timestamp. Legacy and non-M1
payloads retain `None`.

- [ ] **Step 4: Run focused and schema regressions**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_order_proposal.py tests/test_schemas.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/schemas.py `
  tradingagents/agents/execution/order_proposal.py tests/test_order_proposal.py
git commit -m "feat: carry M1 opening context into proposals"
```

### Task 3: Implement pure opening freshness and persistent state

**Files:**
- Create: `tradingagents/brokers/opening_freshness.py`
- Create: `tests/test_opening_freshness.py`
- Modify: `tradingagents/brokers/execution_state.py`
- Modify: `tests/test_execution_state.py`

- [ ] **Step 1: Write the stale/fresh matrix first**

Cover:

```python
def test_identical_consumed_opening_is_stale():
    assert stale_consumed_opening(current, [current]) == current


@pytest.mark.parametrize(
    "change",
    [
        {"confirmation_timestamp": "2026-07-01T23:22:00+00:00"},
        {"last_touch_timestamp": "2026-07-01T23:21:00+00:00"},
        {"touch_count": 5},
        {"reaction_type": "fakeout"},
        {"trigger": "FAILED_HIGH_BREAK_SELL"},
        {"direction": "BUY"},
        {"level": 4041.0},
    ],
)
def test_structural_change_rearms_consumed_opening(change):
    assert stale_consumed_opening({**BASE, **change}, [BASE]) is None
```

Also test same-zone tolerance boundaries, invalid/missing context, and
deterministic newest-record selection.

- [ ] **Step 2: Run and verify RED**

Expected: import failure because `opening_freshness.py` does not exist.

- [ ] **Step 3: Implement the pure comparator**

Expose:

```python
def same_opening_zone(current: Mapping[str, Any], previous: Mapping[str, Any]) -> bool
def stale_consumed_opening(
    current: Mapping[str, Any],
    consumed: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None
```

Use normalized uppercase strings, finite numeric parsing, ISO timestamp
comparison, and `max(current_tolerance, previous_tolerance)`.

- [ ] **Step 4: Verify comparator GREEN**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_opening_freshness.py -v
```

- [ ] **Step 5: Write failing state-preservation tests**

Assert that:

```python
store.record_consumed_opening(context, consumed_at_utc=fixed_time)
store.record_pending_order(...)
store.clear_trade()
assert store.load()["consumed_openings"][0]["opening_context"] == context
```

Add tests for a bounded 128-record list, completed-position archive
preservation, and atomic legacy-state loading.

- [ ] **Step 6: Implement state merge/preservation**

Add `record_consumed_opening`, `archive_position_telemetry`, and
`completed_position_telemetry`. Change `record_pending_order` and
`clear_trade` to merge durable keys instead of replacing the whole document.
Keep active-order fields reset exactly as before.

- [ ] **Step 7: Run state and comparator suites**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_opening_freshness.py tests/test_execution_state.py -q
```

- [ ] **Step 8: Commit**

```powershell
git add tradingagents/brokers/opening_freshness.py `
  tradingagents/brokers/execution_state.py `
  tests/test_opening_freshness.py tests/test_execution_state.py
git commit -m "feat: persist consumed M1 openings"
```

### Task 4: Enforce reset and capture the order timeline

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing stale-guard executor tests**

Tests must prove:

```python
first = executor.execute_proposal(context_proposal)
assert first["status"] == "PLACED"
executor.state.clear_trade()
second = restarted_executor.execute_proposal(context_proposal)
assert second["status"] == "SKIPPED_STALE_OPENING"
assert restarted_broker.placed_requests == []
```

Add separate tests showing a new confirmation, new touch, increased touches,
changed reaction, changed direction, and out-of-zone level still place.
Assert rejected broker orders do not consume context and an expired successful
order remains consumed after cancellation.

- [ ] **Step 2: Run and verify RED**

Expected: duplicate proposal is placed because no freshness guard exists.

- [ ] **Step 3: Implement the pre-send freshness gate**

Before request construction:

```python
context = proposal.opening_context
if _is_one_minute_scalper_proposal(proposal):
    if not context:
        journal OPENING_FRESHNESS_UNAVAILABLE
    elif stale_consumed_opening(context, state["consumed_openings"]):
        return {
            "status": "SKIPPED_STALE_OPENING",
            "reason": "STALE_CONSUMED_OPENING",
            "opening_context": context,
            "account_safety": account_safety,
        }
```

Call `record_consumed_opening` only in the existing successful-placement
branch.

- [ ] **Step 4: Run freshness executor tests GREEN**

Run their exact node IDs and verify all pass.

- [ ] **Step 5: Write failing execution-timeline test**

Configure `FakeBroker.current_symbol_snapshot()` and a deterministic executor
clock, then assert:

```python
timeline = result["execution_timeline"]
assert timeline["decision_quote"]["spread_price"] == 0.29
assert timeline["pre_send_quote"]["spread_price"] == 0.30
assert timeline["submitted_at_utc"] < timeline["acknowledged_at_utc"]
assert state["execution_timeline"] == timeline
```

- [ ] **Step 6: Implement safe quote snapshots**

Read only `observed_at_utc`, `tick_time_utc`, `bid`, `ask`, and
`spread_price`. Record `ORDER_EXECUTION_TIMELINE` after each broker
acknowledgement, including the expiration fallback attempt without replacing
the original attempt.

- [ ] **Step 7: Run execution placement regressions**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_mt5_execution.py -k "opening or timeline or places or expiration" -q
```

- [ ] **Step 8: Commit**

```powershell
git add tradingagents/brokers/mt5_execution.py tests/test_mt5_execution.py
git commit -m "feat: guard stale M1 openings and journal submissions"
```

### Task 5: Complete fill, excursion, and exit evidence

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tradingagents/brokers/execution_state.py`
- Modify: `tests/test_mt5_execution.py`
- Modify: `tests/test_execution_state.py`

- [ ] **Step 1: Write failing first-observation test**

Assert the first monitoring pass emits and persists:

```python
{
    "position_id": "777034",
    "opened_at_utc": "...",
    "entry_price": 2450.0,
    "observed_at_utc": "...",
    "quote": {"bid": 2450.4, "ask": 2450.7, "spread_price": 0.3},
    "fill_to_observation_seconds": ...,
}
```

The event must be emitted exactly once per position.

- [ ] **Step 2: Verify RED, implement, verify GREEN**

Add a `position_first_observation` record beside excursion state and append
`POSITION_FIRST_OBSERVED` only when absent.

- [ ] **Step 3: Write failing archive/reconciliation test**

Simulate sampled MFE/MAE, remove the position, call management once to archive,
then reconcile exact entry/exit deals. Assert:

```python
trade["mfe_points"] == max(sampled_mfe, exit_movement)
trade["mae_points"] == min(sampled_mae, exit_movement)
trade["excursion_source"] == "one_second_samples_plus_exit"
trade["entry_drift"] == expected
trade["order_wait_seconds"] == expected
```

- [ ] **Step 4: Implement archive before clear and summary merge**

When a tracked position disappears, move its proposal, timeline, first
observation, and excursion state into bounded completed telemetry before
clearing active fields. In `_closed_trade_summary`, merge by position ID and
include final exit movement.

- [ ] **Step 5: Run evidence regressions**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_execution_state.py `
  tests/test_mt5_execution.py -k "observation or excursion or reconcile_trade_history" -q
```

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/brokers/execution_state.py `
  tradingagents/brokers/mt5_execution.py `
  tests/test_execution_state.py tests/test_mt5_execution.py
git commit -m "feat: complete M1 execution evidence"
```

### Task 6: Reconcile management races idempotently

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing emergency-race test**

After the second adverse observation, make `close_position` return invalid
request and make the refreshed open-position list empty. Assert:

```python
assert action["reason"] == "POSITION_ALREADY_CLOSED"
assert action["action"] == "NO_ACTION"
assert result["status"] != "POSITION_MANAGEMENT_FAILED"
assert journal_event == "POSITION_CLOSE_RECONCILED"
```

- [ ] **Step 2: Write failing partial-race test**

At the partial threshold, return "Position doesn't exist" and remove the
position before refresh. Assert it is reconciled, not reported as a successful
partial and not counted as failure.

- [ ] **Step 3: Write true-failure control**

Return the same broker failure while keeping the position open. Assert the
existing `POSITION_CLOSE_FAILED` or `POSITION_PARTIAL_CLOSE_FAILED` behavior
remains.

- [ ] **Step 4: Run and verify RED**

Run the three exact tests. Expected: race cases are currently failures.

- [ ] **Step 5: Implement one refresh-only reconciliation helper**

The helper compares the target ticket/identifier against a fresh
`open_positions` result. It returns a `NO_ACTION/POSITION_ALREADY_CLOSED`
action only when the position is absent. Do not retry the close.

- [ ] **Step 6: Run focused and full management tests**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_mt5_execution.py -k "partial or intrabar or rejection or scalp or close" -q
```

- [ ] **Step 7: Commit**

```powershell
git add tradingagents/brokers/mt5_execution.py tests/test_mt5_execution.py
git commit -m "fix: reconcile already-closed MT5 actions"
```

### Task 7: Remove account metadata from outputs and paths

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tradingagents/brokers/execution_state.py`
- Modify: `cli/main.py`
- Modify: `tests/test_mt5_broker.py`
- Modify: `tests/test_mt5_execution.py`
- Modify: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write failing sanitizer tests**

Construct a connection containing login, server, name, company, balance,
equity, and terminal path. Assert `safe_mt5_connection_status` contains DEMO
safety and quote data but none of those values or keys.

- [ ] **Step 2: Write failing mismatch-error tests**

Assert account mismatch exceptions contain neither actual nor expected login
or server values.

- [ ] **Step 3: Write failing hashed-namespace test**

```python
namespace = account_state_namespace("private-server", 123456789)
assert namespace.startswith("account-")
assert "private-server" not in namespace
assert "123456789" not in namespace
assert namespace == account_state_namespace("private-server", 123456789)
```

- [ ] **Step 4: Write failing output-boundary tests**

Assert `CONNECTED`, `STATE_SNAPSHOT`, heartbeat payloads, and `broker-probe`
output do not contain sentinel login/server/name/balance values.

- [ ] **Step 5: Run and verify RED**

Run all new node IDs. Expected: current outputs and state path expose the
sentinels.

- [ ] **Step 6: Implement central sanitizer and hashed namespace**

Use SHA-256 over `server + "\0" + login`, retaining 16 hexadecimal characters.
Use the sanitizer only on output/journal/heartbeat boundaries; broker guard
logic continues to use the complete in-memory connection.

- [ ] **Step 7: Sanitize probe and error text**

`broker-probe` computes account safety and serializes only the safe result.
Mismatch messages identify the failed guard without values.

- [ ] **Step 8: Run safety regressions**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_mt5_broker.py `
  tests/test_mt5_execution.py `
  tests/test_cli_mt5_execution.py -q
```

- [ ] **Step 9: Commit**

```powershell
git add tradingagents/brokers/mt5.py `
  tradingagents/brokers/mt5_execution.py `
  tradingagents/brokers/execution_state.py cli/main.py `
  tests/test_mt5_broker.py tests/test_mt5_execution.py `
  tests/test_cli_mt5_execution.py
git commit -m "fix: keep MT5 account metadata private"
```

### Task 8: Complete documentation and portability artifacts

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `docs/one-minute-scalper-machine-migration.md`
- Modify: `docs/one-minute-scalper-handoff-2026-07-01.md`
- Create: `scripts/setup-windows.ps1`
- Create: `scripts/start-one-minute-demo.ps1`
- Test: `tests/test_portability_artifacts.py`

- [ ] **Step 1: Write failing artifact tests**

Assert:

- both scripts exist and parse as PowerShell;
- the setup script installs project, pytest, and MetaTrader5;
- the runner script sets DEMO, ENTRY_ONLY, fast_only, M1, volume 1.0,
  boost-disabled, session-loss, and hidden-window flags;
- the runner script refuses unless a safe preflight command reports DEMO,
  zero orders, zero positions, and trading enabled;
- `.env.example` has blank credential fields and no real-order
  acknowledgement;
- migration links resolve.

- [ ] **Step 2: Run and verify RED**

Expected: scripts and tests do not exist.

- [ ] **Step 3: Implement safe setup and runner scripts**

The setup script creates `.venv` and installs dependencies. The runner script
calls a sanitized read-only preflight, creates a timestamped results
directory, refuses duplicate workers, and starts one hidden process. It never
prints credentials or account identifiers.

- [ ] **Step 4: Update docs**

Document the new hashed runtime namespace, sanitized probe, consumed-opening
state, scripts, and deliberate exclusions. Preserve the raw-results and
credential exclusions.

- [ ] **Step 5: Run portability tests and PowerShell parsing**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_portability_artifacts.py -v
[void][scriptblock]::Create((Get-Content scripts/setup-windows.ps1 -Raw))
[void][scriptblock]::Create((Get-Content scripts/start-one-minute-demo.ps1 -Raw))
```

- [ ] **Step 6: Commit**

```powershell
git add .env.example README.md docs scripts tests/test_portability_artifacts.py
git commit -m "docs: complete safe Windows portability"
```

### Task 9: Full verification and clean-checkout proof

**Files:**
- Review only all changed and staged files
- Create generated temporary checkout outside the working repository

- [ ] **Step 1: Run focused suites**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest `
  tests/test_one_minute_entry_model.py `
  tests/test_one_minute_signal_replay.py `
  tests/test_order_proposal.py `
  tests/test_opening_freshness.py `
  tests/test_execution_state.py `
  tests/test_execution_journal.py `
  tests/test_mt5_broker.py `
  tests/test_mt5_execution.py `
  tests/test_mt5_runner.py `
  tests/test_cli_mt5_execution.py `
  tests/test_portability_artifacts.py -q
```

- [ ] **Step 2: Run the complete suite**

```powershell
& 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe' -m pytest -q
```

- [ ] **Step 3: Run repository checks**

```powershell
git diff --check
git status --short
git log --oneline --decorate -12
```

- [ ] **Step 4: Run secret and private-metadata scans**

Scan tracked and staged text for private-key, provider-token, populated
credential, raw-account-identifier, and terminal-path patterns. Inspect every
staged filename. No generated `results/`, raw reverse-engineering export,
runtime state, populated `.env`, or account-bearing screenshot may be staged.

- [ ] **Step 5: Validate a clean checkout**

Create a temporary clone from the feature branch, install it into a new
virtual environment, run portability and deterministic replay tests, then
remove only the verified temporary directory. Do not modify or delete the
working repository.

- [ ] **Step 6: Review requirements**

Check every design section and original goal requirement against code, tests,
docs, and command output. Record any gap and fix it test-first before
proceeding.

### Task 10: Integrate, push, and start a fresh DEMO session

**Files:**
- Merge the feature branch into local `main`
- Generated and ignored: `results/<timestamp>-one-minute-scalper-evidence`

- [ ] **Step 1: Merge verified commits into main**

Return to the primary checkout, confirm it is clean, and fast-forward or merge
the verified feature branch without discarding the three existing main
checkpoints.

- [ ] **Step 2: Repeat staged/tracked secret inspection**

Confirm all safe docs, specs, plans, source, tests, fixtures, lock files, and
scripts are tracked and no private artifacts are included.

- [ ] **Step 3: Push main**

```powershell
git push origin main
git fetch origin
git rev-parse HEAD
git rev-parse origin/main
```

Expected: both hashes are identical.

- [ ] **Step 4: Re-check broker state**

Use the sanitized read-only preflight. Require DEMO, trading permission,
fresh tick, zero open orders, and zero open positions. If broker state is not
flat, monitor it and do not close it automatically.

- [ ] **Step 5: Start exactly one hidden worker**

Use `scripts/start-one-minute-demo.ps1`. Keep ENTRY_ONLY, `fast_only`, closed
M1, 1.0 volume, boost disabled, one-active-trade guard, and the configured 600
session-loss cap.

- [ ] **Step 6: Verify the live heartbeat**

Verify the process exists, heartbeat advances, account safety is DEMO and
passed, engine and runner health agree, `reference_source` is `mt5_tick`,
stderr is empty, and broker order/position counts agree with the heartbeat.
Do not force a trade.

- [ ] **Step 7: Leave the worker active and report**

Report commits, test totals, push equality, portability artifacts, deliberate
exclusions, session path, worker PID, latest heartbeat, current candidate or
rejection reason, open counts, DEMO safety, and active-worker status.
