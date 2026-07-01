# One-Minute Lifecycle Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make One Minute Scalper management broker-acknowledgement-safe, durable across fresh telemetry sessions, position-bound, and protected by broker-side pending expiration.

**Architecture:** Keep execution journals in each telemetry session while storing active MT5 trade state in a stable runtime directory. Bind proposal overrides to the active broker ticket and M1 comment, and advance lifecycle stages only after successful MT5 responses.

**Tech Stack:** Python 3.14, pytest, MetaTrader5 adapter, JSON execution state.

---

### Task 1: Broker acknowledgement safety

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Test: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing close-failure tests**

Add tests whose fake broker returns `{"ok": False}` and assert:

```python
assert result["status"] == "POSITION_MANAGEMENT_FAILED"
assert broker.modified_stops == []
assert executor.state.load().get("partial_close_state") is None
assert executor.state.load().get("rejection_exit_state") is None
```

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_mt5_execution.py -k "failed_partial or failed_rejection"
```

Expected: failures showing successful status/state despite `ok=False`.

- [ ] **Step 3: Implement acknowledgement-aware actions**

Return `PARTIAL_CLOSE_FAILED` or `CLOSE_POSITION_FAILED`, journal a failure event,
do not modify lifecycle state, and do not move stops after a rejected close.
Aggregate either action as `POSITION_MANAGEMENT_FAILED`.

- [ ] **Step 4: Verify executor tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_mt5_execution.py
```

Expected: all executor tests pass.

### Task 2: Stable ticket-bound execution state

**Files:**
- Modify: `tradingagents/brokers/execution_state.py`
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `cli/main.py`
- Test: `tests/test_execution_state.py`
- Test: `tests/test_mt5_execution.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write failing state and restart tests**

Tests must assert:

```python
state_store.mark_position_active(123)
assert state_store.load()["active_position_ticket"] == 123

fresh_executor.manage_open_positions()
assert fresh_result["status"] == "POSITION_PARTIALLY_CLOSED"

unrelated_executor.manage_open_positions()
assert unrelated_result["status"] == "NO_POSITION_ACTION"
```

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_execution_state.py tests/test_mt5_execution.py -k "position_active or stable_state or unrelated"
```

Expected: missing active-position state and fresh-state proposal settings.

- [ ] **Step 3: Implement stable state**

Add `active_position_ticket`, `mark_position_active()`, and `clear_trade()` to
`ExecutionStateStore`. Add optional `state_dir` to `MT5Executor`; journals keep
using `results_dir`, while the state store uses `state_dir` when supplied.

Resolve proposal overrides per position only when:

```python
position["comment"] == "TA|M1|FAST"
and saved_ticket == position["ticket"]
```

The CLI supplies:

```python
Path(os.environ.get(
    "TRADINGAGENTS_MT5_EXECUTION_STATE_DIR",
    Path.cwd() / "runtime" / "mt5_execution_state",
))
```

- [ ] **Step 4: Verify state and CLI tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_execution_state.py tests/test_mt5_execution.py tests/test_cli_mt5_execution.py
```

Expected: all selected tests pass.

### Task 3: Broker-side M1 expiration

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Test: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing expiration tests**

Assert M1 requests passed to `check_order` contain:

```python
assert request["type_time"] == "ORDER_TIME_SPECIFIED"
assert request["expiration"] == int(
    datetime.fromisoformat(policy["cancel_after_utc"]).timestamp()
)
```

Also assert normal requests retain their existing `type_time`.

- [ ] **Step 2: Verify the tests fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_mt5_execution.py -k "broker_expiration"
```

Expected: M1 request remains `ORDER_TIME_GTC`.

- [ ] **Step 3: Apply the effective pending policy to the request**

After computing `pending_policy`, set `ORDER_TIME_SPECIFIED` and the exact UTC
epoch deadline before broker validation. Keep the local pre/post-check deadline
guards.

- [ ] **Step 4: Verify executor tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_mt5_execution.py
```

Expected: all executor tests pass.

### Task 4: Full verification and live restart

**Files:**
- Modify only if verification exposes a scoped defect.

- [ ] **Step 1: Run the full suite**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all non-environment-skipped tests pass.

- [ ] **Step 2: Review and commit**

Run `git diff --check`, review the complete diff, commit the implementation, and
push `main`.

- [ ] **Step 3: Restart with fresh telemetry**

Stop any stale runner process, create a new session-specific results directory,
start the ENTRY_ONLY engine runner hidden, and preserve the stable runtime state.

- [ ] **Step 4: Confirm health**

Verify the process remains active and inspect the first heartbeat and cycle for:

```text
trading_mode=ENTRY_ONLY
account_safety.passed=true
no startup exception
```
