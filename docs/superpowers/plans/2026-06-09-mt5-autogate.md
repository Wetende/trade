# MT5 AutoGate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement deterministic MT5 AutoGate with FAST 1m/3m directional scanning under 15m/30m context, NORMAL 15m/30m directional scanning under 1h/4h/1d context, separate straddle scanning, demo-only broker safety, mode isolation, and journal/summary metadata.

**Architecture:** Add a focused `mode_gate` module for trading mode parsing, account safety, health-gate metadata, and method selection helpers. Reuse the existing `MT5Runner` for directional execution and extend it to make explicit AutoGate decisions across fast/normal candidates. Keep straddle isolated, but gate it through the same mode/account metadata and require live demo execution when running as the active straddle method.

**Tech Stack:** Python, Typer CLI, pytest, existing MT5 broker/executor/runner/straddle/summary modules.

---

## File Structure

- Create `tradingagents/brokers/mode_gate.py`: `TradingMode`, parser, account safety metadata, health-gate helpers, method/profile constants.
- Modify `tradingagents/default_config.py`: add `trading_mode`, `require_demo_account`, env overrides, and sync runtime config.
- Modify `cli/main.py`: load new env vars, reject MT5 graph/LLM execution, gate `mt5-run` and `mt5-straddle-run`, and pass metadata into runners/executors.
- Modify `tradingagents/brokers/mt5.py`: add `require_demo_account` to `MT5ConnectionConfig` and enforce before every `order_send` mutation.
- Modify `tradingagents/brokers/mt5_execution.py`: journal account safety and execution gate metadata when connecting/executing.
- Modify `tradingagents/brokers/mt5_runner.py`: add trading mode config, explicit directional selection, fast/normal conflict handling, candidate metadata, health/account metadata.
- Create `tradingagents/brokers/mt5_autogate.py`: coordinate directional candidate analysis, straddle candidate analysis, lifecycle management, method selection, and one execution path for `AUTO_GATED`.
- Modify `tradingagents/brokers/mt5_straddle.py`: add trading mode metadata to heartbeat/results and allow mode-gated live demo path.
- Modify `tradingagents/brokers/runner_summary.py`: aggregate latest trading mode, selected method/profile, mode decision, health gate, account safety.
- Add/modify tests in `tests/test_env_overrides.py`, `tests/test_mt5_broker.py`, `tests/test_mt5_runner.py`, `tests/test_cli_mt5_execution.py`, `tests/test_mt5_runner_summary.py`, and `tests/test_mt5_straddle.py`.

---

### Task 1: Trading Mode Config And Parser

**Files:**
- Create: `tradingagents/brokers/mode_gate.py`
- Modify: `tradingagents/default_config.py`
- Test: `tests/test_env_overrides.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove missing mode defaults to `OFF`, valid env values parse as strings in config, and invalid values fail through `parse_trading_mode`.

```python
def test_trading_mode_defaults_to_off(monkeypatch):
    dc = _reload_with_env(monkeypatch)
    assert dc.DEFAULT_CONFIG["trading_mode"] == "OFF"
    assert dc.DEFAULT_CONFIG["require_demo_account"] is True


def test_trading_mode_env_override(monkeypatch):
    dc = _reload_with_env(monkeypatch, TRADINGAGENTS_TRADING_MODE="AUTO_GATED")
    assert dc.DEFAULT_CONFIG["trading_mode"] == "AUTO_GATED"


def test_invalid_trading_mode_rejected():
    from tradingagents.brokers.mode_gate import parse_trading_mode
    import pytest

    with pytest.raises(ValueError, match="TRADINGAGENTS_TRADING_MODE"):
        parse_trading_mode("ENTRY")
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --group dev pytest tests/test_env_overrides.py::test_trading_mode_defaults_to_off tests/test_env_overrides.py::test_trading_mode_env_override tests/test_env_overrides.py::test_invalid_trading_mode_rejected -q
```

Expected: fail because `mode_gate` and config keys do not exist.

- [ ] **Step 3: Implement mode parser and config**

Create `tradingagents/brokers/mode_gate.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TradingMode(str, Enum):
    OFF = "OFF"
    ENTRY_ONLY = "ENTRY_ONLY"
    STRADDLE_ONLY = "STRADDLE_ONLY"
    AUTO_GATED = "AUTO_GATED"


def parse_trading_mode(value: Any) -> TradingMode:
    raw = "OFF" if value in (None, "") else str(value).strip().upper()
    try:
        return TradingMode(raw)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in TradingMode)
        raise ValueError(
            "TRADINGAGENTS_TRADING_MODE must be one of: " + allowed
        ) from exc


def mode_value(value: Any) -> str:
    return parse_trading_mode(value).value


def health_gate(passed: bool = True, reasons: list[str] | None = None) -> dict[str, Any]:
    return {"passed": bool(passed), "reasons": list(reasons or [])}


@dataclass(frozen=True)
class AccountSafety:
    require_demo: bool
    trade_mode: str | None
    passed: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "require_demo": self.require_demo,
            "trade_mode": self.trade_mode,
            "passed": self.passed,
            "reason": self.reason,
        }
```

Add default config keys and env overrides:

```python
"TRADINGAGENTS_TRADING_MODE": "trading_mode",
"TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT": "require_demo_account",
...
"trading_mode": "OFF",
"require_demo_account": True,
```

- [ ] **Step 4: Run tests to verify GREEN**

Run the same targeted tests. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/mode_gate.py tradingagents/default_config.py tests/test_env_overrides.py
git commit -m "feat: add MT5 trading mode config"
```

---

### Task 2: Strict Demo-Only Broker Guard

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Test: `tests/test_mt5_broker.py`

- [ ] **Step 1: Write failing tests**

Add tests using the existing fake MT5 module patterns:

```python
def test_demo_only_guard_rejects_real_account_order_send():
    mt5 = FakeMT5(trade_mode="REAL")
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Real",
        symbol="XAUUSD",
        require_demo_account=True,
        allow_real_orders=True,
    )
    broker = MT5Broker(config, mt5_module=mt5)
    broker.connect()

    with pytest.raises(MT5BrokerError, match="demo account"):
        broker.place_pending_order(valid_pending_request())

    assert mt5.sent_requests == []


def test_demo_only_guard_allows_demo_account_order_send():
    mt5 = FakeMT5(trade_mode="DEMO")
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        require_demo_account=True,
    )
    broker = MT5Broker(config, mt5_module=mt5)
    broker.connect()

    result = broker.place_pending_order(valid_pending_request())

    assert result["ok"] is True
    assert len(mt5.sent_requests) == 1
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py::test_demo_only_guard_rejects_real_account_order_send tests/test_mt5_broker.py::test_demo_only_guard_allows_demo_account_order_send -q
```

Expected: fail because `require_demo_account` is not defined/enforced.

- [ ] **Step 3: Implement demo-only guard**

Add `require_demo_account: bool = True` to `MT5ConnectionConfig`, validate it is boolean, read `TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT`, and update `_assert_order_send_allowed`:

```python
if self.config.require_demo_account and trade_mode_label != "DEMO":
    raise MT5BrokerError(
        "MT5 demo account is required for broker execution; "
        f"connected trade mode is {trade_mode_label}"
    )
```

Keep the existing real-account acknowledgement guard for future phases, but demo-only takes precedence when enabled.

- [ ] **Step 4: Run tests to verify GREEN**

Run the targeted tests. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/mt5.py tests/test_mt5_broker.py
git commit -m "feat: enforce demo-only MT5 broker safety"
```

---

### Task 3: Directional AutoGate Selection

**Files:**
- Modify: `tradingagents/brokers/mt5_runner.py`
- Test: `tests/test_mt5_runner.py`

- [ ] **Step 1: Write failing tests**

Add focused runner tests using existing `FakeExecutor` and `proposed_order()` helpers:

```python
def test_autogate_selects_fast_when_only_fast_qualifies(tmp_path):
    normal_no_trade = proposed_order()
    normal_no_trade.status = OrderStatus.NO_TRADE
    fast_order = proposed_order()
    fast_order.timeframe = "1m"
    fast_order.confirmation_timeframe = "3m"

    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, trading_mode="AUTO_GATED"),
        executor=executor,
        analysis_func=lambda: [
            ("normal", "2026-06-03 08:15", normal_no_trade, {"entry_profile": "normal"}),
            ("fast", "2026-06-03 08:16", fast_order, {"entry_profile": "fast"}),
        ],
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert result["selected_method"] == "ENTRY_FAST"
    assert result["selected_profile"] == "fast"
    assert result["mode_decision"] == "ENTRY_FAST_SELECTED"
    assert len(executor.executed) == 1


def test_autogate_holds_when_fast_and_normal_conflict(tmp_path):
    normal = proposed_order()
    normal.side = TradeSide.BUY
    fast = proposed_order()
    fast.side = TradeSide.SELL
    fast.timeframe = "1m"
    fast.confirmation_timeframe = "3m"

    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, trading_mode="AUTO_GATED"),
        executor=executor,
        analysis_func=lambda: [
            ("normal", "2026-06-03 08:15", normal, {"entry_profile": "normal"}),
            ("fast", "2026-06-03 08:16", fast, {"entry_profile": "fast"}),
        ],
    )

    result = runner.run_once()

    assert result["status"] == "NO_TRADE"
    assert result["selected_method"] == "HOLD"
    assert result["mode_decision"] == "DIRECTIONAL_CONFLICT_HOLD"
    assert executor.executed == []
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --group dev pytest tests/test_mt5_runner.py::test_autogate_selects_fast_when_only_fast_qualifies tests/test_mt5_runner.py::test_autogate_holds_when_fast_and_normal_conflict -q
```

Expected: fail because runner has no trading mode/metadata/conflict logic.

- [ ] **Step 3: Implement directional selection**

Extend `MT5RunnerConfig`:

```python
trading_mode: str = "ENTRY_ONLY"
```

Normalize via `parse_trading_mode`.

Add explicit candidate selection helpers:

```python
def _select_directional_candidate(self, processed_rows):
    proposed = [row for row in processed_rows if row[4] == "PROPOSED"]
    normal = next((row for row in proposed if row[0] == "normal"), None)
    fast = next((row for row in proposed if row[0] == "fast"), None)
    if normal and fast and _proposal_side(normal[2]) != _proposal_side(fast[2]):
        return None, "DIRECTIONAL_CONFLICT_HOLD", "FAST_NORMAL_DIRECTION_CONFLICT"
    if normal and fast:
        selected = self._higher_quality_directional(normal, fast)
        return selected, _method_for_profile(selected[0]) + "_SELECTED", None
    if fast:
        return fast, "ENTRY_FAST_SELECTED", None
    if normal:
        return normal, "ENTRY_NORMAL_SELECTED", None
    return None, "NO_DIRECTIONAL_CANDIDATE", "NO_PROPOSED_DIRECTIONAL_PROFILE"
```

For initial scoring, prefer fast when both agree and fast has valid brokerable proposal; otherwise normal. Keep scoring deterministic.

Add payload fields:

```python
"trading_mode": self.config.trading_mode,
"selected_method": "ENTRY_FAST" | "ENTRY_NORMAL" | "HOLD",
"selected_profile": profile or None,
"mode_decision": decision,
"mode_rejection_reason": reason,
"candidate_methods": ...
"health_gate": {"passed": True, "reasons": []},
```

- [ ] **Step 4: Run tests to verify GREEN**

Run targeted runner tests. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/mt5_runner.py tests/test_mt5_runner.py
git commit -m "feat: add directional AutoGate selection"
```

---

### Task 4: Summary Metadata

**Files:**
- Modify: `tradingagents/brokers/runner_summary.py`
- Test: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Write failing test**

```python
def test_runner_summary_records_latest_mode_decision(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    summary = store.record_cycle(
        {
            "status": "ORDER_PLACED",
            "trading_mode": "AUTO_GATED",
            "selected_method": "ENTRY_FAST",
            "selected_profile": "fast",
            "mode_decision": "ENTRY_FAST_SELECTED",
            "health_gate": {"passed": True, "reasons": []},
            "account_safety": {"require_demo": True, "trade_mode": "DEMO", "passed": True},
        }
    )

    assert summary["latest_cycle"]["trading_mode"] == "AUTO_GATED"
    assert summary["latest_cycle"]["selected_method"] == "ENTRY_FAST"
    assert summary["latest_cycle"]["mode_decision"] == "ENTRY_FAST_SELECTED"
    assert summary["latest_cycle"]["health_gate"]["passed"] is True
    assert summary["latest_cycle"]["account_safety"]["trade_mode"] == "DEMO"
```

- [ ] **Step 2: Run test to verify RED**

Run:

```bash
uv run --group dev pytest tests/test_mt5_runner_summary.py::test_runner_summary_records_latest_mode_decision -q
```

Expected: fail because summary does not preserve those latest fields.

- [ ] **Step 3: Implement summary fields**

Extend `latest_cycle` with the mode metadata:

```python
"trading_mode": result.get("trading_mode"),
"selected_method": result.get("selected_method"),
"selected_profile": result.get("selected_profile"),
"mode_decision": result.get("mode_decision"),
"mode_rejection_reason": result.get("mode_rejection_reason"),
"health_gate": result.get("health_gate") or {},
"account_safety": result.get("account_safety") or {},
```

- [ ] **Step 4: Run test to verify GREEN**

Run targeted summary test. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/runner_summary.py tests/test_mt5_runner_summary.py
git commit -m "feat: record AutoGate summary metadata"
```

---

### Task 5: CLI Mode Isolation And No Live Graph

**Files:**
- Modify: `cli/main.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write failing tests**

Add tests proving `OFF` disables execution, `ENTRY_ONLY` runs `mt5-run`, `STRADDLE_ONLY` rejects `mt5-run`, and graph mode is rejected:

```python
def test_mt5_run_off_mode_places_no_orders(monkeypatch, tmp_path):
    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "OFF")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)

    result = runner.invoke(app, ["mt5-run", "--once"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["status"] == "TRADING_DISABLED"
    assert payload["trading_mode"] == "OFF"


def test_mt5_run_rejects_straddle_only_mode(monkeypatch, tmp_path):
    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "STRADDLE_ONLY")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)

    result = runner.invoke(app, ["mt5-run", "--once"])

    assert result.exit_code != 0
    assert "mt5-run requires ENTRY_ONLY or AUTO_GATED" in result.output


def test_mt5_run_rejects_graph_decision_mode_for_live_execution(monkeypatch):
    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "ENTRY_ONLY")

    result = runner.invoke(app, ["mt5-run", "--once", "--decision-mode", "graph"])

    assert result.exit_code != 0
    assert "graph decision mode is not allowed for MT5 execution" in result.output
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --group dev pytest tests/test_cli_mt5_execution.py::test_mt5_run_off_mode_places_no_orders tests/test_cli_mt5_execution.py::test_mt5_run_rejects_straddle_only_mode tests/test_cli_mt5_execution.py::test_mt5_run_rejects_graph_decision_mode_for_live_execution -q
```

Expected: fail because CLI does not gate mode.

- [ ] **Step 3: Implement CLI gating**

Add helper:

```python
def _current_trading_mode():
    from tradingagents.brokers.mode_gate import parse_trading_mode
    return parse_trading_mode(DEFAULT_CONFIG.get("trading_mode", "OFF"))
```

Add disabled heartbeat/result helper:

```python
def _trading_disabled_result(command: str) -> dict:
    return {
        "status": "TRADING_DISABLED",
        "trading_mode": "OFF",
        "selected_method": "HOLD",
        "mode_decision": "TRADING_DISABLED",
        "mode_rejection_reason": f"{command} disabled by trading mode OFF",
        "health_gate": {"passed": False, "reasons": ["trading_mode_off"]},
    }
```

In `mt5-run`, call `_load_runtime_env()`, parse mode, return disabled for `OFF`, reject `STRADDLE_ONLY`, reject `graph`, and pass `trading_mode` into `MT5RunnerConfig`.

- [ ] **Step 4: Run tests to verify GREEN**

Run targeted CLI tests. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add cli/main.py tests/test_cli_mt5_execution.py
git commit -m "feat: gate MT5 runner by trading mode"
```

---

### Task 6: Straddle Mode Metadata And Live Demo Path

**Files:**
- Modify: `tradingagents/brokers/mt5_straddle.py`
- Modify: `cli/main.py`
- Test: `tests/test_mt5_straddle.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write failing tests**

Add straddle heartbeat metadata test:

```python
def test_straddle_heartbeat_contains_trading_mode_and_method(tmp_path, monkeypatch):
    broker = FakeBroker()
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker, trading_mode="STRADDLE_ONLY")

    monkeypatch.setattr(
        executor,
        "watch_once",
        lambda *args, **kwargs: {"status": "PAIR_PLACED"},
    )

    result = executor.watch_forever(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        poll_seconds=0,
        max_cycles=1,
    )

    assert result["last_result"]["trading_mode"] == "STRADDLE_ONLY"
    assert result["last_result"]["selected_method"] == "STRADDLE"
```

Add CLI test proving `STRADDLE_ONLY --watch` passes `live=True` or equivalent demo execution flag when mode is active.

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --group dev pytest tests/test_mt5_straddle.py::test_straddle_heartbeat_contains_trading_mode_and_method -q
```

Expected: fail because straddle executor has no mode metadata.

- [ ] **Step 3: Implement straddle metadata and CLI gating**

Add optional `trading_mode: str = "STRADDLE_ONLY"` to `MT5StraddleExecutor.__init__`, include:

```python
"trading_mode": self.trading_mode,
"selected_method": "STRADDLE" if status is actionable else "HOLD",
"selected_profile": None,
"mode_decision": ...
"health_gate": ...
```

In `mt5-straddle-run`, return disabled for `OFF`, reject `ENTRY_ONLY`, and for `STRADDLE_ONLY`/`AUTO_GATED` continuous demo trading pass `live=True` unless the command is explicitly being used as validation outside an active trading mode.

- [ ] **Step 4: Run tests to verify GREEN**

Run targeted straddle and CLI tests. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/mt5_straddle.py cli/main.py tests/test_mt5_straddle.py tests/test_cli_mt5_execution.py
git commit -m "feat: gate MT5 straddle by trading mode"
```

---

### Task 7: AutoGate Runner With Straddle Candidate Integration

**Files:**
- Create: `tradingagents/brokers/mt5_autogate.py`
- Modify: `cli/main.py`
- Modify: `tradingagents/brokers/mt5_runner.py`
- Modify: `tradingagents/brokers/mt5_straddle.py`
- Test: `tests/test_cli_mt5_execution.py`
- Test: `tests/test_mt5_autogate.py`

- [ ] **Step 1: Write failing test**

Add AutoGate runner tests proving straddle is really scanned and can be selected when directional candidates do not qualify.

```python
def test_autogate_selects_straddle_when_directional_holds(tmp_path):
    from tradingagents.brokers.mt5_autogate import MT5AutoGateRunner, MT5AutoGateConfig

    directional_executor = FakeExecutor(active=False)
    straddle_executor = FakeStraddleExecutor(
        candidate={"status": "PROPOSED", "pair": object(), "requests": []}
    )
    normal_no_trade = proposed_order()
    normal_no_trade.status = OrderStatus.NO_TRADE
    fast_no_trade = proposed_order()
    fast_no_trade.status = OrderStatus.NO_TRADE

    runner = MT5AutoGateRunner(
        MT5AutoGateConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        directional_executor=directional_executor,
        straddle_executor=straddle_executor,
        directional_analysis_func=lambda: [
            ("normal", "2026-06-03 08:15", normal_no_trade, {"entry_profile": "normal"}),
            ("fast", "2026-06-03 08:16", fast_no_trade, {"entry_profile": "fast"}),
        ],
        straddle_config=object(),
    )

    result = runner.run_once()

    assert result["status"] == "STRADDLE_ORDER_PLACED"
    assert result["selected_method"] == "STRADDLE"
    assert result["mode_decision"] == "STRADDLE_SELECTED"
    assert straddle_executor.executed_live is True
    assert directional_executor.executed == []
```

Add an active-trade test proving AutoGate manages only and does not scan straddle:

```python
def test_autogate_active_trade_blocks_directional_and_straddle_scans(tmp_path):
    directional_executor = FakeExecutor(active=True)
    straddle_executor = FakeStraddleExecutor()

    runner = MT5AutoGateRunner(
        MT5AutoGateConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        directional_executor=directional_executor,
        straddle_executor=straddle_executor,
        directional_analysis_func=lambda: (_ for _ in ()).throw(AssertionError("no analysis")),
        straddle_config=object(),
    )

    result = runner.run_once()

    assert result["status"] == "ACTIVE_TRADE_MONITORED"
    assert result["selected_method"] == "HOLD"
    assert straddle_executor.candidate_calls == 0
```

Add a CLI-level test that `AUTO_GATED` instantiates `MT5AutoGateRunner` and passes the mode.

```python
def test_auto_gated_mode_runs_directional_runner_with_autogate_config(monkeypatch, tmp_path):
    _isolate_runtime_env(monkeypatch)
    monkeypatch.setenv("TRADINGAGENTS_TRADING_MODE", "AUTO_GATED")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    calls = {}

    class Runner:
        def __init__(
            self,
            runner_config,
            directional_executor,
            straddle_executor,
            directional_analysis_func,
            straddle_config,
            current_as_of_func=None,
        ):
            calls["trading_mode"] = runner_config.trading_mode
        def run_once(self):
            return {"status": "NO_TRADE", "trading_mode": calls["trading_mode"]}
        def run_forever(self):
            raise AssertionError("--once should call run_once")

    monkeypatch.setattr(MT5ConnectionConfig, "from_env", staticmethod(lambda: object()))
    monkeypatch.setattr(mt5_execution, "MT5Executor", FakeExecutorClass)
    monkeypatch.setattr(mt5_autogate, "MT5AutoGateRunner", Runner)

    result = runner.invoke(app, ["mt5-run", "--once"])

    assert result.exit_code == 0
    assert json.loads(result.output)["trading_mode"] == "AUTO_GATED"
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run --group dev pytest tests/test_mt5_autogate.py::test_autogate_selects_straddle_when_directional_holds tests/test_mt5_autogate.py::test_autogate_active_trade_blocks_directional_and_straddle_scans tests/test_cli_mt5_execution.py::test_auto_gated_mode_runs_directional_runner_with_autogate_config -q
```

Expected: fail because `MT5AutoGateRunner` does not exist and CLI does not route to it.

- [ ] **Step 3: Implement AutoGate runner**

Create `tradingagents/brokers/mt5_autogate.py` with:

```python
@dataclass(frozen=True)
class MT5AutoGateConfig:
    results_dir: str | Path
    poll_seconds: int = 30
    max_cycles: int = 0
    max_runtime_seconds: int = 0
    max_session_loss: float = 0.0
    blocked_strategy_rules: tuple[str, ...] = ()
    trading_mode: str = "AUTO_GATED"
```

Implement `run_once`:

```text
1. Snapshot orders/positions through directional executor.
2. Monitor straddle pair and manage active lifecycle.
3. If any active order/position exists, write ACTIVE_TRADE_MONITORED.
4. Reconcile history/session loss.
5. Parse directional analysis rows and select directional candidate.
6. Evaluate straddle candidate using a new non-mutating straddle candidate method.
7. If directional conflict, HOLD.
8. If directional candidate selected, execute directional proposal.
9. Else if straddle candidate is PROPOSED, execute straddle pair with live=True.
10. Else HOLD.
```

Add non-mutating `MT5StraddleExecutor.evaluate_entry_candidate(...)` so AutoGate can scan straddle without recording a dry-run pair or placing orders. It returns the built pair and validated requests when status is `PROPOSED`.

Wire `AUTO_GATED` in `cli/main.py` to construct `MT5AutoGateRunner` with:

- `MT5Executor`,
- `MT5StraddleExecutor`,
- existing `_mt5_runner_engine_analysis_func(config)`,
- default `StraddleBreakoutConfig`,
- existing exit-management and entry-regime config.

- [ ] **Step 4: Run test to verify GREEN**

Run targeted AutoGate and CLI tests. Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/mt5_autogate.py tradingagents/brokers/mt5_straddle.py cli/main.py tests/test_mt5_autogate.py tests/test_cli_mt5_execution.py
git commit -m "feat: add MT5 AutoGate runner"
```

---

### Task 8: Verification And Completion

**Files:**
- Run tests only.

- [ ] **Step 1: Run targeted MT5 suite**

```bash
uv run --group dev pytest tests/test_env_overrides.py tests/test_mt5_broker.py tests/test_mt5_runner.py tests/test_mt5_runner_summary.py tests/test_mt5_straddle.py tests/test_cli_mt5_execution.py -q
```

Expected: all pass.

- [ ] **Step 2: Run full suite**

```bash
uv run --group dev pytest
```

Expected: all pass.

- [ ] **Step 3: Commit any final fixes**

```bash
git status --short
```

If `git status --short` shows code or test fixes that are not already committed, stage only those files and commit them with:

```bash
git add cli/main.py tradingagents/brokers/mode_gate.py tradingagents/brokers/mt5.py tradingagents/brokers/mt5_execution.py tradingagents/brokers/mt5_runner.py tradingagents/brokers/mt5_straddle.py tradingagents/brokers/mt5_autogate.py tradingagents/brokers/runner_summary.py tests/test_env_overrides.py tests/test_mt5_broker.py tests/test_mt5_runner.py tests/test_mt5_runner_summary.py tests/test_mt5_straddle.py tests/test_mt5_autogate.py tests/test_cli_mt5_execution.py
git commit -m "test: verify MT5 AutoGate behavior"
```

- [ ] **Step 4: Push**

```bash
git push
```

Expected: branch updates successfully.

- [ ] **Step 5: Restart demo runner only after tests pass**

Use a fresh telemetry folder and explicit environment:

```bash
TRADINGAGENTS_TRADING_MODE=AUTO_GATED
TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT=true
TRADINGAGENTS_DECISION_MODE=engine
```

Confirm first heartbeat includes:

```json
{
  "trading_mode": "AUTO_GATED",
  "health_gate": {"passed": true},
  "account_safety": {"require_demo": true, "passed": true}
}
```
