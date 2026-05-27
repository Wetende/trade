# MT5 Demo Execution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full MT5 demo execution layer that turns validated `OrderProposal` files into guarded pending limit orders, monitors orders/positions, cancels stale orders, manages stops, and journals every broker action.

**Architecture:** Keep the price-action strategy and order proposal generation as the source of truth. Add an MT5 execution boundary under `tradingagents/brokers/` that maps proposals to broker requests, enforces demo-only safety checks, and runs a single-symbol execution loop. The first supported mode manages one active pending order or position per symbol to keep demo forward testing auditable.

**Tech Stack:** Python, Typer CLI, Pydantic models, official `MetaTrader5` Python package on Windows, pytest with fake MT5 modules.

---

## File Structure

- Modify: `tradingagents/brokers/mt5.py`
  - Own MT5 account connection, safety checks, symbol specs, order request building, order placement, cancellation, modification, and broker state reads.
- Create: `tradingagents/brokers/mt5_execution.py`
  - Own proposal loading, single-symbol active-trade policy, execution loop decisions, stale order cancellation, break-even and trailing stop calls, and journal writing.
- Create: `tradingagents/brokers/execution_journal.py`
  - Append JSONL execution events under the configured results directory.
- Modify: `tradingagents/agents/schemas.py`
  - Add optional execution metadata only if tests prove the execution layer needs a stable schema field beyond current `OrderProposal`.
- Modify: `cli/main.py`
  - Add `mt5-demo-execute` and `mt5-demo-monitor` commands.
- Modify: `.env.example`
  - Add demo execution settings with non-sensitive example values.
- Create/modify tests:
  - `tests/test_mt5_broker.py`
  - `tests/test_mt5_execution.py`
  - `tests/test_execution_journal.py`
  - `tests/test_execution_state.py`
  - `tests/test_cli_mt5_execution.py`

## Assumptions

- The broker account mode is controlled by the MT5 login/server credentials the user puts in local `.env`.
- Code must still verify the connected account before sending any order.
- `TRADINGAGENTS_MT5_ACCOUNT_MODE=demo` is required for all execution commands.
- A configured `TRADINGAGENTS_MT5_EXPECTED_LOGIN` and `TRADINGAGENTS_MT5_EXPECTED_SERVER` must match `account_info()` before `order_send()`.
- One active pending order or open position per symbol is allowed in version 1.
- Only pending limit orders are supported: `BUY_LIMIT` and `SELL_LIMIT`.
- Live trading is blocked in this plan.

---

### Task 1: Demo Safety Configuration

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `.env.example`
- Test: `tests/test_mt5_broker.py`

- [ ] **Step 1: Write failing tests for execution safety config**

Add these tests to `tests/test_mt5_broker.py`:

```python
def test_mt5_config_reads_demo_execution_guards(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SYMBOL", "XAUUSD")
    monkeypatch.setenv("TRADINGAGENTS_MT5_ACCOUNT_MODE", "demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_EXPECTED_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_EXPECTED_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_VOLUME", "0.01")
    monkeypatch.setenv("TRADINGAGENTS_MT5_DEVIATION", "20")
    monkeypatch.setenv("TRADINGAGENTS_MT5_MAGIC", "150015")

    config = MT5ConnectionConfig.from_env()

    assert config.account_mode == "demo"
    assert config.expected_login == 123456789
    assert config.expected_server == "ExampleBroker-Demo"
    assert config.volume == 0.01
    assert config.deviation == 20
    assert config.magic == 150015


def test_mt5_config_rejects_non_demo_execution_mode(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MT5_ACCOUNT_MODE", "live")

    with pytest.raises(MT5BrokerError, match="demo mode is required"):
        MT5ConnectionConfig.from_env()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py::test_mt5_config_reads_demo_execution_guards tests/test_mt5_broker.py::test_mt5_config_rejects_non_demo_execution_mode -q
```

Expected: both tests fail because `MT5ConnectionConfig` does not have the new guard fields.

- [ ] **Step 3: Extend `MT5ConnectionConfig`**

Modify `tradingagents/brokers/mt5.py`:

```python
@dataclass(frozen=True)
class MT5ConnectionConfig:
    login: int
    password: str
    server: str
    symbol: str = "XAUUSD"
    terminal_path: str | None = None
    account_mode: str = "demo"
    expected_login: int | None = None
    expected_server: str | None = None
    volume: float = 0.01
    deviation: int = 20
    magic: int = 150015
```

Add helpers in the same file:

```python
def _int_env(name: str, default: int | None = None) -> int | None:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise MT5BrokerError(f"{name} must be numeric") from exc


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise MT5BrokerError(f"{name} must be numeric") from exc
```

Update `from_env()`:

```python
account_mode = os.environ.get("TRADINGAGENTS_MT5_ACCOUNT_MODE", "demo").strip().lower()
if account_mode != "demo":
    raise MT5BrokerError("MT5 demo mode is required for automated execution")

return cls(
    login=login,
    password=os.environ["TRADINGAGENTS_MT5_PASSWORD"],
    server=os.environ["TRADINGAGENTS_MT5_SERVER"],
    symbol=os.environ.get("TRADINGAGENTS_MT5_SYMBOL", "XAUUSD"),
    terminal_path=os.environ.get("TRADINGAGENTS_MT5_PATH") or None,
    account_mode=account_mode,
    expected_login=_int_env("TRADINGAGENTS_MT5_EXPECTED_LOGIN", login),
    expected_server=os.environ.get("TRADINGAGENTS_MT5_EXPECTED_SERVER")
    or os.environ["TRADINGAGENTS_MT5_SERVER"],
    volume=_float_env("TRADINGAGENTS_MT5_VOLUME", 0.01),
    deviation=_int_env("TRADINGAGENTS_MT5_DEVIATION", 20) or 20,
    magic=_int_env("TRADINGAGENTS_MT5_MAGIC", 150015) or 150015,
)
```

- [ ] **Step 4: Update `.env.example`**

Add:

```bash
# Required for MT5 automated demo execution.
#TRADINGAGENTS_MT5_ACCOUNT_MODE=demo
#TRADINGAGENTS_MT5_EXPECTED_LOGIN=123456789
#TRADINGAGENTS_MT5_EXPECTED_SERVER=YourBroker-Demo
#TRADINGAGENTS_MT5_VOLUME=0.01
#TRADINGAGENTS_MT5_DEVIATION=20
#TRADINGAGENTS_MT5_MAGIC=150015
```

- [ ] **Step 5: Run tests**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py -q
```

Expected: all MT5 broker tests pass.

- [ ] **Step 6: Commit**

```bash
git add .env.example tradingagents/brokers/mt5.py tests/test_mt5_broker.py
git commit -m "feat: add mt5 demo safety config"
```

---

### Task 2: Account and Symbol Safety Checks

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Test: `tests/test_mt5_broker.py`

- [ ] **Step 1: Write failing account guard tests**

Add:

```python
def test_mt5_broker_rejects_unexpected_account_login():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        expected_login=987654321,
        expected_server="ExampleBroker-Demo",
    )

    with pytest.raises(MT5BrokerError, match="unexpected MT5 account login"):
        MT5Broker(config, mt5_module=fake_mt5).connect()


def test_mt5_broker_rejects_unexpected_account_server():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        expected_login=123456789,
        expected_server="OtherBroker-Demo",
    )

    with pytest.raises(MT5BrokerError, match="unexpected MT5 account server"):
        MT5Broker(config, mt5_module=fake_mt5).connect()
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py::test_mt5_broker_rejects_unexpected_account_login tests/test_mt5_broker.py::test_mt5_broker_rejects_unexpected_account_server -q
```

Expected: tests fail because `connect()` does not enforce expected account metadata.

- [ ] **Step 3: Add account guard**

Add method to `MT5Broker`:

```python
def _assert_expected_account(self, account: dict[str, Any]) -> None:
    login = account.get("login")
    server = account.get("server")
    if self.config.expected_login is not None and login != self.config.expected_login:
        raise MT5BrokerError(
            f"unexpected MT5 account login: got {login}, expected {self.config.expected_login}"
        )
    if self.config.expected_server and server != self.config.expected_server:
        raise MT5BrokerError(
            f"unexpected MT5 account server: got {server}, expected {self.config.expected_server}"
        )
```

Call it in `connect()` after `account_info()`:

```python
self._assert_expected_account(account)
```

- [ ] **Step 4: Run tests**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py -q
```

Expected: all MT5 broker tests pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/mt5.py tests/test_mt5_broker.py
git commit -m "feat: guard mt5 demo account"
```

---

### Task 3: Proposal Loading and Broker Request Mapping

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Create: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing tests for proposal-to-request mapping**

Create `tests/test_mt5_execution.py`:

```python
import json
from pathlib import Path

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.mt5 import MT5ConnectionConfig, MT5OrderRequestBuilder


def _proposal(side: TradeAction = TradeAction.BUY) -> OrderProposal:
    return OrderProposal(
        symbol="XAUUSD",
        side=side,
        order_type="LIMIT",
        entry_price=2450.123,
        stop_loss=2447.987,
        take_profit=2456.789,
        timeframe="15m",
        confirmation_timeframe="30m",
        valid_until="2026-05-27 10:15 EDT",
        activation_window_minutes=10,
        cancel_if_not_triggered_after="2026-05-27 10:10 EDT",
        status=OrderStatus.PROPOSED,
        reason="A+ setup passed.",
    )


def test_build_buy_limit_request_rounds_prices():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        volume=0.01,
        deviation=20,
        magic=150015,
    )
    builder = MT5OrderRequestBuilder(config)
    symbol = {
        "name": "XAUUSD",
        "digits": 2,
        "point": 0.01,
        "trade_tick_size": 0.01,
    }

    request = builder.build_pending_limit_request(_proposal(), symbol)

    assert request["symbol"] == "XAUUSD"
    assert request["volume"] == 0.01
    assert request["price"] == 2450.12
    assert request["sl"] == 2447.99
    assert request["tp"] == 2456.79
    assert request["deviation"] == 20
    assert request["magic"] == 150015
    assert request["comment"] == "TradingAgents demo"


def test_build_request_rejects_no_trade_proposal():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
    )
    builder = MT5OrderRequestBuilder(config)
    proposal = _proposal()
    proposal.status = OrderStatus.NO_TRADE

    try:
        builder.build_pending_limit_request(proposal, {"name": "XAUUSD", "digits": 2})
    except ValueError as exc:
        assert "PROPOSED" in str(exc)
    else:
        raise AssertionError("expected request builder to reject NO_TRADE")
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_mt5_execution.py -q
```

Expected: import fails because `MT5OrderRequestBuilder` does not exist.

- [ ] **Step 3: Implement request builder**

Add to `tradingagents/brokers/mt5.py`:

```python
class MT5OrderRequestBuilder:
    def __init__(self, config: MT5ConnectionConfig):
        self.config = config

    def _round_price(self, value: float, symbol_info: dict[str, Any]) -> float:
        digits = int(symbol_info.get("digits") or 2)
        return round(float(value), digits)

    def _order_type(self, side: Any) -> str:
        side_value = str(getattr(side, "value", side)).upper()
        if side_value == "BUY":
            return "BUY_LIMIT"
        if side_value == "SELL":
            return "SELL_LIMIT"
        raise ValueError(f"unsupported proposal side for MT5 limit order: {side_value}")

    def build_pending_limit_request(
        self,
        proposal: Any,
        symbol_info: dict[str, Any],
    ) -> dict[str, Any]:
        status = str(getattr(proposal.status, "value", proposal.status)).upper()
        if status != "PROPOSED":
            raise ValueError("MT5 execution requires a PROPOSED order proposal")
        if proposal.entry_price is None or proposal.stop_loss is None or proposal.take_profit is None:
            raise ValueError("MT5 execution requires entry_price, stop_loss, and take_profit")
        if proposal.symbol != self.config.symbol:
            raise ValueError(
                f"proposal symbol {proposal.symbol} does not match MT5 symbol {self.config.symbol}"
            )

        return {
            "action": "TRADE_ACTION_PENDING",
            "symbol": self.config.symbol,
            "volume": self.config.volume,
            "type": self._order_type(proposal.side),
            "price": self._round_price(proposal.entry_price, symbol_info),
            "sl": self._round_price(proposal.stop_loss, symbol_info),
            "tp": self._round_price(proposal.take_profit, symbol_info),
            "deviation": self.config.deviation,
            "magic": self.config.magic,
            "comment": "TradingAgents demo",
            "type_time": "ORDER_TIME_GTC",
            "type_filling": "ORDER_FILLING_RETURN",
        }
```

- [ ] **Step 4: Run mapping tests**

Run:

```bash
uv run --group dev pytest tests/test_mt5_execution.py -q
```

Expected: request mapping tests pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/mt5.py tests/test_mt5_execution.py
git commit -m "feat: map proposals to mt5 requests"
```

---

### Task 4: MT5 Order Placement, Cancellation, and Modification

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tests/test_mt5_broker.py`

- [ ] **Step 1: Extend fake MT5 for trading calls**

Modify `FakeMT5` in `tests/test_mt5_broker.py`:

```python
class FakeMT5:
    TRADE_RETCODE_DONE = 10009
    TRADE_ACTION_PENDING = 5
    TRADE_ACTION_REMOVE = 8
    TRADE_ACTION_SLTP = 6
    ORDER_TYPE_BUY_LIMIT = 2
    ORDER_TYPE_SELL_LIMIT = 3
    ORDER_TIME_GTC = 0
    ORDER_FILLING_RETURN = 2

    def __init__(self):
        self.initialized_with = None
        self.selected_symbols = []
        self.shutdown_called = False
        self.sent_requests = []

    def order_send(self, request):
        self.sent_requests.append(request)
        return SimpleNamespace(retcode=self.TRADE_RETCODE_DONE, order=111222, deal=0, comment="ok")
```

- [ ] **Step 2: Write failing broker action tests**

Add:

```python
def test_mt5_broker_sends_pending_order_request():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        volume=0.01,
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.place_pending_order(
        {
            "action": "TRADE_ACTION_PENDING",
            "symbol": "XAUUSD",
            "volume": 0.01,
            "type": "BUY_LIMIT",
            "price": 2450.12,
            "sl": 2447.99,
            "tp": 2456.79,
            "deviation": 20,
            "magic": 150015,
            "comment": "TradingAgents demo",
            "type_time": "ORDER_TIME_GTC",
            "type_filling": "ORDER_FILLING_RETURN",
        }
    )

    assert result["ok"] is True
    assert result["order"] == 111222
    assert fake_mt5.sent_requests[0]["action"] == FakeMT5.TRADE_ACTION_PENDING
    assert fake_mt5.sent_requests[0]["type"] == FakeMT5.ORDER_TYPE_BUY_LIMIT


def test_mt5_broker_cancels_order():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    result = broker.cancel_order(111222)

    assert result["ok"] is True
    assert fake_mt5.sent_requests[-1]["action"] == FakeMT5.TRADE_ACTION_REMOVE
    assert fake_mt5.sent_requests[-1]["order"] == 111222
```

- [ ] **Step 3: Run tests and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py::test_mt5_broker_sends_pending_order_request tests/test_mt5_broker.py::test_mt5_broker_cancels_order -q
```

Expected: tests fail because broker methods do not exist.

- [ ] **Step 4: Implement broker request conversion and send methods**

Add to `MT5Broker`:

```python
def _constants(self) -> dict[str, Any]:
    mt5 = self._module()
    return {
        "TRADE_ACTION_PENDING": getattr(mt5, "TRADE_ACTION_PENDING"),
        "TRADE_ACTION_REMOVE": getattr(mt5, "TRADE_ACTION_REMOVE"),
        "TRADE_ACTION_SLTP": getattr(mt5, "TRADE_ACTION_SLTP"),
        "BUY_LIMIT": getattr(mt5, "ORDER_TYPE_BUY_LIMIT"),
        "SELL_LIMIT": getattr(mt5, "ORDER_TYPE_SELL_LIMIT"),
        "ORDER_TIME_GTC": getattr(mt5, "ORDER_TIME_GTC"),
        "ORDER_FILLING_RETURN": getattr(mt5, "ORDER_FILLING_RETURN"),
        "TRADE_RETCODE_DONE": getattr(mt5, "TRADE_RETCODE_DONE"),
    }


def _materialize_request(self, request: dict[str, Any]) -> dict[str, Any]:
    constants = self._constants()
    converted = dict(request)
    converted["action"] = constants[converted["action"]]
    converted["type"] = constants[converted["type"]]
    converted["type_time"] = constants[converted["type_time"]]
    converted["type_filling"] = constants[converted["type_filling"]]
    return converted


def _send(self, request: dict[str, Any]) -> dict[str, Any]:
    mt5 = self._module()
    result = mt5.order_send(request)
    result_dict = _asdict(result)
    ok = result_dict.get("retcode") == self._constants()["TRADE_RETCODE_DONE"]
    result_dict["ok"] = ok
    if not ok:
        result_dict["last_error"] = mt5.last_error()
    return result_dict


def place_pending_order(self, request: dict[str, Any]) -> dict[str, Any]:
    return self._send(self._materialize_request(request))


def cancel_order(self, ticket: int) -> dict[str, Any]:
    return self._send({"action": self._constants()["TRADE_ACTION_REMOVE"], "order": int(ticket)})


def modify_position_stops(
    self,
    position_ticket: int,
    stop_loss: float,
    take_profit: float,
) -> dict[str, Any]:
    request = {
        "action": self._constants()["TRADE_ACTION_SLTP"],
        "position": int(position_ticket),
        "sl": float(stop_loss),
        "tp": float(take_profit),
    }
    return self._send(request)
```

- [ ] **Step 5: Run broker tests**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py -q
```

Expected: all broker tests pass.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/brokers/mt5.py tests/test_mt5_broker.py
git commit -m "feat: add mt5 order actions"
```

---

### Task 5: Execution Journal

**Files:**
- Create: `tradingagents/brokers/execution_journal.py`
- Create: `tests/test_execution_journal.py`

- [ ] **Step 1: Write failing journal tests**

Create `tests/test_execution_journal.py`:

```python
import json

from tradingagents.brokers.execution_journal import ExecutionJournal


def test_execution_journal_appends_jsonl_events(tmp_path):
    journal = ExecutionJournal(tmp_path, "XAUUSD")

    path = journal.append(
        "ORDER_PLACED",
        {"order": 111222, "symbol": "XAUUSD"},
    )

    lines = path.read_text(encoding="utf-8").splitlines()
    event = json.loads(lines[0])
    assert event["event_type"] == "ORDER_PLACED"
    assert event["symbol"] == "XAUUSD"
    assert event["payload"]["order"] == 111222
    assert event["payload"]["symbol"] == "XAUUSD"
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_execution_journal.py -q
```

Expected: import fails because `ExecutionJournal` does not exist.

- [ ] **Step 3: Implement journal**

Create `tradingagents/brokers/execution_journal.py`:

```python
"""JSONL journal for broker execution actions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.dataflows.utils import safe_ticker_component


class ExecutionJournal:
    def __init__(self, results_dir: str | Path, symbol: str):
        self.symbol = symbol
        safe_symbol = safe_ticker_component(symbol)
        self.directory = Path(results_dir) / safe_symbol / "execution_journal"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "mt5_demo_events.jsonl"

    def append(self, event_type: str, payload: dict[str, Any]) -> Path:
        event = {
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "symbol": self.symbol,
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True) + "\n")
        return self.path
```

- [ ] **Step 4: Run journal tests**

Run:

```bash
uv run --group dev pytest tests/test_execution_journal.py -q
```

Expected: journal tests pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/execution_journal.py tests/test_execution_journal.py
git commit -m "feat: add execution journal"
```

---

### Task 6: Execution Service

**Files:**
- Create: `tradingagents/brokers/mt5_execution.py`
- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing execution service tests**

Add to `tests/test_mt5_execution.py`:

```python
from types import SimpleNamespace

from tradingagents.brokers.mt5_execution import MT5DemoExecutor


class FakeBroker:
    def __init__(self):
        self.symbol_info = {
            "name": "XAUUSD",
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
        }
        self.pending_orders = []
        self.positions = []
        self.placed_requests = []
        self.cancelled = []

    def connect(self):
        return {"connected": True, "symbol": self.symbol_info, "account": {"login": 123456789}}

    def open_orders(self, symbol):
        return self.pending_orders

    def open_positions(self, symbol):
        return self.positions

    def place_pending_order(self, request):
        self.placed_requests.append(request)
        return {"ok": True, "order": 111222, "retcode": 10009}

    def cancel_order(self, ticket):
        self.cancelled.append(ticket)
        return {"ok": True, "order": ticket, "retcode": 10009}


def test_executor_places_pending_order_when_no_active_trade(tmp_path):
    broker = FakeBroker()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    executor = MT5DemoExecutor(config, tmp_path, broker=broker)

    result = executor.execute_proposal(_proposal())

    assert result["status"] == "PLACED"
    assert result["order"] == 111222
    assert len(broker.placed_requests) == 1


def test_executor_refuses_when_active_order_exists(tmp_path):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 999, "symbol": "XAUUSD"}]
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    executor = MT5DemoExecutor(config, tmp_path, broker=broker)

    result = executor.execute_proposal(_proposal())

    assert result["status"] == "SKIPPED_ACTIVE_TRADE"
    assert broker.placed_requests == []
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_mt5_execution.py::test_executor_places_pending_order_when_no_active_trade tests/test_mt5_execution.py::test_executor_refuses_when_active_order_exists -q
```

Expected: import fails because `MT5DemoExecutor` does not exist.

- [ ] **Step 3: Implement execution service**

Create `tradingagents/brokers/mt5_execution.py`:

```python
"""MT5 demo execution service for TradingAgents order proposals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tradingagents.agents.schemas import OrderProposal
from tradingagents.brokers.execution_journal import ExecutionJournal
from tradingagents.brokers.mt5 import MT5Broker, MT5ConnectionConfig, MT5OrderRequestBuilder


def load_order_proposal(path: str | Path) -> OrderProposal:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return OrderProposal.model_validate(data)


class MT5DemoExecutor:
    def __init__(
        self,
        config: MT5ConnectionConfig,
        results_dir: str | Path,
        broker: Any | None = None,
    ):
        self.config = config
        self.broker = broker or MT5Broker(config)
        self.builder = MT5OrderRequestBuilder(config)
        self.journal = ExecutionJournal(results_dir, config.symbol)

    def _active_trade_exists(self) -> bool:
        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        return bool(orders or positions)

    def execute_proposal(self, proposal: OrderProposal) -> dict[str, Any]:
        connection = self.broker.connect()
        self.journal.append("CONNECTED", connection)

        if self._active_trade_exists():
            result = {"status": "SKIPPED_ACTIVE_TRADE", "symbol": self.config.symbol}
            self.journal.append("SKIPPED_ACTIVE_TRADE", result)
            return result

        request = self.builder.build_pending_limit_request(
            proposal,
            connection["symbol"],
        )
        self.journal.append("ORDER_REQUEST_BUILT", request)
        send_result = self.broker.place_pending_order(request)
        event_type = "ORDER_PLACED" if send_result.get("ok") else "ORDER_REJECTED"
        self.journal.append(event_type, send_result)
        return {
            "status": "PLACED" if send_result.get("ok") else "REJECTED",
            "order": send_result.get("order"),
            "broker_result": send_result,
        }
```

- [ ] **Step 4: Run execution tests**

Run:

```bash
uv run --group dev pytest tests/test_mt5_execution.py -q
```

Expected: execution tests pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/mt5_execution.py tests/test_mt5_execution.py
git commit -m "feat: add mt5 demo executor"
```

---

### Task 7: Execution State Store

**Files:**
- Create: `tradingagents/brokers/execution_state.py`
- Modify: `tradingagents/brokers/mt5_execution.py`
- Create: `tests/test_execution_state.py`
- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing state-store tests**

Create `tests/test_execution_state.py`:

```python
from datetime import datetime, timezone

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.execution_state import ExecutionStateStore


def _proposal() -> OrderProposal:
    return OrderProposal(
        symbol="XAUUSD",
        side=TradeAction.BUY,
        order_type="LIMIT",
        entry_price=2450.0,
        stop_loss=2447.0,
        take_profit=2456.0,
        timeframe="15m",
        confirmation_timeframe="30m",
        valid_until="2026-05-27 10:15 EDT",
        activation_window_minutes=10,
        cancel_if_not_triggered_after="2026-05-27 10:10 EDT",
        status=OrderStatus.PROPOSED,
        reason="A+ setup passed.",
    )


def test_execution_state_records_active_pending_order(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")

    state = store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    assert state["active_order_ticket"] == 111222
    assert state["symbol"] == "XAUUSD"
    assert state["cancel_after_utc"] == "2026-05-27T14:10:00+00:00"


def test_execution_state_clears_active_pending_order(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    state = store.clear_pending_order()

    assert state["active_order_ticket"] is None
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_execution_state.py -q
```

Expected: import fails because `ExecutionStateStore` does not exist.

- [ ] **Step 3: Implement execution state store**

Create `tradingagents/brokers/execution_state.py`:

```python
"""Small JSON state file for the active MT5 demo order."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.schemas import OrderProposal
from tradingagents.dataflows.utils import safe_ticker_component


class ExecutionStateStore:
    def __init__(self, results_dir: str | Path, symbol: str):
        self.symbol = symbol
        safe_symbol = safe_ticker_component(symbol)
        self.directory = Path(results_dir) / safe_symbol / "execution_state"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "mt5_demo_state.json"

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"symbol": self.symbol, "active_order_ticket": None}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def save(self, state: dict[str, Any]) -> dict[str, Any]:
        self.path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
        return state

    def record_pending_order(
        self,
        ticket: int,
        proposal: OrderProposal,
        placed_at_utc: datetime | None = None,
    ) -> dict[str, Any]:
        placed_at = placed_at_utc or datetime.now(timezone.utc)
        window = proposal.activation_window_minutes or 10
        cancel_after = placed_at + timedelta(minutes=window)
        return self.save(
            {
                "symbol": self.symbol,
                "active_order_ticket": int(ticket),
                "placed_at_utc": placed_at.isoformat(),
                "cancel_after_utc": cancel_after.isoformat(),
                "proposal": proposal.model_dump(mode="json"),
            }
        )

    def clear_pending_order(self) -> dict[str, Any]:
        state = self.load()
        state["active_order_ticket"] = None
        return self.save(state)
```

- [ ] **Step 4: Integrate execution state into the executor**

Add to `tests/test_mt5_execution.py`:

```python
def test_executor_records_active_order_state(tmp_path):
    broker = FakeBroker()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    executor = MT5DemoExecutor(config, tmp_path, broker=broker)

    executor.execute_proposal(_proposal())

    state = executor.state.load()
    assert state["active_order_ticket"] == 111222
    assert state["symbol"] == "XAUUSD"
```

Modify `tradingagents/brokers/mt5_execution.py`:

```python
from tradingagents.brokers.execution_state import ExecutionStateStore
```

Add in `MT5DemoExecutor.__init__()`:

```python
self.state = ExecutionStateStore(results_dir, config.symbol)
```

Add in `execute_proposal()` after `ORDER_PLACED` is journaled:

```python
if send_result.get("ok"):
    self.state.record_pending_order(send_result["order"], proposal)
```

- [ ] **Step 5: Run state-store and executor tests**

Run:

```bash
uv run --group dev pytest tests/test_execution_state.py tests/test_mt5_execution.py::test_executor_records_active_order_state -q
```

Expected: execution state tests and the executor state integration test pass.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/brokers/execution_state.py tradingagents/brokers/mt5_execution.py tests/test_execution_state.py tests/test_mt5_execution.py
git commit -m "feat: track mt5 demo execution state"
```

---

### Task 8: Broker State Reads

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tests/test_mt5_broker.py`

- [ ] **Step 1: Add fake order and position methods**

Modify `FakeMT5`:

```python
def orders_get(self, symbol=None):
    if symbol == "XAUUSD":
        return [SimpleNamespace(ticket=111222, symbol="XAUUSD", price_open=2450.12)]
    return []


def positions_get(self, symbol=None):
    if symbol == "XAUUSD":
        return [
            SimpleNamespace(
                ticket=333444,
                symbol="XAUUSD",
                type=0,
                price_open=2450.12,
                price_current=2453.12,
                sl=2447.99,
                tp=2456.79,
            )
        ]
    return []
```

- [ ] **Step 2: Write failing state-read tests**

Add:

```python
def test_mt5_broker_reads_open_orders_and_positions():
    fake_mt5 = FakeMT5()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    broker = MT5Broker(config, mt5_module=fake_mt5)
    broker.connect()

    orders = broker.open_orders("XAUUSD")
    positions = broker.open_positions("XAUUSD")

    assert orders[0]["ticket"] == 111222
    assert positions[0]["ticket"] == 333444
    assert positions[0]["side"] == "BUY"
    assert positions[0]["entry_price"] == 2450.12
    assert positions[0]["current_price"] == 2453.12
```

- [ ] **Step 3: Run test and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py::test_mt5_broker_reads_open_orders_and_positions -q
```

Expected: test fails because state-read methods do not exist.

- [ ] **Step 4: Implement state-read methods**

Add to `MT5Broker`:

```python
def open_orders(self, symbol: str) -> list[dict[str, Any]]:
    mt5 = self._module()
    orders = mt5.orders_get(symbol=symbol) or []
    return [_asdict(order) for order in orders]


def open_positions(self, symbol: str) -> list[dict[str, Any]]:
    mt5 = self._module()
    positions = mt5.positions_get(symbol=symbol) or []
    normalized = []
    for position in positions:
        item = _asdict(position)
        position_type = item.get("type")
        if position_type == getattr(mt5, "POSITION_TYPE_BUY", 0):
            side = "BUY"
        elif position_type == getattr(mt5, "POSITION_TYPE_SELL", 1):
            side = "SELL"
        else:
            side = str(item.get("side", "")).upper()
        normalized.append(
            {
                **item,
                "side": side,
                "entry_price": item.get("price_open"),
                "stop_loss": item.get("sl"),
                "take_profit": item.get("tp"),
                "current_price": item.get("price_current"),
            }
        )
    return normalized
```

- [ ] **Step 5: Run broker tests**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py -q
```

Expected: all broker tests pass.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/brokers/mt5.py tests/test_mt5_broker.py
git commit -m "feat: read mt5 broker state"
```

---

### Task 9: Stale Pending Order Cancellation

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing stale-order test**

Add:

```python
def test_executor_cancels_stale_active_pending_order(tmp_path):
    broker = FakeBroker()
    broker.pending_orders = [{"ticket": 111}, {"ticket": 222}]
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    executor = MT5DemoExecutor(config, tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "cancel_after_utc": "2026-05-27T14:00:00+00:00",
        }
    )

    result = executor.cancel_stale_pending_orders(now_utc="2026-05-27T14:01:00+00:00")

    assert result["status"] == "CANCELLED"
    assert broker.cancelled == [111]
```

- [ ] **Step 2: Run test and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_mt5_execution.py::test_executor_cancels_stale_active_pending_order -q
```

Expected: test fails because `cancel_stale_pending_orders()` does not exist.

- [ ] **Step 3: Implement cancellation method**

Add to `MT5DemoExecutor`:

```python
def cancel_stale_pending_orders(self, now_utc: str | None = None) -> dict[str, Any]:
    from datetime import datetime, timezone

    self.broker.connect()
    state = self.state.load()
    ticket = state.get("active_order_ticket")
    if ticket is None:
        return {"status": "NO_ACTIVE_ORDER"}
    current = (
        datetime.fromisoformat(now_utc)
        if now_utc
        else datetime.now(timezone.utc)
    )
    cancel_after = datetime.fromisoformat(state["cancel_after_utc"])
    if current < cancel_after:
        return {"status": "ORDER_STILL_ACTIVE", "ticket": ticket}
    result = self.broker.cancel_order(int(ticket))
    self.state.clear_pending_order()
    self.journal.append("ORDER_CANCELLED", {"ticket": ticket, "result": result})
    return {
        "status": "CANCELLED" if result.get("ok") else "CANCEL_FAILED",
        "ticket": ticket,
        "result": result,
    }
```

- [ ] **Step 4: Run execution tests**

Run:

```bash
uv run --group dev pytest tests/test_mt5_execution.py -q
```

Expected: execution tests pass.

- [ ] **Step 5: Commit**

```bash
git add tradingagents/brokers/mt5_execution.py tests/test_mt5_execution.py
git commit -m "feat: cancel stale mt5 pending orders"
```

---

### Task 10: Position Stop Management

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Extend fake broker**

Add to `FakeBroker`:

```python
def __init__(self):
    self.symbol_info = {
        "name": "XAUUSD",
        "digits": 2,
        "point": 0.01,
        "trade_tick_size": 0.01,
    }
    self.pending_orders = []
    self.positions = []
    self.placed_requests = []
    self.cancelled = []
    self.modified_stops = []


def modify_position_stops(self, position_ticket, stop_loss, take_profit):
    self.modified_stops.append(
        {
            "position_ticket": position_ticket,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }
    )
    return {"ok": True, "position": position_ticket}
```

- [ ] **Step 2: Write failing break-even test**

Add:

```python
def test_executor_moves_stop_to_break_even(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2453.0,
        }
    ]
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    executor = MT5DemoExecutor(config, tmp_path, broker=broker)

    result = executor.manage_open_positions(break_even_threshold_pips=20)

    assert result["status"] == "MANAGED"
    assert broker.modified_stops[0]["position_ticket"] == 333444
    assert broker.modified_stops[0]["stop_loss"] == 2450.0
```

- [ ] **Step 3: Run test and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_mt5_execution.py::test_executor_moves_stop_to_break_even -q
```

Expected: test fails because `manage_open_positions()` does not exist.

- [ ] **Step 4: Implement position management**

Add imports:

```python
from tradingagents.agents.price_action.lifecycle import move_stop_to_break_even
```

Add to `MT5DemoExecutor`:

```python
def manage_open_positions(self, break_even_threshold_pips: float = 20.0) -> dict[str, Any]:
    self.broker.connect()
    positions = self.broker.open_positions(self.config.symbol)
    actions = []
    for position in positions:
        managed = move_stop_to_break_even(position, break_even_threshold_pips)
        if managed.get("management_action") == "MOVE_TO_BREAK_EVEN":
            result = self.broker.modify_position_stops(
                int(position["ticket"]),
                float(managed["stop_loss"]),
                float(position["take_profit"]),
            )
            actions.append({"ticket": position["ticket"], "action": "MOVE_TO_BREAK_EVEN", "result": result})
            self.journal.append("POSITION_STOP_MOVED", actions[-1])
    return {"status": "MANAGED" if actions else "NO_POSITION_ACTION", "actions": actions}
```

- [ ] **Step 5: Run execution tests**

Run:

```bash
uv run --group dev pytest tests/test_mt5_execution.py -q
```

Expected: execution tests pass.

- [ ] **Step 6: Commit**

```bash
git add tradingagents/brokers/mt5_execution.py tests/test_mt5_execution.py
git commit -m "feat: manage mt5 demo stops"
```

---

### Task 11: CLI Commands

**Files:**
- Modify: `cli/main.py`
- Create: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli_mt5_execution.py`:

```python
from typer.testing import CliRunner

from cli.main import app


def test_mt5_demo_execute_requires_proposal_path():
    runner = CliRunner()

    result = runner.invoke(app, ["mt5-demo-execute"])

    assert result.exit_code != 0
    assert "Missing option" in result.output or "required" in result.output.lower()


def test_mt5_demo_monitor_command_exists(monkeypatch):
    runner = CliRunner()

    result = runner.invoke(app, ["mt5-demo-monitor", "--help"])

    assert result.exit_code == 0
    assert "Monitor MT5 demo orders and positions" in result.output
```

- [ ] **Step 2: Run tests and verify failure**

Run:

```bash
uv run --group dev pytest tests/test_cli_mt5_execution.py -q
```

Expected: tests fail because CLI commands do not exist.

- [ ] **Step 3: Implement CLI commands**

Add to `cli/main.py`:

```python
@app.command("mt5-demo-execute")
def mt5_demo_execute(
    proposal_path: Path = typer.Option(
        ...,
        "--proposal",
        exists=True,
        readable=True,
        help="Path to a generated order_proposal_*.json file.",
    ),
):
    """Place a guarded MT5 demo pending order from an order proposal."""
    from tradingagents.brokers.mt5 import MT5BrokerError, MT5ConnectionConfig
    from tradingagents.brokers.mt5_execution import MT5DemoExecutor, load_order_proposal

    try:
        config = MT5ConnectionConfig.from_env()
        proposal = load_order_proposal(proposal_path)
        executor = MT5DemoExecutor(config, DEFAULT_CONFIG["results_dir"])
        result = executor.execute_proposal(proposal)
    except (MT5BrokerError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(json.dumps(result, indent=2, sort_keys=True))


@app.command("mt5-demo-monitor")
def mt5_demo_monitor(
    cancel_stale: bool = typer.Option(
        False,
        "--cancel-stale",
        help="Cancel current pending orders for the configured symbol.",
    ),
    manage_stops: bool = typer.Option(
        False,
        "--manage-stops",
        help="Run break-even stop management for open positions.",
    ),
):
    """Monitor MT5 demo orders and positions."""
    from tradingagents.brokers.mt5 import MT5BrokerError, MT5ConnectionConfig
    from tradingagents.brokers.mt5_execution import MT5DemoExecutor

    try:
        config = MT5ConnectionConfig.from_env()
        executor = MT5DemoExecutor(config, DEFAULT_CONFIG["results_dir"])
        results = {}
        if cancel_stale:
            results["cancel_stale"] = executor.cancel_stale_pending_orders()
        if manage_stops:
            results["manage_stops"] = executor.manage_open_positions()
        if not results:
            results["state"] = executor.snapshot_state()
    except MT5BrokerError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(json.dumps(results, indent=2, sort_keys=True))
```

Add to `MT5DemoExecutor`:

```python
def snapshot_state(self) -> dict[str, Any]:
    connection = self.broker.connect()
    orders = self.broker.open_orders(self.config.symbol)
    positions = self.broker.open_positions(self.config.symbol)
    state = {"connection": connection, "orders": orders, "positions": positions}
    self.journal.append("STATE_SNAPSHOT", state)
    return state
```

- [ ] **Step 4: Run CLI tests**

Run:

```bash
uv run --group dev pytest tests/test_cli_mt5_execution.py -q
```

Expected: CLI tests pass.

- [ ] **Step 5: Commit**

```bash
git add cli/main.py tradingagents/brokers/mt5_execution.py tests/test_cli_mt5_execution.py
git commit -m "feat: add mt5 demo execution cli"
```

---

### Task 12: End-to-End Fake MT5 Flow

**Files:**
- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write full fake-flow test**

Add:

```python
def test_full_fake_mt5_demo_flow_places_cancels_and_manages(tmp_path):
    broker = FakeBroker()
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
    )
    executor = MT5DemoExecutor(config, tmp_path, broker=broker)

    placed = executor.execute_proposal(_proposal())
    broker.pending_orders = [{"ticket": placed["order"], "symbol": "XAUUSD"}]
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": placed["order"],
            "cancel_after_utc": "2026-05-27T14:00:00+00:00",
        }
    )
    cancelled = executor.cancel_stale_pending_orders(now_utc="2026-05-27T14:01:00+00:00")
    broker.pending_orders = []
    broker.positions = [
        {
            "ticket": 333444,
            "symbol": "XAUUSD",
            "side": "BUY",
            "entry_price": 2450.0,
            "stop_loss": 2447.0,
            "take_profit": 2456.0,
            "current_price": 2453.0,
        }
    ]
    managed = executor.manage_open_positions(break_even_threshold_pips=20)

    assert placed["status"] == "PLACED"
    assert cancelled["status"] == "CANCELLED"
    assert managed["status"] == "MANAGED"
    journal = tmp_path / "XAUUSD" / "execution_journal" / "mt5_demo_events.jsonl"
    assert journal.exists()
    assert "ORDER_PLACED" in journal.read_text(encoding="utf-8")
    assert "ORDER_CANCELLED" in journal.read_text(encoding="utf-8")
    assert "POSITION_STOP_MOVED" in journal.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run full fake-flow test**

Run:

```bash
uv run --group dev pytest tests/test_mt5_execution.py::test_full_fake_mt5_demo_flow_places_cancels_and_manages -q
```

Expected: fake end-to-end execution flow passes.

- [ ] **Step 3: Run full broker/execution suite**

Run:

```bash
uv run --group dev pytest tests/test_mt5_broker.py tests/test_mt5_execution.py tests/test_execution_journal.py tests/test_cli_mt5_execution.py -q
```

Expected: all broker and execution tests pass.

- [ ] **Step 4: Commit**

```bash
git add tests/test_mt5_execution.py
git commit -m "test: cover mt5 demo execution flow"
```

---

### Task 13: Documentation and Windows Dry Run Checklist

**Files:**
- Modify: `README.md`
- Modify: `.env.example`

- [ ] **Step 1: Update README with MT5 demo execution flow**

Add:

````markdown
## MT5 Demo Execution

The MT5 execution layer is demo-only by default. It requires a Windows machine
with the MetaTrader 5 desktop terminal installed and logged into the same demo
account configured in `.env`.

Required local environment variables:

```bash
TRADINGAGENTS_MT5_LOGIN=123456789
TRADINGAGENTS_MT5_PASSWORD=your-demo-password
TRADINGAGENTS_MT5_SERVER=YourBroker-Demo
TRADINGAGENTS_MT5_SYMBOL=XAUUSD
TRADINGAGENTS_MT5_ACCOUNT_MODE=demo
TRADINGAGENTS_MT5_EXPECTED_LOGIN=123456789
TRADINGAGENTS_MT5_EXPECTED_SERVER=YourBroker-Demo
TRADINGAGENTS_MT5_VOLUME=0.01
```

Check connectivity without placing orders:

```bash
tradingagents broker-probe
```

Place a guarded pending limit order from a generated proposal:

```bash
tradingagents mt5-demo-execute --proposal ~/.tradingagents/logs/XAUUSD/order_proposals/order_proposal_YYYY_MM_DD_HHMM.json
```

Monitor or manage the configured symbol:

```bash
tradingagents mt5-demo-monitor
tradingagents mt5-demo-monitor --cancel-stale
tradingagents mt5-demo-monitor --manage-stops
```

The bot refuses execution unless the connected account login and server match
the expected demo values.
````

- [ ] **Step 2: Run README-related checks**

Run:

```bash
uv run --group dev pytest tests/test_cli_mt5_execution.py tests/test_mt5_broker.py -q
```

Expected: CLI and broker tests pass after documentation changes.

- [ ] **Step 3: Commit**

```bash
git add README.md .env.example
git commit -m "docs: document mt5 demo execution"
```

---

### Task 14: Final Verification

**Files:**
- No new files.

- [ ] **Step 1: Run complete test suite**

Run:

```bash
uv run --group dev pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Confirm working tree**

Run:

```bash
git status --short --branch
```

Expected: current branch has no uncommitted changes.

- [ ] **Step 3: Push branch**

Run:

```bash
git push
```

Expected: branch updates on GitHub.

---

## Self-Review

- Spec coverage: The plan covers demo-only credentials, account guardrails, symbol validation, request mapping, pending limit placement, stale cancellation, broker state reads, stop management, journaling, CLI commands, tests, docs, and final verification.
- Specificity scan: Each task names concrete files, functions, commands, and expected outcomes.
- Type consistency: `MT5ConnectionConfig`, `MT5Broker`, `MT5OrderRequestBuilder`, `MT5DemoExecutor`, `ExecutionJournal`, and `OrderProposal` names remain consistent across tasks.
