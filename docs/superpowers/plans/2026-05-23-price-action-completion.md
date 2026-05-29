# Price Action Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the full non-broker price-action trading system: top-down market structure, all-zone detection, M15 entry confirmation, risk approval, local order lifecycle, trade management, and backtesting/simulation.

**Architecture:** Keep `tradingagents.agents.utils.price_action_tools` as the LangChain tool boundary, but move deterministic trading logic into focused `tradingagents/agents/price_action/` modules. The engine will consume normalized candles for Daily, 4H, 1H, M30, and M15, produce a structured BUY/SELL/HOLD payload, and optionally feed local order lifecycle/backtest code. Real demo broker connectivity is explicitly out of scope; implement a broker-agnostic local/simulated execution layer that can later be wired to MT5 or another XAUUSD broker.

**Tech Stack:** Python 3.10+, pandas, pydantic, pytest, LangChain tool wrapper, existing Typer CLI.

---

## Current State

The repo already has:

- `tradingagents/agents/utils/price_action_tools.py`: first deterministic detector pass for M30/M15, zones, wick rejection, break/retest, and risk math.
- `tradingagents/agents/execution/order_proposal.py`: local JSON order proposal writer.
- `docs/playbook.md`: full strategy rules.
- `tests/test_price_action_tools.py`: initial detector tests.

The next implementation should turn the current first-pass detector into a production-ready local engine, without connecting to a real broker account.

## File Structure

Create a focused package:

- Create `tradingagents/agents/price_action/__init__.py`
  - Exports stable data models and `analyze_playbook`.
- Create `tradingagents/agents/price_action/models.py`
  - Pydantic/dataclass-style models for candles, zones, checklist, setup, risk plan, pending order, managed position, and analysis payloads.
- Create `tradingagents/agents/price_action/candles.py`
  - OHLCV parsing, candle math, wick/body helpers, ATR, timeframe parsing, and 1H-to-4H resampling.
- Create `tradingagents/agents/price_action/sessions.py`
  - Session windows, pre-open block, Sunday Asian block, Monday London/New York preference, last-15-of-4H block.
- Create `tradingagents/agents/price_action/zones.py`
  - Swing detection, all-zone extraction, ATR-based zone tolerance, scoring, range detection, and nearest target lookup.
- Create `tradingagents/agents/price_action/structure.py`
  - Daily/4H/1H permission and M30 bias/context.
- Create `tradingagents/agents/price_action/setups.py`
  - Breakout, support/resistance rejection, break-and-retest, half/full retest depth, strong candle/engulfing checks.
- Create `tradingagents/agents/price_action/risk.py`
  - Gold pip conversion, SL/TP/R:R approval, clean range, break-even threshold config.
- Create `tradingagents/agents/price_action/lifecycle.py`
  - Local pending limit order activation/cancel rules, break-even update, M15 structure trailing, change-of-character exit.
- Create `tradingagents/agents/price_action/backtest.py`
  - Historical replay engine and metrics.
- Create `tradingagents/dataflows/price_action.py`
  - Fetch Daily, 1H, M30, M15, resample 4H, return normalized candles.
- Modify `tradingagents/agents/utils/price_action_tools.py`
  - Thin compatibility wrapper around the new modules.
- Modify `tradingagents/default_config.py`
  - Add price-action config keys.
- Modify `cli/main.py`
  - Add a local backtest/simulation command after the engine exists.

Tests:

- Create `tests/test_price_action_candles.py`
- Create `tests/test_price_action_sessions.py`
- Create `tests/test_price_action_zones.py`
- Create `tests/test_price_action_structure.py`
- Create `tests/test_price_action_setups.py`
- Create `tests/test_price_action_risk.py`
- Create `tests/test_price_action_lifecycle.py`
- Create `tests/test_price_action_backtest.py`
- Update `tests/test_price_action_tools.py`
- Update graph/order tests only if payload fields change.

---

### Task 1: Extract Price-Action Models and Candle Utilities

**Files:**
- Create: `tradingagents/agents/price_action/__init__.py`
- Create: `tradingagents/agents/price_action/models.py`
- Create: `tradingagents/agents/price_action/candles.py`
- Test: `tests/test_price_action_candles.py`
- Modify: `tradingagents/agents/utils/price_action_tools.py`

- [ ] **Step 1: Write failing tests for parsing, wick math, ATR, and 4H resampling**

Create `tests/test_price_action_candles.py`:

```python
import pytest

from tradingagents.agents.price_action.candles import (
    atr,
    lower_wick,
    parse_ohlcv_text,
    resample_candles,
    upper_wick,
    wick_ratio,
)


def test_parse_ohlcv_text_skips_comments_and_normalizes_columns():
    raw = "\n".join(
        [
            "# OHLCV data for XAUUSD",
            "Datetime,Open,High,Low,Close,Volume",
            "2026-05-18 08:00:00,2350,2355,2348,2354,1000",
        ]
    )

    candles = parse_ohlcv_text(raw)

    assert candles[0].timestamp == "2026-05-18 08:00:00"
    assert candles[0].open == 2350
    assert candles[0].high == 2355
    assert candles[0].low == 2348
    assert candles[0].close == 2354


def test_wick_helpers_measure_top_and_bottom_wicks():
    candle = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:00:00,2350,2356,2348,2354,1000"
    )[0]

    assert upper_wick(candle) == 2
    assert lower_wick(candle) == 2
    assert wick_ratio(candle, "upper") == pytest.approx(0.25)
    assert wick_ratio(candle, "lower") == pytest.approx(0.25)


def test_atr_uses_recent_true_ranges():
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:00:00,100,110,95,105,1000\n"
        "2026-05-18 09:00:00,105,112,101,110,1000\n"
        "2026-05-18 10:00:00,110,118,108,117,1000"
    )

    assert atr(candles, period=2) == pytest.approx(10.5)


def test_resample_1h_candles_to_4h():
    candles = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 00:00:00,100,102,99,101,10\n"
        "2026-05-18 01:00:00,101,103,100,102,20\n"
        "2026-05-18 02:00:00,102,105,101,104,30\n"
        "2026-05-18 03:00:00,104,106,103,105,40"
    )

    result = resample_candles(candles, "4h")

    assert len(result) == 1
    assert result[0].open == 100
    assert result[0].high == 106
    assert result[0].low == 99
    assert result[0].close == 105
    assert result[0].volume == 100
```

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
uv run --group dev pytest tests/test_price_action_candles.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.agents.price_action'
```

- [ ] **Step 3: Create models and candle utilities**

Create `tradingagents/agents/price_action/__init__.py`:

```python
"""Deterministic price-action detection engine."""

from .engine import analyze_playbook

__all__ = ["analyze_playbook"]
```

Create `tradingagents/agents/price_action/models.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Direction = Literal["BUY", "SELL", "HOLD"]
ZoneType = Literal["support", "resistance"]
ChecklistValue = Literal["passed", "failed", "unknown"]


@dataclass(frozen=True)
class Candle:
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0


@dataclass
class Zone:
    type: ZoneType
    timeframe: str
    low: float
    high: float
    midpoint: float
    touches: int
    score: int
    source: str
    reactions: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Setup:
    name: str
    direction: Direction
    zone: Zone
    entry_price: float
    stop_loss: float
    take_profit: float | None = None
    risk_distance: float | None = None
    reward_distance: float | None = None
    risk_reward: float | None = None
    retest_depth: float | None = None
    confirmation_candle: Candle | None = None


@dataclass
class PendingOrder:
    symbol: str
    side: Direction
    entry_price: float
    stop_loss: float
    take_profit: float
    candle_open: str
    expires_at: str
    status: Literal["PENDING", "TRIGGERED", "CANCELLED"]
```

Create `tradingagents/agents/price_action/candles.py` with functions matching the tests:

```python
from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Iterable

from .models import Candle


def parse_ohlcv_text(raw_data: str) -> list[Candle]:
    if not isinstance(raw_data, str) or not raw_data.strip():
        return []
    if raw_data.lstrip().startswith("No data found"):
        return []
    data_lines = [
        line
        for line in raw_data.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not data_lines:
        return []
    candles: list[Candle] = []
    for row in csv.DictReader(io.StringIO("\n".join(data_lines))):
        lowered = {str(key).strip().lower(): value for key, value in row.items()}
        timestamp = lowered.get("datetime") or lowered.get("timestamp") or lowered.get("date") or ""
        candles.append(
            Candle(
                timestamp=str(timestamp),
                open=float(lowered["open"]),
                high=float(lowered["high"]),
                low=float(lowered["low"]),
                close=float(lowered["close"]),
                volume=float(lowered.get("volume") or 0),
            )
        )
    return candles


def normalize_candles(data: str | Iterable[dict] | Iterable[Candle] | None) -> list[Candle]:
    if data is None:
        return []
    if isinstance(data, str):
        return parse_ohlcv_text(data)
    candles: list[Candle] = []
    for row in data:
        if isinstance(row, Candle):
            candles.append(row)
            continue
        lowered = {str(key).strip().lower(): value for key, value in row.items()}
        candles.append(
            Candle(
                timestamp=str(lowered.get("timestamp") or lowered.get("datetime") or lowered.get("date") or ""),
                open=float(lowered["open"]),
                high=float(lowered["high"]),
                low=float(lowered["low"]),
                close=float(lowered["close"]),
                volume=float(lowered.get("volume") or 0),
            )
        )
    return candles


def candle_range(candle: Candle) -> float:
    return max(candle.high - candle.low, 0.0)


def body_high(candle: Candle) -> float:
    return max(candle.open, candle.close)


def body_low(candle: Candle) -> float:
    return min(candle.open, candle.close)


def upper_wick(candle: Candle) -> float:
    return max(candle.high - body_high(candle), 0.0)


def lower_wick(candle: Candle) -> float:
    return max(body_low(candle) - candle.low, 0.0)


def wick_ratio(candle: Candle, side: str) -> float:
    total = candle_range(candle)
    if total <= 0:
        return 0.0
    return (lower_wick(candle) if side == "lower" else upper_wick(candle)) / total


def is_bullish(candle: Candle) -> bool:
    return candle.close > candle.open


def is_bearish(candle: Candle) -> bool:
    return candle.close < candle.open


def atr(candles: list[Candle], period: int = 14) -> float:
    if not candles:
        return 0.0
    ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        if previous_close is None:
            true_range = candle.high - candle.low
        else:
            true_range = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        ranges.append(true_range)
        previous_close = candle.close
    recent = ranges[-period:]
    return sum(recent) / len(recent)


def resample_candles(candles: list[Candle], timeframe: str) -> list[Candle]:
    if timeframe.lower() != "4h":
        return candles
    buckets: dict[datetime, list[Candle]] = {}
    for candle in candles:
        parsed = datetime.fromisoformat(candle.timestamp.replace(" ", "T"))
        bucket_start = parsed.replace(hour=(parsed.hour // 4) * 4, minute=0, second=0, microsecond=0)
        buckets.setdefault(bucket_start, []).append(candle)
    result: list[Candle] = []
    for bucket_start in sorted(buckets):
        group = buckets[bucket_start]
        result.append(
            Candle(
                timestamp=bucket_start.strftime("%Y-%m-%d %H:%M:%S"),
                open=group[0].open,
                high=max(c.high for c in group),
                low=min(c.low for c in group),
                close=group[-1].close,
                volume=sum(c.volume for c in group),
            )
        )
    return result
```

- [ ] **Step 4: Run the tests and verify they pass**

Run:

```bash
uv run --group dev pytest tests/test_price_action_candles.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/price_action tests/test_price_action_candles.py
git commit -m "feat: add price action candle utilities"
```

---

### Task 2: Add Configurable Session and Time Filters

**Files:**
- Create: `tradingagents/agents/price_action/sessions.py`
- Modify: `tradingagents/default_config.py`
- Test: `tests/test_price_action_sessions.py`

- [ ] **Step 1: Write failing tests for Asian/London/New York windows and blocks**

Create `tests/test_price_action_sessions.py`:

```python
from tradingagents.agents.price_action.sessions import evaluate_time_filters


def test_london_window_passes_on_monday():
    result = evaluate_time_filters("2026-05-18 04:00", "America/New_York")

    assert result["volume_time"] == "passed"
    assert result["not_sunday_asian_session"] == "passed"


def test_monday_early_asian_is_blocked():
    result = evaluate_time_filters("2026-05-18 01:00", "America/New_York")

    assert result["volume_time"] == "failed"


def test_exactly_15_minutes_before_new_york_open_is_blocked():
    result = evaluate_time_filters("2026-05-18 07:45", "America/New_York")

    assert result["not_15_min_before_open"] == "failed"
    assert result["volume_time"] == "failed"


def test_last_15_minutes_of_4h_candle_is_blocked():
    result = evaluate_time_filters("2026-05-18 07:50", "America/New_York")

    assert result["not_last_15_of_4h"] == "failed"


def test_sunday_asian_session_is_blocked():
    result = evaluate_time_filters("2026-05-17 19:30", "America/New_York")

    assert result["not_sunday_asian_session"] == "failed"
    assert result["volume_time"] == "failed"
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
uv run --group dev pytest tests/test_price_action_sessions.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.agents.price_action.sessions'
```

- [ ] **Step 3: Implement session evaluation**

Create `tradingagents/agents/price_action/sessions.py`:

```python
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

PASS = "passed"
FAIL = "failed"
UNKNOWN = "unknown"

DEFAULT_SESSION_OPENS = [time(19, 0), time(3, 0), time(8, 0)]
DEFAULT_SESSION_WINDOWS = [
    ("asian", time(19, 0), time(23, 59, 59)),
    ("london", time(3, 0), time(11, 0)),
    ("new_york", time(8, 0), time(12, 0)),
]


def parse_market_time(as_of: str, market_timezone: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(as_of).replace(" ", "T"))
    except ValueError:
        return None
    tz = ZoneInfo(market_timezone)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def in_window(current: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def minutes_before(dt: datetime, open_time: time) -> int:
    session_open = dt.replace(hour=open_time.hour, minute=open_time.minute, second=0, microsecond=0)
    if session_open < dt:
        session_open += timedelta(days=1)
    return int((session_open - dt).total_seconds() // 60)


def evaluate_time_filters(as_of: str, market_timezone: str = "America/New_York") -> dict[str, str]:
    dt = parse_market_time(as_of, market_timezone)
    if dt is None:
        return {
            "volume_time": UNKNOWN,
            "not_last_15_of_4h": UNKNOWN,
            "not_15_min_before_open": UNKNOWN,
            "not_sunday_asian_session": UNKNOWN,
        }
    current = dt.time()
    in_pre_open = any(0 <= minutes_before(dt, open_time) <= 15 for open_time in DEFAULT_SESSION_OPENS)
    in_last_15_of_4h = ((dt.hour + 1) % 4 == 0) and dt.minute >= 45
    is_sunday_asian = dt.weekday() == 6 and dt.hour >= 17
    is_monday_early_asian = dt.weekday() == 0 and dt.hour < 3
    in_session = any(in_window(current, start, end) for _, start, end in DEFAULT_SESSION_WINDOWS)
    hard_block = in_pre_open or in_last_15_of_4h or is_sunday_asian or is_monday_early_asian
    return {
        "volume_time": PASS if in_session and not hard_block else FAIL,
        "not_last_15_of_4h": FAIL if in_last_15_of_4h else PASS,
        "not_15_min_before_open": FAIL if in_pre_open else PASS,
        "not_sunday_asian_session": FAIL if is_sunday_asian else PASS,
    }
```

Modify `tradingagents/default_config.py` by adding these keys inside `DEFAULT_CONFIG`:

```python
    "price_action": {
        "market_timezone": "America/New_York",
        "session_windows": [
            {"name": "asian", "start": "19:00", "end": "23:59:59"},
            {"name": "london", "start": "03:00", "end": "11:00"},
            {"name": "new_york", "start": "08:00", "end": "12:00"},
        ],
        "session_open_block_minutes": 15,
        "monday_block_before_london": True,
    },
```

- [ ] **Step 4: Run the tests and verify they pass**

```bash
uv run --group dev pytest tests/test_price_action_sessions.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/price_action/sessions.py tradingagents/default_config.py tests/test_price_action_sessions.py
git commit -m "feat: add price action session filters"
```

---

### Task 3: Implement All-Zone Detection, Scoring, and Range Classification

**Files:**
- Create: `tradingagents/agents/price_action/zones.py`
- Test: `tests/test_price_action_zones.py`
- Modify: `tradingagents/agents/utils/price_action_tools.py`

- [ ] **Step 1: Write failing zone tests**

Create `tests/test_price_action_zones.py`:

```python
from tradingagents.agents.price_action.candles import parse_ohlcv_text
from tradingagents.agents.price_action.zones import (
    calculate_support_resistance,
    classify_range,
    nearest_target_zone,
)


def _candles():
    return parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 06:00:00,98,100,95.5,97,1000\n"
        "2026-05-18 06:30:00,99,105.0,98.0,104,1000\n"
        "2026-05-18 07:00:00,100,101,95.0,96,1000\n"
        "2026-05-18 07:30:00,100,104.8,97.0,104,1000\n"
        "2026-05-18 08:00:00,99,101,94.9,96,1000\n"
        "2026-05-18 08:30:00,99,103,98.0,102,1000"
    )


def test_detects_support_and_resistance_clusters():
    zones = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)

    assert any(zone.type == "support" and zone.touches == 2 for zone in zones)
    assert any(zone.type == "resistance" and zone.touches == 2 for zone in zones)


def test_scores_higher_timeframe_zones_above_lower_timeframe_zones():
    daily = calculate_support_resistance(_candles(), timeframe="1d", tolerance=0.5)[0]
    m30 = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)[0]

    assert daily.score > m30.score


def test_classifies_sideways_equal_highs_and_lows_as_range():
    zones = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)
    result = classify_range(_candles(), zones)

    assert result["market_type"] == "RANGE"
    assert result["support_zone"]["type"] == "support"
    assert result["resistance_zone"]["type"] == "resistance"


def test_nearest_target_zone_uses_opposite_zone():
    zones = calculate_support_resistance(_candles(), timeframe="30m", tolerance=0.5)
    target = nearest_target_zone(zones, direction="BUY", entry_price=96.0)

    assert target["type"] == "resistance"
    assert target["midpoint"] > 96.0
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
uv run --group dev pytest tests/test_price_action_zones.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.agents.price_action.zones'
```

- [ ] **Step 3: Move/refine zone logic into `zones.py`**

Implement `tradingagents/agents/price_action/zones.py` with these public functions:

```python
from __future__ import annotations

from .candles import atr
from .models import Candle, Zone


def timeframe_weight(timeframe: str) -> int:
    tf = timeframe.lower()
    if tf in {"1d", "d", "daily"}:
        return 5
    if tf in {"4h", "240m"}:
        return 4
    if tf in {"1h", "60m"}:
        return 3
    if tf in {"30m", "m30"}:
        return 2
    return 1


def default_zone_tolerance(candles: list[Candle], timeframe: str) -> float:
    current_atr = atr(candles)
    tf = timeframe.lower()
    multiplier = 0.30 if tf in {"1d", "d", "daily"} else 0.25 if tf in {"4h", "240m"} else 0.20 if tf in {"1h", "60m"} else 0.15
    return max(0.5, current_atr * multiplier)


def calculate_support_resistance(
    candles: list[Candle],
    timeframe: str,
    tolerance: float | None = None,
    min_touches: int = 2,
) -> list[Zone]:
    zone_tolerance = tolerance if tolerance is not None else default_zone_tolerance(candles, timeframe)
    swing_highs = []
    swing_lows = []
    for index in range(1, len(candles) - 1):
        previous_candle = candles[index - 1]
        candle = candles[index]
        next_candle = candles[index + 1]
        if candle.high > previous_candle.high and candle.high >= next_candle.high:
            swing_highs.append((candle.timestamp, candle.high))
        if candle.low < previous_candle.low and candle.low <= next_candle.low:
            swing_lows.append((candle.timestamp, candle.low))
    return _cluster(swing_lows, "support", timeframe, zone_tolerance, min_touches) + _cluster(
        swing_highs, "resistance", timeframe, zone_tolerance, min_touches
    )


def _cluster(points: list[tuple[str, float]], zone_type: str, timeframe: str, tolerance: float, min_touches: int) -> list[Zone]:
    clusters: list[list[tuple[str, float]]] = []
    for point in sorted(points, key=lambda item: item[1]):
        for cluster in clusters:
            midpoint = sum(price for _, price in cluster) / len(cluster)
            if abs(point[1] - midpoint) <= tolerance:
                cluster.append(point)
                break
        else:
            clusters.append([point])
    zones: list[Zone] = []
    for cluster in clusters:
        if len(cluster) < min_touches:
            continue
        prices = [price for _, price in cluster]
        low = min(prices) - tolerance
        high = max(prices) + tolerance
        touches = len(cluster)
        zones.append(
            Zone(
                type=zone_type,
                timeframe=timeframe,
                low=round(low, 4),
                high=round(high, 4),
                midpoint=round((low + high) / 2, 4),
                touches=touches,
                score=timeframe_weight(timeframe) + touches * 2,
                source="swing_cluster",
                reactions=[{"timestamp": timestamp, "price": round(price, 4)} for timestamp, price in cluster],
            )
        )
    return sorted(zones, key=lambda zone: zone.score, reverse=True)


def classify_range(candles: list[Candle], zones: list[Zone]) -> dict:
    support_zones = [zone for zone in zones if zone.type == "support"]
    resistance_zones = [zone for zone in zones if zone.type == "resistance"]
    if not support_zones or not resistance_zones:
        return {"market_type": "UNCLEAR"}
    support = max(support_zones, key=lambda zone: zone.score)
    resistance = max(resistance_zones, key=lambda zone: zone.score)
    closes_inside = [
        candle
        for candle in candles
        if support.low <= candle.close <= resistance.high
    ]
    inside_ratio = len(closes_inside) / len(candles) if candles else 0
    if support.touches >= 2 and resistance.touches >= 2 and inside_ratio >= 0.70:
        return {
            "market_type": "RANGE",
            "support_zone": zone_to_dict(support),
            "resistance_zone": zone_to_dict(resistance),
            "inside_close_ratio": round(inside_ratio, 4),
        }
    return {"market_type": "UNCLEAR"}


def nearest_target_zone(zones: list[Zone], direction: str, entry_price: float) -> dict | None:
    if direction == "BUY":
        candidates = [zone for zone in zones if zone.type == "resistance" and zone.midpoint > entry_price]
        selected = min(candidates, key=lambda zone: zone.midpoint, default=None)
    else:
        candidates = [zone for zone in zones if zone.type == "support" and zone.midpoint < entry_price]
        selected = max(candidates, key=lambda zone: zone.midpoint, default=None)
    return zone_to_dict(selected) if selected else None


def zone_to_dict(zone: Zone | None) -> dict | None:
    if zone is None:
        return None
    return {
        "type": zone.type,
        "timeframe": zone.timeframe,
        "low": zone.low,
        "high": zone.high,
        "midpoint": zone.midpoint,
        "touches": zone.touches,
        "score": zone.score,
        "source": zone.source,
        "reactions": zone.reactions,
    }
```

- [ ] **Step 4: Run zone tests**

```bash
uv run --group dev pytest tests/test_price_action_zones.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/price_action/zones.py tests/test_price_action_zones.py
git commit -m "feat: detect price action zones"
```

---

### Task 4: Add Top-Down Data Fetching Without Broker Execution

**Files:**
- Create: `tradingagents/dataflows/price_action.py`
- Modify: `tradingagents/agents/utils/price_action_tools.py`
- Test: `tests/test_price_action_dataflows.py`

- [ ] **Step 1: Write failing tests for multi-timeframe fetch orchestration**

Create `tests/test_price_action_dataflows.py`:

```python
from tradingagents.dataflows.price_action import fetch_price_action_timeframes


def test_fetches_all_required_timeframes_and_resamples_4h(monkeypatch):
    calls = []

    def fake_route(method, symbol, period, interval):
        calls.append((method, symbol, period, interval))
        return "\n".join(
            [
                "Datetime,Open,High,Low,Close,Volume",
                "2026-05-18 00:00:00,100,102,99,101,10",
                "2026-05-18 01:00:00,101,103,100,102,20",
                "2026-05-18 02:00:00,102,105,101,104,30",
                "2026-05-18 03:00:00,104,106,103,105,40",
            ]
        )

    monkeypatch.setattr("tradingagents.dataflows.price_action.route_to_vendor", fake_route)

    result = fetch_price_action_timeframes("XAUUSD")

    assert set(result) == {"1d", "4h", "1h", "30m", "15m"}
    assert ("get_intraday_price_data", "XAUUSD", "60d", "1h") in calls
    assert result["4h"][0].open == 100
    assert result["4h"][0].close == 105
```

- [ ] **Step 2: Run the test and verify it fails**

```bash
uv run --group dev pytest tests/test_price_action_dataflows.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.dataflows.price_action'
```

- [ ] **Step 3: Implement top-down data fetching**

Create `tradingagents/dataflows/price_action.py`:

```python
from __future__ import annotations

from tradingagents.agents.price_action.candles import parse_ohlcv_text, resample_candles
from tradingagents.dataflows.interface import route_to_vendor


def fetch_price_action_timeframes(symbol: str) -> dict[str, list]:
    daily_raw = route_to_vendor("get_intraday_price_data", symbol, "1y", "1d")
    one_hour_raw = route_to_vendor("get_intraday_price_data", symbol, "60d", "1h")
    thirty_raw = route_to_vendor("get_intraday_price_data", symbol, "10d", "30m")
    fifteen_raw = route_to_vendor("get_intraday_price_data", symbol, "10d", "15m")

    one_hour = parse_ohlcv_text(one_hour_raw)
    return {
        "1d": parse_ohlcv_text(daily_raw),
        "4h": resample_candles(one_hour, "4h"),
        "1h": one_hour,
        "30m": parse_ohlcv_text(thirty_raw),
        "15m": parse_ohlcv_text(fifteen_raw),
    }
```

- [ ] **Step 4: Wire the tool wrapper to use all timeframes**

Modify `tradingagents/agents/utils/price_action_tools.py` so `get_playbook_setups` fetches through `fetch_price_action_timeframes(symbol)` and passes all candle lists to the new engine. Keep existing function names `calculate_support_resistance`, `detect_breakouts`, `detect_sr_bounce`, `detect_break_and_retest`, and `analyze_playbook` as compatibility wrappers that call the new modules.

- [ ] **Step 5: Run tests**

```bash
uv run --group dev pytest tests/test_price_action_dataflows.py tests/test_price_action_tools.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 6: Commit**

```bash
git add tradingagents/dataflows/price_action.py tradingagents/agents/utils/price_action_tools.py tests/test_price_action_dataflows.py
git commit -m "feat: fetch price action timeframes"
```

---

### Task 5: Implement Higher-Timeframe Permission and M30 Bias

**Files:**
- Create: `tradingagents/agents/price_action/structure.py`
- Test: `tests/test_price_action_structure.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_price_action_structure.py`:

```python
from tradingagents.agents.price_action.structure import evaluate_higher_timeframe_permission, determine_m30_bias


def test_daily_block_rejects_trade():
    result = evaluate_higher_timeframe_permission(
        daily="SELL_ALLOWED",
        h4="BUY_ALLOWED",
        h1="BUY_ALLOWED",
        planned_direction="BUY",
    )

    assert result["permission"] == "NO_TRADE"
    assert "Daily blocks BUY" in result["reason"]


def test_h4_neutral_allows_if_daily_not_blocking_and_h1_agrees():
    result = evaluate_higher_timeframe_permission(
        daily="NEUTRAL",
        h4="NEUTRAL",
        h1="BUY_ALLOWED",
        planned_direction="BUY",
    )

    assert result["permission"] == "BUY_ALLOWED"


def test_h1_must_agree():
    result = evaluate_higher_timeframe_permission(
        daily="NEUTRAL",
        h4="NEUTRAL",
        h1="NEUTRAL",
        planned_direction="BUY",
    )

    assert result["permission"] == "NO_TRADE"


def test_m30_bias_comes_from_breakout_direction():
    result = determine_m30_bias([{"direction": "BUY", "name": "Breakout"}])

    assert result["m30_bias"] == "BULLISH"
    assert result["m30_context"] == "BREAKOUT"
```

- [ ] **Step 2: Run and verify failure**

```bash
uv run --group dev pytest tests/test_price_action_structure.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.agents.price_action.structure'
```

- [ ] **Step 3: Implement structure logic**

Create `tradingagents/agents/price_action/structure.py`:

```python
from __future__ import annotations


def evaluate_higher_timeframe_permission(daily: str, h4: str, h1: str, planned_direction: str) -> dict:
    wanted = f"{planned_direction}_ALLOWED"
    opposite = "SELL_ALLOWED" if planned_direction == "BUY" else "BUY_ALLOWED"
    if daily == opposite:
        return {"permission": "NO_TRADE", "reason": f"Daily blocks {planned_direction}"}
    if h4 == opposite:
        return {"permission": "NO_TRADE", "reason": f"4H blocks {planned_direction}"}
    if h1 != wanted:
        return {"permission": "NO_TRADE", "reason": f"1H does not agree with {planned_direction}"}
    return {"permission": wanted, "reason": "Higher timeframe permission passed"}


def determine_m30_bias(breakouts: list[dict]) -> dict:
    if not breakouts:
        return {"m30_bias": "UNCLEAR", "m30_context": "UNCLEAR"}
    direction = breakouts[0]["direction"]
    return {
        "m30_bias": "BULLISH" if direction == "BUY" else "BEARISH",
        "m30_context": breakouts[0]["name"].upper().replace(" ", "_"),
        "m30_breakout": breakouts[0],
    }
```

- [ ] **Step 4: Run tests**

```bash
uv run --group dev pytest tests/test_price_action_structure.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/price_action/structure.py tests/test_price_action_structure.py
git commit -m "feat: add higher timeframe permission"
```

---

### Task 6: Complete Setup Detection Rules

**Files:**
- Create: `tradingagents/agents/price_action/setups.py`
- Test: `tests/test_price_action_setups.py`
- Modify: `tradingagents/agents/utils/price_action_tools.py`

- [ ] **Step 1: Write setup tests**

Create `tests/test_price_action_setups.py`:

```python
from tradingagents.agents.price_action.candles import parse_ohlcv_text
from tradingagents.agents.price_action.models import Zone
from tradingagents.agents.price_action.setups import (
    detect_break_and_retest,
    detect_breakouts,
    detect_sr_bounce,
    is_strong_directional_close,
)


def _zone():
    return Zone(
        type="resistance",
        timeframe="30m",
        low=100,
        high=102,
        midpoint=101,
        touches=2,
        score=9,
        source="test",
    )


def test_strong_directional_close_accepts_bullish_step_candle():
    candle = parse_ohlcv_text("Datetime,Open,High,Low,Close,Volume\n2026-05-18 08:15:00,102,108,101,107,1000")[0]

    assert is_strong_directional_close(candle, "BUY") is True


def test_breakout_requires_close_outside_zone():
    candle = parse_ohlcv_text("Datetime,Open,High,Low,Close,Volume\n2026-05-18 08:15:00,101,103,100,102.5,1000")[0]

    result = detect_breakouts([candle], [_zone()])

    assert result[0]["direction"] == "BUY"


def test_retest_requires_half_zone_coverage_and_close_in_direction():
    candles = parse_ohlcv_text("Datetime,Open,High,Low,Close,Volume\n2026-05-18 08:15:00,103,104,101,103,1000")

    result = detect_break_and_retest(candles, [_zone()], direction="BUY")

    assert result[0]["retest_depth"] >= 0.5


def test_retest_rejects_full_close_back_inside_zone():
    candles = parse_ohlcv_text("Datetime,Open,High,Low,Close,Volume\n2026-05-18 08:15:00,103,104,101,101.5,1000")

    assert detect_break_and_retest(candles, [_zone()], direction="BUY") == []


def test_support_bounce_requires_wick_for_stop_loss():
    support = Zone(type="support", timeframe="1h", low=95, high=96, midpoint=95.5, touches=2, score=9, source="test")
    candles = parse_ohlcv_text("Datetime,Open,High,Low,Close,Volume\n2026-05-18 08:15:00,96,100,94.5,99,1000")

    result = detect_sr_bounce(candles, [support])

    assert result[0].direction == "BUY"
    assert result[0].stop_loss < 94.5
```

- [ ] **Step 2: Run and verify failure**

```bash
uv run --group dev pytest tests/test_price_action_setups.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.agents.price_action.setups'
```

- [ ] **Step 3: Implement setup detection using `models.Zone` and `models.Setup`**

Move existing setup logic from `price_action_tools.py` into `tradingagents/agents/price_action/setups.py`. Ensure:

- Breakout needs closed candle close outside zone.
- Retest allows small wick through zone.
- Retest needs at least `0.50` zone coverage.
- Full close back inside old zone invalidates retest.
- Buy needs lower wick for stop-loss.
- Sell needs upper wick for stop-loss.
- Strong directional close accepts engulfing or large step candle.

- [ ] **Step 4: Run setup tests**

```bash
uv run --group dev pytest tests/test_price_action_setups.py -q
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/price_action/setups.py tests/test_price_action_setups.py tradingagents/agents/utils/price_action_tools.py
git commit -m "feat: complete price action setup detection"
```

---

### Task 7: Implement Risk Approval, Clean Range, Gold Pip Conversion, and Targets

**Files:**
- Create: `tradingagents/agents/price_action/risk.py`
- Test: `tests/test_price_action_risk.py`
- Modify: `tradingagents/agents/price_action/setups.py`
- Modify: `tradingagents/agents/utils/price_action_tools.py`

- [ ] **Step 1: Write risk tests**

Create `tests/test_price_action_risk.py`:

```python
from tradingagents.agents.price_action.models import Setup, Zone
from tradingagents.agents.price_action.risk import (
    approve_risk,
    gold_points_to_pips,
    move_to_break_even_allowed,
)


def _setup(direction="BUY"):
    zone = Zone(type="support", timeframe="1h", low=95, high=96, midpoint=95.5, touches=2, score=9, source="test")
    return Setup(name="Support/Resistance Bounce", direction=direction, zone=zone, entry_price=100, stop_loss=98)


def test_gold_points_to_pips_uses_playbook_conversion():
    assert gold_points_to_pips(5.0) == 50


def test_approve_risk_requires_minimum_clean_range():
    target = {"type": "resistance", "midpoint": 106}

    result = approve_risk(_setup(), target_zone=target, minimum_rr=1.5, preferred_rr=3.0)

    assert result["approved"] is True
    assert result["risk_reward"] == 3.0
    assert result["take_profit"] == 106


def test_approve_risk_rejects_tight_target():
    target = {"type": "resistance", "midpoint": 102}

    result = approve_risk(_setup(), target_zone=target, minimum_rr=1.5, preferred_rr=3.0)

    assert result["approved"] is False
    assert result["reason"] == "Clean range is below minimum risk-to-reward"


def test_break_even_uses_fixed_gold_pips():
    assert move_to_break_even_allowed(entry=2350.00, current=2355.00, direction="BUY", threshold_pips=50) is True
```

- [ ] **Step 2: Run and verify failure**

```bash
uv run --group dev pytest tests/test_price_action_risk.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.agents.price_action.risk'
```

- [ ] **Step 3: Implement risk module**

Create `tradingagents/agents/price_action/risk.py`:

```python
from __future__ import annotations

from .models import Setup


def gold_points_to_pips(points: float) -> float:
    return round(points * 10, 4)


def approve_risk(setup: Setup, target_zone: dict | None, minimum_rr: float = 1.5, preferred_rr: float = 3.0) -> dict:
    if target_zone is None:
        return {"approved": False, "reason": "No target zone available"}
    risk = abs(setup.entry_price - setup.stop_loss)
    if risk <= 0:
        return {"approved": False, "reason": "Invalid stop-loss distance"}
    target_price = float(target_zone["midpoint"])
    reward = abs(target_price - setup.entry_price)
    risk_reward = round(reward / risk, 2)
    if risk_reward < minimum_rr:
        return {"approved": False, "reason": "Clean range is below minimum risk-to-reward"}
    capped_reward = min(reward, risk * preferred_rr)
    take_profit = setup.entry_price + capped_reward if setup.direction == "BUY" else setup.entry_price - capped_reward
    return {
        "approved": True,
        "entry_price": round(setup.entry_price, 4),
        "stop_loss": round(setup.stop_loss, 4),
        "take_profit": round(take_profit, 4),
        "risk_distance": round(risk, 4),
        "reward_distance": round(abs(take_profit - setup.entry_price), 4),
        "risk_reward": round(abs(take_profit - setup.entry_price) / risk, 2),
    }


def move_to_break_even_allowed(entry: float, current: float, direction: str, threshold_pips: float) -> bool:
    moved_points = current - entry if direction == "BUY" else entry - current
    return gold_points_to_pips(moved_points) >= threshold_pips
```

- [ ] **Step 4: Run risk tests**

```bash
uv run --group dev pytest tests/test_price_action_risk.py -q
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/price_action/risk.py tests/test_price_action_risk.py
git commit -m "feat: add price action risk approval"
```

---

### Task 8: Build the Full Top-Down Analysis Engine

**Files:**
- Create: `tradingagents/agents/price_action/engine.py`
- Modify: `tradingagents/agents/utils/price_action_tools.py`
- Test: `tests/test_price_action_engine.py`
- Update: `tests/test_price_action_tools.py`

- [ ] **Step 1: Write engine tests**

Create `tests/test_price_action_engine.py`:

```python
from tradingagents.agents.price_action.candles import parse_ohlcv_text
from tradingagents.agents.price_action.engine import analyze_playbook


def candles(raw_rows: str):
    return parse_ohlcv_text("Datetime,Open,High,Low,Close,Volume\n" + raw_rows)


def test_engine_approves_buy_when_top_down_and_m15_retest_align():
    data = {
        "1d": candles("2026-05-15 00:00:00,90,110,89,106,1000\n2026-05-16 00:00:00,106,112,101,110,1000\n2026-05-17 00:00:00,110,115,105,114,1000"),
        "4h": candles("2026-05-18 00:00:00,98,105,95,104,1000\n2026-05-18 04:00:00,104,108,102,107,1000\n2026-05-18 08:00:00,107,112,105,111,1000"),
        "1h": candles("2026-05-18 06:00:00,100,105,99,104,1000\n2026-05-18 07:00:00,104,108,103,107,1000\n2026-05-18 08:00:00,107,112,105,111,1000"),
        "30m": candles("2026-05-18 05:30:00,98,100,95.5,97,1000\n2026-05-18 06:00:00,99,105,98,104,1000\n2026-05-18 06:30:00,100,101,95,96,1000\n2026-05-18 07:00:00,100,104.8,97,104,1000\n2026-05-18 07:30:00,99,101,94.9,96,1000\n2026-05-18 08:00:00,101,107.2,100.5,106.8,1000"),
        "15m": candles("2026-05-18 07:45:00,105.5,106.1,104.7,105.4,1000\n2026-05-18 08:00:00,105.9,106.5,104.8,106.2,1000\n2026-05-18 08:15:00,106,107.2,104.9,106.9,1000"),
    }

    payload = analyze_playbook("XAUUSD", "2026-05-18 08:30", data, market_timezone="America/New_York")

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["checklist"]["timeframe_correlation"] == "passed"
    assert payload["checklist"]["clean_range_to_fill"] == "passed"


def test_engine_rejects_when_time_filter_fails():
    data = {"1d": [], "4h": [], "1h": [], "30m": [], "15m": []}

    payload = analyze_playbook("XAUUSD", "2026-05-17 19:30", data, market_timezone="America/New_York")

    assert payload["status"] == "NO_SETUP"
    assert payload["checklist"]["not_sunday_asian_session"] == "failed"
```

- [ ] **Step 2: Run and verify failure**

```bash
uv run --group dev pytest tests/test_price_action_engine.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.agents.price_action.engine'
```

- [ ] **Step 3: Implement `engine.py`**

Implement `tradingagents/agents/price_action/engine.py` to:

1. Evaluate time filters.
2. Detect zones for `1d`, `4h`, `1h`, and `30m`.
3. Classify ranges.
4. Determine Daily/4H/1H permissions.
5. Determine M30 bias from breakout/context.
6. Detect M15 entry setup.
7. Require M30 direction = M15 setup direction.
8. Find nearest target zone.
9. Run risk approval.
10. Return JSON-serializable payload with:

```python
{
    "symbol": symbol.upper(),
    "as_of": as_of,
    "status": "SETUP_FOUND" or "NO_SETUP",
    "recommendation": "BUY" or "SELL" or "HOLD",
    "setups": [...],
    "zones": [...],
    "market_context": {...},
    "checklist": {...},
    "risk": {...},
    "message": "...",
}
```

- [ ] **Step 4: Keep public tool compatibility**

Modify `tradingagents/agents/utils/price_action_tools.py` so existing imports still work:

```python
from tradingagents.agents.price_action.engine import analyze_playbook
from tradingagents.agents.price_action.sessions import evaluate_time_filters
from tradingagents.agents.price_action.setups import detect_break_and_retest, detect_breakouts, detect_sr_bounce
from tradingagents.agents.price_action.zones import calculate_support_resistance
```

Wrap dataclass results into dictionaries where existing tests expect dictionaries.

- [ ] **Step 5: Run engine and existing tool tests**

```bash
uv run --group dev pytest tests/test_price_action_engine.py tests/test_price_action_tools.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/price_action/engine.py tradingagents/agents/utils/price_action_tools.py tests/test_price_action_engine.py tests/test_price_action_tools.py
git commit -m "feat: add top down price action engine"
```

---

### Task 9: Implement Local Order Lifecycle Without Broker Connection

**Files:**
- Create: `tradingagents/agents/price_action/lifecycle.py`
- Test: `tests/test_price_action_lifecycle.py`
- Modify: `tradingagents/agents/execution/order_proposal.py`

- [ ] **Step 1: Write lifecycle tests**

Create `tests/test_price_action_lifecycle.py`:

```python
from tradingagents.agents.price_action.lifecycle import (
    build_pending_order,
    cancel_stale_order,
    trigger_pending_order,
)


def test_pending_limit_order_expires_after_first_10_minutes_of_m15_candle():
    order = build_pending_order(
        symbol="XAUUSD",
        side="BUY",
        entry_price=2350.0,
        stop_loss=2348.0,
        take_profit=2356.0,
        candle_open="2026-05-18 08:30",
    )

    assert order.expires_at == "2026-05-18 08:40"


def test_order_triggers_if_price_hits_entry_before_expiry():
    order = build_pending_order("XAUUSD", "BUY", 2350.0, 2348.0, 2356.0, "2026-05-18 08:30")

    result = trigger_pending_order(order, current_time="2026-05-18 08:35", high=2352, low=2349.8)

    assert result.status == "TRIGGERED"


def test_order_cancels_if_not_triggered_after_expiry():
    order = build_pending_order("XAUUSD", "BUY", 2350.0, 2348.0, 2356.0, "2026-05-18 08:30")

    result = cancel_stale_order(order, current_time="2026-05-18 08:41")

    assert result.status == "CANCELLED"
```

- [ ] **Step 2: Run and verify failure**

```bash
uv run --group dev pytest tests/test_price_action_lifecycle.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.agents.price_action.lifecycle'
```

- [ ] **Step 3: Implement lifecycle module**

Create `tradingagents/agents/price_action/lifecycle.py`:

```python
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from .models import PendingOrder


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace(" ", "T"))


def build_pending_order(symbol: str, side: str, entry_price: float, stop_loss: float, take_profit: float, candle_open: str) -> PendingOrder:
    opened = _parse(candle_open)
    expires = opened + timedelta(minutes=10)
    return PendingOrder(
        symbol=symbol,
        side=side,
        entry_price=entry_price,
        stop_loss=stop_loss,
        take_profit=take_profit,
        candle_open=opened.strftime("%Y-%m-%d %H:%M"),
        expires_at=expires.strftime("%Y-%m-%d %H:%M"),
        status="PENDING",
    )


def trigger_pending_order(order: PendingOrder, current_time: str, high: float, low: float) -> PendingOrder:
    if order.status != "PENDING":
        return order
    if _parse(current_time) > _parse(order.expires_at):
        return replace(order, status="CANCELLED")
    hit = low <= order.entry_price <= high
    return replace(order, status="TRIGGERED") if hit else order


def cancel_stale_order(order: PendingOrder, current_time: str) -> PendingOrder:
    if order.status == "PENDING" and _parse(current_time) > _parse(order.expires_at):
        return replace(order, status="CANCELLED")
    return order
```

- [ ] **Step 4: Add lifecycle metadata to local order proposal**

Modify `tradingagents/agents/execution/order_proposal.py` to include pending order timing fields in the JSON artifact when entry/SL/TP are present:

```python
"activation_window_minutes": 10,
"cancel_if_not_triggered_after": valid_until,
```

Keep the existing `OrderProposal` model backward-compatible by adding optional fields with defaults.

- [ ] **Step 5: Run lifecycle and order proposal tests**

```bash
uv run --group dev pytest tests/test_price_action_lifecycle.py tests/test_order_proposal.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/price_action/lifecycle.py tradingagents/agents/execution/order_proposal.py tests/test_price_action_lifecycle.py tests/test_order_proposal.py
git commit -m "feat: add local order lifecycle"
```

---

### Task 10: Implement Break-Even, M15 Trailing, and Change-of-Character Management

**Files:**
- Modify: `tradingagents/agents/price_action/lifecycle.py`
- Test: `tests/test_price_action_lifecycle.py`

- [ ] **Step 1: Add management tests**

Append to `tests/test_price_action_lifecycle.py`:

```python
from tradingagents.agents.price_action.lifecycle import (
    move_stop_to_break_even,
    trail_stop_from_m15_structure,
)


def test_moves_stop_to_break_even_after_50_pips_profit():
    position = {
        "side": "BUY",
        "entry_price": 2350.0,
        "stop_loss": 2348.0,
        "current_price": 2355.0,
    }

    result = move_stop_to_break_even(position, threshold_pips=50)

    assert result["stop_loss"] == 2350.0
    assert result["management_action"] == "MOVE_TO_BREAK_EVEN"


def test_trails_buy_stop_below_new_higher_low():
    position = {"side": "BUY", "entry_price": 2350.0, "stop_loss": 2350.0}
    m15_structure = [{"higher_low": 2352.0}, {"higher_low": 2354.0}]

    result = trail_stop_from_m15_structure(position, m15_structure, buffer_points=0.2)

    assert result["stop_loss"] == 2353.8
    assert result["management_action"] == "TRAIL_STOP"


def test_trails_sell_stop_above_new_lower_high():
    position = {"side": "SELL", "entry_price": 2350.0, "stop_loss": 2350.0}
    m15_structure = [{"lower_high": 2348.0}, {"lower_high": 2346.0}]

    result = trail_stop_from_m15_structure(position, m15_structure, buffer_points=0.2)

    assert result["stop_loss"] == 2346.2
    assert result["management_action"] == "TRAIL_STOP"
```

- [ ] **Step 2: Run and verify failure**

```bash
uv run --group dev pytest tests/test_price_action_lifecycle.py -q
```

Expected:

```text
ImportError: cannot import name 'move_stop_to_break_even'
```

- [ ] **Step 3: Implement management functions**

Append to `tradingagents/agents/price_action/lifecycle.py`:

```python
from .risk import gold_points_to_pips


def move_stop_to_break_even(position: dict, threshold_pips: float) -> dict:
    side = position["side"]
    entry = float(position["entry_price"])
    current = float(position["current_price"])
    moved_points = current - entry if side == "BUY" else entry - current
    if gold_points_to_pips(moved_points) < threshold_pips:
        return {**position, "management_action": "HOLD_STOP"}
    return {**position, "stop_loss": entry, "management_action": "MOVE_TO_BREAK_EVEN"}


def trail_stop_from_m15_structure(position: dict, m15_structure: list[dict], buffer_points: float) -> dict:
    side = position["side"]
    if side == "BUY":
        higher_lows = [item["higher_low"] for item in m15_structure if "higher_low" in item]
        if not higher_lows:
            return {**position, "management_action": "HOLD_STOP"}
        new_stop = max(higher_lows) - buffer_points
        if new_stop <= position["stop_loss"]:
            return {**position, "management_action": "HOLD_STOP"}
        return {**position, "stop_loss": round(new_stop, 4), "management_action": "TRAIL_STOP"}
    lower_highs = [item["lower_high"] for item in m15_structure if "lower_high" in item]
    if not lower_highs:
        return {**position, "management_action": "HOLD_STOP"}
    new_stop = min(lower_highs) + buffer_points
    if new_stop >= position["stop_loss"]:
        return {**position, "management_action": "HOLD_STOP"}
    return {**position, "stop_loss": round(new_stop, 4), "management_action": "TRAIL_STOP"}
```

- [ ] **Step 4: Run lifecycle tests**

```bash
uv run --group dev pytest tests/test_price_action_lifecycle.py -q
```

Expected:

```text
6 passed
```

- [ ] **Step 5: Commit**

```bash
git add tradingagents/agents/price_action/lifecycle.py tests/test_price_action_lifecycle.py
git commit -m "feat: add local trade management"
```

---

### Task 11: Add Historical Backtest/Simulation Engine

**Files:**
- Create: `tradingagents/agents/price_action/backtest.py`
- Create: `tests/test_price_action_backtest.py`
- Modify: `cli/main.py`

- [ ] **Step 1: Write backtest tests**

Create `tests/test_price_action_backtest.py`:

```python
from tradingagents.agents.price_action.backtest import summarize_backtest


def test_summarize_backtest_reports_core_metrics():
    trades = [
        {"result_r": -1.0, "setup": "Break and Retest", "session": "london", "zone_timeframe": "4h"},
        {"result_r": 3.0, "setup": "Break and Retest", "session": "new_york", "zone_timeframe": "1h"},
        {"result_r": 4.0, "setup": "Support/Resistance Bounce", "session": "new_york", "zone_timeframe": "1d"},
    ]

    summary = summarize_backtest(trades)

    assert summary["trade_count"] == 3
    assert summary["win_rate"] == 66.67
    assert summary["average_win_r"] == 3.5
    assert summary["average_loss_r"] == -1.0
    assert summary["net_r"] == 6.0
```

- [ ] **Step 2: Run and verify failure**

```bash
uv run --group dev pytest tests/test_price_action_backtest.py -q
```

Expected:

```text
ModuleNotFoundError: No module named 'tradingagents.agents.price_action.backtest'
```

- [ ] **Step 3: Implement summary metrics**

Create `tradingagents/agents/price_action/backtest.py`:

```python
from __future__ import annotations


def summarize_backtest(trades: list[dict]) -> dict:
    wins = [trade for trade in trades if trade["result_r"] > 0]
    losses = [trade for trade in trades if trade["result_r"] <= 0]
    trade_count = len(trades)
    win_rate = round((len(wins) / trade_count) * 100, 2) if trade_count else 0.0
    average_win = round(sum(trade["result_r"] for trade in wins) / len(wins), 2) if wins else 0.0
    average_loss = round(sum(trade["result_r"] for trade in losses) / len(losses), 2) if losses else 0.0
    net_r = round(sum(trade["result_r"] for trade in trades), 2)
    return {
        "trade_count": trade_count,
        "win_rate": win_rate,
        "average_win_r": average_win,
        "average_loss_r": average_loss,
        "net_r": net_r,
    }
```

- [ ] **Step 4: Add CLI backtest command**

Modify `cli/main.py` by adding:

```python
@app.command()
def backtest(
    symbol: str = typer.Option("XAUUSD", "--symbol"),
):
    console.print(f"[yellow]Backtest simulation scaffold ready for {symbol}.[/yellow]")
    console.print("[yellow]Use the price_action.backtest module with historical fixtures or fetched candles.[/yellow]")
```

This command is intentionally local-only and does not place orders.

- [ ] **Step 5: Run backtest and CLI tests**

```bash
uv run --group dev pytest tests/test_price_action_backtest.py tests/test_cli_timeframe.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/price_action/backtest.py tests/test_price_action_backtest.py cli/main.py
git commit -m "feat: add price action backtest metrics"
```

---

### Task 12: Integrate Tool Output, Reports, and Full Regression

**Files:**
- Modify: `tradingagents/agents/utils/price_action_tools.py`
- Modify: `tradingagents/agents/analysts/market_analyst.py`
- Modify: `tradingagents/agents/trader/trader.py`
- Modify: `tests/test_price_action_graph.py`
- Modify: `tests/test_order_proposal.py`

- [ ] **Step 1: Add regression test for structured payload fields**

Append to `tests/test_price_action_tools.py`:

```python
def test_get_playbook_setups_payload_contains_engine_sections(monkeypatch):
    def fake_fetch(symbol):
        from tradingagents.agents.price_action.candles import parse_ohlcv_text
        candles = parse_ohlcv_text(
            "Datetime,Open,High,Low,Close,Volume\n"
            "2026-05-18 08:00:00,100,105,99,104,1000\n"
            "2026-05-18 08:15:00,104,108,103,107,1000"
        )
        return {"1d": candles, "4h": candles, "1h": candles, "30m": candles, "15m": candles}

    monkeypatch.setattr("tradingagents.agents.utils.price_action_tools.fetch_price_action_timeframes", fake_fetch)

    raw = get_playbook_setups.invoke(
        {
            "symbol": "XAUUSD",
            "as_of": "2026-05-18 08:30",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
        }
    )
    payload = json.loads(raw)

    assert "checklist" in payload
    assert "market_context" in payload
    assert "zones" in payload
    assert "setups" in payload
```

- [ ] **Step 2: Run and verify failure or old-shape mismatch**

```bash
uv run --group dev pytest tests/test_price_action_tools.py::test_get_playbook_setups_payload_contains_engine_sections -q
```

Expected:

```text
FAIL
```

The failure should be due to the tool not yet using `fetch_price_action_timeframes` or missing one of the expected sections.

- [ ] **Step 3: Finalize tool payload compatibility**

Ensure `get_playbook_setups` returns JSON with these top-level keys for both `SETUP_FOUND` and `NO_SETUP`:

```python
[
    "symbol",
    "as_of",
    "timeframe",
    "confirmation_timeframe",
    "status",
    "recommendation",
    "setups",
    "checklist",
    "zones",
    "market_context",
    "message",
]
```

Update analyst/trader prompts only if they need the new fields named explicitly.

- [ ] **Step 4: Run focused integration tests**

```bash
uv run --group dev pytest tests/test_price_action_tools.py tests/test_price_action_graph.py tests/test_order_proposal.py tests/test_signal_processing.py -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 5: Run full test suite**

```bash
uv run --group dev pytest -q
```

Expected:

```text
all tests passed
```

- [ ] **Step 6: Commit**

```bash
git add tradingagents/agents/utils/price_action_tools.py tradingagents/agents/analysts/market_analyst.py tradingagents/agents/trader/trader.py tests
git commit -m "feat: integrate complete price action engine"
```

---

## Execution Notes

- Keep real broker/demo-account connectivity out of scope.
- Do implement local/simulated order lifecycle and trade management because they do not require broker credentials.
- Keep every detector deterministic. The LLM may explain the tool payload, but it must not invent setups.
- Preserve the existing `get_playbook_setups` tool name so the graph does not need a routing rewrite.
- Keep local order proposals safe: no live orders, no broker API calls.
- Prefer `NO_SETUP` / `HOLD` whenever a required checklist item is missing, failed, or unknown.

## Verification Commands

Run after each task:

```bash
uv run --group dev pytest <task-specific-tests> -q
```

Run before declaring implementation complete:

```bash
uv run --group dev pytest -q
```

Expected final result:

```text
all tests passed
```

## Self-Review

Spec coverage:

- Trading windows: Task 2.
- Sunday Asian block: Task 2.
- Last 15 minutes of 4H block: Task 2.
- 15 minutes before session open block: Task 2.
- Daily/4H/1H permission: Task 5.
- M30 bias and M15 entry confirmation: Tasks 5, 6, and 8.
- Auto zones only: Task 3.
- All zones logged/scored/tested: Task 3 and Task 11.
- Ranging market: Task 3.
- Breakout and break/retest: Task 6.
- Retest half/full wick-zone coverage: Task 6.
- Wick rejection: Task 6.
- Limit order at wick/retest price: Tasks 6, 7, and 9.
- Cancel order after first 10 minutes of M15 candle: Task 9.
- Stop-loss beyond wick with buffer: Tasks 6 and 7.
- Gold pip conversion: Task 7.
- Break-even: Task 10.
- M15 structure trailing: Task 10.
- Fixed R:R and clean range: Task 7.
- Backtesting/simulation: Task 11.
- Broker-generic future path without broker connection: Task 9 and Execution Notes.

Placeholder scan:

- No unresolved placeholder markers.
- No undefined file paths.
- Broker connection is explicitly out of scope, not left ambiguous.

Type consistency:

- `Candle`, `Zone`, `Setup`, and `PendingOrder` are defined before later tasks use them.
- Public tool compatibility functions remain named as the existing code expects.
