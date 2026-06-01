# Deterministic Engine Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` or `superpowers:subagent-driven-development` to implement this plan task-by-task. Keep the checkboxes updated as work is completed.

**Goal:** Make the price-action engine the direct market decision-maker for MT5 runner execution, with the LLM used only for explanation/reporting. The bot should analyze candles, produce telemetry, build order proposals, and execute demo broker orders from deterministic engine output.

**Architecture:** Add an engine-first decision path alongside the existing LLM graph. The MT5 runner should default to the engine-first path for broker validation. The legacy graph can remain available for rich human reports, but it must not be required for trade approval, side, entry, stop, target, or order status. Engine payloads and telemetry become the source of truth.

**Tech Stack:** Python 3.13, Typer CLI, pytest, existing price-action engine, yfinance dataflow, MT5 runner/executor, JSON telemetry artifacts under `~/.tradingagents/logs`.

---

## Ground Rules

- Work on `main`; do not create a branch.
- Keep `.env` safe by default. Broker-mode tests must use process-local environment overrides only.
- Keep demo volume at `0.01` during validation.
- Do not loosen the core M30/M15 checklist to force trades.
- Do not use the LLM to decide trade side, entry, stop loss, take profit, or whether the order is brokerable.
- The LLM may summarize or explain a completed engine decision after the deterministic decision is already made.
- Every implementation task must include focused tests before broad live-run validation.

---

## File Structure

- Create: `tradingagents/agents/price_action/decision.py`
  - Engine-first decision service: fetch candles, run `analyze_playbook`, persist payload, build deterministic report fields.
- Modify: `tradingagents/agents/utils/price_action_tools.py`
  - Share existing engine payload persistence and avoid duplicate data-fetch/analyze logic.
- Modify: `tradingagents/agents/execution/order_proposal.py`
  - Keep engine payload as primary source; remove any remaining LLM dependency from proposed orders.
- Modify: `tradingagents/brokers/runner_summary.py`
  - Categorize HOLD reasons from telemetry and data health before proposal text.
- Modify: `tradingagents/brokers/mt5_runner.py`
  - Accept engine-first analysis function and preserve telemetry/proposal metadata in each cycle.
- Modify: `cli/main.py`
  - Add `--decision-mode engine|graph` for `mt5-run`; default to `engine` for runner execution.
- Modify: `tradingagents/default_config.py`
  - Add `TRADINGAGENTS_DECISION_MODE`, defaulting to `engine`.
- Modify: `docs/playbook.md`
  - State that the production runner decision path is engine-first; LLM is explanation-only.
- Modify tests:
  - `tests/test_engine_decision.py`
  - `tests/test_order_proposal.py`
  - `tests/test_mt5_runner.py`
  - `tests/test_mt5_runner_summary.py`
  - `tests/test_cli_mt5_execution.py`
  - `tests/test_price_action_tools.py`

---

## Task 1: Add Engine-First Decision Service

**Files:**
- Create: `tradingagents/agents/price_action/decision.py`
- Create: `tests/test_engine_decision.py`
- Modify: `tradingagents/agents/utils/price_action_tools.py`

- [ ] **Step 1: Write tests for an engine-only decision**

Add tests that monkeypatch candle fetching and assert:

- The decision service does not require an LLM.
- It calls the price-action engine directly.
- It returns `engine_payload`, `engine_telemetry`, `telemetry_path`, `data_status`, `price_action_report`, and `as_of`.
- It writes the raw engine payload under `<results_dir>/<symbol>/engine_telemetry/`.

Expected test names:

```python
def test_engine_decision_runs_without_llm_and_writes_payload(...):
    ...

def test_engine_decision_returns_data_health_hold_when_data_is_unhealthy(...):
    ...
```

- [ ] **Step 2: Implement `run_engine_decision`**

Create a function with a small stable interface:

```python
def run_engine_decision(
    symbol: str,
    *,
    broker_symbol: str | None,
    results_dir: str | Path,
    timeframe: str = "15m",
    confirmation_timeframe: str = "30m",
    market_timezone: str = "America/New_York",
    session_config: dict | None = None,
) -> dict:
    ...
```

The function should:

- Fetch the top-down candle snapshot.
- Run `analyze_playbook`.
- Persist the engine payload.
- Return a graph-compatible state dictionary containing the engine payload and telemetry.
- Render a deterministic report from payload fields, not from an LLM.

- [ ] **Step 3: Reuse existing payload writer**

If `write_engine_payload` already has the needed behavior, import and reuse it. If this creates an import cycle, move the persistence helper to a smaller neutral module such as:

```text
tradingagents/agents/price_action/persistence.py
```

- [ ] **Step 4: Verify Task 1**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_engine_decision.py tests\test_price_action_tools.py -q
```

Expected: new engine decision tests pass without constructing any LLM client.

---

## Task 2: Make Order Proposal Fully Engine-Primary

**Files:**
- Modify: `tradingagents/agents/execution/order_proposal.py`
- Modify: `tests/test_order_proposal.py`

- [ ] **Step 1: Add regression tests for LLM text not controlling execution**

Cover these cases:

- Engine says `NO_SETUP`, LLM text says `BUY`; proposal must be `NO_TRADE`.
- Engine says `SETUP_FOUND BUY`, LLM text says `HOLD`; proposal must be `PROPOSED BUY`.
- Engine setup has missing entry/SL/TP; proposal must be `NO_TRADE`.
- Engine payload has risk failure; proposal reason must include telemetry/checklist/risk details.

Expected test names:

```python
def test_engine_no_setup_overrides_llm_buy_text(...):
    ...

def test_engine_setup_found_overrides_llm_hold_text(...):
    ...
```

- [ ] **Step 2: Tighten `build_order_proposal`**

Current behavior already prefers engine payload when present. Make that contract explicit:

- If `engine_payload` exists, never parse `trade_plan` for action or levels.
- If `engine_payload.status == SETUP_FOUND`, only engine recommendation and engine levels can create a `PROPOSED` order.
- If `engine_payload.status != SETUP_FOUND`, always return `NO_TRADE`.
- Preserve the LLM fallback only when there is no engine payload at all, for backward compatibility with the old graph.

- [ ] **Step 3: Verify Task 2**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_order_proposal.py -q
```

Expected: all order proposal tests pass, including old fallback behavior.

---

## Task 3: Fix Runner Summary To Trust Telemetry First

**Files:**
- Modify: `tradingagents/brokers/runner_summary.py`
- Modify: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Add regression for misleading proposal text**

Add a test using:

- `analysis.data_status.healthy == True`
- `analysis.telemetry.decision_stage == "no_m15_setup"`
- proposal reason text containing misleading phrases like "no price data"

Expected result:

```python
assert hold_reason == "no_m15_setup"
```

- [ ] **Step 2: Update categorization priority**

Priority should be:

1. Explicit unhealthy `analysis.data_status.healthy is False` -> `data_health`.
2. `telemetry.decision_stage`.
3. `telemetry.primary_hold_reason`.
4. Proposal reason text as fallback only.

This prevents old LLM wording from corrupting the run summary.

- [ ] **Step 3: Verify Task 3**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_runner_summary.py tests\test_mt5_runner.py -q
```

Expected: summary categories match deterministic telemetry.

---

## Task 4: Add Runner Decision Mode

**Files:**
- Modify: `cli/main.py`
- Modify: `tradingagents/default_config.py`
- Modify: `tests/test_cli_mt5_execution.py`
- Modify: `tests/test_mt5_runner.py`

- [ ] **Step 1: Add CLI tests**

Tests should prove:

- `tradingagents mt5-run --decision-mode engine --once` uses the engine decision function.
- `tradingagents mt5-run --decision-mode graph --once` keeps the existing graph path available.
- Invalid decision mode fails with a clear CLI error.
- The default decision mode is `engine`.

- [ ] **Step 2: Add config value**

Add:

```text
TRADINGAGENTS_DECISION_MODE=engine
```

Supported values:

- `engine`: deterministic engine-first path.
- `graph`: legacy LLM graph path.

- [ ] **Step 3: Wire `mt5-run`**

In `cli/main.py`, build the runner analysis function from decision mode:

- `engine`: call `run_engine_decision`, then `build_order_proposal` / proposal executor.
- `graph`: call the existing `_mt5_runner_analysis_func` graph path.

The runner result shape must stay compatible:

```python
{
    "status": "NO_TRADE" | "PROPOSED" | "ORDER_PLACED" | ...,
    "as_of": "...",
    "analysis": {
        "telemetry": {...},
        "data_status": {...},
        "telemetry_path": "...",
        "order_proposal_path": "...",
    },
    "proposal": {...},
}
```

- [ ] **Step 4: Verify Task 4**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_cli_mt5_execution.py tests\test_mt5_runner.py -q
```

Expected: runner can operate in engine mode without LLM graph construction.

---

## Task 5: Add Deterministic Human Report Rendering

**Files:**
- Modify: `tradingagents/agents/price_action/decision.py`
- Create or modify: `tests/test_engine_decision.py`

- [ ] **Step 1: Test deterministic report contents**

For `NO_SETUP`, report should include:

- Symbol and candle time.
- M30 context.
- Candidate count.
- Failed checklist item.
- Risk reason or data health reason.
- Final action `HOLD`.

For `SETUP_FOUND`, report should include:

- Setup name.
- Side.
- Entry.
- Stop loss.
- Take profit.
- Risk-to-reward.
- Final action `BUY` or `SELL`.

- [ ] **Step 2: Implement deterministic report renderer**

Create a renderer like:

```python
def render_engine_decision_report(payload: dict) -> str:
    ...
```

This report is not the LLM report. It is the reliable audit text used by CLI panels, summary files, and test reports.

- [ ] **Step 3: Verify Task 5**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_engine_decision.py -q
```

Expected: report text is stable and does not require an LLM.

---

## Task 6: Keep LLM As Optional Explanation Only

**Files:**
- Modify: `tradingagents/graph/setup.py` or add a small explanation helper only if needed.
- Modify: `docs/playbook.md`
- Modify tests only if code changes are needed.

- [ ] **Step 1: Define the LLM boundary**

Document this boundary clearly:

- Engine decides.
- Engine writes telemetry.
- Engine builds order proposal.
- MT5 executes from proposal.
- LLM explains after the decision, using telemetry as input.

- [ ] **Step 2: Add optional explanation path only if useful**

Do not make the runner depend on this. If implemented, the LLM explanation function should accept engine payload and return a markdown explanation. It must not return order fields.

Allowed output:

```python
{
    "human_explanation": "...",
}
```

Forbidden output:

```python
{
    "side": "...",
    "entry_price": ...,
    "stop_loss": ...,
    "take_profit": ...,
    "status": "..."
}
```

- [ ] **Step 3: Verify Task 6**

Run targeted tests if code changed, otherwise verify docs diff:

```powershell
git diff -- docs\\playbook.md
```

Expected: docs state the LLM is explanation-only for runner execution.

---

## Task 7: End-To-End Dry Runner Verification

**Files:**
- Modify tests only if a contract gap is discovered.

- [ ] **Step 1: Run focused regression suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_engine_decision.py tests\test_order_proposal.py tests\test_mt5_runner_summary.py tests\test_mt5_runner.py tests\test_cli_mt5_execution.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run broader safety suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_price_action_engine.py tests\test_price_action_structure.py tests\test_price_action_tools.py tests\test_price_action_dataflows.py tests\test_env_overrides.py tests\test_import_smoke.py tests\test_model_validation.py -q
```

Expected: all broader tests pass.

- [ ] **Step 3: Run one dry engine-mode runner cycle**

Use safe dry-run mode:

```powershell
$env:TRADINGAGENTS_MT5_ACCOUNT_MODE='demo'
$env:TRADINGAGENTS_MT5_EXECUTION_MODE='dry_run'
$env:TRADINGAGENTS_DECISION_MODE='engine'
.venv\Scripts\tradingagents.exe mt5-run --once --decision-mode engine
```

Expected:

- No LLM calls are required.
- An engine payload is written.
- An order proposal is written.
- Summary includes telemetry reason.
- No broker order is placed in dry-run mode.

---

## Task 8: Demo Broker Validation

**Files:**
- No source changes unless a bug is found.

- [ ] **Step 1: Confirm account state**

Run:

```powershell
.venv\Scripts\tradingagents.exe mt5-monitor
```

Expected:

- Connected to Valetax demo account.
- Correct login/server.
- Open orders: 0.
- Open positions: 0.

- [ ] **Step 2: Run a short engine-mode demo broker test**

Use process-local overrides only:

```powershell
$env:TRADINGAGENTS_MT5_ACCOUNT_MODE='demo'
$env:TRADINGAGENTS_MT5_EXECUTION_MODE='broker'
$env:TRADINGAGENTS_MT5_VOLUME='0.01'
$env:TRADINGAGENTS_DECISION_MODE='engine'
.venv\Scripts\tradingagents.exe mt5-run --duration-hours 1 --poll-seconds 30 --decision-mode engine
```

Expected:

- Runner reads live market data.
- No LLM is required.
- If no setup appears, HOLD reasons come from telemetry.
- If a setup appears, proposal levels come from the engine.
- MT5 receives an order only after `SETUP_FOUND`.

- [ ] **Step 3: Review summary**

Inspect:

```text
<run_dir>\mt5_runner\summary.json
<run_dir>\mt5_runner\cycles.jsonl
<run_dir>\<symbol>\engine_telemetry\
<run_dir>\<symbol>\order_proposals\
```

Expected:

- HOLD categories match telemetry.
- No misleading LLM wording affects summary.
- Any order proposal is traceable to the engine payload that created it.

---

## Final Acceptance Checklist

- [x] MT5 runner can run in `engine` mode without constructing or calling an LLM decision chain.
- [x] Engine payload is written for every fresh decision.
- [x] Order proposals use engine payload first and ignore conflicting LLM text.
- [x] Summary HOLD categorization trusts telemetry and data health before proposal text.
- [x] `graph` mode remains available for legacy/reporting workflows.
- [x] The LLM boundary is documented: explanation only, not execution authority.
- [x] Focused and broader regression tests pass.
- [x] A dry-run `mt5-run --once --decision-mode engine` produces telemetry and proposal artifacts.

---

## Plain-English Outcome

After this plan is implemented, the bot's market understanding will come directly from its price-action engine. The engine will read the candles, apply the M30/M15 checklist, decide HOLD or SETUP_FOUND, and generate the order proposal. The LLM can still help explain the decision to a human, but it will no longer be the source of truth for whether to buy, sell, hold, or what levels to send to MT5.
