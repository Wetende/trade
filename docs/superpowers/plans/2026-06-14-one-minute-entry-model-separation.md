# One Minute Entry Model Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the directional engine into two isolated entry models so the 1m model can only trade the equal-high/equal-low candle story, while the 15m/30m model keeps the existing A+/B+ price-action playbook.

**Architecture:** `tradingagents/agents/price_action/engine.py` becomes a thin dispatcher. The 15m/30m model moves into `normal_entry_model.py`; the 1m model lives in `one_minute_entry_model.py` and must not call generic breakout, support/resistance bounce, or break-and-retest detectors. Shared files remain limited to candles, models, structure, zones, risk, and payload helpers.

**Tech Stack:** Python, pytest, MetaTrader 5 execution integration, existing TradingAgents price-action package.

---

## Non-Negotiable Behavior

- The 1m model uses the last 60 closed 1m candles as history.
- The 1m model does not use `detect_breakouts`, `detect_break_and_retest`, or `detect_sr_bounce`.
- The 1m model does not emit generic setup names: `Breakout`, `Support/Resistance Bounce`, `Aggressive Respect`, or vague `Confirmed Break`.
- The 1m model emits explicit trigger names only:
  - `LOW_RESPECT_BUY`
  - `HIGH_RESPECT_SELL`
  - `LOW_BREAK_SELL`
  - `HIGH_BREAK_BUY`
  - `FAILED_LOW_BREAK_BUY`
  - `FAILED_HIGH_BREAK_SELL`
- The 1m model returns HOLD when the candle story is unclear, even if old generic detectors would have found a trade.
- Base volume remains the MT5 configured volume.
- `volume_multiplier=1.5` is allowed only for clean equal-level reversal/fakeout triggers:
  - `LOW_RESPECT_BUY`
  - `HIGH_RESPECT_SELL`
  - `FAILED_LOW_BREAK_BUY`
  - `FAILED_HIGH_BREAK_SELL`
- `volume_multiplier=1.5` is not allowed for raw break triggers:
  - `LOW_BREAK_SELL`
  - `HIGH_BREAK_BUY`
- The normal 15m/30m model keeps the existing playbook and may still use breakout, support/resistance, break-and-retest, and impulse logic.

---

## File Structure

### Create

- `tradingagents/agents/price_action/one_minute_entry_model.py`
  - Owns all 1m trigger detection, confidence, risk, volume multiplier, and payload generation.
  - Must not import generic setup detectors from `tradingagents.agents.price_action.setups`.

- `tradingagents/agents/price_action/normal_entry_model.py`
  - Owns current 15m/30m deterministic playbook logic.
  - May use generic setup detectors and higher-timeframe context.

- `tradingagents/agents/price_action/payloads.py`
  - Shared payload/telemetry helpers only.
  - No setup detection.

- `tests/test_one_minute_entry_model.py`
  - Direct tests for 1m trigger families, volume rules, unclear-story holds, and forbidden generic setup leakage.

### Modify

- `tradingagents/agents/price_action/engine.py`
  - Replace monolithic implementation with a thin dispatcher.

- `tests/test_price_action_engine.py`
  - Keep normal model tests.
  - Update fast-profile tests to assert explicit 1m trigger behavior.

- `tests/test_order_proposal.py`
  - Update expectations from old `Confirmed Break`/`Aggressive Respect` names to explicit 1m trigger names where relevant.

- `tests/test_engine_decision.py`
  - Update report label tests so 1m reports say `1m Trigger`, `1m History`, and explicit trigger family.

### Do Not Modify

- `tradingagents/brokers/mt5.py`
- `tradingagents/brokers/mt5_execution.py`
- `tradingagents/brokers/mt5_runner.py`

Broker execution is not the root issue in this refactor.

---

### Task 1: Add Failing Integration Tests For Fast-Model Isolation

**Files:**
- Modify: `tests/test_price_action_engine.py`

- [ ] **Step 1: Add a test proving fast 1m never calls generic setup detectors**

Add this test near the existing fast-profile tests:

```python
def test_fast_one_minute_profile_does_not_call_generic_setup_detectors(monkeypatch):
    data = {
        "1m": candles(
            "2026-06-10 09:50:00,100.0,100.6,99.8,100.2,1000\n"
            "2026-06-10 09:51:00,100.2,100.8,100.0,100.4,1000\n"
            "2026-06-10 09:52:00,100.4,101.0,100.2,100.7,1000\n"
            "2026-06-10 09:53:00,100.7,101.2,100.5,101.0,1000\n"
            "2026-06-10 09:54:00,101.0,101.5,100.8,101.3,1000"
        )
    }

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("fast 1m model must not call generic setup detectors")

    monkeypatch.setattr(engine, "detect_breakouts", fail_if_called, raising=False)
    monkeypatch.setattr(engine, "detect_break_and_retest", fail_if_called, raising=False)
    monkeypatch.setattr(engine, "detect_sr_bounce", fail_if_called, raising=False)

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "zone_timeframes": ("1m",),
            "context_timeframes": ("1m",),
            "governing_timeframes": ("1m",),
            "fast_history_window_candles": 60,
            "fast_min_trigger_candles": 3,
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["telemetry"]["decision_stage"] == "one_minute_no_trigger"
```

- [ ] **Step 2: Run the failing test**

Run:

```bash
uv run --group dev pytest tests/test_price_action_engine.py::test_fast_one_minute_profile_does_not_call_generic_setup_detectors -q
```

Expected before implementation:

```text
FAILED ... AssertionError: fast 1m model must not call generic setup detectors
```

- [ ] **Step 3: Add a test proving unclear 1m story cannot trade**

Add:

```python
def test_fast_one_minute_profile_holds_when_story_is_unclear():
    data = {
        "1m": candles(
            "2026-06-10 10:00:00,100.0,100.7,99.7,100.1,1000\n"
            "2026-06-10 10:01:00,100.1,100.8,99.8,100.3,1000\n"
            "2026-06-10 10:02:00,100.3,101.0,100.0,100.5,1000\n"
            "2026-06-10 10:03:00,100.5,101.1,100.2,100.6,1000\n"
            "2026-06-10 10:04:00,100.6,101.2,100.4,100.8,1000"
        )
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 10:05",
        data,
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "zone_timeframes": ("1m",),
            "context_timeframes": ("1m",),
            "governing_timeframes": ("1m",),
            "fast_history_window_candles": 60,
            "fast_min_trigger_candles": 3,
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["market_context"]["one_minute_story"]["classification"] == "UNCLEAR"
```

- [ ] **Step 4: Run the failing unclear-story test**

Run:

```bash
uv run --group dev pytest tests/test_price_action_engine.py::test_fast_one_minute_profile_holds_when_story_is_unclear -q
```

Expected before implementation:

```text
FAILED
```

The current system can still approve generic fast setups in unclear 1m history.

---

### Task 2: Add Direct Tests For The Dedicated 1m Trigger Model

**Files:**
- Create: `tests/test_one_minute_entry_model.py`
- Create later: `tradingagents/agents/price_action/one_minute_entry_model.py`

- [ ] **Step 1: Add direct test file**

Create `tests/test_one_minute_entry_model.py`:

```python
from pathlib import Path

from tradingagents.agents.price_action.candles import parse_ohlcv_text
from tradingagents.agents.price_action.one_minute_entry_model import (
    HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS,
    analyze_one_minute_entry,
)


def candles(raw_rows: str):
    return parse_ohlcv_text("Datetime,Open,High,Low,Close,Volume\n" + raw_rows)


def fast_config(**overrides):
    config = {
        "time_filter_mode": "allow",
        "entry_profile": "fast",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "fast_history_window_candles": 60,
        "fast_min_trigger_candles": 3,
        "minimum_setup_grade": "B_PLUS",
        "minimum_stop_distance_price": 0.3,
        "one_minute_max_stop_distance_price": 2.0,
        "one_minute_boost_max_stop_distance_price": 1.2,
    }
    config.update(overrides)
    return config


def test_low_respect_buy_uses_explicit_trigger_and_boost_volume():
    payload = analyze_one_minute_entry(
        "XAUUSD",
        "2026-06-10 09:55",
        {"1m": candles(
            "2026-06-10 09:50:00,2000.0,2000.8,1998.6,1999.4,1000\n"
            "2026-06-10 09:51:00,1999.4,2001.0,1998.0,2000.7,1000\n"
            "2026-06-10 09:52:00,2000.7,2001.4,1999.7,2001.0,1000\n"
            "2026-06-10 09:53:00,2001.0,2001.2,1999.2,1999.8,1000\n"
            "2026-06-10 09:54:00,1999.8,2000.7,1998.1,2000.4,1000"
        )},
        market_timezone="America/New_York",
        session_config=fast_config(),
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"
    assert payload["risk"]["volume_multiplier"] == 1.5
    assert payload["risk"]["position_lifecycle"] == "FAST_PARTIAL_SCALE"
    assert payload["market_context"]["one_minute_story"]["classification"] == "LOW_RESPECT"


def test_high_respect_sell_uses_explicit_trigger_and_boost_volume():
    payload = analyze_one_minute_entry(
        "XAUUSD",
        "2026-06-10 10:07",
        {"1m": candles(
            "2026-06-10 10:02:00,2002.0,2005.0,2001.0,2002.1,1000\n"
            "2026-06-10 10:03:00,2002.1,2003.0,2000.7,2001.0,1000\n"
            "2026-06-10 10:04:00,2001.0,2004.9,2000.9,2001.7,1000\n"
            "2026-06-10 10:05:00,2001.7,2002.2,2000.8,2001.0,1000\n"
            "2026-06-10 10:06:00,2001.0,2001.2,1999.4,1999.7,1000"
        )},
        market_timezone="America/New_York",
        session_config=fast_config(),
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "HIGH_RESPECT_SELL"
    assert payload["risk"]["volume_multiplier"] == 1.5
    assert payload["market_context"]["one_minute_story"]["classification"] == "HIGH_RESPECT"


def test_low_break_sell_uses_base_volume():
    payload = analyze_one_minute_entry(
        "XAUUSD",
        "2026-06-10 10:22",
        {"1m": candles(
            "2026-06-10 10:17:00,2000.0,2000.8,1998.0,1999.5,1000\n"
            "2026-06-10 10:18:00,1999.5,2001.0,1998.0,2000.4,1000\n"
            "2026-06-10 10:19:00,2000.4,2001.1,1999.0,1999.4,1000\n"
            "2026-06-10 10:20:00,1999.4,2000.2,1998.1,1998.5,1000\n"
            "2026-06-10 10:21:00,1998.5,1999.0,1997.2,1997.5,1000"
        )},
        market_timezone="America/New_York",
        session_config=fast_config(),
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "LOW_BREAK_SELL"
    assert payload["risk"].get("volume_multiplier") is None


def test_high_break_buy_uses_base_volume():
    payload = analyze_one_minute_entry(
        "XAUUSD",
        "2026-06-10 10:32",
        {"1m": candles(
            "2026-06-10 10:27:00,100.0,102.0,99.5,101.0,1000\n"
            "2026-06-10 10:28:00,101.0,102.1,100.4,100.8,1000\n"
            "2026-06-10 10:29:00,100.8,101.7,100.1,100.6,1000\n"
            "2026-06-10 10:30:00,100.6,102.0,100.2,101.4,1000\n"
            "2026-06-10 10:31:00,101.4,103.2,101.2,103.0,1000"
        )},
        market_timezone="America/New_York",
        session_config=fast_config(),
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "HIGH_BREAK_BUY"
    assert payload["risk"].get("volume_multiplier") is None


def test_failed_low_break_buy_uses_boost_volume():
    payload = analyze_one_minute_entry(
        "XAUUSD",
        "2026-06-10 10:42",
        {"1m": candles(
            "2026-06-10 10:37:00,100.0,100.8,98.0,99.4,1000\n"
            "2026-06-10 10:38:00,99.4,100.4,98.1,99.8,1000\n"
            "2026-06-10 10:39:00,99.8,100.2,98.4,99.1,1000\n"
            "2026-06-10 10:40:00,99.1,99.8,97.7,98.4,1000\n"
            "2026-06-10 10:41:00,98.4,100.5,97.6,100.2,1000"
        )},
        market_timezone="America/New_York",
        session_config=fast_config(),
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "FAILED_LOW_BREAK_BUY"
    assert payload["risk"]["volume_multiplier"] == 1.5


def test_failed_high_break_sell_uses_boost_volume():
    payload = analyze_one_minute_entry(
        "XAUUSD",
        "2026-06-10 10:52",
        {"1m": candles(
            "2026-06-10 10:47:00,100.0,102.0,99.6,101.5,1000\n"
            "2026-06-10 10:48:00,101.5,101.9,100.4,101.0,1000\n"
            "2026-06-10 10:49:00,101.0,102.1,100.8,101.7,1000\n"
            "2026-06-10 10:50:00,101.7,102.4,101.0,102.2,1000\n"
            "2026-06-10 10:51:00,102.2,102.5,99.9,100.1,1000"
        )},
        market_timezone="America/New_York",
        session_config=fast_config(),
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "FAILED_HIGH_BREAK_SELL"
    assert payload["risk"]["volume_multiplier"] == 1.5


def test_unclear_story_holds_without_setup():
    payload = analyze_one_minute_entry(
        "XAUUSD",
        "2026-06-10 11:05",
        {"1m": candles(
            "2026-06-10 11:00:00,100.0,100.5,99.8,100.1,1000\n"
            "2026-06-10 11:01:00,100.1,100.6,99.9,100.2,1000\n"
            "2026-06-10 11:02:00,100.2,100.7,100.0,100.3,1000\n"
            "2026-06-10 11:03:00,100.3,100.8,100.1,100.4,1000\n"
            "2026-06-10 11:04:00,100.4,100.9,100.2,100.5,1000"
        )},
        market_timezone="America/New_York",
        session_config=fast_config(),
    )

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["market_context"]["one_minute_story"]["classification"] == "UNCLEAR"


def test_one_minute_model_source_does_not_import_generic_setup_detectors():
    source = Path("tradingagents/agents/price_action/one_minute_entry_model.py").read_text()
    forbidden = [
        "detect_breakouts",
        "detect_break_and_retest",
        "detect_sr_bounce",
        "Support/Resistance Bounce",
        '"Breakout"',
        '"Confirmed Break"',
        '"Aggressive Respect"',
    ]
    for needle in forbidden:
        assert needle not in source


def test_only_high_confidence_equal_level_triggers_can_boost_volume():
    assert HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS == {
        "LOW_RESPECT_BUY",
        "HIGH_RESPECT_SELL",
        "FAILED_LOW_BREAK_BUY",
        "FAILED_HIGH_BREAK_SELL",
    }
```

- [ ] **Step 2: Run direct model tests and verify import failure**

Run:

```bash
uv run --group dev pytest tests/test_one_minute_entry_model.py -q
```

Expected before implementation:

```text
FAILED ... ModuleNotFoundError: No module named 'tradingagents.agents.price_action.one_minute_entry_model'
```

---

### Task 3: Create The Dedicated 1m Entry Model

**Files:**
- Create: `tradingagents/agents/price_action/one_minute_entry_model.py`

- [ ] **Step 1: Create module with explicit trigger constants and model API**

Create `tradingagents/agents/price_action/one_minute_entry_model.py` with:

```python
"""Dedicated one-minute equal-level entry model."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from tradingagents.agents.price_action.candles import (
    body_high,
    body_low,
    candle_range,
    is_bearish,
    is_bullish,
    lower_wick,
    normalize_candles,
    upper_wick,
    wick_ratio,
)
from tradingagents.agents.price_action.models import Candle, Setup, Zone


ONE_MINUTE_TRIGGER_NAMES = {
    "LOW_RESPECT_BUY",
    "HIGH_RESPECT_SELL",
    "LOW_BREAK_SELL",
    "HIGH_BREAK_BUY",
    "FAILED_LOW_BREAK_BUY",
    "FAILED_HIGH_BREAK_SELL",
}

HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS = {
    "LOW_RESPECT_BUY",
    "HIGH_RESPECT_SELL",
    "FAILED_LOW_BREAK_BUY",
    "FAILED_HIGH_BREAK_SELL",
}

DEFAULT_HISTORY_WINDOW_CANDLES = 60
DEFAULT_MIN_TRIGGER_CANDLES = 3


@dataclass(frozen=True)
class OneMinuteTrigger:
    name: str
    direction: str
    level: float
    entry_price: float
    stop_loss: float
    confirmation_candle: Candle
    confidence: str
    story: dict[str, Any]


def analyze_one_minute_entry(
    symbol: str,
    as_of: str,
    timeframe_data: dict[str, Any],
    market_timezone: str = "America/New_York",
    session_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = session_config or {}
    candles = normalize_candles(timeframe_data.get("1m", []))
    history_window = _positive_int(
        config.get("fast_history_window_candles"),
        DEFAULT_HISTORY_WINDOW_CANDLES,
    )
    min_trigger_candles = max(
        DEFAULT_MIN_TRIGGER_CANDLES,
        _positive_int(
            config.get("fast_min_trigger_candles"),
            DEFAULT_MIN_TRIGGER_CANDLES,
        ),
    )
    history = candles[-history_window:]
    market_context = _one_minute_market_context(
        history,
        history_window=history_window,
        min_trigger_candles=min_trigger_candles,
    )

    if len(history) < min_trigger_candles:
        return _hold_payload(
            symbol,
            as_of,
            market_context,
            "Insufficient closed 1m candles. Default to HOLD.",
            decision_stage="data_insufficient",
        )

    trigger = _select_cleanest_trigger(history, config)
    if trigger is None:
        market_context["one_minute_story"]["classification"] = "UNCLEAR"
        return _hold_payload(
            symbol,
            as_of,
            market_context,
            "No clean 1m equal-level trigger. Default to HOLD.",
            decision_stage="one_minute_no_trigger",
        )

    risk = _risk_for_trigger(trigger, config)
    if not risk["approved"]:
        market_context["one_minute_story"] = trigger.story
        return _hold_payload(
            symbol,
            as_of,
            market_context,
            str(risk["reason"]),
            decision_stage="one_minute_risk_filter",
            setup=_setup_from_trigger(trigger),
            risk=risk,
        )

    setup = _setup_from_trigger(trigger)
    market_context["one_minute_story"] = trigger.story
    return {
        "symbol": symbol,
        "as_of": as_of,
        "status": "SETUP_FOUND",
        "recommendation": trigger.direction,
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "entry_profile": "fast",
        "activation_window_minutes": int(config.get("activation_window_minutes", 6)),
        "checklist": {
            "candle_closed": "passed",
            "playbook_setup": "passed",
            "one_minute_trigger": "passed",
            "clean_range_to_fill": "passed",
            "fast_trigger_quality": "passed",
        },
        "zones": [],
        "market_context": market_context,
        "setups": [_setup_to_dict(setup, risk, "A_PLUS")],
        "risk": risk,
        "message": f"One-minute trigger {trigger.name} passed.",
        "telemetry": {
            "decision_stage": "one_minute_setup_found",
            "primary_hold_reason": None,
            "candidate_setup_count": 1,
            "approved_candidate_count": 1,
            "timeframe_rows": {"1m": len(candles)},
            "market_context": market_context,
            "candidate_evaluations": [
                {
                    "approved": True,
                    "setup_grade": "A_PLUS",
                    "setup": _setup_to_dict(setup, risk, "A_PLUS"),
                    "risk": risk,
                    "trigger": asdict(trigger),
                }
            ],
        },
    }
```

- [ ] **Step 2: Add the trigger-detection helpers in the same file**

Add:

```python
def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _one_minute_market_context(
    history: list[Candle],
    *,
    history_window: int,
    min_trigger_candles: int,
) -> dict[str, Any]:
    return {
        "entry_profile": "fast",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "one_minute_story": {
            "classification": "UNCLEAR",
            "history_window_candles": history_window,
            "evaluated_history_candles": len(history),
            "trigger_window_min_candles": min_trigger_candles,
            "trigger_selection": "cleanest_recent_story",
        },
        "fast_microstructure": {
            "enabled": True,
            "entry_timeframe": "1m",
            "window_timeframe": "1m",
            "history_window_candles": history_window,
            "evaluated_history_candles": len(history),
            "trigger_window_min_candles": min_trigger_candles,
            "trigger_selection": "cleanest_recent_story",
            "rules": sorted(ONE_MINUTE_TRIGGER_NAMES),
        },
    }


def _median_range(candles: list[Candle]) -> float:
    ranges = sorted(candle_range(candle) for candle in candles if candle_range(candle) > 0)
    if not ranges:
        return 0.2
    return ranges[len(ranges) // 2]


def _level_tolerance(candles: list[Candle]) -> float:
    return max(0.2, _median_range(candles[-12:]) * 0.20)


def _stop_buffer(candles: list[Candle]) -> float:
    return max(0.15, _median_range(candles[-8:]) * 0.15)


def _find_equal_lows(candles: list[Candle], tolerance: float) -> tuple[Candle, Candle, float] | None:
    prior = candles[:-1]
    for second_index in range(len(prior) - 1, 0, -1):
        second = prior[second_index]
        for first_index in range(second_index - 1, -1, -1):
            first = prior[first_index]
            if abs(float(first.low) - float(second.low)) <= tolerance:
                return first, second, min(float(first.low), float(second.low))
    return None


def _find_equal_highs(candles: list[Candle], tolerance: float) -> tuple[Candle, Candle, float] | None:
    prior = candles[:-1]
    for second_index in range(len(prior) - 1, 0, -1):
        second = prior[second_index]
        for first_index in range(second_index - 1, -1, -1):
            first = prior[first_index]
            if abs(float(first.high) - float(second.high)) <= tolerance:
                return first, second, max(float(first.high), float(second.high))
    return None


def _bullish_rejection(candle: Candle) -> bool:
    return (
        is_bullish(candle)
        and lower_wick(candle) > 0
        and wick_ratio(candle, "lower") >= 0.20
        and candle.close >= candle.low + candle_range(candle) * 0.60
    )


def _bearish_rejection(candle: Candle) -> bool:
    return (
        is_bearish(candle)
        and upper_wick(candle) > 0
        and wick_ratio(candle, "upper") >= 0.20
        and candle.close <= candle.high - candle_range(candle) * 0.60
    )


def _strong_bearish_break(candle: Candle, level: float) -> bool:
    return is_bearish(candle) and candle.close < level and wick_ratio(candle, "lower") <= 0.35


def _strong_bullish_break(candle: Candle, level: float) -> bool:
    return is_bullish(candle) and candle.close > level and wick_ratio(candle, "upper") <= 0.35


def _failed_low_break(candle: Candle, level: float) -> bool:
    return candle.low < level and candle.close > level and _bullish_rejection(candle)


def _failed_high_break(candle: Candle, level: float) -> bool:
    return candle.high > level and candle.close < level and _bearish_rejection(candle)


def _trigger(
    name: str,
    direction: str,
    level: float,
    entry: float,
    stop: float,
    candle: Candle,
    confidence: str,
) -> OneMinuteTrigger:
    return OneMinuteTrigger(
        name=name,
        direction=direction,
        level=round(float(level), 4),
        entry_price=round(float(entry), 4),
        stop_loss=round(float(stop), 4),
        confirmation_candle=candle,
        confidence=confidence,
        story={
            "classification": name.rsplit("_", 1)[0],
            "trigger_name": name,
            "direction": direction,
            "level": round(float(level), 4),
            "confidence": confidence,
        },
    )


def _select_cleanest_trigger(
    history: list[Candle],
    config: dict[str, Any],
) -> OneMinuteTrigger | None:
    latest = history[-1]
    tolerance = _level_tolerance(history)
    buffer = _stop_buffer(history)
    lows = _find_equal_lows(history, tolerance)
    highs = _find_equal_highs(history, tolerance)
    triggers: list[OneMinuteTrigger] = []

    if lows is not None:
        _first, _second, level = lows
        if _failed_low_break(latest, level):
            triggers.append(_trigger("FAILED_LOW_BREAK_BUY", "BUY", level, latest.close, latest.low - buffer, latest, "HIGH"))
        elif _strong_bearish_break(latest, level):
            triggers.append(_trigger("LOW_BREAK_SELL", "SELL", level, latest.close, latest.high + buffer, latest, "NORMAL"))
        elif abs(float(latest.low) - level) <= tolerance and _bullish_rejection(latest):
            triggers.append(_trigger("LOW_RESPECT_BUY", "BUY", level, latest.high, min(level, latest.low) - buffer, latest, "HIGH"))

    if highs is not None:
        _first, _second, level = highs
        if _failed_high_break(latest, level):
            triggers.append(_trigger("FAILED_HIGH_BREAK_SELL", "SELL", level, latest.close, latest.high + buffer, latest, "HIGH"))
        elif _strong_bullish_break(latest, level):
            triggers.append(_trigger("HIGH_BREAK_BUY", "BUY", level, latest.close, latest.low - buffer, latest, "NORMAL"))
        elif abs(float(latest.high) - level) <= tolerance and _bearish_rejection(latest):
            triggers.append(_trigger("HIGH_RESPECT_SELL", "SELL", level, latest.low, max(level, latest.high) + buffer, latest, "HIGH"))

    if not triggers:
        return None

    priority = {
        "FAILED_LOW_BREAK_BUY": 0,
        "FAILED_HIGH_BREAK_SELL": 0,
        "LOW_RESPECT_BUY": 1,
        "HIGH_RESPECT_SELL": 1,
        "LOW_BREAK_SELL": 2,
        "HIGH_BREAK_BUY": 2,
    }
    return sorted(triggers, key=lambda item: priority[item.name])[0]
```

- [ ] **Step 3: Add risk and payload helpers in the same file**

Add:

```python
def _setup_from_trigger(trigger: OneMinuteTrigger) -> Setup:
    zone_type = "support" if "LOW" in trigger.name else "resistance"
    zone = Zone(
        type=zone_type,
        timeframe="1m",
        low=trigger.level,
        high=trigger.level,
        midpoint=trigger.level,
        touches=2,
        score=24.0 if trigger.confidence == "HIGH" else 18.0,
        source=f"one_minute_{trigger.name.lower()}",
    )
    return Setup(
        name=trigger.name,
        direction=trigger.direction,
        zone=zone,
        entry_price=trigger.entry_price,
        stop_loss=trigger.stop_loss,
        confirmation_candle=trigger.confirmation_candle,
    )


def _risk_for_trigger(trigger: OneMinuteTrigger, config: dict[str, Any]) -> dict[str, Any]:
    entry = float(trigger.entry_price)
    stop = float(trigger.stop_loss)
    risk_distance = abs(entry - stop)
    max_stop = float(config.get("one_minute_max_stop_distance_price", 2.0))
    boost_max_stop = float(config.get("one_minute_boost_max_stop_distance_price", 1.2))
    if risk_distance <= 0:
        return {"approved": False, "reason": "Invalid one-minute stop distance."}
    if risk_distance > max_stop:
        return {
            "approved": False,
            "reason": (
                "One-minute stop distance is too wide: "
                f"distance={risk_distance:.2f}, maximum={max_stop:.2f}"
            ),
        }

    preferred_rr = 1.5
    reward = risk_distance * preferred_rr
    take_profit = entry + reward if trigger.direction == "BUY" else entry - reward
    risk = {
        "approved": True,
        "entry_price": round(entry, 4),
        "stop_loss": round(stop, 4),
        "take_profit": round(take_profit, 4),
        "risk_distance": round(risk_distance, 4),
        "reward_distance": round(reward, 4),
        "risk_reward": preferred_rr,
        "available_risk_reward": preferred_rr,
        "risk_model": "ONE_MINUTE_EQUAL_LEVEL_SCALP",
        "one_minute_trigger": trigger.name,
        "one_minute_confidence": trigger.confidence,
        "break_even_trigger_points": round(max(0.35, min(0.8, risk_distance * 0.55)), 2),
        "break_even_lock_points": round(max(0.05, min(0.15, risk_distance * 0.10)), 2),
        "partial_first_trigger_points": round(max(0.4, min(1.0, risk_distance * 0.70)), 2),
        "partial_first_target_volume": 1.0,
        "partial_second_trigger_points": round(max(0.6, min(1.5, risk_distance * 1.00)), 2),
        "partial_second_target_volume": 0.4,
        "trailing_trigger_points": round(max(0.6, min(1.5, risk_distance * 1.00)), 2),
        "trailing_distance_points": round(max(0.25, min(0.8, risk_distance * 0.40)), 2),
        "position_lifecycle": "FAST_PARTIAL_SCALE",
    }
    if (
        trigger.name in HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS
        and risk_distance <= boost_max_stop
    ):
        risk["volume_multiplier"] = 1.5
    return risk


def _setup_to_dict(setup: Setup, risk: dict[str, Any] | None = None, setup_grade: str | None = None) -> dict[str, Any]:
    result = {
        "name": setup.name,
        "direction": setup.direction,
        "zone": {
            "type": setup.zone.type,
            "timeframe": setup.zone.timeframe,
            "low": setup.zone.low,
            "high": setup.zone.high,
            "midpoint": setup.zone.midpoint,
            "touches": setup.zone.touches,
            "score": setup.zone.score,
            "source": setup.zone.source,
        },
        "entry_price": setup.entry_price,
        "stop_loss": setup.stop_loss,
        "confirmation_candle": {
            "timestamp": setup.confirmation_candle.timestamp,
            "open": setup.confirmation_candle.open,
            "high": setup.confirmation_candle.high,
            "low": setup.confirmation_candle.low,
            "close": setup.confirmation_candle.close,
            "volume": setup.confirmation_candle.volume,
        },
    }
    if setup_grade:
        result["setup_grade"] = setup_grade
    if risk and risk.get("approved"):
        for key in (
            "take_profit",
            "risk_distance",
            "reward_distance",
            "risk_reward",
            "volume_multiplier",
            "position_lifecycle",
            "one_minute_trigger",
            "one_minute_confidence",
            "break_even_trigger_points",
            "break_even_lock_points",
            "partial_first_trigger_points",
            "partial_first_target_volume",
            "partial_second_trigger_points",
            "partial_second_target_volume",
            "trailing_trigger_points",
            "trailing_distance_points",
        ):
            if key in risk:
                result[key] = risk[key]
    return result


def _hold_payload(
    symbol: str,
    as_of: str,
    market_context: dict[str, Any],
    message: str,
    *,
    decision_stage: str,
    setup: Setup | None = None,
    risk: dict[str, Any] | None = None,
) -> dict[str, Any]:
    setups = [_setup_to_dict(setup, risk)] if setup is not None else []
    return {
        "symbol": symbol,
        "as_of": as_of,
        "status": "NO_SETUP",
        "recommendation": "HOLD",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "entry_profile": "fast",
        "activation_window_minutes": 6,
        "checklist": {
            "candle_closed": "passed",
            "playbook_setup": "failed",
            "one_minute_trigger": "failed",
            "clean_range_to_fill": "failed" if risk and not risk.get("approved") else "unknown",
            "fast_trigger_quality": "failed",
        },
        "zones": [],
        "market_context": market_context,
        "setups": setups,
        "risk": risk or {"approved": False},
        "message": message,
        "telemetry": {
            "decision_stage": decision_stage,
            "primary_hold_reason": message,
            "candidate_setup_count": len(setups),
            "approved_candidate_count": 0,
            "market_context": market_context,
            "timeframe_rows": {
                "1m": market_context["one_minute_story"]["evaluated_history_candles"]
            },
            "candidate_evaluations": [],
        },
    }
```

- [ ] **Step 4: Run direct model tests**

Run:

```bash
uv run --group dev pytest tests/test_one_minute_entry_model.py -q
```

Expected:

```text
8 passed
```

---

### Task 4: Move Normal Model Out Of The Shared Engine

**Files:**
- Move: `tradingagents/agents/price_action/engine.py` to `tradingagents/agents/price_action/normal_entry_model.py`
- Create: `tradingagents/agents/price_action/engine.py`

- [ ] **Step 1: Move the existing monolithic engine to the normal model file**

Run:

```bash
git mv tradingagents/agents/price_action/engine.py tradingagents/agents/price_action/normal_entry_model.py
```

- [ ] **Step 2: Rename the old public function in `normal_entry_model.py`**

In `tradingagents/agents/price_action/normal_entry_model.py`, change:

```python
def analyze_playbook(
```

to:

```python
def analyze_normal_entry(
```

- [ ] **Step 3: Delete old fast/micro logic from `normal_entry_model.py`**

Remove these names entirely from `normal_entry_model.py`:

```text
FAST_MICRO_SETUP_NAMES
DEFAULT_FAST_HISTORY_WINDOW_CANDLES
DEFAULT_FAST_MIN_TRIGGER_CANDLES
_fast_micro_signal
_fast_trigger_quality
_fast_micro_confidence
_dynamic_fast_exit_settings
_is_fast_profile
_clear_fast_window_direction
_micro_tolerance
_micro_zone
_micro_stop_buffer
_micro_setup
_find_respected_low
_find_respected_high
_find_broken_respected_lows
_find_broken_respected_highs
_find_confirmed_respected_lows
_find_confirmed_respected_highs
_detect_fast_microstructure_setups
_approve_micro_scalp_risk
```

- [ ] **Step 4: Simplify normal candidate generation**

In `analyze_normal_entry`, candidate generation must become:

```python
candidate_setups = _unique_setups(
    [
        *detect_breakouts(entry_candles, entry_reference_zones),
        *detect_break_and_retest(
            entry_candles,
            entry_reference_zones,
            direction=confirmation_direction,
        ),
        *detect_sr_bounce(entry_candles, entry_reference_zones),
    ]
)
```

Remove `micro_setups` and all `is_micro_setup` branches. Normal logic may keep:

```python
approve_risk(...)
evaluate_higher_timeframe_permission(...)
confirmation_context_clear
timeframe_correlation
```

- [ ] **Step 5: Create the new dispatcher `engine.py`**

Create `tradingagents/agents/price_action/engine.py`:

```python
"""Price-action engine dispatcher.

The engine routes to exactly one deterministic entry model:
- normal 15m/30m directional playbook
- fast 1m equal-level candle-story model
"""

from __future__ import annotations

from typing import Any

from tradingagents.agents.price_action.normal_entry_model import analyze_normal_entry
from tradingagents.agents.price_action.one_minute_entry_model import analyze_one_minute_entry


def analyze_playbook(
    symbol: str,
    as_of: str,
    timeframe_data: dict[str, Any],
    market_timezone: str = "America/New_York",
    session_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    config = session_config or {}
    profile_name = str(config.get("entry_profile", "normal")).strip().lower()
    timeframe = str(config.get("timeframe", "15m")).strip().lower()
    if profile_name == "fast" and timeframe in {"1m", "m1"}:
        return analyze_one_minute_entry(
            symbol,
            as_of,
            timeframe_data,
            market_timezone=market_timezone,
            session_config=session_config,
        )
    return analyze_normal_entry(
        symbol,
        as_of,
        timeframe_data,
        market_timezone=market_timezone,
        session_config=session_config,
    )
```

- [ ] **Step 6: Run isolation tests**

Run:

```bash
uv run --group dev pytest tests/test_price_action_engine.py::test_fast_one_minute_profile_does_not_call_generic_setup_detectors tests/test_price_action_engine.py::test_fast_one_minute_profile_holds_when_story_is_unclear -q
```

Expected:

```text
2 passed
```

---

### Task 5: Update Existing Fast Tests To Explicit Trigger Names

**Files:**
- Modify: `tests/test_price_action_engine.py`

- [ ] **Step 1: Replace old fast setup-name assertions**

Update assertions:

```python
assert payload["setups"][0]["name"] == "Aggressive Respect"
```

to:

```python
assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"
```

Update assertions:

```python
assert payload["setups"][0]["name"] == "Confirmed Break"
```

to the correct explicit trigger for the fixture:

```python
assert payload["setups"][0]["name"] in {
    "LOW_BREAK_SELL",
    "HIGH_BREAK_BUY",
    "FAILED_LOW_BREAK_BUY",
    "FAILED_HIGH_BREAK_SELL",
}
```

For tests with known fixture direction, use exact names:

```python
assert payload["setups"][0]["name"] == "LOW_BREAK_SELL"
```

or:

```python
assert payload["setups"][0]["name"] == "HIGH_BREAK_BUY"
```

- [ ] **Step 2: Delete tests that intentionally monkeypatch generic detectors for fast**

Delete or rewrite these old fast tests because they encode the behavior we are removing:

```text
test_fast_engine_rejects_entry_against_one_minute_market_state
test_fast_engine_rejects_entries_when_confirmation_context_is_unclear
test_fast_engine_requires_a_plus_when_counter_higher_timeframe_bias
```

Replace them with tests against explicit 1m model behavior:

```python
def test_fast_one_minute_does_not_need_confirmation_context():
    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 09:55",
        {
            "1m": candles(
                "2026-06-10 09:50:00,2000.0,2000.8,1998.6,1999.4,1000\n"
                "2026-06-10 09:51:00,1999.4,2001.0,1998.0,2000.7,1000\n"
                "2026-06-10 09:52:00,2000.7,2001.4,1999.7,2001.0,1000\n"
                "2026-06-10 09:53:00,2001.0,2001.2,1999.2,1999.8,1000\n"
                "2026-06-10 09:54:00,1999.8,2000.7,1998.1,2000.4,1000"
            )
        },
        market_timezone="America/New_York",
        session_config={
            "time_filter_mode": "allow",
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "fast_history_window_candles": 60,
            "fast_min_trigger_candles": 3,
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.3,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"
    assert payload["confirmation_timeframe"] == "1m"
```

- [ ] **Step 3: Run price-action engine tests**

Run:

```bash
uv run --group dev pytest tests/test_price_action_engine.py -q
```

Expected:

```text
passed
```

---

### Task 6: Update Order Proposal And Report Tests

**Files:**
- Modify: `tests/test_order_proposal.py`
- Modify: `tests/test_engine_decision.py`

- [ ] **Step 1: Update order proposal tests**

In `tests/test_order_proposal.py`, replace fast setup test payloads using:

```python
"name": "Confirmed Break"
```

with:

```python
"name": "LOW_RESPECT_BUY"
```

and add:

```python
"one_minute_trigger": "LOW_RESPECT_BUY",
"one_minute_confidence": "HIGH",
```

inside the risk payload.

Assert:

```python
assert proposal["setup_name"] == "LOW_RESPECT_BUY"
assert proposal["strategy_type"] == "LOW_RESPECT_BUY"
assert proposal["volume_multiplier"] == 1.5
assert proposal["position_lifecycle"] == "FAST_PARTIAL_SCALE"
```

- [ ] **Step 2: Update strategy type mapping if needed**

If `_strategy_type_from_setup()` in `tradingagents/agents/execution/order_proposal.py` normalizes unknown setup names to a generic value, add:

```python
ONE_MINUTE_TRIGGER_TYPES = {
    "LOW_RESPECT_BUY",
    "HIGH_RESPECT_SELL",
    "LOW_BREAK_SELL",
    "HIGH_BREAK_BUY",
    "FAILED_LOW_BREAK_BUY",
    "FAILED_HIGH_BREAK_SELL",
}
```

and return the setup name unchanged for those.

- [ ] **Step 3: Run proposal/report tests**

Run:

```bash
uv run --group dev pytest tests/test_order_proposal.py tests/test_engine_decision.py -q
```

Expected:

```text
passed
```

---

### Task 7: Static Guard Against Future Mixing

**Files:**
- Create or modify: `tests/test_one_minute_entry_model.py`

- [ ] **Step 1: Add static no-mixing assertions**

Add:

```python
def test_one_minute_model_does_not_contain_old_fast_setup_names():
    source = Path("tradingagents/agents/price_action/one_minute_entry_model.py").read_text()
    assert "Aggressive Respect" not in source
    assert "Confirmed Break" not in source
    assert "Support/Resistance Bounce" not in source
    assert '"Breakout"' not in source
```

- [ ] **Step 2: Add dispatcher static assertion**

Add:

```python
def test_engine_dispatcher_has_no_setup_detection_logic():
    source = Path("tradingagents/agents/price_action/engine.py").read_text()
    forbidden = [
        "detect_breakouts",
        "detect_break_and_retest",
        "detect_sr_bounce",
        "_detect_fast_microstructure_setups",
        "_find_respected_low",
        "_find_respected_high",
    ]
    for needle in forbidden:
        assert needle not in source
```

- [ ] **Step 3: Run static guard tests**

Run:

```bash
uv run --group dev pytest tests/test_one_minute_entry_model.py::test_one_minute_model_does_not_contain_old_fast_setup_names tests/test_one_minute_entry_model.py::test_engine_dispatcher_has_no_setup_detection_logic -q
```

Expected:

```text
2 passed
```

---

### Task 8: Run Full Verification

**Files:**
- No code edits.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run --group dev pytest tests/test_one_minute_entry_model.py tests/test_price_action_engine.py tests/test_order_proposal.py tests/test_engine_decision.py -q
```

Expected:

```text
passed
```

- [ ] **Step 2: Run full suite**

Run:

```bash
uv run --group dev pytest
```

Expected:

```text
0 failed
```

- [ ] **Step 3: Confirm no old fast logic remains in dispatcher**

Run:

```bash
rg "Aggressive Respect|Confirmed Break|_detect_fast_microstructure|detect_breakouts|detect_sr_bounce|detect_break_and_retest" tradingagents/agents/price_action/engine.py tradingagents/agents/price_action/one_minute_entry_model.py
```

Expected:

```text
no matches
```

- [ ] **Step 4: Confirm normal model still owns generic playbook logic**

Run:

```bash
rg "detect_breakouts|detect_sr_bounce|detect_break_and_retest" tradingagents/agents/price_action/normal_entry_model.py
```

Expected:

```text
matches in normal_entry_model.py
```

- [ ] **Step 5: Do not restart live runner automatically**

Stop after tests. The runner should be restarted only after the user explicitly approves the new 1m model behavior.

---

## Self-Review

- Spec coverage: The plan separates 1m and 15m/30m models, removes old fast generic detector mixing, restricts 1.5 volume to clean equal-level reversal/fakeout triggers, and adds journal-visible explicit trigger names.
- Placeholder scan: No `TBD`, `TODO`, or open-ended test instructions remain.
- Type consistency: Public APIs are `analyze_playbook`, `analyze_normal_entry`, and `analyze_one_minute_entry`. The 1m model emits the existing engine payload shape so `build_order_proposal()` continues to work.
- Scope check: This plan does not alter MT5 execution, straddle, live runner mode gates, or broker safety. Those remain separate systems.
