# MT5 Native Analysis Feed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Feed the live MT5 runner with `XAUUSD.vx` candles from MetaTrader 5 instead of `GC=F` Yahoo candles, and block order proposals whose entries are too far from the live MT5 quote.

**Architecture:** Add an MT5 candle adapter that returns the existing `PriceActionSnapshot` shape, then inject that snapshot into `run_engine_decision` only for `mt5-run --decision-mode engine`. Keep the normal research/reporting dataflow unchanged. Add an execution-side distance guard so a future feed mismatch cannot place far-away pending orders.

**Tech Stack:** Python, pytest, MetaTrader5 Python bridge, existing deterministic price-action engine, existing MT5 broker/executor classes

---

## File Structure

- Modify `tradingagents/brokers/mt5.py`: add timeframe constants, rate normalization, and `MT5Broker.fetch_rates`.
- Create `tradingagents/dataflows/mt5_price_action.py`: build the engine's `PriceActionSnapshot` from MT5 candles and derive 4h candles from 1h data.
- Modify `tradingagents/agents/price_action/decision.py`: allow callers to pass a prebuilt snapshot while keeping the current Yahoo path as the default.
- Modify `cli/main.py`: wire `mt5-run --decision-mode engine` to use MT5-native candles and pass the broker symbol as the engine symbol.
- Modify `tradingagents/brokers/mt5_execution.py`: keep proposal execution unchanged, but surface the new distance guard result as `SKIPPED_INVALID_ENTRY`.
- Modify `.env`: set the live analysis symbol to `XAUUSD.vx` and add a maximum entry-distance setting for the next run.
- Test `tests/test_mt5_broker.py`: cover MT5 rate fetching and normalization.
- Test `tests/test_mt5_price_action_dataflow.py`: cover MT5 snapshot construction and 4h derivation.
- Test `tests/test_engine_decision.py`: cover snapshot injection into `run_engine_decision`.
- Test `tests/test_cli_mt5_execution.py`: cover live runner wiring.
- Test `tests/test_mt5_execution.py`: cover the price-distance guard.

### Task 1: Add MT5 rate fetching to the broker

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tests/test_mt5_broker.py`

- [ ] **Step 1: Write the failing broker test**

Add this test to `tests/test_mt5_broker.py`:

```python
def test_mt5_broker_fetch_rates_normalizes_mt5_candles():
    fake = FakeMT5()
    fake.rates = [
        {
            "time": 1779613200,
            "open": 4500.10,
            "high": 4501.20,
            "low": 4499.50,
            "close": 4500.80,
            "tick_volume": 123,
        },
        {
            "time": 1779614100,
            "open": 4500.80,
            "high": 4502.00,
            "low": 4500.40,
            "close": 4501.60,
            "tick_volume": 140,
        },
    ]
    broker = MT5Broker(
        MT5ConnectionConfig(
            login=123456789,
            password="secret",
            server="ExampleBroker-Demo",
            symbol="XAUUSD",
        ),
        mt5_module=fake,
    )
    broker.connect()

    candles = broker.fetch_rates("15m", count=2)

    assert fake.copy_rates_calls == [("XAUUSD", fake.TIMEFRAME_M15, 0, 2)]
    assert candles == [
        {
            "timestamp": "2026-05-24T09:00:00+00:00",
            "open": 4500.10,
            "high": 4501.20,
            "low": 4499.50,
            "close": 4500.80,
            "volume": 123.0,
        },
        {
            "timestamp": "2026-05-24T09:15:00+00:00",
            "open": 4500.80,
            "high": 4502.00,
            "low": 4500.40,
            "close": 4501.60,
            "volume": 140.0,
        },
    ]
```

Also add these fields and method to `FakeMT5` in the same test file:

```python
TIMEFRAME_M15 = 15
TIMEFRAME_M30 = 30
TIMEFRAME_H1 = 60
TIMEFRAME_D1 = 1440

def copy_rates_from_pos(self, symbol, timeframe, start_pos, count):
    self.copy_rates_calls.append((symbol, timeframe, start_pos, count))
    return self.rates
```

Initialize these attributes in `FakeMT5.__init__`:

```python
self.rates = []
self.copy_rates_calls = []
```

- [ ] **Step 2: Run the broker test and confirm it fails**

Run:

```powershell
python -m uv run --group dev pytest tests/test_mt5_broker.py::test_mt5_broker_fetch_rates_normalizes_mt5_candles -q
```

Expected: failure because `MT5Broker.fetch_rates` does not exist.

- [ ] **Step 3: Implement MT5 timeframe and rate normalization**

In `tradingagents/brokers/mt5.py`, add imports:

```python
from datetime import datetime, timezone
```

Add this method inside `MT5Broker`:

```python
    def fetch_rates(self, timeframe: str, count: int) -> list[dict[str, Any]]:
        """Fetch normalized OHLCV candles for the configured MT5 symbol."""
        self._assert_active_session()
        if count <= 0:
            raise MT5BrokerError("MT5 rate count must be positive")

        mt5 = self._module()
        timeframe_constants = {
            "15m": getattr(mt5, "TIMEFRAME_M15", None),
            "30m": getattr(mt5, "TIMEFRAME_M30", None),
            "1h": getattr(mt5, "TIMEFRAME_H1", None),
            "1d": getattr(mt5, "TIMEFRAME_D1", None),
        }
        mt5_timeframe = timeframe_constants.get(timeframe)
        if mt5_timeframe is None:
            raise MT5BrokerError(f"unsupported MT5 timeframe: {timeframe}")

        rates = mt5.copy_rates_from_pos(self.config.symbol, mt5_timeframe, 0, count)
        if rates is None:
            raise MT5BrokerError(f"MT5 copy_rates_from_pos failed: {mt5.last_error()}")

        candles: list[dict[str, Any]] = []
        for rate in rates:
            item = _asdict(rate) or dict(rate)
            candles.append(
                {
                    "timestamp": datetime.fromtimestamp(
                        int(item["time"]),
                        tz=timezone.utc,
                    ).isoformat(),
                    "open": float(item["open"]),
                    "high": float(item["high"]),
                    "low": float(item["low"]),
                    "close": float(item["close"]),
                    "volume": float(item.get("tick_volume", item.get("real_volume", 0))),
                }
            )
        return candles
```

- [ ] **Step 4: Run the broker test and confirm it passes**

Run:

```powershell
python -m uv run --group dev pytest tests/test_mt5_broker.py::test_mt5_broker_fetch_rates_normalizes_mt5_candles -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit Task 1**

Run:

```powershell
git add tradingagents/brokers/mt5.py tests/test_mt5_broker.py
git commit -m "feat: fetch mt5 candle rates"
```

### Task 2: Build an MT5 price-action snapshot adapter

**Files:**
- Create: `tradingagents/dataflows/mt5_price_action.py`
- Create: `tests/test_mt5_price_action_dataflow.py`

- [ ] **Step 1: Write the failing snapshot test**

Create `tests/test_mt5_price_action_dataflow.py`:

```python
from tradingagents.agents.price_action.models import Candle
from tradingagents.dataflows.mt5_price_action import fetch_mt5_price_action_snapshot


class FakeBroker:
    def __init__(self):
        self.calls = []

    def fetch_rates(self, timeframe, count):
        self.calls.append((timeframe, count))
        return [
            {
                "timestamp": "2026-06-02T19:00:00+00:00",
                "open": 4500.0,
                "high": 4501.0,
                "low": 4499.0,
                "close": 4500.5,
                "volume": 100.0,
            },
            {
                "timestamp": "2026-06-02T19:15:00+00:00",
                "open": 4500.5,
                "high": 4502.0,
                "low": 4500.0,
                "close": 4501.5,
                "volume": 120.0,
            },
        ]


def test_fetch_mt5_price_action_snapshot_uses_existing_shape():
    broker = FakeBroker()

    snapshot = fetch_mt5_price_action_snapshot(
        broker,
        as_of="2026-06-02T19:16:00-04:00",
        market_timezone="America/New_York",
    )

    assert broker.calls == [
        ("1d", 260),
        ("1h", 1200),
        ("30m", 500),
        ("15m", 1000),
    ]
    assert set(snapshot.candles) == {"1d", "4h", "1h", "30m", "15m"}
    assert isinstance(snapshot.candles["15m"][0], Candle)
    assert snapshot.data_status["timeframes"]["15m"]["rows"] == 2
```

- [ ] **Step 2: Run the snapshot test and confirm it fails**

Run:

```powershell
python -m uv run --group dev pytest tests/test_mt5_price_action_dataflow.py -q
```

Expected: import failure because `tradingagents.dataflows.mt5_price_action` does not exist.

- [ ] **Step 3: Implement the MT5 snapshot adapter**

Create `tradingagents/dataflows/mt5_price_action.py`:

```python
"""MT5-backed price-action data fetching helpers."""

from __future__ import annotations

from typing import Any

from tradingagents.agents.price_action.candles import resample_candles
from tradingagents.agents.price_action.models import Candle
from tradingagents.dataflows.data_health import build_data_status
from tradingagents.dataflows.price_action import PriceActionSnapshot


MT5_TIMEFRAME_COUNTS = {
    "1d": 260,
    "1h": 1200,
    "30m": 500,
    "15m": 1000,
}


def _to_candle(row: dict[str, Any]) -> Candle:
    return Candle(
        timestamp=str(row["timestamp"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0)),
    )


def fetch_mt5_price_action_snapshot(
    broker: Any,
    *,
    as_of: str,
    market_timezone: str = "America/New_York",
) -> PriceActionSnapshot:
    candles_by_timeframe = {
        timeframe: [_to_candle(row) for row in broker.fetch_rates(timeframe, count)]
        for timeframe, count in MT5_TIMEFRAME_COUNTS.items()
    }
    candles_by_timeframe["4h"] = resample_candles(candles_by_timeframe["1h"], "4h")

    candles = {
        "1d": candles_by_timeframe["1d"],
        "4h": candles_by_timeframe["4h"],
        "1h": candles_by_timeframe["1h"],
        "30m": candles_by_timeframe["30m"],
        "15m": candles_by_timeframe["15m"],
    }
    return PriceActionSnapshot(
        candles=candles,
        data_status=build_data_status(candles, as_of, market_timezone),
    )
```

- [ ] **Step 4: Run the snapshot test and confirm it passes**

Run:

```powershell
python -m uv run --group dev pytest tests/test_mt5_price_action_dataflow.py -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit Task 2**

Run:

```powershell
git add tradingagents/dataflows/mt5_price_action.py tests/test_mt5_price_action_dataflow.py
git commit -m "feat: build mt5 price action snapshot"
```

### Task 3: Allow the deterministic engine to use an injected snapshot

**Files:**
- Modify: `tradingagents/agents/price_action/decision.py`
- Modify: `tests/test_engine_decision.py`

- [ ] **Step 1: Write the failing decision test**

Add this test to `tests/test_engine_decision.py`:

```python
from tradingagents.dataflows.price_action import PriceActionSnapshot


def test_run_engine_decision_accepts_prebuilt_snapshot(tmp_path):
    candles = {
        timeframe: [
            Candle(
                timestamp="2026-06-02T19:00:00-04:00",
                open=4500.0,
                high=4502.0,
                low=4499.0,
                close=4501.0,
                volume=100.0,
            )
            for _ in range(20)
        ]
        for timeframe in ("1d", "4h", "1h", "30m", "15m")
    }
    snapshot = PriceActionSnapshot(
        candles=candles,
        data_status={
            "healthy": False,
            "blocking_timeframes": ["15m"],
            "timeframes": {
                timeframe: {"rows": len(rows), "status": "stale"}
                for timeframe, rows in candles.items()
            },
        },
    )

    state = run_engine_decision(
        "XAUUSD.vx",
        broker_symbol="XAUUSD.vx",
        as_of="2026-06-02T19:16:00-04:00",
        results_dir=tmp_path,
        snapshot=snapshot,
    )

    assert state["company_of_interest"] == "XAUUSD.vx"
    assert state["broker_symbol"] == "XAUUSD.vx"
    assert state["data_status"]["blocking_timeframes"] == ["15m"]
```

- [ ] **Step 2: Run the decision test and confirm it fails**

Run:

```powershell
python -m uv run --group dev pytest tests/test_engine_decision.py::test_run_engine_decision_accepts_prebuilt_snapshot -q
```

Expected: failure because `run_engine_decision` does not accept `snapshot`.

- [ ] **Step 3: Add the snapshot parameter**

In `tradingagents/agents/price_action/decision.py`, change the signature:

```python
def run_engine_decision(
    symbol: str,
    *,
    broker_symbol: str | None,
    as_of: str,
    results_dir: str | Path,
    timeframe: str = "15m",
    confirmation_timeframe: str = "30m",
    market_timezone: str = "America/New_York",
    session_config: dict[str, Any] | None = None,
    snapshot: Any | None = None,
) -> dict[str, Any]:
```

Replace the existing snapshot fetch block with:

```python
    if snapshot is None:
        snapshot = fetch_price_action_snapshot(
            symbol,
            as_of=as_of,
            market_timezone=market_timezone,
        )
```

- [ ] **Step 4: Run the decision test and confirm it passes**

Run:

```powershell
python -m uv run --group dev pytest tests/test_engine_decision.py::test_run_engine_decision_accepts_prebuilt_snapshot -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit Task 3**

Run:

```powershell
git add tradingagents/agents/price_action/decision.py tests/test_engine_decision.py
git commit -m "feat: allow injected price action snapshots"
```

### Task 4: Wire MT5-native candles into `mt5-run --decision-mode engine`

**Files:**
- Modify: `cli/main.py`
- Modify: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write the failing CLI wiring test**

Add a test that monkeypatches `tradingagents.dataflows.mt5_price_action.fetch_mt5_price_action_snapshot`, calls the engine analysis function with an `MT5ConnectionConfig`, and asserts the passed broker uses `XAUUSD.vx`.

```python
def test_mt5_runner_engine_analysis_uses_mt5_snapshot(monkeypatch, tmp_path):
    from cli.main import _mt5_runner_engine_analysis_func
    from tradingagents.brokers.mt5 import MT5ConnectionConfig
    from tradingagents.dataflows.price_action import PriceActionSnapshot

    seen = {}

    def fake_snapshot(broker, *, as_of, market_timezone):
        seen["symbol"] = broker.config.symbol
        return PriceActionSnapshot(
            candles={timeframe: [] for timeframe in ("1d", "4h", "1h", "30m", "15m")},
            data_status={
                "healthy": False,
                "blocking_timeframes": ["15m"],
                "timeframes": {},
            },
        )

    monkeypatch.setattr(
        "tradingagents.dataflows.mt5_price_action.fetch_mt5_price_action_snapshot",
        fake_snapshot,
    )
    monkeypatch.setattr(
        "cli.main.DEFAULT_CONFIG",
        {
            "results_dir": str(tmp_path),
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "market_timezone": "America/New_York",
            "price_action": {},
        },
    )
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_SYMBOL", "GC=F")
    monkeypatch.setenv("TRADINGAGENTS_BROKER_SYMBOL", "XAUUSD.vx")

    config = MT5ConnectionConfig(
        login=1,
        password="secret",
        server="Demo",
        symbol="XAUUSD.vx",
    )

    analyze_once = _mt5_runner_engine_analysis_func(config)
    _as_of, proposal, analysis = analyze_once()

    assert seen["symbol"] == "XAUUSD.vx"
    assert proposal.broker_symbol == "XAUUSD.vx"
    assert analysis["engine_status"] == "NO_SETUP"
```

- [ ] **Step 2: Run the CLI wiring test and confirm it fails**

Run:

```powershell
python -m uv run --group dev pytest tests/test_cli_mt5_execution.py::test_mt5_runner_engine_analysis_uses_mt5_snapshot -q
```

Expected: failure because `_mt5_runner_engine_analysis_func` does not accept `config` and does not fetch MT5 snapshots.

- [ ] **Step 3: Implement the CLI wiring**

In `cli/main.py`, change the helper signature:

```python
def _mt5_runner_engine_analysis_func(mt5_config=None):
```

Inside `analyze_once`, import the MT5 broker and snapshot adapter:

```python
        from tradingagents.brokers.mt5 import MT5Broker
        from tradingagents.dataflows.mt5_price_action import fetch_mt5_price_action_snapshot
```

Before calling `run_engine_decision`, add:

```python
        engine_symbol = selections.get("broker_symbol") or selections["ticker"]
        snapshot = None
        if mt5_config is not None:
            analysis_broker = MT5Broker(mt5_config)
            analysis_broker.connect()
            snapshot = fetch_mt5_price_action_snapshot(
                analysis_broker,
                as_of=selections["as_of"],
                market_timezone=selections.get(
                    "market_timezone",
                    DEFAULT_CONFIG["market_timezone"],
                ),
            )
            engine_symbol = mt5_config.symbol
```

Pass `engine_symbol` and `snapshot` into `run_engine_decision`:

```python
        state = run_engine_decision(
            symbol=engine_symbol,
            broker_symbol=selections.get("broker_symbol") or engine_symbol,
            as_of=selections["as_of"],
            results_dir=DEFAULT_CONFIG["results_dir"],
            timeframe=selections.get("timeframe", DEFAULT_CONFIG["timeframe"]),
            confirmation_timeframe=selections.get(
                "confirmation_timeframe",
                DEFAULT_CONFIG["confirmation_timeframe"],
            ),
            market_timezone=selections.get(
                "market_timezone",
                DEFAULT_CONFIG["market_timezone"],
            ),
            session_config=DEFAULT_CONFIG.get("price_action"),
            snapshot=snapshot,
        )
```

In `mt5_run`, pass the config:

```python
        analysis_func = (
            _mt5_runner_engine_analysis_func(config)
            if normalized_decision_mode == "engine"
            else _mt5_runner_analysis_func()
        )
```

- [ ] **Step 4: Run the CLI wiring test and confirm it passes**

Run:

```powershell
python -m uv run --group dev pytest tests/test_cli_mt5_execution.py::test_mt5_runner_engine_analysis_uses_mt5_snapshot -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit Task 4**

Run:

```powershell
git add cli/main.py tests/test_cli_mt5_execution.py
git commit -m "feat: use mt5 candles for live engine runner"
```

### Task 5: Add a broker quote distance guard

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Write the failing distance-guard test**

Add this test to `tests/test_mt5_execution.py`:

```python
def test_executor_skips_entry_far_from_live_quote(tmp_path):
    config = MT5ConnectionConfig(
        login=123456789,
        password="secret",
        server="ExampleBroker-Demo",
        symbol="XAUUSD",
        max_entry_distance_points=10.0,
    )
    broker = FakeBroker()
    broker.symbol_info = {
        "name": "XAUUSD",
        "bid": 4476.39,
        "ask": 4476.72,
        "digits": 2,
        "point": 0.01,
        "trade_tick_size": 0.01,
        "trade_stops_level": 50,
    }
    executor = MT5Executor(config, tmp_path, broker=broker)
    proposal = _proposal(side=TradeAction.SELL)
    proposal.entry_price = 4517.47
    proposal.stop_loss = 4517.91
    proposal.take_profit = 4516.15
    proposal.broker_symbol = "XAUUSD"

    result = executor.execute_proposal(proposal)

    assert result["status"] == "SKIPPED_INVALID_ENTRY"
    assert "too far from live MT5 quote" in result["error"]
    assert broker.placed_requests == []
```

- [ ] **Step 2: Run the distance-guard test and confirm it fails**

Run:

```powershell
python -m uv run --group dev pytest tests/test_mt5_execution.py::test_executor_skips_entry_far_from_live_quote -q
```

Expected: failure because `max_entry_distance_points` does not exist and the far entry is not rejected.

- [ ] **Step 3: Add config and env plumbing**

In `MT5ConnectionConfig`, add:

```python
    max_entry_distance_points: float = 10.0
```

In `__post_init__`, add:

```python
        try:
            max_entry_distance_points = float(self.max_entry_distance_points)
        except (TypeError, ValueError) as exc:
            raise MT5BrokerError("MT5 max entry distance points must be numeric") from exc
        if not math.isfinite(max_entry_distance_points) or max_entry_distance_points < 0:
            raise MT5BrokerError("MT5 max entry distance points must be non-negative")
        object.__setattr__(
            self,
            "max_entry_distance_points",
            max_entry_distance_points,
        )
```

In `from_env`, pass:

```python
            max_entry_distance_points=_float_env(
                "TRADINGAGENTS_MAX_ENTRY_DISTANCE_POINTS",
                10.0,
            ),
```

- [ ] **Step 4: Add the distance guard**

In `MT5OrderRequestBuilder`, add:

```python
    def _assert_entry_near_quote(
        self,
        entry: float,
        symbol_info: dict[str, Any],
    ) -> None:
        max_distance = float(self.config.max_entry_distance_points)
        if max_distance <= 0:
            return
        bid, ask = self._quote(symbol_info)
        distance = min(abs(entry - bid), abs(entry - ask))
        if distance > max_distance:
            raise ValueError(
                f"entry price is too far from live MT5 quote: "
                f"entry={entry}, bid={bid}, ask={ask}, distance={distance:.2f}, "
                f"max_distance={max_distance:.2f}"
            )
```

Call it after `entry` is rounded and before `_resolve_order_type`:

```python
        self._assert_entry_near_quote(entry, symbol_info)
```

- [ ] **Step 5: Run the distance-guard test and confirm it passes**

Run:

```powershell
python -m uv run --group dev pytest tests/test_mt5_execution.py::test_executor_skips_entry_far_from_live_quote -q
```

Expected: `1 passed`.

- [ ] **Step 6: Commit Task 5**

Run:

```powershell
git add tradingagents/brokers/mt5.py tests/test_mt5_execution.py
git commit -m "feat: guard mt5 entries by quote distance"
```

### Task 6: Update live environment for the next fresh session

**Files:**
- Modify: `.env`

- [ ] **Step 1: Replace the live analysis symbol**

Set these values in `.env`:

```dotenv
TRADINGAGENTS_ANALYSIS_SYMBOL=XAUUSD.vx
TRADINGAGENTS_BROKER_SYMBOL=XAUUSD.vx
TRADINGAGENTS_MT5_SYMBOL=XAUUSD.vx
TRADINGAGENTS_MAX_ENTRY_DISTANCE_POINTS=10.0
```

- [ ] **Step 2: Point telemetry at a new session**

Set:

```dotenv
TRADINGAGENTS_RESULTS_DIR=C:\Users\Administrator\.tradingagents\sessions\2026-06-03-mt5-native-feed
```

Create the directory:

```powershell
New-Item -ItemType Directory -Force 'C:\Users\Administrator\.tradingagents\sessions\2026-06-03-mt5-native-feed'
```

- [ ] **Step 3: Confirm `.env` stays untracked**

Run:

```powershell
git status --short .env
```

Expected: no tracked diff is shown for `.env`.

### Task 7: Verify the whole live path before restarting overnight

**Files:**
- Verify: `tradingagents/brokers/mt5.py`
- Verify: `tradingagents/dataflows/mt5_price_action.py`
- Verify: `tradingagents/agents/price_action/decision.py`
- Verify: `cli/main.py`
- Verify: `tradingagents/brokers/mt5_execution.py`

- [ ] **Step 1: Run the targeted tests**

Run:

```powershell
python -m uv run --group dev pytest tests/test_mt5_broker.py tests/test_mt5_price_action_dataflow.py tests/test_engine_decision.py tests/test_cli_mt5_execution.py tests/test_mt5_execution.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run the full test suite**

Run:

```powershell
python -m uv run --group dev pytest -q
```

Expected: all tests pass.

- [ ] **Step 3: Probe the broker**

Run:

```powershell
python -m uv run tradingagents broker-probe
```

Expected: connected account is `641206942`, server is `ValetaxGlobal-Live3`, symbol is `XAUUSD.vx`, and bid/ask are current.

- [ ] **Step 4: Run one engine cycle only**

Run:

```powershell
python -m uv run tradingagents mt5-run --once --decision-mode engine
```

Expected:

- Engine payload symbol is `XAUUSD.vx`.
- Proposal `broker_symbol` is `XAUUSD.vx`.
- If a setup is found, entry is within `TRADINGAGENTS_MAX_ENTRY_DISTANCE_POINTS` of live bid/ask.
- If no setup is found, no order is placed.

- [ ] **Step 5: Commit verification docs if any were changed**

Run:

```powershell
git status --short
```

Expected: only intentional source/test/docs changes are present.

## Self-Review

- Spec coverage: The plan covers the diagnosed mismatch by replacing live engine data with MT5 candles, keeping research dataflow unchanged, and adding a guard against future far-away entries.
- Placeholder scan: No implementation step depends on unspecified behavior; each code-changing task includes concrete test and implementation snippets.
- Type consistency: The plan uses `PriceActionSnapshot`, `MT5Broker.fetch_rates`, `fetch_mt5_price_action_snapshot`, and `snapshot=` consistently across tasks.
