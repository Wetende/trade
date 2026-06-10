# MT5 Market Data Compliance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the TradingAgents MT5 directional and straddle runners read MT5 market data exactly according to the official MetaTrader 5 Python API semantics, then upgrade market-state journaling so entry decisions are based on closed candles, live ticks, broker constraints, and clear playbook state.

**Architecture:** Separate closed-bar analysis from live tick execution. MT5 candle snapshots must use closed candles only; current bid/ask and spread must come from `symbol_info_tick()`/`symbol_info()`. The deterministic engine should journal market understanding before setup detection: data health, spread, volatility, trend/range state, structure, setup trigger, invalidation, risk, execution guard, management, and review fields.

**Tech Stack:** Python 3.13, MetaTrader5 Python package, pytest, existing TradingAgents deterministic price-action engine, existing MT5 broker/executor/runner modules.

---

## Official MQL5 Python Documentation Basis

Use these official sources as implementation constraints:

- Python integration index: https://www.mql5.com/en/docs/python_metatrader5
- `copy_rates_from_pos`: `start_pos=0` means current bar, not last closed bar. https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py
- MQL5 `CopyRates`: position `0` is current bar; current uncompleted bar can be returned with `start_pos=0,count=1`. https://www.mql5.com/en/docs/series/copyrates
- `copy_rates_from` and `copy_rates_range`: time arguments must be UTC because MT5 stores bar/tick time in UTC. https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py and https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py
- `symbol_info_tick`: source of current bid/ask/current tick. https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfotick_py
- `symbol_info`: source of symbol properties such as spread, digits, stop level, freeze level, and execution settings. https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py
- `terminal_info`: source of terminal connectivity/trading flags. https://www.mql5.com/en/docs/python_metatrader5/mt5terminalinfo_py
- `account_info`: source of account mode, trade permission, equity/margin, server. https://www.mql5.com/en/docs/python_metatrader5/mt5accountinfo_py
- `orders_get`: source of active pending orders. https://www.mql5.com/en/docs/python_metatrader5/mt5ordersget_py
- `positions_get`: source of open positions. https://www.mql5.com/en/docs/python_metatrader5/mt5positionsget_py
- `history_deals_get`: source of filled/closed trade history. https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py
- `order_check`: preflight request validation and funds check. https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py
- `order_send`: final request send and retcode response. https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py

---

## File Structure

- Modify: `tradingagents/brokers/mt5.py`
  - Add a closed-candle-safe rates API.
  - Preserve raw `fetch_rates()` compatibility if needed.
  - Normalize MT5 rate `spread` and `real_volume` into returned candle dicts.
  - Add `order_check()` wrapper if absent.

- Modify: `tradingagents/dataflows/mt5_price_action.py`
  - Use closed candles for all analysis timeframes.
  - Include market snapshot metadata: current tick, symbol info, spread, server/UTC timing.

- Modify: `tradingagents/agents/price_action/models.py`
  - Add small dataclasses for market state if existing model style supports it.
  - Keep JSON output simple and serializable.

- Modify: `tradingagents/agents/price_action/structure.py`
  - Improve structure/state classification from closed candles.
  - Separate trend/range/volatility state from setup trigger.

- Modify: `tradingagents/agents/price_action/engine.py`
  - Add a first-class `market_state` section.
  - Use closed-candle metadata and market-state gates before setup detection.
  - Record near-miss candidates even when no trade is approved.

- Modify: `tradingagents/agents/price_action/decision.py`
  - Render richer deterministic reports.

- Modify: `tradingagents/brokers/mt5_execution.py`
  - Optionally call `order_check()` before `order_send()`.
  - Journal order-check result separately.

- Modify: `tradingagents/brokers/runner_summary.py`
  - Aggregate market-state and near-miss reasons.

- Modify tests:
  - `tests/test_mt5_broker.py`
  - `tests/test_mt5_price_action_dataflow.py`
  - `tests/test_price_action_structure.py`
  - `tests/test_price_action_engine.py`
  - `tests/test_mt5_execution.py`
  - `tests/test_mt5_runner_summary.py`
  - `tests/test_cli_mt5_execution.py`

---

## Task 1: Make MT5 Rate Fetching Closed-Bar Safe

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Test: `tests/test_mt5_broker.py`

- [ ] **Step 1: Write failing tests for closed-bar fetching**

Add tests that prove analysis fetches start from position `1`, not `0`.

```python
def test_mt5_broker_fetch_closed_rates_skips_current_bar():
    fake = FakeMT5()
    fake.rates = [
        {"time": 1779613200, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "tick_volume": 10, "spread": 3, "real_volume": 0},
        {"time": 1779612300, "open": 2, "high": 3, "low": 1.5, "close": 2.5, "tick_volume": 11, "spread": 4, "real_volume": 0},
    ]
    broker = MT5Broker(MT5ConnectionConfig(login=123, password="x", server="Demo", symbol="XAUUSD"), mt5_module=fake)
    broker.connect()

    candles = broker.fetch_closed_rates("15m", count=2)

    assert fake.copy_rates_calls == [("XAUUSD", fake.TIMEFRAME_M15, 1, 2)]
    assert len(candles) == 2
    assert candles[0]["spread"] == 3
    assert candles[0]["real_volume"] == 0.0
```

- [ ] **Step 2: Run the focused failing test**

Run:

```powershell
.\.venv\Scripts\pytest.exe tests\test_mt5_broker.py::test_mt5_broker_fetch_closed_rates_skips_current_bar -q
```

Expected: fail because `fetch_closed_rates` does not exist.

- [ ] **Step 3: Implement closed-rate method**

Add this method next to `fetch_rates` in `MT5Broker`:

```python
def fetch_closed_rates(self, timeframe: str, count: int) -> list[dict[str, Any]]:
    """Fetch closed OHLCV bars; MT5 start_pos=0 is the current forming bar."""
    return self._fetch_rates_from_pos(timeframe, count, start_pos=1)
```

Refactor existing `fetch_rates` into:

```python
def fetch_rates(self, timeframe: str, count: int) -> list[dict[str, Any]]:
    """Fetch normalized OHLCV bars including MT5 bar 0, the current forming bar."""
    return self._fetch_rates_from_pos(timeframe, count, start_pos=0)
```

Add:

```python
def _fetch_rates_from_pos(self, timeframe: str, count: int, *, start_pos: int) -> list[dict[str, Any]]:
    self._assert_active_session()
    rate_count = self._positive_count(count)
    if start_pos < 0:
        raise MT5BrokerError("MT5 rate start_pos must be non-negative")
    mt5 = self._module()
    timeframe_constants = {
        "1m": getattr(mt5, "TIMEFRAME_M1", None),
        "3m": getattr(mt5, "TIMEFRAME_M3", None),
        "15m": getattr(mt5, "TIMEFRAME_M15", None),
        "30m": getattr(mt5, "TIMEFRAME_M30", None),
        "1h": getattr(mt5, "TIMEFRAME_H1", None),
        "1d": getattr(mt5, "TIMEFRAME_D1", None),
    }
    mt5_timeframe = timeframe_constants.get(timeframe)
    if mt5_timeframe is None:
        raise MT5BrokerError(f"unsupported MT5 timeframe: {timeframe}")
    rates = mt5.copy_rates_from_pos(self.config.symbol, mt5_timeframe, start_pos, rate_count)
    if rates is None:
        raise MT5BrokerError(f"MT5 copy_rates_from_pos failed: {mt5.last_error()}")
    server_time_offset_seconds = self._server_time_offset_seconds(mt5)
    return [self._normalize_rate(rate, server_time_offset_seconds) for rate in rates]
```

Move rate dict creation into:

```python
def _normalize_rate(self, rate: Any, server_time_offset_seconds: int) -> dict[str, Any]:
    item = _asdict(rate)
    raw_timestamp = int(self._rate_value(rate, item, "time"))
    return {
        "timestamp": datetime.fromtimestamp(raw_timestamp - server_time_offset_seconds, tz=timezone.utc).isoformat(),
        "open": float(self._rate_value(rate, item, "open")),
        "high": float(self._rate_value(rate, item, "high")),
        "low": float(self._rate_value(rate, item, "low")),
        "close": float(self._rate_value(rate, item, "close")),
        "volume": float(self._rate_value(rate, item, "tick_volume", self._rate_value(rate, item, "real_volume", 0))),
        "spread": float(self._rate_value(rate, item, "spread", 0)),
        "real_volume": float(self._rate_value(rate, item, "real_volume", 0)),
    }
```

- [ ] **Step 4: Run broker tests**

Run:

```powershell
.\.venv\Scripts\pytest.exe tests\test_mt5_broker.py -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/brokers/mt5.py tests/test_mt5_broker.py
git commit -m "fix: add closed MT5 rate fetching"
```

---

## Task 2: Use Closed Candles in MT5 Price-Action Snapshots

**Files:**
- Modify: `tradingagents/dataflows/mt5_price_action.py`
- Test: `tests/test_mt5_price_action_dataflow.py`

- [ ] **Step 1: Write failing test for closed snapshot fetch**

```python
def test_fetch_mt5_price_action_snapshot_uses_closed_rates():
    broker = FakeBroker()
    broker.closed_rates = {
        "1d": [], "1h": [], "30m": [], "15m": [], "3m": [], "1m": [],
    }
    broker.fetch_closed_rates_calls = []

    fetch_mt5_price_action_snapshot(broker, as_of="2026-05-29 10:15")

    assert broker.fetch_closed_rates_calls
    assert broker.fetch_rates_calls == []
```

- [ ] **Step 2: Run failing test**

```powershell
.\.venv\Scripts\pytest.exe tests\test_mt5_price_action_dataflow.py::test_fetch_mt5_price_action_snapshot_uses_closed_rates -q
```

Expected: fail because current code calls `fetch_rates`.

- [ ] **Step 3: Replace analysis fetches**

In `fetch_mt5_price_action_snapshot`, replace:

```python
broker.fetch_rates(timeframe, count)
```

with:

```python
broker.fetch_closed_rates(timeframe, count)
```

Keep straddle behavior unchanged for now because it already drops the newest bar internally; later we can migrate it to `fetch_closed_rates` for consistency.

- [ ] **Step 4: Add snapshot metadata**

If broker supports it, include:

```python
market_snapshot = {
    "source": "MT5",
    "bars_are_closed": True,
    "time_basis": "UTC",
}
```

Return it inside `PriceActionSnapshot` only if that model already permits metadata. If not, add a `metadata: dict[str, Any] = field(default_factory=dict)` field and update tests.

- [ ] **Step 5: Run dataflow tests**

```powershell
.\.venv\Scripts\pytest.exe tests\test_mt5_price_action_dataflow.py tests/test_price_action_data_health.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/dataflows/mt5_price_action.py tradingagents/dataflows/price_action.py tests/test_mt5_price_action_dataflow.py
git commit -m "fix: analyze only closed MT5 candles"
```

---

## Task 3: Fix Last-Closed-Candle Time Alignment

**Files:**
- Modify: `cli/utils.py`
- Test: `tests/test_cli_timeframe.py`

- [ ] **Step 1: Write boundary test**

At exact candle boundary, `last_closed_candle("15m", now=10:15:00)` currently returns `10:15`, but the candle that opened at `10:15` is not closed. Expected last closed candle is `10:00`.

```python
def test_last_closed_candle_at_exact_boundary_returns_previous_bucket():
    now = datetime(2026, 5, 17, 10, 15, 0, tzinfo=ZoneInfo("America/New_York"))
    assert last_closed_candle("15m", "America/New_York", now=now) == "2026-05-17 10:00"
```

- [ ] **Step 2: Run failing test**

```powershell
.\.venv\Scripts\pytest.exe tests/test_cli_timeframe.py::test_last_closed_candle_at_exact_boundary_returns_previous_bucket -q
```

Expected: fail with `10:15 != 10:00`.

- [ ] **Step 3: Implement exact-boundary correction**

Change `last_closed_candle`:

```python
local_now = (now or datetime.now(tz)).astimezone(tz)
bucket_minute = (local_now.minute // minutes) * minutes
bucket = local_now.replace(minute=bucket_minute, second=0, microsecond=0)
if local_now == bucket:
    bucket = bucket - timedelta(minutes=minutes)
return bucket.strftime("%Y-%m-%d %H:%M")
```

Import `timedelta` if not already imported.

- [ ] **Step 4: Run time tests**

```powershell
.\.venv\Scripts\pytest.exe tests/test_cli_timeframe.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```powershell
git add cli/utils.py tests/test_cli_timeframe.py
git commit -m "fix: avoid current candle at timeframe boundary"
```

---

## Task 4: Add Market State Before Setup Detection

**Files:**
- Modify: `tradingagents/agents/price_action/structure.py`
- Modify: `tradingagents/agents/price_action/engine.py`
- Test: `tests/test_price_action_structure.py`
- Test: `tests/test_price_action_engine.py`

- [ ] **Step 1: Add tests for trend/range/volatility state**

```python
def test_classify_market_state_detects_bearish_expansion():
    candles = [
        Candle(timestamp=f"2026-05-29T10:{i:02d}:00+00:00", open=100-i, high=101-i, low=98-i, close=99-i, volume=100)
        for i in range(20)
    ]
    state = classify_market_state(candles, [], timeframe="30m")
    assert state["trend"] == "BEARISH"
    assert state["volatility"] in {"NORMAL", "EXPANDING"}
    assert state["state"] in {"TRENDING", "BREAKDOWN"}
```

```python
def test_classify_market_state_detects_range():
    candles = [
        Candle(timestamp=f"2026-05-29T10:{i:02d}:00+00:00", open=100, high=101, low=99, close=100.2 if i % 2 else 99.8, volume=100)
        for i in range(30)
    ]
    zones = calculate_support_resistance(candles, timeframe="30m", tolerance=0.5, min_touches=2)
    state = classify_market_state(candles, zones, timeframe="30m")
    assert state["state"] in {"RANGING", "CHOPPY"}
```

- [ ] **Step 2: Run failing tests**

```powershell
.\.venv\Scripts\pytest.exe tests/test_price_action_structure.py::test_classify_market_state_detects_bearish_expansion tests/test_price_action_structure.py::test_classify_market_state_detects_range -q
```

Expected: fail because `classify_market_state` does not exist.

- [ ] **Step 3: Implement `classify_market_state`**

Add to `structure.py`:

```python
def classify_market_state(candles: list[Candle | dict[str, Any]], zones: list[Zone | dict[str, Any]], timeframe: str) -> dict[str, Any]:
    normalized = list(candles or [])
    if len(normalized) < 10:
        return {"timeframe": timeframe, "state": "UNKNOWN", "trend": "UNKNOWN", "volatility": "UNKNOWN", "reason": "not enough closed candles"}
    recent = normalized[-20:]
    highs = [_candle_value(c, "high") for c in recent]
    lows = [_candle_value(c, "low") for c in recent]
    closes = [_candle_value(c, "close") for c in recent]
    ranges = [max(_candle_value(c, "high") - _candle_value(c, "low"), 0.0) for c in recent]
    avg_range = sum(ranges) / len(ranges)
    prior_avg = sum(ranges[:10]) / max(len(ranges[:10]), 1)
    recent_avg = sum(ranges[-5:]) / max(len(ranges[-5:]), 1)
    higher_lows = lows[-1] > lows[0] and min(lows[-5:]) > min(lows[:5])
    higher_highs = highs[-1] > highs[0] and max(highs[-5:]) > max(highs[:5])
    lower_lows = lows[-1] < lows[0] and min(lows[-5:]) < min(lows[:5])
    lower_highs = highs[-1] < highs[0] and max(highs[-5:]) < max(highs[:5])
    if higher_highs and higher_lows:
        trend = "BULLISH"
        state = "TRENDING"
    elif lower_highs and lower_lows:
        trend = "BEARISH"
        state = "TRENDING"
    elif max(highs) - min(lows) <= max(avg_range * 4, 0.0001):
        trend = "NEUTRAL"
        state = "RANGING"
    else:
        trend = "MIXED"
        state = "CHOPPY"
    if recent_avg > prior_avg * 1.35:
        volatility = "EXPANDING"
    elif recent_avg < prior_avg * 0.65:
        volatility = "DEAD"
    else:
        volatility = "NORMAL"
    return {"timeframe": timeframe, "state": state, "trend": trend, "volatility": volatility, "average_range": round(avg_range, 4), "reason": f"{timeframe} {state} {trend} volatility={volatility}"}
```

- [ ] **Step 4: Put market state into engine payload**

In `engine.py`, after zone construction and before setup detection:

```python
market_states = {
    tf: classify_market_state(candles_by_tf.get(tf, []), zones_by_tf.get(tf, []), tf)
    for tf in zone_lookup_timeframes
}
market_context["market_states"] = market_states
market_context["primary_market_state"] = market_states.get(governing_timeframes[0]) if governing_timeframes else None
```

Add to telemetry:

```python
"market_states": market_context.get("market_states", {}),
"primary_market_state": market_context.get("primary_market_state"),
```

- [ ] **Step 5: Run structure and engine tests**

```powershell
.\.venv\Scripts\pytest.exe tests/test_price_action_structure.py tests/test_price_action_engine.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/agents/price_action/structure.py tradingagents/agents/price_action/engine.py tests/test_price_action_structure.py tests/test_price_action_engine.py
git commit -m "feat: add deterministic market state telemetry"
```

---

## Task 5: Separate Context Zones from Entry Trigger Zones

**Files:**
- Modify: `tradingagents/agents/price_action/profiles.py`
- Modify: `tradingagents/agents/price_action/engine.py`
- Test: `tests/test_price_action_profiles.py`
- Test: `tests/test_price_action_engine.py`

- [ ] **Step 1: Add profile test**

```python
def test_normal_profile_separates_context_and_entry_zone_timeframes():
    profile = normal_profile({})
    assert profile.zone_timeframes == ("30m",)
    assert profile.context_timeframes == ("1d", "4h", "1h", "30m")
```

- [ ] **Step 2: Run failing test**

```powershell
.\.venv\Scripts\pytest.exe tests/test_price_action_profiles.py::test_normal_profile_separates_context_and_entry_zone_timeframes -q
```

Expected: fail because `context_timeframes` does not exist and normal currently includes `1d/4h/1h` in setup zones.

- [ ] **Step 3: Extend `EntryProfile`**

Change dataclass:

```python
context_timeframes: tuple[str, ...]
```

Set normal:

```python
zone_timeframes=("30m",)
context_timeframes=("1d", "4h", "1h", "30m")
```

Set fast:

```python
zone_timeframes=("30m", "15m")
context_timeframes=("30m", "15m")
```

- [ ] **Step 4: Pass context timeframes into engine config**

In `cli/main.py` profile config:

```python
"context_timeframes": profile.context_timeframes,
```

In required timeframe list:

```python
*profile.context_timeframes,
```

- [ ] **Step 5: Update engine zone logic**

Use context timeframes for structure/market state and zone timeframes for setup triggers:

```python
context_timeframes = tuple(str(tf) for tf in profile_config.get("context_timeframes", zone_timeframes))
zone_lookup_timeframes = tuple(dict.fromkeys((*context_timeframes, *zone_timeframes, *governing_timeframes, confirmation_timeframe)))
```

Only extend `zones` for `zone_timeframes`, not context-only timeframes.

- [ ] **Step 6: Add regression test against Daily-zone entry**

Use the 21:45 pattern: Daily support can be recorded as context but cannot create a 15m bounce entry directly.

```python
def test_normal_engine_does_not_use_daily_zone_as_entry_trigger():
    payload = analyze_playbook(
        "XAUUSD.vx",
        "2026-06-09 21:45",
        timeframe_data,
        session_config={
            "entry_profile": "normal",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "zone_timeframes": ("30m",),
            "context_timeframes": ("1d", "4h", "1h", "30m"),
            "governing_timeframes": ("30m",),
            "minimum_setup_grade": "B_PLUS",
        },
    )
    for item in payload["telemetry"].get("candidate_evaluations", []):
        assert item["setup"]["zone"]["timeframe"] != "1d"
```

- [ ] **Step 7: Run focused tests**

```powershell
.\.venv\Scripts\pytest.exe tests/test_price_action_profiles.py tests/test_price_action_engine.py tests/test_cli_mt5_execution.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```powershell
git add tradingagents/agents/price_action/profiles.py tradingagents/agents/price_action/engine.py cli/main.py tests/test_price_action_profiles.py tests/test_price_action_engine.py tests/test_cli_mt5_execution.py
git commit -m "fix: separate entry zones from context zones"
```

---

## Task 6: Upgrade M30/15m Direction From Event-Only to State-Aware

**Files:**
- Modify: `tradingagents/agents/price_action/engine.py`
- Modify: `tradingagents/agents/price_action/structure.py`
- Test: `tests/test_price_action_engine.py`

- [ ] **Step 1: Add test for bearish structure allowing sell context**

```python
def test_m30_bearish_structure_can_govern_sell_without_latest_breakout():
    payload = analyze_playbook(
        "XAUUSD.vx",
        "2026-05-29 10:15",
        bearish_m30_sell_setup_data,
        session_config={
            "entry_profile": "normal",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "zone_timeframes": ("30m",),
            "context_timeframes": ("1d", "4h", "1h", "30m"),
            "governing_timeframes": ("30m",),
            "minimum_setup_grade": "B_PLUS",
        },
    )
    assert payload["market_context"]["m30_bias"] == "BEARISH"
    assert payload["market_context"]["m30_context"] in {"STRUCTURE", "BREAKOUT", "REJECTION"}
```

- [ ] **Step 2: Run failing test**

```powershell
.\.venv\Scripts\pytest.exe tests/test_price_action_engine.py::test_m30_bearish_structure_can_govern_sell_without_latest_breakout -q
```

Expected: fail because current `_timeframe_context` only uses latest breakout/rejection.

- [ ] **Step 3: Update `_timeframe_context` fallback**

After breakout/rejection checks:

```python
structure = classify_timeframe_structure(candles, zones, timeframe)
permission = str(structure.get("permission") or "")
if permission == "BUY_ALLOWED":
    return {"m30_bias": "BULLISH", "m30_context": "STRUCTURE", "m30_structure": structure, "source_timeframe": timeframe}
if permission == "SELL_ALLOWED":
    return {"m30_bias": "BEARISH", "m30_context": "STRUCTURE", "m30_structure": structure, "source_timeframe": timeframe}
return {**context, "m30_structure": structure}
```

- [ ] **Step 4: Ensure trigger still controls entries**

Do not approve trades from structure alone. Structure may satisfy `confirmation_context_clear` and `timeframe_correlation`, but `playbook_setup`, trigger candle, invalidation, and risk must still pass.

- [ ] **Step 5: Run engine tests**

```powershell
.\.venv\Scripts\pytest.exe tests/test_price_action_engine.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/agents/price_action/engine.py tradingagents/agents/price_action/structure.py tests/test_price_action_engine.py
git commit -m "feat: use structure-aware governing context"
```

---

## Task 7: Add Spread and Live Tick Health Gate for Entry Engine

**Files:**
- Modify: `tradingagents/dataflows/mt5_price_action.py`
- Modify: `tradingagents/agents/price_action/engine.py`
- Test: `tests/test_mt5_price_action_dataflow.py`
- Test: `tests/test_price_action_engine.py`

- [ ] **Step 1: Add snapshot metadata fields**

Add metadata containing:

```python
{
    "tick": {"bid": bid, "ask": ask, "time": tick_time},
    "symbol_info": {"spread": spread, "digits": digits, "trade_stops_level": stops_level, "trade_freeze_level": freeze_level},
    "spread_points": ask - bid,
}
```

- [ ] **Step 2: Add engine test for spread block**

```python
def test_engine_blocks_entry_when_live_spread_too_wide():
    snapshot = PriceActionSnapshot(candles=timeframe_data, data_status=healthy, metadata={"spread_points": 2.5})
    state = run_engine_decision(..., snapshot=snapshot, session_config={"max_entry_spread_points": 0.5})
    assert state["engine_payload"]["status"] == "NO_SETUP"
    assert "spread_too_wide" in state["engine_payload"]["telemetry"]["health_reasons"]
```

- [ ] **Step 3: Implement spread gate**

In `analyze_playbook`:

```python
metadata = profile_config.get("market_metadata") or {}
spread_points = metadata.get("spread_points")
max_spread = profile_config.get("max_entry_spread_points")
health_reasons = []
if max_spread is not None and spread_points is not None and float(spread_points) > float(max_spread):
    health_reasons.append("spread_too_wide")
```

If `health_reasons` is non-empty, return HOLD before setup detection and journal reasons.

- [ ] **Step 4: Wire metadata through CLI**

Pass snapshot metadata into `profile_config`:

```python
"market_metadata": getattr(profile_snapshot, "metadata", {}),
```

- [ ] **Step 5: Run tests**

```powershell
.\.venv\Scripts\pytest.exe tests/test_mt5_price_action_dataflow.py tests/test_price_action_engine.py tests/test_cli_mt5_execution.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/dataflows/mt5_price_action.py tradingagents/agents/price_action/engine.py cli/main.py tests/test_mt5_price_action_dataflow.py tests/test_price_action_engine.py tests/test_cli_mt5_execution.py
git commit -m "feat: gate entries on live MT5 spread"
```

---

## Task 8: Add Order Check Before Order Send

**Files:**
- Modify: `tradingagents/brokers/mt5.py`
- Modify: `tradingagents/brokers/mt5_execution.py`
- Test: `tests/test_mt5_broker.py`
- Test: `tests/test_mt5_execution.py`

- [ ] **Step 1: Add broker wrapper test**

```python
def test_mt5_broker_order_check_returns_check_result():
    fake = FakeMT5()
    fake.order_check_result = SimpleNamespace(retcode=0, comment="Done", request={"symbol": "XAUUSD"})
    broker = MT5Broker(MT5ConnectionConfig(login=123, password="x", server="Demo", symbol="XAUUSD"), mt5_module=fake)
    broker.connect()
    result = broker.check_order({"symbol": "XAUUSD"})
    assert result["retcode"] == 0
    assert result["comment"] == "Done"
```

- [ ] **Step 2: Implement broker `check_order`**

```python
def check_order(self, request: dict[str, Any]) -> dict[str, Any]:
    self._assert_order_send_allowed()
    mt5 = self._module()
    result = mt5.order_check(self._materialize_request(request))
    if result is None:
        raise MT5BrokerError(f"MT5 order_check failed: {mt5.last_error()}")
    return _asdict(result)
```

- [ ] **Step 3: Add executor test**

```python
def test_executor_journals_order_check_before_send():
    result = executor.execute_proposal(valid_proposal)
    assert journal.events[0]["event"] == "CONNECTED"
    assert any(event["event"] == "ORDER_CHECKED" for event in journal.events)
    assert broker.place_pending_order_calls
```

- [ ] **Step 4: Call order check in executor**

After request built:

```python
check_result = self.broker.check_order(request)
self.journal.append("ORDER_CHECKED", check_result)
retcode = check_result.get("retcode")
if retcode not in (0, None) and str(check_result.get("comment") or "").upper() not in {"DONE", "OK"}:
    result = {"status": "SKIPPED_ORDER_CHECK", "reason": "ORDER_CHECK_FAILED", "order_check": check_result, "proposal": proposal.model_dump(mode="json"), "account_safety": account_safety}
    self.journal.append("ORDER_SKIPPED", result)
    return result
```

Keep retcode acceptance conservative and compatible with fake tests; adjust once real broker `order_check` retcodes are observed in telemetry.

- [ ] **Step 5: Run execution tests**

```powershell
.\.venv\Scripts\pytest.exe tests/test_mt5_broker.py tests/test_mt5_execution.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/brokers/mt5.py tradingagents/brokers/mt5_execution.py tests/test_mt5_broker.py tests/test_mt5_execution.py
git commit -m "feat: preflight MT5 orders with order_check"
```

---

## Task 9: Improve Near-Miss Journaling for AI Offline Review

**Files:**
- Modify: `tradingagents/agents/price_action/engine.py`
- Modify: `tradingagents/agents/price_action/decision.py`
- Modify: `tradingagents/brokers/runner_summary.py`
- Test: `tests/test_price_action_engine.py`
- Test: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Add engine test for near misses**

```python
def test_engine_journals_near_miss_candidates_when_no_trade():
    payload = analyze_playbook("XAUUSD.vx", "2026-05-29 10:15", timeframe_data, session_config=config)
    assert "near_misses" in payload["telemetry"]
    for item in payload["telemetry"]["near_misses"]:
        assert "setup_name" in item
        assert "direction" in item
        assert "failed_rules" in item
        assert "reason" in item
```

- [ ] **Step 2: Implement near-miss telemetry**

When building `candidate_evaluations`, add:

```python
near_misses = [
    {
        "setup_name": item["setup"]["name"],
        "direction": item["setup"]["direction"],
        "zone_timeframe": item["setup"]["zone"].get("timeframe"),
        "failed_rules": item.get("failed_rules", []),
        "risk_reward": (item.get("risk") or {}).get("risk_reward"),
        "reason": item.get("rejection_reason"),
    }
    for item in evaluations
    if not item.get("approved")
]
```

Add to telemetry:

```python
"near_misses": near_misses,
```

- [ ] **Step 3: Render near misses in report**

In `render_engine_decision_report`, add a `## Near Misses` section with at most five rows:

```python
for item in near_misses[:5]:
    lines.append(f"- {item['direction']} {item['setup_name']} on {item.get('zone_timeframe')}: {', '.join(item.get('failed_rules') or [])}; {item.get('reason')}")
```

- [ ] **Step 4: Aggregate near-miss counts**

In `RunnerSummaryStore._empty_summary`, add:

```python
"near_miss_counts": {},
"near_miss_failed_rule_counts": {},
```

In `record_cycle`, count `telemetry_source.get("near_misses")`.

- [ ] **Step 5: Run tests**

```powershell
.\.venv\Scripts\pytest.exe tests/test_price_action_engine.py tests/test_mt5_runner_summary.py -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/agents/price_action/engine.py tradingagents/agents/price_action/decision.py tradingagents/brokers/runner_summary.py tests/test_price_action_engine.py tests/test_mt5_runner_summary.py
git commit -m "feat: journal near-miss setup reasons"
```

---

## Task 10: Run Integration Verification and Fresh Demo Session

**Files:**
- No source edits unless verification exposes a bug.

- [ ] **Step 1: Run full suite**

```powershell
.\.venv\Scripts\pytest.exe -q
```

Expected: all tests pass.

- [ ] **Step 2: Confirm no old runner process**

```powershell
Get-CimInstance Win32_Process -Filter "name = 'python.exe'" | Select-Object ProcessId,CommandLine
```

Expected: no stale `cli.main mt5-run` process before starting fresh.

- [ ] **Step 3: Start fresh ENTRY_ONLY telemetry**

Use a new results directory:

```powershell
$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$env:TRADINGAGENTS_RESULTS_DIR = "C:\Users\Administrator\Desktop\trade\results\$stamp-entry-only-closed-bars"
$env:TRADINGAGENTS_TRADING_MODE = "ENTRY_ONLY"
$env:TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT = "true"
$env:TRADINGAGENTS_DECISION_MODE = "engine"
$env:TRADINGAGENTS_FAST_ENTRIES_ENABLED = "true"
$env:TRADINGAGENTS_TIMEFRAME = "15m"
$env:TRADINGAGENTS_CONFIRMATION_TIMEFRAME = "30m"
$env:TRADINGAGENTS_FAST_TIMEFRAME = "1m"
$env:TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME = "3m"
.\.venv\Scripts\python.exe -m cli.main mt5-run --poll-seconds 30 --decision-mode engine
```

- [ ] **Step 4: Verify first heartbeat**

Check:

```powershell
Get-Content "$env:TRADINGAGENTS_RESULTS_DIR\mt5_runner\heartbeat.json" -Raw | ConvertFrom-Json
```

Expected:

```text
trading_mode = ENTRY_ONLY
account_safety.passed = true
health_gate.passed = true
analysis telemetry includes market_states
analysis telemetry includes bars_are_closed or equivalent metadata
```

- [ ] **Step 5: Commit final verification notes if docs changed**

Only commit if a tracked documentation file was updated:

```powershell
git status --short
git add <tracked-doc-files>
git commit -m "docs: record MT5 closed-bar verification"
```

---

## Acceptance Criteria

- Directional MT5 analysis never uses MT5 bar `0` as a closed candle.
- Current bid/ask/spread comes from `symbol_info_tick()`/`symbol_info()`, not from the close of a forming candle.
- `last_closed_candle()` does not return the just-opened candle at exact timeframe boundaries.
- Normal profile uses higher timeframes for context, not direct Daily/4H/1H entry triggers.
- M30/15m context can be derived from structure/state, not only latest breakout/rejection.
- Every HOLD logs market state, primary context, setup near misses, failed rules, risk reason, spread state, and data health.
- MT5 order execution records `order_check` before `order_send`.
- Runner summary aggregates market-state and near-miss reasons for offline AI review.
- Full test suite passes.
- Fresh demo telemetry confirms `ENTRY_ONLY`, demo safety, closed-bar analysis, and richer journaling.

---

## Execution Notes

- Do not add LLM live decision-making.
- Do not change real-money safety behavior.
- Do not loosen entry rules until closed-bar correctness and market-state journaling are verified.
- Keep straddle disabled for this phase unless explicitly testing straddle-only.
- If any MT5 behavior differs from docs on the live terminal, journal the observed raw MT5 response and update tests to match the official API plus observed broker constraints.
