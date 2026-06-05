# 1m/3m Fast Entries And Risk Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add independent 1m/3m entries beside the existing 15m/30m engine, while fixing stale-order cancellation and enforcing gold stop-distance risk guards.

**Architecture:** Keep the existing 15m/30m engine as the normal entry profile. Generalize the deterministic price-action engine so the same breakout, break/retest, and support/resistance bounce logic can run under a fast profile using 1m trigger candles and 3m confirmation context. The runner evaluates both profiles in one process, shares one MT5 executor, and uses broker-state synchronization before cancellation so filled/closed tickets are not repeatedly cancelled.

**Tech Stack:** Python 3.13, Typer CLI, MetaTrader5 Python bridge, Pydantic schemas, pytest.

---

## File Structure

- Modify `tradingagents/brokers/mt5_execution.py`: synchronize tracked pending order tickets against live MT5 orders/positions before attempting cancellation.
- Modify `tradingagents/brokers/execution_state.py`: preserve profile metadata in pending-order state and support clean state clearing after sync.
- Modify `tradingagents/brokers/mt5.py`: add 1m/3m MT5 rate support and enforce minimum stop distance using price distance plus spread multiple.
- Modify `tradingagents/dataflows/data_health.py`: support profile-specific required timeframes and report active trading/confirmation timeframe health.
- Modify `tradingagents/dataflows/mt5_price_action.py`: fetch 1m and 3m candles in addition to existing 15m/30m/1h/1d data.
- Create `tradingagents/agents/price_action/profiles.py`: define normal and fast entry profile configuration.
- Modify `tradingagents/agents/price_action/engine.py`: run the same playbook logic against configurable entry/confirmation timeframes and apply fast-profile counter-bias rules.
- Modify `tradingagents/agents/execution/order_proposal.py`: write profile-specific activation windows into order proposals.
- Modify `tradingagents/default_config.py` and `cli/main.py`: expose fast-entry and risk settings through env overrides.
- Modify `tradingagents/brokers/mt5_runner.py`: support multi-profile analysis results and per-profile processed-candle state.
- Modify `tradingagents/brokers/runner_summary.py`: add profile-aware counts so telemetry distinguishes normal vs fast entries.
- Modify tests:
  - `tests/test_mt5_execution.py`
  - `tests/test_mt5_broker.py`
  - `tests/test_mt5_price_action_dataflow.py`
  - `tests/test_price_action_engine.py`
  - `tests/test_order_proposal.py`
  - `tests/test_env_overrides.py`
  - `tests/test_cli_mt5_execution.py`
  - `tests/test_mt5_runner.py`
  - `tests/test_mt5_runner_summary.py`

---

### Task 1: Fix Stale-Ticket Cancellation Sync

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tradingagents/brokers/execution_state.py`
- Test: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write failing tests for already-filled and already-closed tracked tickets**

Append these tests near the existing cancellation tests in `tests/test_mt5_execution.py`:

```python
def test_executor_clears_state_when_tracked_ticket_is_open_position(tmp_path):
    broker = FakeBroker()
    broker.positions = [{"ticket": 111, "symbol": "XAUUSD"}]
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "cancel_after_utc": "2026-05-27T14:00:00+00:00",
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:00+00:00"
    )

    assert result["status"] == "ORDER_ALREADY_FILLED"
    assert result["ticket"] == 111
    assert broker.cancelled == []
    assert executor.state.load()["active_order_ticket"] is None


def test_executor_clears_state_when_tracked_ticket_is_not_open_anymore(tmp_path):
    broker = FakeBroker()
    executor = MT5Executor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD",
            "active_order_ticket": 111,
            "cancel_after_utc": "2026-05-27T14:00:00+00:00",
        }
    )

    result = executor.cancel_stale_pending_orders(
        now_utc="2026-05-27T14:01:00+00:00"
    )

    assert result["status"] == "ORDER_NOT_OPEN"
    assert result["ticket"] == 111
    assert broker.cancelled == []
    assert executor.state.load()["active_order_ticket"] is None
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_execution.py::test_executor_clears_state_when_tracked_ticket_is_open_position tests/test_mt5_execution.py::test_executor_clears_state_when_tracked_ticket_is_not_open_anymore -q
```

Expected: both tests fail because `cancel_stale_pending_orders()` currently calls `cancel_order()` for stale tickets even when MT5 has no matching open order.

- [ ] **Step 3: Add live ticket sync before cancellation**

In `tradingagents/brokers/mt5_execution.py`, add this private helper inside `MT5Executor`:

```python
    def _sync_tracked_ticket(self, ticket: int) -> dict[str, Any] | None:
        orders = self.broker.open_orders(self.config.symbol)
        positions = self.broker.open_positions(self.config.symbol)
        open_order_tickets = {int(order["ticket"]) for order in orders if order.get("ticket")}
        open_position_tickets = {
            int(position["ticket"]) for position in positions if position.get("ticket")
        }

        if ticket in open_order_tickets:
            return None
        if ticket in open_position_tickets:
            self.state.clear_pending_order()
            result = {
                "status": "ORDER_ALREADY_FILLED",
                "ticket": ticket,
                "symbol": self.config.symbol,
            }
            self.journal.append("ORDER_STATE_SYNCED", result)
            return result

        self.state.clear_pending_order()
        result = {
            "status": "ORDER_NOT_OPEN",
            "ticket": ticket,
            "symbol": self.config.symbol,
        }
        self.journal.append("ORDER_STATE_SYNCED", result)
        return result
```

Then update `cancel_stale_pending_orders()` after loading `ticket`:

```python
        ticket = int(ticket)
        sync_result = self._sync_tracked_ticket(ticket)
        if sync_result is not None:
            return sync_result
```

Keep the existing stale-time check and cancellation path after that block.

- [ ] **Step 4: Run focused cancellation tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_execution.py::test_executor_clears_state_when_tracked_ticket_is_open_position tests/test_mt5_execution.py::test_executor_clears_state_when_tracked_ticket_is_not_open_anymore tests/test_mt5_execution.py::test_executor_cancels_stale_active_pending_order tests/test_mt5_execution.py::test_executor_leaves_non_stale_active_pending_order -q
```

Expected: all selected tests pass.

- [ ] **Step 5: Commit the cancellation sync**

```powershell
git add tradingagents/brokers/mt5_execution.py tests/test_mt5_execution.py
git commit -m "fix: sync stale MT5 order tickets before cancellation"
```

---

### Task 2: Add Gold Stop-Distance Risk Guards

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tradingagents/default_config.py`
- Modify: `cli/main.py`
- Test: `tests/test_mt5_broker.py`
- Test: `tests/test_env_overrides.py`

- [ ] **Step 1: Write failing config tests**

In `tests/test_mt5_broker.py`, add:

```python
def test_mt5_config_reads_min_stop_distance_guards(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_MT5_LOGIN", "123456789")
    monkeypatch.setenv("TRADINGAGENTS_MT5_PASSWORD", "secret")
    monkeypatch.setenv("TRADINGAGENTS_MT5_SERVER", "ExampleBroker-Demo")
    monkeypatch.setenv("TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE", "2.5")
    monkeypatch.setenv("TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE", "4")

    config = MT5ConnectionConfig.from_env()

    assert config.min_stop_distance_price == 2.5
    assert config.min_stop_spread_multiple == 4.0
```

In `tests/test_env_overrides.py`, add:

```python
def test_fast_risk_env_updates_price_action_config(monkeypatch):
    dc = _reload_with_env(
        monkeypatch,
        TRADINGAGENTS_FAST_ENTRIES_ENABLED="true",
        TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE="2.5",
        TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE="4",
    )

    assert dc.DEFAULT_CONFIG["fast_entries_enabled"] is True
    assert dc.DEFAULT_CONFIG["minimum_stop_distance_price"] == 2.5
    assert dc.DEFAULT_CONFIG["minimum_stop_spread_multiple"] == 4.0
    assert dc.DEFAULT_CONFIG["price_action"]["minimum_stop_distance_price"] == 2.5
    assert dc.DEFAULT_CONFIG["price_action"]["minimum_stop_spread_multiple"] == 4.0
```

- [ ] **Step 2: Run config tests and verify they fail**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_broker.py::test_mt5_config_reads_min_stop_distance_guards tests/test_env_overrides.py::test_fast_risk_env_updates_price_action_config -q
```

Expected: fail because config fields and env overrides do not exist yet.

- [ ] **Step 3: Add config fields and env overrides**

In `tradingagents/brokers/mt5.py`, update `MT5ConnectionConfig`:

```python
    min_stop_distance_price: float = 2.5
    min_stop_spread_multiple: float = 4.0
```

Inside `__post_init__`, after `max_entry_distance_points`, add:

```python
        for attr, label in (
            ("min_stop_distance_price", "MT5 minimum stop distance price"),
            ("min_stop_spread_multiple", "MT5 minimum stop spread multiple"),
        ):
            try:
                value = float(getattr(self, attr))
            except (TypeError, ValueError) as exc:
                raise MT5BrokerError(f"{label} must be numeric") from exc
            if not math.isfinite(value) or value < 0:
                raise MT5BrokerError(f"{label} must be non-negative")
            object.__setattr__(self, attr, value)
```

Inside `from_env()`, pass:

```python
            min_stop_distance_price=_float_env(
                "TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE",
                2.5,
            ),
            min_stop_spread_multiple=_float_env(
                "TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE",
                4.0,
            ),
```

In `tradingagents/default_config.py`, add env overrides:

```python
    "TRADINGAGENTS_FAST_ENTRIES_ENABLED": "fast_entries_enabled",
    "TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE": "minimum_stop_distance_price",
    "TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE": "minimum_stop_spread_multiple",
```

Add defaults:

```python
    "fast_entries_enabled": False,
    "minimum_stop_distance_price": 2.5,
    "minimum_stop_spread_multiple": 4.0,
```

After the existing `DEFAULT_CONFIG["price_action"]` assignments, add:

```python
DEFAULT_CONFIG["price_action"]["minimum_stop_distance_price"] = DEFAULT_CONFIG[
    "minimum_stop_distance_price"
]
DEFAULT_CONFIG["price_action"]["minimum_stop_spread_multiple"] = DEFAULT_CONFIG[
    "minimum_stop_spread_multiple"
]
```

Mirror the same env overrides and nested `price_action` assignments in `cli/main.py` inside `_load_runtime_env()`.

- [ ] **Step 4: Write failing builder test for too-tight stop**

In `tests/test_mt5_broker.py`, add:

```python
def test_mt5_request_builder_rejects_stop_distance_below_gold_guard():
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        min_stop_distance_price=2.5,
        min_stop_spread_multiple=4.0,
    )
    proposal = OrderProposal(
        symbol="XAUUSD",
        broker_symbol="XAUUSD",
        side=TradeAction.BUY,
        order_type="AUTO",
        entry_price=4460.87,
        stop_loss=4460.35,
        take_profit=4462.42,
        valid_until="2026-06-03 06:30 EDT",
        status=OrderStatus.PROPOSED,
        reason="too tight stop",
    )

    with pytest.raises(ValueError, match="stop distance is below minimum"):
        MT5OrderRequestBuilder(config).build_pending_order_request(
            proposal,
            {
                "name": "XAUUSD",
                "digits": 2,
                "point": 0.01,
                "trade_tick_size": 0.01,
                "trade_stops_level": 1,
                "bid": 4460.50,
                "ask": 4460.83,
            },
        )
```

- [ ] **Step 5: Add stop-distance validation in request builder**

In `tradingagents/brokers/mt5.py`, add this method to `MT5OrderRequestBuilder`:

```python
    def _assert_stop_distance(
        self,
        entry: float,
        stop: float,
        symbol_info: dict[str, Any],
    ) -> None:
        minimum = float(self.config.min_stop_distance_price)
        if symbol_info.get("bid") not in (None, "") and symbol_info.get("ask") not in (None, ""):
            bid, ask = self._quote(symbol_info)
            spread_distance = abs(ask - bid) * float(self.config.min_stop_spread_multiple)
            minimum = max(minimum, spread_distance)
        stop_distance = abs(entry - stop)
        if stop_distance < minimum:
            raise ValueError(
                "stop distance is below minimum: "
                f"distance={stop_distance:.2f}, minimum={minimum:.2f}"
            )
```

In `build_pending_order_request()`, after rounding `entry`, `stop`, and `target`, call:

```python
        self._assert_stop_distance(entry, stop, symbol_info)
```

- [ ] **Step 6: Run risk-guard tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_broker.py::test_mt5_config_reads_min_stop_distance_guards tests/test_mt5_broker.py::test_mt5_request_builder_rejects_stop_distance_below_gold_guard tests/test_env_overrides.py::test_fast_risk_env_updates_price_action_config -q
```

Expected: all selected tests pass.

- [ ] **Step 7: Commit risk guards**

```powershell
git add tradingagents/brokers/mt5.py tradingagents/default_config.py cli/main.py tests/test_mt5_broker.py tests/test_env_overrides.py
git commit -m "feat: enforce MT5 stop-distance risk guards"
```

---

### Task 3: Add 1m/3m MT5 Candle Support

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tradingagents/dataflows/data_health.py`
- Modify: `tradingagents/dataflows/mt5_price_action.py`
- Test: `tests/test_mt5_broker.py`
- Test: `tests/test_mt5_price_action_dataflow.py`

- [ ] **Step 1: Write failing timeframe tests**

In `tests/test_mt5_broker.py`, add:

```python
def test_mt5_fetch_rates_supports_one_and_three_minute_timeframes():
    fake_mt5 = FakeMT5Module()
    fake_mt5.copy_rates = [
        {"time": 1780495200, "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "tick_volume": 10}
    ]
    fake_mt5.TIMEFRAME_M1 = 1
    fake_mt5.TIMEFRAME_M3 = 3
    broker = MT5Broker(_config(), mt5_module=fake_mt5)
    broker.connect()

    broker.fetch_rates("1m", 1)
    broker.fetch_rates("3m", 1)

    assert fake_mt5.copy_rates_calls[-2]["timeframe"] == 1
    assert fake_mt5.copy_rates_calls[-1]["timeframe"] == 3
```

In `tests/test_mt5_price_action_dataflow.py`, add:

```python
def test_fetch_mt5_price_action_snapshot_includes_fast_timeframes():
    broker = FakeBroker()

    snapshot = fetch_mt5_price_action_snapshot(
        broker,
        as_of="2026-06-03 08:15",
        market_timezone="America/New_York",
    )

    assert "1m" in snapshot.candles
    assert "3m" in snapshot.candles
    assert snapshot.data_status["timeframes"]["1m"]["available"] is True
    assert snapshot.data_status["timeframes"]["3m"]["available"] is True
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_broker.py::test_mt5_fetch_rates_supports_one_and_three_minute_timeframes tests/test_mt5_price_action_dataflow.py::test_fetch_mt5_price_action_snapshot_includes_fast_timeframes -q
```

Expected: fail because 1m/3m are not supported in `fetch_rates()` or data health.

- [ ] **Step 3: Add 1m/3m rates**

In `tradingagents/brokers/mt5.py`, extend `timeframe_constants` in `fetch_rates()`:

```python
            "1m": getattr(mt5, "TIMEFRAME_M1", None),
            "3m": getattr(mt5, "TIMEFRAME_M3", None),
```

In `tradingagents/dataflows/mt5_price_action.py`, update counts:

```python
MT5_TIMEFRAME_COUNTS = {
    "1d": 260,
    "1h": 1200,
    "30m": 500,
    "15m": 1000,
    "3m": 1200,
    "1m": 1500,
}
```

Update the returned `candles` dict:

```python
    candles = {
        "1d": candles_by_timeframe["1d"],
        "4h": candles_by_timeframe["4h"],
        "1h": candles_by_timeframe["1h"],
        "30m": candles_by_timeframe["30m"],
        "15m": candles_by_timeframe["15m"],
        "3m": candles_by_timeframe["3m"],
        "1m": candles_by_timeframe["1m"],
    }
```

In `tradingagents/dataflows/data_health.py`, add:

```python
    "3m": 15,
    "1m": 5,
```

to `MAX_AGE_MINUTES`, add:

```python
    "3m": 6,
    "1m": 3,
```

to `MAX_FUTURE_DRIFT_MINUTES`, and update `build_data_status()` signature:

```python
def build_data_status(
    timeframe_data: dict[str, list[Any]],
    as_of: str,
    market_timezone: str,
    required_timeframes: tuple[str, ...] = REQUIRED_TIMEFRAMES,
    trading_timeframe: str = "15m",
    confirmation_timeframe: str = "30m",
) -> dict[str, Any]:
```

Loop over `required_timeframes`, and return:

```python
        "trading_timeframe": statuses[trading_timeframe],
        "confirmation_timeframe": statuses[confirmation_timeframe],
```

Call `build_data_status()` from `fetch_mt5_price_action_snapshot()` with:

```python
        required_timeframes=tuple(candles),
        trading_timeframe="15m",
        confirmation_timeframe="30m",
```

- [ ] **Step 4: Run dataflow tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_broker.py::test_mt5_fetch_rates_supports_one_and_three_minute_timeframes tests/test_mt5_price_action_dataflow.py -q
```

Expected: selected tests pass.

- [ ] **Step 5: Commit fast timeframe data support**

```powershell
git add tradingagents/brokers/mt5.py tradingagents/dataflows/data_health.py tradingagents/dataflows/mt5_price_action.py tests/test_mt5_broker.py tests/test_mt5_price_action_dataflow.py
git commit -m "feat: add MT5 one and three minute candles"
```

---

### Task 4: Define Entry Profiles And Activation Windows

**Files:**
- Create: `tradingagents/agents/price_action/profiles.py`
- Modify: `tradingagents/agents/execution/order_proposal.py`
- Modify: `tradingagents/default_config.py`
- Modify: `cli/main.py`
- Test: `tests/test_order_proposal.py`
- Test: `tests/test_env_overrides.py`

- [ ] **Step 1: Write failing profile and activation-window tests**

In `tests/test_order_proposal.py`, add:

```python
def test_engine_order_proposal_uses_fast_profile_activation_window(tmp_path):
    state = {
        "company_of_interest": "XAUUSD.vx",
        "broker_symbol": "XAUUSD.vx",
        "as_of": "2026-06-03 08:15",
        "timeframe": "1m",
        "confirmation_timeframe": "3m",
        "market_timezone": "America/New_York",
        "engine_payload": {
            "status": "SETUP_FOUND",
            "recommendation": "BUY",
            "entry_profile": "fast",
            "activation_window_minutes": 6,
            "message": "Fast A+ setup passed.",
            "setups": [
                {
                    "name": "Breakout",
                    "direction": "BUY",
                    "entry_price": 4460.87,
                    "stop_loss": 4458.37,
                    "take_profit": 4465.87,
                    "setup_grade": "A_PLUS",
                }
            ],
            "risk": {"take_profit": 4465.87},
        },
    }

    proposal_state = create_order_proposal_executor({"results_dir": tmp_path})(state)
    proposal = json.loads(Path(proposal_state["order_proposal_path"]).read_text())

    assert proposal["timeframe"] == "1m"
    assert proposal["confirmation_timeframe"] == "3m"
    assert proposal["activation_window_minutes"] == 6
    assert proposal["cancel_if_not_triggered_after"] == "2026-06-03 08:21 EDT"
```

In `tests/test_env_overrides.py`, extend the new fast env test:

```python
    assert dc.DEFAULT_CONFIG["normal_activation_window_minutes"] == 30
    assert dc.DEFAULT_CONFIG["fast_activation_window_minutes"] == 6
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_order_proposal.py::test_engine_order_proposal_uses_fast_profile_activation_window tests/test_env_overrides.py::test_fast_risk_env_updates_price_action_config -q
```

Expected: fail because profile activation windows are not configured.

- [ ] **Step 3: Create profile definitions**

Create `tradingagents/agents/price_action/profiles.py`:

```python
"""Entry profile configuration for deterministic price-action engines."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EntryProfile:
    name: str
    timeframe: str
    confirmation_timeframe: str
    zone_timeframes: tuple[str, ...]
    activation_window_minutes: int
    independent_direction: bool = False
    counter_bias_minimum_grade: str = "A_PLUS"


def normal_profile(config: dict[str, Any] | None = None) -> EntryProfile:
    cfg = config or {}
    return EntryProfile(
        name="normal",
        timeframe=str(cfg.get("timeframe", "15m")),
        confirmation_timeframe=str(cfg.get("confirmation_timeframe", "30m")),
        zone_timeframes=("1d", "4h", "1h", "30m"),
        activation_window_minutes=int(cfg.get("normal_activation_window_minutes", 30)),
        independent_direction=False,
    )


def fast_profile(config: dict[str, Any] | None = None) -> EntryProfile:
    cfg = config or {}
    return EntryProfile(
        name="fast",
        timeframe=str(cfg.get("fast_timeframe", "1m")),
        confirmation_timeframe=str(cfg.get("fast_confirmation_timeframe", "3m")),
        zone_timeframes=("1d", "4h", "1h", "30m", "15m", "3m"),
        activation_window_minutes=int(cfg.get("fast_activation_window_minutes", 6)),
        independent_direction=True,
        counter_bias_minimum_grade=str(
            cfg.get("fast_counter_bias_minimum_grade", "A_PLUS")
        ),
    )
```

- [ ] **Step 4: Add env defaults and order proposal support**

In `tradingagents/default_config.py` and `cli/main.py`, add env overrides:

```python
    "TRADINGAGENTS_FAST_TIMEFRAME": "fast_timeframe",
    "TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME": "fast_confirmation_timeframe",
    "TRADINGAGENTS_NORMAL_ACTIVATION_WINDOW_MINUTES": "normal_activation_window_minutes",
    "TRADINGAGENTS_FAST_ACTIVATION_WINDOW_MINUTES": "fast_activation_window_minutes",
    "TRADINGAGENTS_FAST_COUNTER_BIAS_MIN_GRADE": "fast_counter_bias_minimum_grade",
```

Add defaults:

```python
    "fast_timeframe": "1m",
    "fast_confirmation_timeframe": "3m",
    "normal_activation_window_minutes": 30,
    "fast_activation_window_minutes": 6,
    "fast_counter_bias_minimum_grade": "A_PLUS",
```

In `tradingagents/agents/execution/order_proposal.py`, change both engine and graph proposal paths so activation windows come from payload/config:

```python
    activation_window_minutes = None
    if status == OrderStatus.PROPOSED:
        activation_window_minutes = int(
            payload.get("activation_window_minutes")
            or state.get("activation_window_minutes")
            or 10
        )
```

For non-engine fallback, use:

```python
    activation_window_minutes = (
        int(config.get("normal_activation_window_minutes", 30))
        if status == OrderStatus.PROPOSED
        else None
    )
```

- [ ] **Step 5: Run profile tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_order_proposal.py::test_engine_order_proposal_uses_fast_profile_activation_window tests/test_env_overrides.py::test_fast_risk_env_updates_price_action_config -q
```

Expected: selected tests pass.

- [ ] **Step 6: Commit profiles and activation windows**

```powershell
git add tradingagents/agents/price_action/profiles.py tradingagents/agents/execution/order_proposal.py tradingagents/default_config.py cli/main.py tests/test_order_proposal.py tests/test_env_overrides.py
git commit -m "feat: add entry profiles and activation windows"
```

---

### Task 5: Generalize The Price-Action Engine For 1m/3m

**Files:**
- Modify: `tradingagents/agents/price_action/engine.py`
- Test: `tests/test_price_action_engine.py`

- [ ] **Step 1: Write failing fast-profile engine tests**

In `tests/test_price_action_engine.py`, add:

```python
def test_engine_can_run_fast_profile_with_one_minute_entries(monkeypatch):
    data = {
        **aligned_buy_setup_data(),
        "3m": candles(
            "2026-06-03 08:06:00,100,103,99,102,1000\n"
            "2026-06-03 08:09:00,102,106,101,105,1000"
        ),
        "1m": candles(
            "2026-06-03 08:10:00,104,105,103,104.5,1000\n"
            "2026-06-03 08:11:00,104.5,106.5,104,106,1000"
        ),
    }
    zone = Zone(
        type="resistance",
        timeframe="3m",
        low=104.0,
        high=105.0,
        midpoint=104.5,
        touches=3,
        score=20.0,
        source="test",
    )
    setup = Setup(
        name="Breakout",
        direction="BUY",
        zone=zone,
        entry_price=106.0,
        stop_loss=103.0,
        confirmation_candle=data["1m"][-1],
    )

    monkeypatch.setattr(engine, "calculate_support_resistance", lambda candles, timeframe: [zone] if timeframe == "3m" else [])
    monkeypatch.setattr(engine, "detect_breakouts", lambda raw_candles, zones: [setup] if raw_candles == data["1m"] else [])
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        engine,
        "nearest_target_zone",
        lambda *_args, **_kwargs: {"midpoint": 112.0},
    )
    monkeypatch.setattr(
        engine,
        "approve_risk",
        lambda *_args, **_kwargs: {
            "approved": True,
            "take_profit": 112.0,
            "risk_distance": 3.0,
            "reward_distance": 6.0,
            "risk_reward": 2.0,
            "available_risk_reward": 2.0,
        },
    )

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-03 08:12",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "zone_timeframes": ("1d", "4h", "1h", "30m", "15m", "3m"),
            "minimum_stop_distance_price": 2.5,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["entry_profile"] == "fast"
    assert payload["timeframe"] == "1m"
    assert payload["confirmation_timeframe"] == "3m"
```

Add a counter-bias rejection test:

```python
def test_fast_engine_requires_a_plus_when_counter_higher_timeframe_bias(monkeypatch):
    data = {
        **aligned_buy_setup_data(),
        "3m": candles(
            "2026-06-03 08:06:00,100,103,99,102,1000\n"
            "2026-06-03 08:09:00,102,106,101,105,1000"
        ),
        "1m": candles(
            "2026-06-03 08:10:00,104,105,103,104.5,1000\n"
            "2026-06-03 08:11:00,104.5,106.5,104,106,1000"
        ),
    }
    zone = Zone("resistance", "3m", 104, 105, 104.5, 3, 20, "test")
    setup = Setup("Breakout", "BUY", zone, 106.0, 103.0, data["1m"][-1])

    monkeypatch.setattr(engine, "calculate_support_resistance", lambda candles, timeframe: [zone])
    monkeypatch.setattr(engine, "detect_breakouts", lambda raw_candles, zones: [setup])
    monkeypatch.setattr(engine, "detect_break_and_retest", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "detect_sr_bounce", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(engine, "nearest_target_zone", lambda *_args, **_kwargs: {"midpoint": 110})
    monkeypatch.setattr(
        engine,
        "approve_risk",
        lambda *_args, **_kwargs: {
            "approved": True,
            "take_profit": 110,
            "risk_distance": 3,
            "reward_distance": 4,
            "risk_reward": 1.33,
            "available_risk_reward": 1.33,
        },
    )

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-03 08:12",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "3m",
            "minimum_setup_grade": "B_PLUS",
            "b_plus_min_rr": 1.2,
            "higher_timeframe_bias": "SELL",
            "fast_counter_bias_minimum_grade": "A_PLUS",
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["telemetry"]["decision_stage"] == "counter_bias_grade_filter"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_price_action_engine.py::test_engine_can_run_fast_profile_with_one_minute_entries tests/test_price_action_engine.py::test_fast_engine_requires_a_plus_when_counter_higher_timeframe_bias -q
```

Expected: fail because the engine is hardcoded to 15m/30m.

- [ ] **Step 3: Generalize engine timeframe variables**

In `tradingagents/agents/price_action/engine.py`, inside `analyze_playbook()`, derive profile settings:

```python
    profile_name = str((session_config or {}).get("entry_profile", "normal"))
    entry_timeframe = str((session_config or {}).get("timeframe", "15m"))
    confirmation_timeframe = str(
        (session_config or {}).get("confirmation_timeframe", "30m")
    )
    zone_timeframes = tuple(
        (session_config or {}).get(
            "zone_timeframes",
            ("1d", "4h", "1h", confirmation_timeframe),
        )
    )
```

Replace hardcoded `m15` with `entry_candles = candles_by_tf.get(entry_timeframe, [])`.
Replace hardcoded `m30` with `confirmation_candles = candles_by_tf.get(confirmation_timeframe, [])`.
Replace fixed `("1d", "4h", "1h", "30m")` zone loop with `zone_timeframes`.
Use `confirmation_zones = zones_by_tf.get(confirmation_timeframe, [])`.

Update `_payload()` to accept `entry_profile`, `timeframe`, `confirmation_timeframe`, and `activation_window_minutes`:

```python
        "entry_profile": entry_profile,
        "timeframe": timeframe,
        "confirmation_timeframe": confirmation_timeframe,
        "activation_window_minutes": activation_window_minutes,
```

Pass these values from every `_payload()` call.

- [ ] **Step 4: Add minimum stop distance and counter-bias filtering**

Inside candidate evaluation, after risk approval:

```python
        minimum_stop_distance = float(
            (session_config or {}).get("minimum_stop_distance_price", 0.0)
        )
        stop_distance = abs(float(setup.entry_price) - float(setup.stop_loss))
        if minimum_stop_distance and stop_distance < minimum_stop_distance:
            candidate_checklist["clean_range_to_fill"] = FAIL
            b_plus_risk = {
                **b_plus_risk,
                "approved": False,
                "reason": (
                    "Stop distance is below minimum: "
                    f"distance={stop_distance:.2f}, minimum={minimum_stop_distance:.2f}"
                ),
            }
```

After `setup_grade` is calculated, apply the fast counter-bias rule:

```python
        higher_timeframe_bias = str(
            (session_config or {}).get("higher_timeframe_bias") or ""
        ).upper()
        is_counter_bias = (
            profile_name == "fast"
            and higher_timeframe_bias in {"BUY", "SELL"}
            and setup.direction != higher_timeframe_bias
        )
        if is_counter_bias and _setup_grade_rank(setup_grade) < _setup_grade_rank(
            (session_config or {}).get("fast_counter_bias_minimum_grade", "A_PLUS")
        ):
            approved = False
            rejection_reason = "Fast counter-bias setup requires A_PLUS grade."
```

If the best rejected candidate failed only from counter-bias grade, return telemetry stage `counter_bias_grade_filter`.

- [ ] **Step 5: Run engine tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_price_action_engine.py tests/test_engine_decision.py -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit generalized engine**

```powershell
git add tradingagents/agents/price_action/engine.py tests/test_price_action_engine.py
git commit -m "feat: generalize price-action engine for fast entries"
```

---

### Task 6: Run Normal And Fast Profiles In One MT5 Runner

**Files:**
- Modify: `tradingagents/brokers/mt5_runner.py`
- Modify: `cli/main.py`
- Test: `tests/test_mt5_runner.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write failing multi-profile runner tests**

In `tests/test_mt5_runner.py`, add:

```python
def test_runner_executes_first_proposed_profile_and_marks_each_profile(tmp_path):
    normal_no_trade = proposed_order()
    normal_no_trade.status = OrderStatus.NO_TRADE
    fast_order = proposed_order()
    fast_order.timeframe = "1m"
    fast_order.confirmation_timeframe = "3m"

    executor = FakeExecutor(active=False)
    runner = MT5Runner(
        MT5RunnerConfig(results_dir=tmp_path, poll_seconds=5, max_cycles=1),
        executor=executor,
        analysis_func=lambda: [
            ("normal", "2026-06-03 08:15", normal_no_trade, {"entry_profile": "normal"}),
            ("fast", "2026-06-03 08:16", fast_order, {"entry_profile": "fast"}),
        ],
    )

    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert result["entry_profile"] == "fast"
    assert len(executor.executed) == 1
    assert runner._load_state()["last_processed_by_profile"]["normal"] == "2026-06-03 08:15"
    assert runner._load_state()["last_processed_by_profile"]["fast"] == "2026-06-03 08:16"
```

In `tests/test_cli_mt5_execution.py`, add:

```python
def test_mt5_runner_engine_analysis_func_returns_fast_and_normal_profiles(monkeypatch, tmp_path):
    from tradingagents.agents.price_action import decision

    calls = []
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "results_dir", tmp_path)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_entries_enabled", True)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_timeframe", "1m")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "fast_confirmation_timeframe", "3m")
    monkeypatch.setattr(
        cli_main,
        "build_env_selections",
        lambda as_of=None: {
            "ticker": "XAUUSD.vx",
            "broker_symbol": "XAUUSD.vx",
            "as_of": as_of or "2026-06-03 08:15",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "market_timezone": "America/New_York",
        },
    )

    def fake_run_engine_decision(**kwargs):
        calls.append(kwargs)
        return {
            "company_of_interest": kwargs["symbol"],
            "broker_symbol": kwargs["broker_symbol"],
            "as_of": kwargs["as_of"],
            "timeframe": kwargs["timeframe"],
            "confirmation_timeframe": kwargs["confirmation_timeframe"],
            "market_timezone": kwargs["market_timezone"],
            "price_action_report": "Action: HOLD",
            "trade_plan": "Action: HOLD",
            "telemetry_path": str(tmp_path / "payload.json"),
            "engine_payload": {
                "status": "NO_SETUP",
                "recommendation": "HOLD",
                "message": "No setup.",
                "telemetry": {"decision_stage": "no_m15_setup"},
                "data_status": {"healthy": True},
            },
        }

    monkeypatch.setattr(decision, "run_engine_decision", fake_run_engine_decision)

    results = cli_main._mt5_runner_engine_analysis_func(object())()

    assert len(results) == 2
    assert results[0][0] == "normal"
    assert results[1][0] == "fast"
    assert calls[0]["timeframe"] == "15m"
    assert calls[1]["timeframe"] == "1m"
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner.py::test_runner_executes_first_proposed_profile_and_marks_each_profile tests/test_cli_mt5_execution.py::test_mt5_runner_engine_analysis_func_returns_fast_and_normal_profiles -q
```

Expected: fail because runner only handles one tuple.

- [ ] **Step 3: Add list-result support to runner**

In `tradingagents/brokers/mt5_runner.py`, add a parser that accepts existing tuple results and new profile rows:

```python
    def _parse_analysis_results(self, result) -> list[tuple[str, str, OrderProposal, dict]]:
        if isinstance(result, list):
            rows = []
            for item in result:
                if len(item) == 4:
                    profile, as_of, proposal, analysis = item
                    rows.append((str(profile), as_of, proposal, dict(analysis or {})))
                else:
                    as_of, proposal, analysis = self._parse_analysis_result(item)
                    rows.append(("normal", as_of, proposal, analysis))
            return rows
        as_of, proposal, analysis = self._parse_analysis_result(result)
        return [("normal", as_of, proposal, analysis)]
```

Update `_load_state()` expected shape:

```python
        return {
            "last_processed_by_profile": {},
            **json.loads(self.state_path.read_text(encoding="utf-8")),
        }
```

In `run_once()`, replace the single analysis result section with:

```python
        try:
            analysis_rows = self._parse_analysis_results(self.analysis_func())
        except Exception as exc:
            return self._write_heartbeat({...})

        last_processed = dict(state.get("last_processed_by_profile") or {})
        processed_rows = []
        selected = None
        for profile, as_of, proposal, analysis in analysis_rows:
            if last_processed.get(profile) == as_of:
                continue
            status = str(getattr(proposal.status, "value", proposal.status)).upper()
            processed_rows.append((profile, as_of, proposal, analysis, status))
            last_processed[profile] = as_of
            if selected is None and status == "PROPOSED":
                selected = (profile, as_of, proposal, analysis)

        self._save_state({"last_processed_by_profile": last_processed})
        if selected is None:
            return self._write_heartbeat(
                {
                    "status": "NO_TRADE" if processed_rows else "CANDLE_ALREADY_PROCESSED",
                    "started_at_utc": started_at,
                    "profiles": [
                        {
                            "entry_profile": profile,
                            "as_of": as_of,
                            "proposal": proposal.model_dump(mode="json"),
                            "analysis": analysis,
                            "status": status,
                        }
                        for profile, as_of, proposal, analysis, status in processed_rows
                    ],
                }
            )

        profile, as_of, proposal, analysis = selected
        execution = self.executor.execute_proposal(proposal)
        return self._write_heartbeat(
            {
                "status": "ORDER_PLACED" if execution.get("status") == "PLACED" else "ORDER_NOT_PLACED",
                "started_at_utc": started_at,
                "entry_profile": profile,
                "as_of": as_of,
                "proposal": proposal.model_dump(mode="json"),
                "execution": execution,
                "analysis": analysis,
            }
        )
```

Keep backward compatibility for old two- and three-item tuples.

- [ ] **Step 4: Add normal and fast analysis rows in CLI**

In `cli/main.py`, import profiles in `_mt5_runner_engine_analysis_func()`:

```python
        from tradingagents.agents.price_action.profiles import fast_profile, normal_profile
```

Build profile list:

```python
        profiles = [normal_profile(DEFAULT_CONFIG)]
        if DEFAULT_CONFIG.get("fast_entries_enabled"):
            profiles.append(fast_profile(DEFAULT_CONFIG))
```

For each profile:

```python
            profile_config = {
                **DEFAULT_CONFIG.get("price_action", {}),
                "entry_profile": profile.name,
                "timeframe": profile.timeframe,
                "confirmation_timeframe": profile.confirmation_timeframe,
                "zone_timeframes": profile.zone_timeframes,
                "fast_counter_bias_minimum_grade": profile.counter_bias_minimum_grade,
            }
            profile_as_of = last_closed_candle(
                profile.timeframe,
                selections.get("market_timezone", DEFAULT_CONFIG["market_timezone"]),
            )
```

Call `run_engine_decision()` with profile timeframe and config, then return:

```python
            rows.append((profile.name, profile_as_of, proposal, analysis))
```

For backward compatibility, if fast entries are disabled, return the existing single tuple instead of a list.

- [ ] **Step 5: Run runner and CLI tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner.py tests/test_cli_mt5_execution.py -q
```

Expected: selected test files pass.

- [ ] **Step 6: Commit multi-profile runner**

```powershell
git add tradingagents/brokers/mt5_runner.py cli/main.py tests/test_mt5_runner.py tests/test_cli_mt5_execution.py
git commit -m "feat: run normal and fast MT5 entry profiles"
```

---

### Task 7: Add Profile-Aware Telemetry Summary

**Files:**
- Modify: `tradingagents/brokers/runner_summary.py`
- Test: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Write failing summary test**

In `tests/test_mt5_runner_summary.py`, add:

```python
def test_runner_summary_counts_statuses_by_entry_profile(tmp_path):
    store = RunnerSummaryStore(tmp_path)

    store.record_cycle(
        {
            "status": "ORDER_PLACED",
            "entry_profile": "fast",
            "as_of": "2026-06-03 08:16",
            "execution": {"status": "PLACED", "order": 1},
            "analysis": {"telemetry": {"decision_stage": "setup_found"}},
        }
    )
    summary = store.record_cycle(
        {
            "status": "NO_TRADE",
            "profiles": [
                {
                    "entry_profile": "normal",
                    "as_of": "2026-06-03 08:15",
                    "status": "NO_TRADE",
                    "analysis": {
                        "telemetry": {
                            "decision_stage": "no_m15_setup",
                            "primary_hold_reason": "No valid M15 setup.",
                        }
                    },
                }
            ],
        }
    )

    assert summary["profile_status_counts"]["fast"]["ORDER_PLACED"] == 1
    assert summary["profile_status_counts"]["normal"]["NO_TRADE"] == 1
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner_summary.py::test_runner_summary_counts_statuses_by_entry_profile -q
```

Expected: fail because summary does not track profile counts.

- [ ] **Step 3: Add profile counts**

In `tradingagents/brokers/runner_summary.py`, when initializing summary, add:

```python
            "profile_status_counts": {},
```

Add helper:

```python
    def _record_profile_status(self, summary: dict, profile: str, status: str) -> None:
        counts = summary.setdefault("profile_status_counts", {}).setdefault(profile, {})
        counts[status] = counts.get(status, 0) + 1
```

Inside `record_cycle()`, call it for direct profile payloads:

```python
        if payload.get("entry_profile"):
            self._record_profile_status(
                summary,
                str(payload["entry_profile"]),
                status,
            )
```

Also call it for `payload.get("profiles", [])`:

```python
        for profile_row in payload.get("profiles", []):
            self._record_profile_status(
                summary,
                str(profile_row.get("entry_profile", "normal")),
                str(profile_row.get("status", "UNKNOWN")),
            )
```

- [ ] **Step 4: Run summary tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_runner_summary.py -q
```

Expected: tests pass.

- [ ] **Step 5: Commit summary telemetry**

```powershell
git add tradingagents/brokers/runner_summary.py tests/test_mt5_runner_summary.py
git commit -m "feat: summarize MT5 runner status by entry profile"
```

---

### Task 8: End-To-End Verification And Demo Restart

**Files:**
- Modify: `.env` only if the user wants the runner restarted immediately.
- Verify: test suite and one dry `mt5-run --once` cycle.

- [ ] **Step 1: Run focused automated tests**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\python.exe -m pytest tests/test_mt5_execution.py tests/test_mt5_broker.py tests/test_mt5_price_action_dataflow.py tests/test_price_action_engine.py tests/test_order_proposal.py tests/test_env_overrides.py tests/test_cli_mt5_execution.py tests/test_mt5_runner.py tests/test_mt5_runner_summary.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run one MT5 engine cycle without starting overnight runner**

Run:

```powershell
C:\Users\Administrator\Desktop\trade\.venv\Scripts\tradingagents.exe mt5-run --once --decision-mode engine
```

Expected: command exits with JSON. The JSON contains either direct `entry_profile` on an order event or `profiles` with both `normal` and `fast` rows when no trade is placed.

- [ ] **Step 3: Update runtime `.env` for the next fresh session**

Set or confirm these values in `C:\Users\Administrator\Desktop\trade\.env`:

```text
TRADINGAGENTS_RESULTS_DIR=C:\Users\Administrator\.tradingagents\sessions\2026-06-03-fast-entries-risk-controls
TRADINGAGENTS_ANALYSIS_SYMBOL=XAUUSD.vx
TRADINGAGENTS_BROKER_SYMBOL=XAUUSD.vx
TRADINGAGENTS_MT5_SYMBOL=XAUUSD.vx
TRADINGAGENTS_FAST_ENTRIES_ENABLED=true
TRADINGAGENTS_FAST_TIMEFRAME=1m
TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME=3m
TRADINGAGENTS_NORMAL_ACTIVATION_WINDOW_MINUTES=30
TRADINGAGENTS_FAST_ACTIVATION_WINDOW_MINUTES=6
TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE=2.50
TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE=4
TRADINGAGENTS_MIN_SETUP_GRADE=B_PLUS
TRADINGAGENTS_B_PLUS_MIN_RR=1.2
```

- [ ] **Step 4: Start the fresh runner**

Run:

```powershell
Start-Process -FilePath 'C:\Users\Administrator\Desktop\trade\.venv\Scripts\tradingagents.exe' -ArgumentList @('mt5-run', '--decision-mode', 'engine') -WorkingDirectory 'C:\Users\Administrator\Desktop\trade' -WindowStyle Hidden
```

Expected: one `tradingagents.exe` runner process remains active, and the new session writes `mt5_runner\heartbeat.json` plus profile-aware summary telemetry.

- [ ] **Step 5: Commit final config-safe code changes**

Do not commit `.env`. Commit any remaining source/test changes:

```powershell
git status --short
git add tradingagents tests cli docs
git commit -m "feat: add fast MT5 entries with risk controls"
```

---

## Self-Review

- Spec coverage: the plan covers independent 1m/3m entries, preservation of 15m/30m entries, A+/B+ grading reuse, stricter counter-bias behavior, gold stop-distance risk guards, activation windows, stale-ticket cancellation sync, telemetry separation, verification, and fresh-run setup.
- Placeholder scan: no placeholder tasks are left; every task includes file paths, test examples, implementation snippets, commands, and expected outcomes.
- Type consistency: profile names are strings (`normal`, `fast`), runner multi-profile rows use `(profile, as_of, proposal, analysis)`, order proposals keep existing `OrderProposal` schema fields, and config keys are consistent across `default_config.py`, `cli/main.py`, and tests.
