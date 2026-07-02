# MT5 Demo Trading Blockers Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unblock end-to-end monitored MT5 demo trading by separating analysis market data from broker execution symbols, removing the price-action import cycle, and making the analysis CLI runnable from configured backend settings.

**Architecture:** Keep the existing MT5 demo broker guardrails. The strategy layer should be free to analyze a liquid market-data symbol such as `GC=F`, while the MT5 adapter executes the broker-specific symbol such as `XAUUSD.vx`. The analysis stack also needs to import cleanly without a circular dependency between `tradingagents.agents` and `tradingagents.dataflows.price_action`. Finally, the analysis CLI should honor environment-based backend configuration so the monitored demo loop can run without hand-editing prompts every time.

**Tech Stack:** Python, Typer, Pydantic, python-dotenv, yfinance, MetaTrader5, pytest.

---

## Verified Current State

- `tradingagents broker-probe` succeeds against the Valetax demo account.
- `tradingagents mt5-demo-monitor` succeeds and shows no open orders or positions.
- The MT5 terminal is connected to `<MT5_SERVER>`.
- The broker symbol on this account is `XAUUSD.vx`.
- `yfinance` has usable gold data for `GC=F`, but not for `XAUUSD.vx`.
- No LLM provider key or local Ollama server is configured yet, so `tradingagents analyze` cannot generate a proposal end to end.
- Importing `tradingagents.dataflows.price_action` currently trips a circular import through `tradingagents.agents.__init__ -> agent_utils -> price_action_tools`.

## Task 1: Split Analysis Symbol From Broker Symbol

**Files:**
- Modify: `tradingagents/agents/schemas.py`
- Modify: `tradingagents/agents/execution/order_proposal.py`
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `cli/main.py`
- Modify: `docs/mt5-demo-windows.md`
- Modify: `.env.example`
- Test: `tests/test_mt5_broker.py`
- Test: `tests/test_mt5_execution.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Add a regression test that proves one proposal can carry both symbols**

Add a focused test that models:

- analysis / data symbol: `GC=F`
- broker symbol: `XAUUSD.vx`

The test should assert that the order-proposal artifact preserves the analysis symbol separately from the broker execution symbol.

- [ ] **Step 2: Extend the proposal schema with an explicit broker symbol**

Add a field such as `broker_symbol` to `OrderProposal` so the artifact can store:

- the analysis symbol used to generate the setup
- the broker symbol required by MT5 execution

Keep the existing `symbol` field aligned with the analysis side unless the codebase decides to rename it everywhere in one pass.

- [ ] **Step 3: Teach the order-proposal writer to persist the broker symbol**

Update `tradingagents/agents/execution/order_proposal.py` so the generated JSON includes the broker symbol alongside the analysis symbol. The MT5 execution layer should read the broker symbol from the proposal instead of assuming the analysis symbol and broker symbol are identical.

- [ ] **Step 4: Update MT5 validation to compare against the broker symbol**

Update `tradingagents/brokers/mt5.py` and `tradingagents/brokers/mt5_execution.py` so:

- the broker connection continues to validate the MT5 terminal symbol
- the execution layer rejects a proposal when its broker symbol does not match the configured MT5 broker symbol

The broker symbol for this account should remain `XAUUSD.vx`.

- [ ] **Step 5: Document the split clearly**

Update `docs/mt5-demo-windows.md` and `.env.example` so the setup explicitly explains:

- which symbol is used for analysis / market data
- which symbol is used for MT5 execution
- that they may differ for gold on this broker

- [ ] **Step 6: Run the MT5-focused tests**

Run:

```powershell
uv run --group dev pytest tests/test_mt5_broker.py tests/test_mt5_execution.py tests/test_cli_mt5_execution.py -q
```

Expected: MT5 broker and execution tests pass with the new symbol split.

## Task 2: Break the Circular Import in the Price-Action Dataflow

**Files:**
- Modify: `tradingagents/agents/__init__.py`
- Modify: `tradingagents/agents/utils/agent_utils.py`
- Modify: `tradingagents/agents/utils/price_action_tools.py`
- Modify: `tradingagents/dataflows/price_action.py`
- Create: `tests/test_import_smoke.py`

- [ ] **Step 1: Add an import smoke test**

Add a small test that imports the price-action dataflow module directly without raising `ImportError`.

The goal is to make this pass:

```powershell
uv run --group dev python -c "from tradingagents.dataflows.price_action import fetch_price_action_timeframes; print('ok')"
```

- [ ] **Step 2: Remove the eager import loop**

Stop `tradingagents.agents.__init__` from importing heavy submodules that immediately re-import `tradingagents.dataflows.price_action`.

The safest fix is usually to move the `get_playbook_setups` import inside the function that needs it, or to slim down `tradingagents.agents.__init__` so it does not eagerly import the whole analyst stack at package import time.

- [ ] **Step 3: Verify the dataflow imports cleanly**

Run the import smoke test again and confirm it passes without the circular import error.

Then re-run the MT5 tests from Task 1 to make sure the import refactor did not break execution paths.

## Task 3: Make Analysis Runnable From Backend Configuration

**Files:**
- Modify: `cli/main.py`
- Modify: `cli/utils.py`
- Modify: `.env.example`
- Modify: `docs/mt5-demo-windows.md`
- Modify: `README.md`
- Create: `tests/test_cli_config.py`

- [ ] **Step 1: Add a non-interactive analysis path**

Teach the analysis CLI to honor environment-based provider and model settings when they are already configured.

The current behavior always prompts for provider and model choices, which makes unattended demo runs awkward even after a backend key is present.

- [ ] **Step 2: Document the required backend setup**

Update the docs so the collaborator knows that one of these must be configured before `tradingagents analyze` can generate proposals:

- a provider API key, such as OpenAI, DeepSeek, Anthropic, Google, xAI, Qwen, GLM, MiniMax, or OpenRouter
- or a local Ollama backend reachable through `OLLAMA_BASE_URL`

- [ ] **Step 3: Add a test for env-driven CLI selection**

Add a CLI test that proves the analysis command can use environment-backed provider/model settings without requiring interactive prompts.

- [ ] **Step 4: Re-run the monitored demo flow**

Once a backend is configured and the symbol split is in place, run:

```powershell
tradingagents analyze
tradingagents mt5-demo-execute --proposal "<generated proposal path>"
tradingagents mt5-demo-monitor
```

Expected: a full demo trading cycle can be started and then monitored without manual CLI prompt wiring.

## Notes

- This is still demo-only. Keep the live-trading guard in place.
- The MT5 transport itself is already working, so this plan is about unblocking the remaining analysis and orchestration pieces.
