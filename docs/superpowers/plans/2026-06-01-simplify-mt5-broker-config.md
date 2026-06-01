# Simplify MT5 Broker Configuration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Keep checkboxes updated as each step is completed.

**Goal:** Replace the current user-facing MT5 mode matrix with one clean broker connection. The bot should use the MT5 credentials provided, detect the connected account type from MT5 itself, and run one normal execution path. The LLM remains explanation-only; the engine remains the trading decision-maker.

**Architecture:** Remove user-managed `account_mode` and `execution_mode` from normal configuration. `MT5ConnectionConfig` should represent a broker connection, not a set of modes. The MT5 adapter should inspect `account_info().trade_mode`, record the detected account type as broker metadata, and enforce real-money acknowledgement only when MT5 reports a real account. Request-building-only behavior should move to tests/internal helpers instead of being a normal runtime mode.

**Current constraint:** A two-hour engine-mode runner is active. Do not modify MT5 execution code until that run finishes or is manually stopped.

---

## Ground Rules

- Work on `main`; do not create a branch.
- Do not modify execution code while an MT5 runner process is active.
- Preserve real-money safety: if MT5 reports a real account, broker order sending requires explicit acknowledgement.
- Remove user-facing mode language from source, CLI help, active docs, and setup examples.
- Keep test-only request-building behavior, but do not expose it as normal trading configuration.
- Keep `broker-probe`, `mt5-monitor`, and `mt5-run` as the visible MT5 commands.
- Do not loosen engine trade rules, risk rules, order validation, symbol checks, volume checks, or account login/server checks.

---

## Target User Experience

The user should configure one broker connection:

```env
TRADINGAGENTS_MT5_LOGIN=...
TRADINGAGENTS_MT5_PASSWORD=...
TRADINGAGENTS_MT5_SERVER=...
TRADINGAGENTS_MT5_SYMBOL=XAUUSD.vx
TRADINGAGENTS_MT5_VOLUME=0.01
TRADINGAGENTS_MT5_EXPECTED_LOGIN=...
TRADINGAGENTS_MT5_EXPECTED_SERVER=...
```

Normal command:

```powershell
.venv\Scripts\tradingagents.exe mt5-run --duration-hours 2 --poll-seconds 30 --decision-mode engine
```

Expected meaning:

- Use the credentials and terminal account that were provided.
- Detect the MT5 account type automatically.
- If the engine returns `SETUP_FOUND`, send the broker order.
- If the engine returns `NO_SETUP`, hold.
- If MT5 reports a real-money account and acknowledgement is missing, block broker order sending before `order_send`.

---

## File Structure

- Modify: `tradingagents/brokers/mt5.py`
  - Remove user-facing `account_mode` and `execution_mode`.
  - Add MT5 trade-mode detection and real-account acknowledgement at connect/send time.
- Modify: `tradingagents/brokers/mt5_execution.py`
  - Remove runtime `dry_run` branches from normal executor behavior.
  - Keep request-building tests through direct request builder or fake broker helpers.
- Modify: `cli/main.py`
  - Remove process/environment assumptions about execution mode.
  - Keep `mt5-run`, `mt5-monitor`, `broker-probe`.
- Modify: tests:
  - `tests/test_mt5_broker.py`
  - `tests/test_mt5_execution.py`
  - `tests/test_cli_mt5_execution.py`
- Modify active docs:
  - `docs/windows-agent-handoff.md`
  - `docs/mt5-windows-vps.md`
  - `docs/playbook.md`
- Replace or retire:
  - `docs/mt5-demo-windows.md`
    - Either rename to `docs/mt5-windows.md` or merge into `docs/mt5-windows-vps.md`.
- Optional cleanup:
  - Historical plan files under `docs/superpowers/plans/` may retain history, but active setup docs should not instruct users to set old modes.

---

## Task 0: Wait For Current Runner To Finish

- [ ] **Step 1: Confirm runner state**

Run:

```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match 'mt5-run|tradingagents' } |
  Select-Object ProcessId,Name,CommandLine
```

Expected before refactor:

- No active `mt5-run` process, or the user has explicitly approved stopping it.

- [ ] **Step 2: Capture final runner state**

Run:

```powershell
.venv\Scripts\tradingagents.exe mt5-monitor
```

Expected:

- Connected account shown.
- Open orders and positions are known.
- If orders/positions exist, decide whether to monitor, cancel, or leave them before code changes.

---

## Task 1: Redesign MT5 Connection Config

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tests/test_mt5_broker.py`

- [ ] **Step 1: Write failing config tests**

Replace old mode tests with:

```python
def test_mt5_config_from_env_does_not_require_account_mode(...):
    ...

def test_mt5_config_from_env_does_not_require_execution_mode(...):
    ...

def test_mt5_config_reads_connection_credentials_and_volume(...):
    ...
```

Expected behavior:

- `TRADINGAGENTS_MT5_ACCOUNT_MODE` is not required.
- `TRADINGAGENTS_MT5_EXECUTION_MODE` is not required.
- `MT5ConnectionConfig` has no public `account_mode` field.
- `MT5ConnectionConfig` has no public `execution_mode` field.

- [ ] **Step 2: Implement simplified config**

Remove from `MT5ConnectionConfig`:

```python
account_mode
execution_mode
allow_real_orders
```

Keep:

```python
login
password
server
symbol
terminal_path
expected_login
expected_server
volume
deviation
magic
order_comment
```

Add only if needed:

```python
real_order_acknowledged: bool = False
```

This is not a trading mode. It is an acknowledgement flag used only if MT5 reports a real-money account.

- [ ] **Step 3: Verify Task 1**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_broker.py -q
```

Expected:

- Config tests pass without requiring old mode variables.

---

## Task 2: Detect Account Type From MT5

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tests/test_mt5_broker.py`

- [ ] **Step 1: Add trade-mode label tests**

Add tests for MT5 reported trade modes:

```python
def test_mt5_broker_reports_detected_account_type(...):
    ...

def test_mt5_broker_accepts_detected_non_real_account_without_user_mode(...):
    ...

def test_mt5_broker_blocks_real_account_order_without_acknowledgement(...):
    ...

def test_mt5_broker_allows_real_account_order_with_acknowledgement(...):
    ...
```

Expected:

- `connect()` returns broker metadata with detected account type.
- Non-real accounts do not need a user-selected account mode.
- Real account order sending requires acknowledgement.

- [ ] **Step 2: Implement trade-mode detection**

Add a helper:

```python
def _trade_mode_label(self, trade_mode: Any) -> str:
    ...
```

Mapping should be based on MT5 constants:

- `ACCOUNT_TRADE_MODE_DEMO` -> `DEMO`
- `ACCOUNT_TRADE_MODE_CONTEST` -> `CONTEST`
- `ACCOUNT_TRADE_MODE_REAL` -> `REAL`
- unknown -> `UNKNOWN`

This is broker metadata, not user configuration.

- [ ] **Step 3: Add account metadata to connection result**

`connect()` should include:

```python
"account": {
    ...
    "trade_mode": account.get("trade_mode"),
    "trade_mode_label": "...",
}
```

- [ ] **Step 4: Enforce real-account acknowledgement at send boundary**

Before `order_send`, `order_remove`, or stop modification:

- Re-read `account_info()`.
- If detected label is `REAL` and acknowledgement is missing, raise `MT5BrokerError`.
- If detected label is not `REAL`, proceed.

Use the existing acknowledgement value unless renamed:

```text
TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK
```

Optional rename:

```text
TRADINGAGENTS_MT5_REAL_ORDER_ACK=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK
```

Prefer keeping the existing name for backward compatibility unless the user explicitly wants a full rename.

- [ ] **Step 5: Verify Task 2**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_broker.py -q
```

Expected:

- Account type is detected from MT5.
- Real account safety is enforced at send time.
- Login/server mismatch checks still work.

---

## Task 3: Remove Runtime Dry-Run Mode From Normal Execution

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tests/test_mt5_execution.py`
- Modify: `tests/test_mt5_broker.py`

- [ ] **Step 1: Replace dry-run tests with request-builder tests**

Old behavior:

- `execution_mode=dry_run` builds but does not send.

New behavior:

- Request builder can still be tested directly.
- Fake broker tests can still inspect generated requests.
- Normal executor sends through broker when proposal is `PROPOSED`.

Replace tests like:

```python
test_executor_dry_run_builds_request_without_placing_order_or_state
test_executor_dry_run_stale_cancel_does_not_call_broker
test_executor_dry_run_manage_positions_does_not_modify_stops
test_mt5_broker_dry_run_does_not_send_order
```

With tests like:

```python
def test_order_request_builder_builds_pending_limit_request(...):
    ...

def test_executor_sends_broker_order_for_proposed_engine_trade(...):
    ...

def test_executor_does_not_send_for_no_trade_proposal(...):
    ...
```

- [ ] **Step 2: Remove dry-run branches**

Remove runtime checks like:

```python
if self.config.execution_mode == "dry_run":
    ...
```

Normal executor behavior should be:

- `NO_TRADE` proposal: do not call broker.
- `PROPOSED` proposal: call broker.
- Existing active order/position: monitor/manage as before.

- [ ] **Step 3: Keep a developer-only validation helper if needed**

If we still need request-only validation, expose it through direct Python API or tests, not through normal env config.

Acceptable:

```python
MT5OrderRequestBuilder(config).build_pending_limit_request(...)
```

Avoid:

```env
TRADINGAGENTS_MT5_EXECUTION_MODE=dry_run
```

- [ ] **Step 4: Verify Task 3**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py tests\test_mt5_broker.py -q
```

Expected:

- No production execution tests depend on `dry_run`.
- Request builder remains covered.
- `NO_TRADE` still never calls broker.

---

## Task 4: Clean CLI And Runner Launch Flow

**Files:**
- Modify: `cli/main.py`
- Modify: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Add CLI tests for simple broker behavior**

Expected:

- `mt5-run` creates `MT5ConnectionConfig.from_env()` with no account/execution mode variables.
- `mt5-run --decision-mode engine` remains the default decision path.
- `broker-probe` remains connection-only.
- `mt5-monitor` remains monitor/cancel/manage only.

- [ ] **Step 2: Remove old mode assumptions**

Remove CLI docs/help/runtime examples that imply:

- account mode must be selected by user.
- execution mode must be switched to place broker orders.

- [ ] **Step 3: Verify Task 4**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_cli_mt5_execution.py -q
```

Expected:

- CLI tests pass.
- No normal command requires old mode variables.

---

## Task 5: Clean Active Documentation

**Files:**
- Modify: `docs/windows-agent-handoff.md`
- Modify: `docs/mt5-windows-vps.md`
- Modify: `docs/playbook.md`
- Replace or rename: `docs/mt5-demo-windows.md`

- [ ] **Step 1: Rename or merge the demo-specific runbook**

Preferred:

```powershell
git mv docs\mt5-demo-windows.md docs\mt5-windows.md
```

Then update references.

Alternative:

- Merge useful content into `docs/mt5-windows-vps.md`.
- Delete `docs/mt5-demo-windows.md` if it becomes duplicate.

- [ ] **Step 2: Remove old env variables from active docs**

Remove normal setup instructions for:

```text
TRADINGAGENTS_MT5_ACCOUNT_MODE
TRADINGAGENTS_MT5_EXECUTION_MODE
```

Keep only the real-money acknowledgement if real-account safety remains:

```text
TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK
```

- [ ] **Step 3: Update playbook language**

Replace language such as:

- "demo mode"
- "demo execution"
- "later live execution"

With:

- "broker connection"
- "forward test account"
- "real-money acknowledgement when MT5 reports a real account"

- [ ] **Step 4: Verify active docs**

Run:

```powershell
rg -n "TRADINGAGENTS_MT5_ACCOUNT_MODE|TRADINGAGENTS_MT5_EXECUTION_MODE|demo mode|broker mode|dry_run" docs README.md -S
```

Expected:

- No active setup docs instruct users to configure old modes.
- Historical plan files may still mention old behavior only as project history.

---

## Task 6: Remove Dead Code And Old Tests

**Files:**
- Modify source and tests as discovered.

- [ ] **Step 1: Search for old mode code**

Run:

```powershell
rg -n "account_mode|execution_mode|_EXECUTION_MODES|_ACCOUNT_MODE_CONSTANTS|dry_run|TRADINGAGENTS_MT5_ACCOUNT_MODE|TRADINGAGENTS_MT5_EXECUTION_MODE" tradingagents cli tests -S
```

Expected:

- No production code depends on old user-managed modes.
- Any remaining account-type labels are internal MT5 trade-mode metadata only.

- [ ] **Step 2: Remove dead branches**

Remove:

- mode validation branches.
- dry-run send bypasses.
- old error messages.
- old mode-specific tests.

- [ ] **Step 3: Verify no stale API references**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_import_smoke.py tests\test_model_validation.py -q
```

Expected:

- Import smoke tests pass.

---

## Task 7: Full Verification

- [ ] **Step 1: Run focused MT5 suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_broker.py tests\test_mt5_execution.py tests\test_cli_mt5_execution.py tests\test_mt5_runner.py tests\test_mt5_runner_summary.py -q
```

Expected:

- All focused MT5 tests pass.

- [ ] **Step 2: Run full suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Expected:

- Full suite passes.

- [ ] **Step 3: Run connection-only broker probe**

Run:

```powershell
.venv\Scripts\tradingagents.exe broker-probe
```

Expected:

- Connected account details show detected `trade_mode_label`.
- No order is placed.

- [ ] **Step 4: Run monitor check**

Run:

```powershell
.venv\Scripts\tradingagents.exe mt5-monitor
```

Expected:

- Open orders and positions are visible.
- No order is placed unless cancel/manage flags are intentionally used.

---

## Final Acceptance Checklist

- [ ] Users no longer configure `TRADINGAGENTS_MT5_ACCOUNT_MODE`.
- [ ] Users no longer configure `TRADINGAGENTS_MT5_EXECUTION_MODE`.
- [ ] `mt5-run` has one normal broker execution path.
- [ ] MT5 account type is detected from `account_info().trade_mode`.
- [ ] Detected account type is logged/reported as metadata, not selected as a mode.
- [ ] Real-account order sending is blocked unless acknowledgement is present.
- [ ] Request-building-only behavior exists only in tests/internal APIs.
- [ ] Active docs do not tell users to switch modes before trading.
- [ ] Dead mode branches and old mode tests are removed.
- [ ] Full test suite passes.

---

## Plain-English Outcome

After this refactor, the bot will feel like one broker-connected trading system. You provide MT5 credentials, symbol, volume, expected login/server, and the bot uses that broker account. It does not ask you to choose demo, real, contest, dry-run, or broker mode. MT5 tells the bot what kind of account is connected. The only special protection kept is for real-money accounts: if MT5 reports a real account, order sending requires an explicit real-money acknowledgement before the broker call is allowed.
