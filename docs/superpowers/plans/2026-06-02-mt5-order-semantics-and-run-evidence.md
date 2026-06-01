# MT5 Order Semantics And Run Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deterministic M30/M15 engine produce broker-valid MT5 pending orders, improve run evidence, and keep the LLM out of trade decisions.

**Architecture:** The price-action engine remains the source of truth for `BUY`, `SELL`, or `HOLD`. The proposal layer carries enough strategy metadata for execution, while the MT5 broker adapter converts that proposal into a valid broker request using the current bid/ask and broker symbol specifications. The runner summary records every order lifecycle and data/telemetry issue so each forward test can be audited without guessing.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, MetaTrader5 Python bridge, yfinance, local JSON/JSONL telemetry.

---

## Context

The fixed two-hour run at:

```text
C:\Users\Wetende\.tradingagents\logs\live_runs\m15_three_entries_run_fixed_20260602_002914
```

proved that the engine now sees the three M15 entry families: Breakout, Support/Resistance Bounce, and Break and Retest. It also proved the MT5 runner can place and cancel pending orders. But the run exposed new execution-layer issues:

- Two broker requests were rejected with MT5 retcode `10015` / `Invalid price`.
- Four pending orders were accepted but never filled; each was cancelled after the activation window.
- The broker adapter currently converts every valid proposal into `BUY_LIMIT` or `SELL_LIMIT`.
- Breakout continuation entries often need `BUY_STOP` or `SELL_STOP` depending on current bid/ask.
- The runner summary counts placed/rejected orders but does not yet preserve enough order lifecycle detail for a clean run report.
- GC=F/yfinance warnings still appear intermittently and need clearer evidence in run summaries.

The playbook direction is:

```text
Daily / 4H / 1H = context and danger zones
M30 = setup context and trading bias
M15 = exact entry model
LLM = explanation only, not execution authority
```

## File Structure

- Modify `tradingagents/agents/schemas.py`
  - Add explicit proposal metadata fields: `setup_name`, `strategy_type`, and `order_type` values that can represent `AUTO`, `BUY_LIMIT`, `SELL_LIMIT`, `BUY_STOP`, `SELL_STOP`, and legacy `LIMIT`.
- Modify `tradingagents/agents/execution/order_proposal.py`
  - Preserve setup name/strategy type from the deterministic engine payload.
  - Keep proposal `order_type` as `AUTO` for engine-driven proposals so MT5 execution decides the broker-valid pending order from live bid/ask.
  - Keep legacy LLM fallback proposals as `LIMIT` only for compatibility, but they must not override engine payloads.
- Modify `tradingagents/brokers/mt5.py`
  - Rename or extend `build_pending_limit_request` into `build_pending_order_request`.
  - Resolve `AUTO` proposals into `BUY_LIMIT`, `SELL_LIMIT`, `BUY_STOP`, or `SELL_STOP`.
  - Validate entry price against current `bid`/`ask` and broker stop-level distance before sending.
  - Support MetaTrader constants for `ORDER_TYPE_BUY_STOP` and `ORDER_TYPE_SELL_STOP`.
- Modify `tradingagents/brokers/mt5_execution.py`
  - Use the generalized pending-order builder.
  - Convert stale/invalid entry prices into a structured skipped execution result, not an unhandled runner error.
  - Journal `ORDER_SKIPPED` with reason `ENTRY_PRICE_STALE_OR_INVALID` when the setup is no longer placeable.
- Modify `tradingagents/brokers/runner_summary.py`
  - Count broker skips separately from broker rejections.
  - Capture latest execution status, retcode/comment, order type, setup, and skip reason.
  - Aggregate order lifecycle counts: placed, rejected, skipped, cancelled, active-monitored.
- Modify `tradingagents/brokers/mt5_runner.py`
  - Preserve execution details in heartbeat and summary when an order is skipped before broker send.
  - Keep `last_processed_as_of` only after a placement attempt or structured execution skip, not after ordinary `NO_TRADE`.
- Modify `tradingagents/dataflows/y_finance.py`
  - Make retry metadata explicit in returned text for empty responses and exceptions.
  - Keep retries small and deterministic for live use.
- Modify tests:
  - `tests/test_order_proposal.py`
  - `tests/test_mt5_execution.py`
  - `tests/test_mt5_broker.py`
  - `tests/test_mt5_runner.py`
  - `tests/test_mt5_runner_summary.py`
  - `tests/test_y_finance_retry.py`

## External Research Notes

MetaTrader 5 treats pending order type as part of the trade request. The Python `order_send` API expects a `MqlTradeRequest` with `action`, `type`, `price`, `sl`, `tp`, filling/time policy, and other fields; the server validates that request before accepting it. MetaTrader's own trading help explains that chart position determines available pending order types: above current price allows `Sell Limit` and `Buy Stop`; below current price allows `Buy Limit` and `Sell Stop`. This matches the run evidence: a valid strategy can still be rejected if the pending order type does not match current market price.

Trading education material around breakout/retest agrees with the playbook's separation:

- A direct breakout needs a closed candle beyond support/resistance and must avoid false-breakout chasing.
- Break-and-retest waits for the broken level to hold as new support/resistance before entry.
- Support/resistance bounce needs rejection confirmation, not a blind zone touch.

The implementation should therefore avoid market orders and avoid forcing every entry into a limit order. The broker adapter should choose the pending order type that matches the setup and current quote.

## Task 1: Preserve Engine Setup Metadata In Proposals

**Files:**
- Modify: `tradingagents/agents/schemas.py`
- Modify: `tradingagents/agents/execution/order_proposal.py`
- Test: `tests/test_order_proposal.py`

- [ ] **Step 1: Write failing tests for engine metadata**

Add tests showing that engine proposals carry setup identity and use `AUTO` execution intent:

```python
def test_engine_proposal_records_strategy_metadata_and_auto_order_type(tmp_path):
    state = _state("**Action**: HOLD\n\n**Reason**: LLM ignored.", tmp_path)
    state["engine_payload"] = {
        "status": "SETUP_FOUND",
        "recommendation": "SELL",
        "setups": [
            {
                "name": "Breakout",
                "strategy_type": "BREAKOUT",
                "direction": "SELL",
                "entry_price": 4490.85,
                "stop_loss": 4491.29,
                "take_profit": 4489.52,
            }
        ],
        "risk": {"approved": True, "risk_reward": 3.02, "take_profit": 4489.52},
        "telemetry": {"decision_stage": "setup_found"},
    }

    proposal = build_order_proposal(state)

    assert proposal.status == OrderStatus.PROPOSED
    assert proposal.order_type == "AUTO"
    assert proposal.setup_name == "Breakout"
    assert proposal.strategy_type == "BREAKOUT"
```

Add a second test for existing JSON compatibility:

```python
def test_order_proposal_defaults_missing_metadata_for_old_json():
    proposal = OrderProposal.model_validate(
        {
            "symbol": "GC=F",
            "broker_symbol": "XAUUSD.vx",
            "side": "BUY",
            "order_type": "LIMIT",
            "entry_price": 2450,
            "stop_loss": 2440,
            "take_profit": 2470,
            "valid_until": "2026-05-17 10:30 EDT",
            "status": "PROPOSED",
            "reason": "legacy artifact",
        }
    )

    assert proposal.setup_name is None
    assert proposal.strategy_type is None
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_order_proposal.py::test_engine_proposal_records_strategy_metadata_and_auto_order_type tests\test_order_proposal.py::test_order_proposal_defaults_missing_metadata_for_old_json -q
```

Expected: fail because `OrderProposal` does not yet have `setup_name` or `strategy_type`, and engine proposals still use `LIMIT`.

- [ ] **Step 3: Implement proposal metadata**

In `OrderProposal`, add optional fields:

```python
setup_name: Optional[str] = None
strategy_type: Optional[str] = None
```

In `render_order_proposal`, include those fields only when present:

```python
if proposal.setup_name:
    parts.extend(["", f"**Setup Name**: {proposal.setup_name}"])
if proposal.strategy_type:
    parts.extend(["", f"**Strategy Type**: {proposal.strategy_type}"])
```

In `_proposal_from_engine_payload`, set:

```python
setup_name = None
strategy_type = None
if payload_status == "SETUP_FOUND" and recommendation in {"BUY", "SELL"}:
    setup = (payload.get("setups") or [{}])[0]
    setup_name = str(setup.get("name") or "").strip() or None
    strategy_type = str(setup.get("strategy_type") or setup_name or "").strip().upper().replace(" ", "_") or None
```

For engine proposals with complete levels, set:

```python
order_type="AUTO"
setup_name=setup_name
strategy_type=strategy_type
```

Leave non-engine fallback proposals as `order_type="LIMIT"` for now, because they are compatibility-only and should not be used by `mt5-run` when engine telemetry exists.

- [ ] **Step 4: Run proposal tests and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_order_proposal.py -q
```

Expected: all proposal tests pass.

## Task 2: Resolve Broker-Valid Pending Order Type From Current Bid/Ask

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tests/test_mt5_execution.py`
- Modify: `tests/test_mt5_broker.py`

- [ ] **Step 1: Write failing builder tests**

Add tests to `tests/test_mt5_execution.py`:

```python
def test_build_breakout_buy_above_ask_as_buy_stop():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.setup_name = "Breakout"
    proposal.strategy_type = "BREAKOUT"
    proposal.entry_price = 4508.00
    proposal.stop_loss = 4506.00
    proposal.take_profit = 4512.00

    request = builder.build_pending_order_request(
        proposal,
        {"name": "XAUUSD", "digits": 2, "trade_tick_size": 0.01, "bid": 4506.99, "ask": 4507.32},
    )

    assert request["type"] == "BUY_STOP"
```

```python
def test_build_breakout_sell_below_bid_as_sell_stop():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.SELL)
    proposal.order_type = "AUTO"
    proposal.setup_name = "Breakout"
    proposal.strategy_type = "BREAKOUT"
    proposal.entry_price = 4506.00
    proposal.stop_loss = 4508.00
    proposal.take_profit = 4502.00

    request = builder.build_pending_order_request(
        proposal,
        {"name": "XAUUSD", "digits": 2, "trade_tick_size": 0.01, "bid": 4506.99, "ask": 4507.32},
    )

    assert request["type"] == "SELL_STOP"
```

```python
def test_build_retest_buy_below_ask_as_buy_limit():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.setup_name = "Break and Retest"
    proposal.strategy_type = "BREAK_AND_RETEST"
    proposal.entry_price = 4506.50
    proposal.stop_loss = 4505.00
    proposal.take_profit = 4510.00

    request = builder.build_pending_order_request(
        proposal,
        {"name": "XAUUSD", "digits": 2, "trade_tick_size": 0.01, "bid": 4506.99, "ask": 4507.32},
    )

    assert request["type"] == "BUY_LIMIT"
```

```python
def test_build_retest_sell_above_bid_as_sell_limit():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.SELL)
    proposal.order_type = "AUTO"
    proposal.setup_name = "Break and Retest"
    proposal.strategy_type = "BREAK_AND_RETEST"
    proposal.entry_price = 4507.50
    proposal.stop_loss = 4509.00
    proposal.take_profit = 4504.00

    request = builder.build_pending_order_request(
        proposal,
        {"name": "XAUUSD", "digits": 2, "trade_tick_size": 0.01, "bid": 4506.99, "ask": 4507.32},
    )

    assert request["type"] == "SELL_LIMIT"
```

```python
def test_build_auto_rejects_stale_buy_entry_between_bid_and_ask():
    builder = MT5OrderRequestBuilder(_config())
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.entry_price = 4507.10
    proposal.stop_loss = 4505.00
    proposal.take_profit = 4511.00

    with pytest.raises(ValueError, match="entry price is stale or inside spread"):
        builder.build_pending_order_request(
            proposal,
            {"name": "XAUUSD", "digits": 2, "trade_tick_size": 0.01, "bid": 4506.99, "ask": 4507.32},
        )
```

- [ ] **Step 2: Write failing broker materialization tests**

In `tests/test_mt5_broker.py`, extend `FakeMT5` with:

```python
ORDER_TYPE_BUY_STOP = 4
ORDER_TYPE_SELL_STOP = 5
```

Add tests:

```python
def test_mt5_broker_materializes_buy_stop_order():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(login=123456789, password="secret", server="ExampleBroker-Demo", symbol="XAUUSD")
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    request = _valid_pending_request()
    request.update({"type": "BUY_STOP", "price": 4510.00, "sl": 4508.00, "tp": 4515.00})

    result = broker.place_pending_order(request)

    assert result["ok"] is True
    assert fake_mt5.sent_requests[0]["type"] == FakeMT5.ORDER_TYPE_BUY_STOP
```

```python
def test_mt5_broker_materializes_sell_stop_order():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(login=123456789, password="secret", server="ExampleBroker-Demo", symbol="XAUUSD")
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()
    request = _valid_pending_request()
    request.update({"type": "SELL_STOP", "price": 4500.00, "sl": 4502.00, "tp": 4495.00})

    result = broker.place_pending_order(request)

    assert result["ok"] is True
    assert fake_mt5.sent_requests[0]["type"] == FakeMT5.ORDER_TYPE_SELL_STOP
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py::test_build_breakout_buy_above_ask_as_buy_stop tests\test_mt5_execution.py::test_build_breakout_sell_below_bid_as_sell_stop tests\test_mt5_execution.py::test_build_retest_buy_below_ask_as_buy_limit tests\test_mt5_execution.py::test_build_retest_sell_above_bid_as_sell_limit tests\test_mt5_execution.py::test_build_auto_rejects_stale_buy_entry_between_bid_and_ask tests\test_mt5_broker.py::test_mt5_broker_materializes_buy_stop_order tests\test_mt5_broker.py::test_mt5_broker_materializes_sell_stop_order -q
```

Expected: fail because `build_pending_order_request`, stop-order constants, and validation do not exist.

- [ ] **Step 4: Implement generalized pending-order builder**

In `MT5OrderRequestBuilder`:

```python
PENDING_ORDER_TYPES = {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}
```

Add:

```python
def _quote(self, symbol_info: dict[str, Any]) -> tuple[float, float]:
    bid = self._round_price(symbol_info.get("bid"), symbol_info)
    ask = self._round_price(symbol_info.get("ask"), symbol_info)
    if bid <= 0 or ask <= 0 or bid > ask:
        raise ValueError("symbol bid/ask are required for AUTO pending order selection")
    return bid, ask
```

Add:

```python
def _explicit_order_type(self, proposal: OrderProposal) -> str:
    value = str(getattr(proposal, "order_type", "")).strip().upper()
    if value == "LIMIT":
        return self._legacy_limit_order_type(proposal.side)
    if value in self.PENDING_ORDER_TYPES:
        return value
    if value == "AUTO":
        raise ValueError("AUTO order type must be resolved from current bid/ask")
    raise ValueError(f"unsupported MT5 pending order type: {value}")
```

Add:

```python
def _auto_order_type(self, proposal: OrderProposal, entry: float, symbol_info: dict[str, Any]) -> str:
    bid, ask = self._quote(symbol_info)
    side_value = str(getattr(proposal.side, "value", proposal.side)).upper()
    strategy = str(getattr(proposal, "strategy_type", "") or getattr(proposal, "setup_name", "") or "").upper()

    if bid < entry < ask:
        raise ValueError("entry price is stale or inside spread")
    if side_value == "BUY":
        return "BUY_STOP" if entry >= ask else "BUY_LIMIT"
    if side_value == "SELL":
        return "SELL_STOP" if entry <= bid else "SELL_LIMIT"
    raise ValueError(f"unsupported proposal side for MT5 pending order: {side_value}")
```

Keep this intentionally simple: current price determines valid pending order type. Strategy metadata is logged and preserved, but the final broker validity check is quote-based.

Update level validation:

```python
if request_type in {"BUY_LIMIT", "BUY_STOP"} and not (stop < entry < target):
    raise ValueError("invalid BUY levels for MT5 pending order")
if request_type in {"SELL_LIMIT", "SELL_STOP"} and not (target < entry < stop):
    raise ValueError("invalid SELL levels for MT5 pending order")
```

Keep compatibility:

```python
def build_pending_limit_request(...):
    return self.build_pending_order_request(...)
```

- [ ] **Step 5: Add MT5 stop constants and validation**

In `_constants`, add:

```python
"BUY_STOP": self._constant("ORDER_TYPE_BUY_STOP"),
"SELL_STOP": self._constant("ORDER_TYPE_SELL_STOP"),
```

In `_symbolic_maps`, add:

```python
"BUY_STOP": constants["BUY_STOP"],
"SELL_STOP": constants["SELL_STOP"],
```

In `_validate_pending_order_request`, allow:

```python
if request["type"] not in {"BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"}:
    ...
```

Level validation must use BUY/SELL side group rather than limit-only wording.

- [ ] **Step 6: Run MT5 broker/execution tests and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py tests\test_mt5_broker.py -q
```

Expected: all MT5 execution and broker tests pass.

## Task 3: Turn Stale Entry Prices Into Structured Skips

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tradingagents/brokers/mt5_runner.py`
- Test: `tests/test_mt5_execution.py`
- Test: `tests/test_mt5_runner.py`

- [ ] **Step 1: Write failing executor test**

Add:

```python
def test_executor_skips_stale_auto_entry_without_broker_send(tmp_path):
    broker = FakeBroker()
    broker.symbol_info = {
        "name": "XAUUSD",
        "digits": 2,
        "point": 0.01,
        "trade_tick_size": 0.01,
        "bid": 4506.99,
        "ask": 4507.32,
    }
    proposal = _proposal(TradeAction.BUY)
    proposal.order_type = "AUTO"
    proposal.entry_price = 4507.10
    proposal.stop_loss = 4505.00
    proposal.take_profit = 4511.00
    executor = MT5Executor(_config(), tmp_path, broker=broker)

    result = executor.execute_proposal(proposal)

    assert result["status"] == "SKIPPED_INVALID_ENTRY"
    assert result["reason"] == "ENTRY_PRICE_STALE_OR_INVALID"
    assert broker.placed_requests == []
```

- [ ] **Step 2: Write failing runner summary test**

Add:

```python
def test_runner_records_invalid_entry_skip_as_order_not_placed(tmp_path):
    proposal = _proposal()
    proposal.status = OrderStatus.PROPOSED

    class Executor:
        def snapshot_state(self):
            return {"orders": [], "positions": []}
        def cancel_stale_pending_orders(self):
            return {"status": "NO_ACTIVE_ORDER"}
        def manage_open_positions(self):
            return {"status": "NO_POSITION_ACTION"}
        def execute_proposal(self, proposal):
            return {"status": "SKIPPED_INVALID_ENTRY", "reason": "ENTRY_PRICE_STALE_OR_INVALID"}

    runner = MT5Runner(
        MT5RunnerConfig(tmp_path, poll_seconds=5, max_cycles=1),
        executor=Executor(),
        analysis_func=lambda: ("2026-06-01 10:15", proposal, {"telemetry": {}}),
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_NOT_PLACED"
    assert result["execution"]["status"] == "SKIPPED_INVALID_ENTRY"
    assert result["summary"]["execution_skip_counts"]["ENTRY_PRICE_STALE_OR_INVALID"] == 1
```

- [ ] **Step 3: Run tests and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py::test_executor_skips_stale_auto_entry_without_broker_send tests\test_mt5_runner.py::test_runner_records_invalid_entry_skip_as_order_not_placed -q
```

Expected: fail because `ValueError` is not yet converted into a structured skip and summary has no skip counts.

- [ ] **Step 4: Implement structured execution skip**

In `MT5Executor.execute_proposal`, wrap builder errors:

```python
try:
    request = self.builder.build_pending_order_request(proposal, connection["symbol"])
except ValueError as exc:
    result = {
        "status": "SKIPPED_INVALID_ENTRY",
        "reason": "ENTRY_PRICE_STALE_OR_INVALID",
        "error": str(exc),
        "proposal": proposal.model_dump(mode="json"),
    }
    self.journal.append("ORDER_SKIPPED", result)
    return result
```

Use `build_pending_order_request` instead of `build_pending_limit_request`.

In `MT5Runner`, keep status mapping:

```python
"ORDER_PLACED" if execution.get("status") == "PLACED" else "ORDER_NOT_PLACED"
```

This already handles skip statuses as `ORDER_NOT_PLACED`.

- [ ] **Step 5: Run executor/runner tests and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_execution.py tests\test_mt5_runner.py -q
```

Expected: all executor and runner tests pass.

## Task 4: Improve Runner Summary For Order Lifecycle And Candidate Evidence

**Files:**
- Modify: `tradingagents/brokers/runner_summary.py`
- Test: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Write failing summary tests**

Add:

```python
def test_runner_summary_counts_execution_skips_and_latest_order_context(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    summary = store.record_cycle(
        {
            "status": "ORDER_NOT_PLACED",
            "as_of": "2026-06-01 10:15",
            "execution": {
                "status": "SKIPPED_INVALID_ENTRY",
                "reason": "ENTRY_PRICE_STALE_OR_INVALID",
                "proposal": {
                    "setup_name": "Breakout",
                    "strategy_type": "BREAKOUT",
                    "order_type": "AUTO",
                    "side": "SELL",
                },
            },
            "analysis": {
                "telemetry": {
                    "candidate_evaluations": [
                        {"setup": {"name": "Breakout"}, "approved": True},
                        {"setup": {"name": "Support/Resistance Bounce"}, "approved": False},
                    ]
                },
                "data_status": {"healthy": True},
            },
        }
    )

    assert summary["orders_skipped"] == 1
    assert summary["execution_skip_counts"]["ENTRY_PRICE_STALE_OR_INVALID"] == 1
    assert summary["candidate_strategy_counts"]["Breakout"] == 1
    assert summary["candidate_strategy_counts"]["Support/Resistance Bounce"] == 1
    assert summary["latest_execution"]["status"] == "SKIPPED_INVALID_ENTRY"
    assert summary["latest_execution"]["setup_name"] == "Breakout"
```

Add:

```python
def test_runner_summary_records_rejection_retcode_comment(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    summary = store.record_cycle(
        {
            "status": "ORDER_NOT_PLACED",
            "execution": {
                "status": "REJECTED",
                "broker_result": {
                    "retcode": 10015,
                    "comment": "Invalid price",
                    "request": {"type": "SELL_LIMIT"},
                },
            },
            "analysis": {"data_status": {"healthy": True}},
        }
    )

    assert summary["broker_rejections"] == 1
    assert summary["latest_execution"]["retcode"] == 10015
    assert summary["latest_execution"]["comment"] == "Invalid price"
    assert summary["latest_execution"]["request_type"] == "SELL_LIMIT"
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_runner_summary.py -q
```

Expected: fail because summary fields do not exist yet.

- [ ] **Step 3: Implement summary fields**

In `_empty_summary`, add:

```python
"orders_skipped": 0,
"execution_skip_counts": {},
"candidate_strategy_counts": {},
"approved_candidate_strategy_counts": {},
"latest_execution": {},
```

In `record_cycle`, aggregate candidate telemetry:

```python
for item in telemetry.get("candidate_evaluations") or []:
    setup = item.get("setup") or {}
    name = str(setup.get("name") or "unknown")
    candidate_counts[name] += 1
    if item.get("approved") is True:
        approved_counts[name] += 1
```

For execution:

```python
execution_status = str(execution.get("status") or "")
if execution_status.startswith("SKIPPED"):
    summary["orders_skipped"] += 1
    reason = str(execution.get("reason") or "UNKNOWN")
    skip_counts[reason] += 1
```

Build `latest_execution` from execution payload:

```python
summary["latest_execution"] = {
    "status": execution_status or None,
    "reason": execution.get("reason"),
    "retcode": broker_result.get("retcode"),
    "comment": broker_result.get("comment"),
    "request_type": request.get("type"),
    "order": execution.get("order"),
    "setup_name": proposal.get("setup_name"),
    "strategy_type": proposal.get("strategy_type"),
    "side": proposal.get("side"),
}
```

- [ ] **Step 4: Run summary tests and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_mt5_runner_summary.py -q
```

Expected: all summary tests pass.

## Task 5: Make YFinance Gaps Easier To Audit

**Files:**
- Modify: `tradingagents/dataflows/y_finance.py`
- Test: `tests/test_y_finance_retry.py`

- [ ] **Step 1: Write failing retry-metadata test**

Add:

```python
def test_yfinance_intraday_reports_retry_exception_metadata(monkeypatch, tmp_path):
    _stub_yfinance_runtime(monkeypatch, tmp_path)

    class FailingThenWorkingTicker:
        def __init__(self):
            self.calls = 0
        def history(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary yahoo gap")
            return _frame()

    fake = FailingThenWorkingTicker()
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: fake)
    monkeypatch.setattr(y_finance.time, "sleep", lambda seconds: None)

    text = y_finance.get_YFin_intraday_data("GC=F", period="10d", interval="15m")

    assert fake.calls == 2
    assert "# yfinance attempts: 2" in text
    assert "# yfinance retry warning: temporary yahoo gap" in text
```

- [ ] **Step 2: Run test and verify RED**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_y_finance_retry.py::test_yfinance_intraday_reports_retry_exception_metadata -q
```

Expected: fail because formatted successful data does not include retry warning metadata.

- [ ] **Step 3: Implement retry warning line**

Change `_history_with_retries` to keep the last warning string even if a later retry succeeds:

```python
last_warning = None
...
except Exception as exc:
    last_error = exc
    last_warning = str(exc)
...
return data, attempt, last_warning
```

Change `_format_history` signature:

```python
def _format_history(..., retry_warning: str | None = None) -> str:
```

Add to header:

```python
if retry_warning:
    header += f"# yfinance retry warning: {retry_warning}\n"
```

Pass `retry_warning` from both `get_YFin_data_online` and `get_YFin_intraday_data`.

- [ ] **Step 4: Run yfinance tests and verify GREEN**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_y_finance_retry.py tests\test_price_action_data_health.py tests\test_price_action_dataflows.py -q
```

Expected: all dataflow tests pass.

## Task 6: Update Documentation For Broker Order Semantics

**Files:**
- Modify: `docs/playbook.md`
- Modify: `docs/mt5-windows.md`
- Modify: `docs/windows-agent-handoff.md`

- [ ] **Step 1: Update docs after tests pass**

In `docs/playbook.md`, update Broker adapter responsibilities:

```text
- Choose the broker-valid pending order type from the setup, side, entry price, and current bid/ask.
- Use `BUY_LIMIT` / `SELL_LIMIT` when the entry waits for a pullback.
- Use `BUY_STOP` / `SELL_STOP` when the entry waits for continuation through a level.
- Skip stale entries instead of chasing market price.
```

In MT5 runbooks, replace "pending limit order" wording with "pending order" and note that the adapter supports limit and stop pending orders.

- [ ] **Step 2: Run docs-safe verification**

Run:

```powershell
rg -n "pending limit|LIMIT order proposals|BUY_LIMIT or SELL_LIMIT|dry_run|account_mode" docs tradingagents tests
```

Expected: remaining matches are either legacy tests, explicit compatibility paths, or wording that is still accurate.

## Task 7: Full Verification, Commit, And Push

**Files:**
- All modified files above.

- [ ] **Step 1: Run focused tests**

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\test_order_proposal.py tests\test_mt5_execution.py tests\test_mt5_broker.py tests\test_mt5_runner.py tests\test_mt5_runner_summary.py tests\test_y_finance_retry.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full suite**

Run:

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Expected: full suite passes.

- [ ] **Step 3: Review git diff**

Run:

```powershell
git diff -- tradingagents tests docs reports
git status --short
```

Expected: only intended code, docs, and report files are changed.

- [ ] **Step 4: Commit**

Run:

```powershell
git add tradingagents tests docs reports
git commit -m "fix: align mt5 pending orders with strategy entries"
```

Expected: commit succeeds on `main`.

- [ ] **Step 5: Push**

Run:

```powershell
git push origin main
```

Expected: changes are pushed to `https://github.com/toodennis106/trade.git`.

## Acceptance Criteria

- Engine-generated proposals carry the setup name and strategy family.
- Engine-generated proposals use `AUTO` order intent.
- MT5 execution can create `BUY_LIMIT`, `SELL_LIMIT`, `BUY_STOP`, and `SELL_STOP`.
- MT5 broker request materialization supports stop pending order constants.
- Stale/inside-spread entries are skipped safely before `order_send`.
- Runner summary records skipped execution reasons and latest broker retcode/comment.
- Runner summary aggregates candidate strategy counts from telemetry.
- YFinance retry warnings are visible in successful formatted data after transient failures.
- Docs no longer imply that the bot only places limit orders.
- Full test suite passes.
- Changes are committed and pushed to `main`.

## Self-Review

- Spec coverage: The plan covers order-type bug, pending-order non-fills, rejection reporting, candidate evidence, data warning visibility, docs cleanup, verification, commit, and push.
- Placeholder scan: No `TBD`, `TODO`, or "implement later" placeholders are present.
- Type consistency: `OrderProposal.setup_name`, `OrderProposal.strategy_type`, `order_type="AUTO"`, `build_pending_order_request`, `SKIPPED_INVALID_ENTRY`, and `ENTRY_PRICE_STALE_OR_INVALID` are used consistently across tasks.
- Scope: This plan does not loosen trading strategy rules. It fixes broker semantics and evidence quality so the next forward test is meaningful.
