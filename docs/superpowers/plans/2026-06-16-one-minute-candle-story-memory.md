# One Minute Candle Story Memory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the One Minute Scalper so it remembers two-high/two-low openings from the last 60 closed 1m candles, recognizes clean impulse breaks from those openings, and manages rejection exits fast enough to avoid leaving the remaining position exposed.

**Architecture:** Keep the model deterministic and isolated in `tradingagents/agents/price_action/one_minute_entry_model.py`. Rebuild candle-story memory from the last 60 closed candles each cycle, journal that memory, allow only clean impulse breaks from remembered two-touch/three-touch zones, and keep old raw breaks rejected. Pass live bid/ask into the model only for quote-distance validation and pending-entry placement.

**Tech Stack:** Python 3.13, pytest, existing TradingAgents price-action engine, MT5 pending-order executor, JSON telemetry.

---

## File Structure

- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
  - Owns candle-story memory, level memory, candidate generation, scoring, selected setup metadata, and one-minute telemetry.
- Modify: `tradingagents/agents/price_action/decision.py`
  - Passes live spread, bid, and ask from MT5 market health into the deterministic one-minute model.
- Modify: `tradingagents/brokers/mt5_execution.py`
  - Hardens candle-rejection exits so a rejected trade does not leave the remaining half exposed to the original stop.
- Modify: `tradingagents/brokers/runner_summary.py`
  - No structural change expected, but add tests to confirm new trigger names aggregate through existing candidate summary logic.
- Modify: `tests/test_one_minute_entry_model.py`
  - Unit tests for memory, symmetric low/high behavior, clean impulse breaks, stale impulse rejection, and telemetry.
- Modify: `tests/test_price_action_engine.py`
  - Integration tests proving the price-action engine routes clean one-minute impulse breaks without 3m/15m context.
- Modify: `tests/test_engine_decision.py`
  - Test live bid/ask propagation into the one-minute model config.
- Modify: `tests/test_mt5_execution.py`
  - Tests for full/safer exit after candle rejection.
- Modify: `tests/test_mt5_runner_summary.py`
  - Tests for clean impulse trigger aggregation.

---

## Behavior Rules

The model must still be one trade at a time through the existing MT5 active-trade guard.

The model must use the last 60 fully closed 1m candles as memory. It must not depend on 3m/15m/30m context for the One Minute Scalper.

The model must classify the latest candle relative to the previous candle and remembered zones:

```text
equal_high
equal_low
higher_high
higher_low
lower_high
lower_low
broke_high_zone
broke_low_zone
rejected_high_zone
rejected_low_zone
failed_high_break
failed_low_break
```

The model must distinguish old raw breaks from clean impulse breaks:

```text
HIGH_BREAK_BUY and LOW_BREAK_SELL remain raw-break candidates and stay rejected.
CLEAN_HIGH_IMPULSE_BUY and CLEAN_LOW_IMPULSE_SELL are new allowed trigger names.
```

A clean impulse break is allowed only when:

```text
- a remembered two-touch or three-touch high/low zone exists
- latest closed candle breaks beyond that zone
- latest candle closes strongly in the break direction
- close is not too extended from the remembered level
- live bid/ask has not moved too far beyond the confirmation close
- stop distance is spread-safe and within the one-minute scalp maximum
- spread is acceptable through the existing market health gate
- market is not overlapping chop
```

---

## Task 1: Add Candle Story Memory Tests

**Files:**
- Modify: `tests/test_one_minute_entry_model.py`

- [ ] **Step 1: Add a helper for chart-like two-high impulse candles**

Add this helper near the other test helpers:

```python
def _two_high_then_impulse_buy_history():
    return [
        _candle(0, 100.0, 100.6, 99.7, 100.3),
        _candle(1, 100.3, 101.0, 100.1, 100.8),
        _candle(2, 100.8, 101.95, 100.4, 101.7),  # first high
        _candle(3, 101.7, 101.8, 100.3, 100.6),
        _candle(4, 100.6, 101.9, 100.2, 101.5),   # second high
        _candle(5, 101.5, 101.6, 100.7, 100.9),
        _candle(6, 100.9, 102.55, 100.8, 102.45), # clean break close
    ]
```

- [ ] **Step 2: Add a helper for symmetric two-low impulse sell candles**

Add this helper after `_two_high_then_impulse_buy_history`:

```python
def _two_low_then_impulse_sell_history():
    return [
        _candle(0, 100.0, 100.3, 99.4, 99.7),
        _candle(1, 99.7, 100.1, 98.05, 98.4),     # first low
        _candle(2, 98.4, 99.4, 98.2, 99.1),
        _candle(3, 99.1, 99.5, 98.08, 98.7),      # second low
        _candle(4, 98.7, 99.2, 98.5, 99.0),
        _candle(5, 99.0, 99.1, 97.45, 97.55),     # clean break close
    ]
```

- [ ] **Step 3: Write failing memory telemetry test for highs**

Add this test:

```python
def test_one_minute_scalper_journals_high_zone_memory_and_latest_relation():
    payload = _payload(
        _two_high_then_impulse_buy_history(),
        fast_history_window_candles=7,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=102.48,
        current_ask_price=102.68,
    )

    story = payload["market_context"]["one_minute_story"]

    assert story["latest_candle_relation"]["higher_high"] is True
    assert story["latest_candle_relation"]["higher_low"] is True
    assert story["latest_candle_relation"]["broke_high_zone"] is True
    assert story["latest_candle_relation"]["broke_low_zone"] is False
    high_openings = [
        item for item in story["active_openings"] if item["side"] == "high"
    ]
    assert high_openings
    assert high_openings[0]["touch_count"] >= 2
    assert high_openings[0]["state"] == "broken_up"
```

- [ ] **Step 4: Write failing memory telemetry test for lows**

Add this test:

```python
def test_one_minute_scalper_journals_low_zone_memory_and_latest_relation():
    payload = _payload(
        _two_low_then_impulse_sell_history(),
        fast_history_window_candles=6,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=97.35,
        current_ask_price=97.55,
    )

    story = payload["market_context"]["one_minute_story"]

    assert story["latest_candle_relation"]["lower_low"] is True
    assert story["latest_candle_relation"]["lower_high"] is True
    assert story["latest_candle_relation"]["broke_low_zone"] is True
    assert story["latest_candle_relation"]["broke_high_zone"] is False
    low_openings = [
        item for item in story["active_openings"] if item["side"] == "low"
    ]
    assert low_openings
    assert low_openings[0]["touch_count"] >= 2
    assert low_openings[0]["state"] == "broken_down"
```

- [ ] **Step 5: Run tests and verify failure**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py::test_one_minute_scalper_journals_high_zone_memory_and_latest_relation tests/test_one_minute_entry_model.py::test_one_minute_scalper_journals_low_zone_memory_and_latest_relation -q
```

Expected: both fail with missing `latest_candle_relation` or `active_openings`.

---

## Task 2: Implement Candle Story Memory

**Files:**
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Test: `tests/test_one_minute_entry_model.py`

- [ ] **Step 1: Add memory dataclasses**

Add after `OneMinuteCandidate`:

```python
@dataclass(frozen=True)
class OneMinuteCandleRelation:
    equal_high: bool
    equal_low: bool
    higher_high: bool
    higher_low: bool
    lower_high: bool
    lower_low: bool
    broke_high_zone: bool
    broke_low_zone: bool
    rejected_high_zone: bool
    rejected_low_zone: bool
    failed_high_break: bool
    failed_low_break: bool


@dataclass(frozen=True)
class OneMinuteOpeningMemory:
    side: str
    level: float
    touch_count: int
    level_type: str
    first_touch_index: int
    last_touch_index: int
    tolerance: float
    state: str
```

- [ ] **Step 2: Add serialization helpers**

Add below `_detect_equal_levels`:

```python
def _opening_state(level: OneMinuteLevel, latest: Candle, tolerance: float) -> str:
    margin = max(0.05, tolerance * 0.25)
    if level.side == "high":
        if float(latest.close) > level.level + margin:
            return "broken_up"
        if (
            float(latest.high) > level.level + margin
            and float(latest.close) < level.level
        ):
            return "failed_break_up"
        if abs(float(latest.high) - level.level) <= tolerance:
            return "respected_high"
        return "watching_high"
    if float(latest.close) < level.level - margin:
        return "broken_down"
    if (
        float(latest.low) < level.level - margin
        and float(latest.close) > level.level
    ):
        return "failed_break_down"
    if abs(float(latest.low) - level.level) <= tolerance:
        return "respected_low"
    return "watching_low"


def _opening_to_dict(opening: OneMinuteOpeningMemory) -> dict[str, Any]:
    return {
        "side": opening.side,
        "level": round(opening.level, 4),
        "touch_count": opening.touch_count,
        "level_type": opening.level_type,
        "first_touch_index": opening.first_touch_index,
        "last_touch_index": opening.last_touch_index,
        "tolerance": round(opening.tolerance, 4),
        "state": opening.state,
    }
```

- [ ] **Step 3: Add memory builder**

Add below `_opening_to_dict`:

```python
def _build_opening_memory(
    history: list[Candle],
    tolerance: float,
) -> list[OneMinuteOpeningMemory]:
    if len(history) < 2:
        return []
    latest = history[-1]
    prior = history[:-1]
    levels = [
        *_detect_equal_levels(prior, tolerance, side="low"),
        *_detect_equal_levels(prior, tolerance, side="high"),
    ]
    memory: list[OneMinuteOpeningMemory] = []
    for level in levels:
        memory.append(
            OneMinuteOpeningMemory(
                side=level.side,
                level=level.level,
                touch_count=level.touch_count,
                level_type=level.level_type,
                first_touch_index=level.first_touch_index,
                last_touch_index=level.last_touch_index,
                tolerance=level.tolerance,
                state=_opening_state(level, latest, tolerance),
            )
        )
    return sorted(
        memory,
        key=lambda item: (
            item.state.startswith("broken"),
            item.state.startswith("failed"),
            item.touch_count,
            item.last_touch_index,
        ),
        reverse=True,
    )
```

- [ ] **Step 4: Add latest relation helper**

Add below `_build_opening_memory`:

```python
def _latest_candle_relation(
    history: list[Candle],
    tolerance: float,
    openings: list[OneMinuteOpeningMemory],
) -> OneMinuteCandleRelation:
    latest = history[-1]
    previous = history[-2]
    latest_high = float(latest.high)
    latest_low = float(latest.low)
    previous_high = float(previous.high)
    previous_low = float(previous.low)

    broke_high_zone = any(
        opening.side == "high" and opening.state == "broken_up"
        for opening in openings
    )
    broke_low_zone = any(
        opening.side == "low" and opening.state == "broken_down"
        for opening in openings
    )
    rejected_high_zone = any(
        opening.side == "high" and opening.state == "respected_high"
        for opening in openings
    )
    rejected_low_zone = any(
        opening.side == "low" and opening.state == "respected_low"
        for opening in openings
    )
    failed_high_break = any(
        opening.side == "high" and opening.state == "failed_break_up"
        for opening in openings
    )
    failed_low_break = any(
        opening.side == "low" and opening.state == "failed_break_down"
        for opening in openings
    )

    return OneMinuteCandleRelation(
        equal_high=abs(latest_high - previous_high) <= tolerance,
        equal_low=abs(latest_low - previous_low) <= tolerance,
        higher_high=latest_high > previous_high + tolerance,
        higher_low=latest_low > previous_low + tolerance,
        lower_high=latest_high < previous_high - tolerance,
        lower_low=latest_low < previous_low - tolerance,
        broke_high_zone=broke_high_zone,
        broke_low_zone=broke_low_zone,
        rejected_high_zone=rejected_high_zone,
        rejected_low_zone=rejected_low_zone,
        failed_high_break=failed_high_break,
        failed_low_break=failed_low_break,
    )
```

- [ ] **Step 5: Journal memory in `analyze_one_minute_entry`**

After `history` and `tolerance` are created, add:

```python
    openings = _build_opening_memory(history, tolerance) if len(history) >= 2 else []
    latest_relation = (
        _latest_candle_relation(history, tolerance, openings)
        if len(history) >= 2
        else OneMinuteCandleRelation(
            equal_high=False,
            equal_low=False,
            higher_high=False,
            higher_low=False,
            lower_high=False,
            lower_low=False,
            broke_high_zone=False,
            broke_low_zone=False,
            rejected_high_zone=False,
            rejected_low_zone=False,
            failed_high_break=False,
            failed_low_break=False,
        )
    )
```

Then add these fields to `story`:

```python
        "latest_candle_relation": asdict(latest_relation),
        "active_openings": [_opening_to_dict(opening) for opening in openings],
```

- [ ] **Step 6: Run memory tests**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py::test_one_minute_scalper_journals_high_zone_memory_and_latest_relation tests/test_one_minute_entry_model.py::test_one_minute_scalper_journals_low_zone_memory_and_latest_relation -q
```

Expected: both pass.

- [ ] **Step 7: Commit**

```powershell
git add tradingagents/agents/price_action/one_minute_entry_model.py tests/test_one_minute_entry_model.py
git commit -m "feat: journal one-minute candle story memory"
```

---

## Task 3: Add Clean Impulse Break Tests

**Files:**
- Modify: `tests/test_one_minute_entry_model.py`
- Modify: `tests/test_price_action_engine.py`

- [ ] **Step 1: Add failing direct model test for clean high impulse buy**

Add this test:

```python
def test_one_minute_scalper_allows_clean_high_impulse_buy_from_remembered_two_highs():
    payload = _payload(
        _two_high_then_impulse_buy_history(),
        fast_history_window_candles=7,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=102.48,
        current_ask_price=102.68,
    )

    candidate = payload["telemetry"]["selected_candidate"]

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "CLEAN_HIGH_IMPULSE_BUY"
    assert candidate["trigger"] == "CLEAN_HIGH_IMPULSE_BUY"
    assert candidate["reaction_type"] == "impulse_break"
    assert "CLEAN_IMPULSE_BREAK" in candidate["score_reasons"]
    assert "RAW_BREAK_EXECUTION_DISABLED" not in candidate["rejection_reasons"]
```

- [ ] **Step 2: Add failing direct model test for clean low impulse sell**

Add this test:

```python
def test_one_minute_scalper_allows_clean_low_impulse_sell_from_remembered_two_lows():
    payload = _payload(
        _two_low_then_impulse_sell_history(),
        fast_history_window_candles=6,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=97.35,
        current_ask_price=97.55,
    )

    candidate = payload["telemetry"]["selected_candidate"]

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "SELL"
    assert payload["setups"][0]["name"] == "CLEAN_LOW_IMPULSE_SELL"
    assert candidate["trigger"] == "CLEAN_LOW_IMPULSE_SELL"
    assert candidate["reaction_type"] == "impulse_break"
    assert "CLEAN_IMPULSE_BREAK" in candidate["score_reasons"]
    assert "RAW_BREAK_EXECUTION_DISABLED" not in candidate["rejection_reasons"]
```

- [ ] **Step 3: Add failing test proving old raw break remains rejected**

Add this test:

```python
def test_one_minute_scalper_still_rejects_messy_raw_break_without_clean_impulse():
    candles = _base_history() + [
        _candle(57, 99.8, 101.0, 99.5, 100.3),
        _candle(58, 100.2, 100.95, 99.8, 100.5),
        _candle(59, 100.6, 103.8, 100.4, 101.1),
    ]

    payload = _payload(
        candles,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=101.0,
        current_ask_price=101.2,
    )

    assert payload["status"] == "NO_SETUP"
    candidate = _candidate_by_trigger(payload, "HIGH_BREAK_BUY")
    assert "RAW_BREAK_EXECUTION_DISABLED" in candidate["rejection_reasons"]
```

- [ ] **Step 4: Add engine integration test for one-minute high impulse buy**

Add this test near other one-minute engine tests in `tests/test_price_action_engine.py`:

```python
def test_one_minute_engine_executes_clean_high_impulse_buy_without_extra_context():
    data = {
        "1m": candles(
            "2026-06-10 20:30:00,100.0,100.6,99.7,100.3,1000\n"
            "2026-06-10 20:31:00,100.3,101.0,100.1,100.8,1000\n"
            "2026-06-10 20:35:00,100.8,101.95,100.4,101.7,1000\n"
            "2026-06-10 20:36:00,101.7,101.8,100.3,100.6,1000\n"
            "2026-06-10 20:52:00,100.6,101.9,100.2,101.5,1000\n"
            "2026-06-10 20:53:00,101.5,101.6,100.7,100.9,1000\n"
            "2026-06-10 20:58:00,100.9,102.55,100.8,102.45,1000"
        ),
    }

    payload = analyze_playbook(
        "XAUUSD",
        "2026-06-10 20:59",
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
            "minimum_setup_grade": "B_PLUS",
            "minimum_stop_distance_price": 0.25,
            "current_spread_price": 0.20,
            "current_bid_price": 102.48,
            "current_ask_price": 102.68,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == "CLEAN_HIGH_IMPULSE_BUY"
    assert payload["market_context"]["one_minute_story"]["classification"] == "CLEAN_HIGH_IMPULSE_BUY"
```

- [ ] **Step 5: Run tests and verify failure**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py::test_one_minute_scalper_allows_clean_high_impulse_buy_from_remembered_two_highs tests/test_one_minute_entry_model.py::test_one_minute_scalper_allows_clean_low_impulse_sell_from_remembered_two_lows tests/test_one_minute_entry_model.py::test_one_minute_scalper_still_rejects_messy_raw_break_without_clean_impulse tests/test_price_action_engine.py::test_one_minute_engine_executes_clean_high_impulse_buy_without_extra_context -q
```

Expected: clean impulse tests fail because the triggers do not exist yet.

---

## Task 4: Implement Clean Impulse Break Triggers

**Files:**
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Test: `tests/test_one_minute_entry_model.py`
- Test: `tests/test_price_action_engine.py`

- [ ] **Step 1: Add trigger constants**

Replace the break trigger constants block with:

```python
LOW_BREAK_SELL = "LOW_BREAK_SELL"
HIGH_BREAK_BUY = "HIGH_BREAK_BUY"
CLEAN_LOW_IMPULSE_SELL = "CLEAN_LOW_IMPULSE_SELL"
CLEAN_HIGH_IMPULSE_BUY = "CLEAN_HIGH_IMPULSE_BUY"
FAILED_LOW_BREAK_BUY = "FAILED_LOW_BREAK_BUY"
FAILED_HIGH_BREAK_SELL = "FAILED_HIGH_BREAK_SELL"
```

Then replace `BREAK_ONE_MINUTE_TRIGGERS` with:

```python
RAW_BREAK_ONE_MINUTE_TRIGGERS = {
    LOW_BREAK_SELL,
    HIGH_BREAK_BUY,
}

CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS = {
    CLEAN_LOW_IMPULSE_SELL,
    CLEAN_HIGH_IMPULSE_BUY,
}

BREAK_ONE_MINUTE_TRIGGERS = {
    *RAW_BREAK_ONE_MINUTE_TRIGGERS,
    *CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS,
}
```

- [ ] **Step 2: Add clean impulse helper**

Add below `_confirmation_type`:

```python
def _is_clean_impulse_break(
    *,
    direction: str,
    level: OneMinuteLevel,
    latest: Candle,
    tolerance: float,
    current_spread_price: float,
) -> bool:
    if level.touch_count < 2:
        return False
    extension = abs(float(latest.close) - float(level.level))
    max_extension = max(tolerance * 3.0, current_spread_price * 2.0, 0.45)
    if extension > max_extension:
        return False
    if direction == "BUY":
        return _decisive_directional_close("BUY", latest)
    if direction == "SELL":
        return _decisive_directional_close("SELL", latest)
    return False
```

- [ ] **Step 3: Select clean impulse trigger names in `_candidate_from_level`**

Inside `_candidate_from_level`, replace the low-side break branch:

```python
        elif float(latest.close) < level.level - break_margin:
            trigger_name = LOW_BREAK_SELL
            direction = "SELL"
            reaction_type = "break"
```

with:

```python
        elif float(latest.close) < level.level - break_margin:
            direction = "SELL"
            if _is_clean_impulse_break(
                direction=direction,
                level=level,
                latest=latest,
                tolerance=tolerance,
                current_spread_price=current_spread_price,
            ):
                trigger_name = CLEAN_LOW_IMPULSE_SELL
                reaction_type = "impulse_break"
            else:
                trigger_name = LOW_BREAK_SELL
                reaction_type = "break"
```

Replace the high-side break branch:

```python
        elif float(latest.close) > level.level + break_margin:
            trigger_name = HIGH_BREAK_BUY
            direction = "BUY"
            reaction_type = "break"
```

with:

```python
        elif float(latest.close) > level.level + break_margin:
            direction = "BUY"
            if _is_clean_impulse_break(
                direction=direction,
                level=level,
                latest=latest,
                tolerance=tolerance,
                current_spread_price=current_spread_price,
            ):
                trigger_name = CLEAN_HIGH_IMPULSE_BUY
                reaction_type = "impulse_break"
            else:
                trigger_name = HIGH_BREAK_BUY
                reaction_type = "break"
```

- [ ] **Step 4: Score clean impulses without raw-break rejection**

In `_score_candidate`, replace:

```python
        candidate.rejection_reasons.append(RAW_BREAK_EXECUTION_DISABLED)
```

with:

```python
        if candidate.trigger in RAW_BREAK_ONE_MINUTE_TRIGGERS:
            candidate.rejection_reasons.append(RAW_BREAK_EXECUTION_DISABLED)
        elif candidate.trigger in CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS:
            candidate.score += 2
            candidate.score_reasons.append("CLEAN_IMPULSE_BREAK")
```

- [ ] **Step 5: Prioritize clean impulse breaks**

Replace `_selection_priority` with:

```python
def _selection_priority(candidate: OneMinuteCandidate) -> int:
    if candidate.reaction_type == "impulse_break":
        return 3
    if candidate.reaction_type in {"fakeout", "respect"}:
        return 2
    if candidate.reaction_type == "break":
        return 1
    return 0
```

- [ ] **Step 6: Add new triggers to telemetry rule list**

In `fast_microstructure["rules"]`, insert the clean impulse triggers:

```python
                CLEAN_LOW_IMPULSE_SELL,
                CLEAN_HIGH_IMPULSE_BUY,
```

- [ ] **Step 7: Run clean impulse tests**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py::test_one_minute_scalper_allows_clean_high_impulse_buy_from_remembered_two_highs tests/test_one_minute_entry_model.py::test_one_minute_scalper_allows_clean_low_impulse_sell_from_remembered_two_lows tests/test_one_minute_entry_model.py::test_one_minute_scalper_still_rejects_messy_raw_break_without_clean_impulse tests/test_price_action_engine.py::test_one_minute_engine_executes_clean_high_impulse_buy_without_extra_context -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add tradingagents/agents/price_action/one_minute_entry_model.py tests/test_one_minute_entry_model.py tests/test_price_action_engine.py
git commit -m "feat: allow clean one-minute impulse breaks"
```

---

## Task 5: Add Live Quote Drift Guard for Impulse Entries

**Files:**
- Modify: `tradingagents/agents/price_action/decision.py`
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Modify: `tests/test_engine_decision.py`
- Modify: `tests/test_one_minute_entry_model.py`

- [ ] **Step 1: Add failing test for bid/ask propagation**

In `tests/test_engine_decision.py`, add:

```python
def test_engine_passes_live_bid_ask_into_one_minute_profile(monkeypatch):
    captured_config = {}

    def fake_analyze_playbook(symbol, as_of, candles, market_timezone, session_config):
        captured_config.update(session_config)
        return {
            "status": "NO_SETUP",
            "recommendation": "HOLD",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
            "telemetry": {"decision_stage": "one_minute_no_trigger"},
            "market_context": {},
        }

    monkeypatch.setattr(
        "tradingagents.agents.price_action.decision.analyze_playbook",
        fake_analyze_playbook,
    )

    snapshot = _snapshot_with_market_metadata(
        candles={"1m": [{"timestamp": "2026-06-10 09:00", "open": 1, "high": 2, "low": 0.5, "close": 1.5}]},
        symbol={"bid": 4339.84, "ask": 4340.13, "spread_price": 0.29},
    )

    decide_price_action(
        "XAUUSD.vx",
        "2026-06-10 09:01",
        snapshot,
        profile_config={
            "entry_profile": "fast",
            "timeframe": "1m",
            "confirmation_timeframe": "1m",
        },
    )

    assert captured_config["current_spread_price"] == 0.29
    assert captured_config["current_bid_price"] == 4339.84
    assert captured_config["current_ask_price"] == 4340.13
```

If `_snapshot_with_market_metadata` does not exist in this file, create a small local fixture using the existing snapshot helper pattern already used in `tests/test_engine_decision.py`.

- [ ] **Step 2: Pass bid/ask from decision layer**

In `tradingagents/agents/price_action/decision.py`, after:

```python
        if market_health.get("spread_price") is not None:
            analysis_config["current_spread_price"] = market_health["spread_price"]
```

add:

```python
        if market_health.get("bid") is not None:
            analysis_config["current_bid_price"] = market_health["bid"]
        if market_health.get("ask") is not None:
            analysis_config["current_ask_price"] = market_health["ask"]
```

- [ ] **Step 3: Add failing stale impulse test**

In `tests/test_one_minute_entry_model.py`, add:

```python
def test_one_minute_scalper_rejects_clean_impulse_when_live_quote_moved_too_far():
    payload = _payload(
        _two_high_then_impulse_buy_history(),
        fast_history_window_candles=7,
        minimum_stop_distance_price=0.25,
        current_spread_price=0.20,
        current_bid_price=104.20,
        current_ask_price=104.40,
    )

    assert payload["status"] == "NO_SETUP"
    candidate = _candidate_by_trigger(payload, "CLEAN_HIGH_IMPULSE_BUY")
    assert "IMPULSE_ENTRY_MOVED_AWAY" in candidate["rejection_reasons"]
```

- [ ] **Step 4: Add quote config parsing**

In `analyze_one_minute_entry`, after `current_spread_price`, add:

```python
    current_bid_price = _positive_float(config.get("current_bid_price"), 0.0)
    current_ask_price = _positive_float(config.get("current_ask_price"), 0.0)
    max_live_entry_drift = _positive_float(
        config.get("fast_impulse_max_live_entry_drift_price"),
        max(current_spread_price * 3.0, 0.60),
    )
```

Add these to `story`:

```python
        "current_bid_price": round(current_bid_price, 4),
        "current_ask_price": round(current_ask_price, 4),
        "max_live_entry_drift": round(max_live_entry_drift, 4),
```

- [ ] **Step 5: Extend `_build_candidates` and `_candidate_from_level` signatures**

Add parameters to both functions:

```python
    current_bid_price: float,
    current_ask_price: float,
    max_live_entry_drift: float,
```

Pass them through from `analyze_one_minute_entry` to `_build_candidates`, and from `_build_candidates` to `_candidate_from_level`.

- [ ] **Step 6: Add impulse live-drift validation**

In `_candidate_from_level`, after risk is built and before returning the approved candidate, add:

```python
    if trigger_name in CLEAN_IMPULSE_ONE_MINUTE_TRIGGERS:
        quote = current_ask_price if direction == "BUY" else current_bid_price
        if quote > 0:
            drift = abs(quote - float(latest.close))
            if drift > max_live_entry_drift:
                candidate = OneMinuteCandidate(
                    trigger=trigger_name,
                    direction=direction,
                    reaction_type=reaction_type,
                    confirmation_type=confirmation,
                    level=level,
                    entry_price=float(risk["entry_price"]),
                    stop_loss=float(risk["stop_loss"]),
                    take_profit=float(risk["take_profit"]),
                    risk_distance=float(risk["risk_distance"]),
                    reward_distance=float(risk["reward_distance"]),
                    risk=risk,
                )
                candidate.rejection_reasons.append("IMPULSE_ENTRY_MOVED_AWAY")
                candidate.risk["fast_trigger_quality"] = {
                    **candidate.risk.get("fast_trigger_quality", {}),
                    "live_quote": round(quote, 4),
                    "live_entry_drift": round(drift, 4),
                    "max_live_entry_drift": round(max_live_entry_drift, 4),
                }
                return candidate
```

- [ ] **Step 7: Run quote and impulse tests**

Run:

```powershell
uv run --group dev pytest tests/test_engine_decision.py::test_engine_passes_live_bid_ask_into_one_minute_profile tests/test_one_minute_entry_model.py::test_one_minute_scalper_rejects_clean_impulse_when_live_quote_moved_too_far tests/test_one_minute_entry_model.py::test_one_minute_scalper_allows_clean_high_impulse_buy_from_remembered_two_highs -q
```

Expected: all pass.

- [ ] **Step 8: Commit**

```powershell
git add tradingagents/agents/price_action/decision.py tradingagents/agents/price_action/one_minute_entry_model.py tests/test_engine_decision.py tests/test_one_minute_entry_model.py
git commit -m "feat: guard one-minute impulse entries with live quote drift"
```

---

## Task 6: Harden Candle-Rejection Trade Management

**Files:**
- Modify: `tradingagents/brokers/mt5_execution.py`
- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Add failing test for full exit when rejection appears before protection**

In `tests/test_mt5_execution.py`, add:

```python
def test_executor_fully_closes_unprotected_buy_on_rejection_candle(tmp_path):
    broker = FakeBroker(
        positions=[
            {
                "ticket": 101,
                "identifier": 101,
                "symbol": "XAUUSD.vx",
                "side": "BUY",
                "volume": 1.0,
                "entry_price": 4337.60,
                "price_current": 4337.40,
                "stop_loss": 4336.90,
                "take_profit": 4338.67,
            }
        ],
        rates={
            "1m": [
                {"timestamp": "2026-06-16T17:37:00+00:00", "open": 4337.6, "high": 4337.9, "low": 4337.3, "close": 4337.7},
                {"timestamp": "2026-06-16T17:38:00+00:00", "open": 4338.0, "high": 4338.16, "low": 4337.18, "close": 4337.43},
            ]
        },
    )
    executor = MT5Executor(
        _mt5_config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            candle_rejection_exit_enabled=True,
            candle_rejection_partial_fraction=0.5,
            break_even_trigger_points=0.43,
            break_even_lock_points=0.09,
        ),
    )

    result = executor.manage_open_positions()

    assert result["status"] == "MANAGED"
    assert result["actions"][0]["action"] == "FULL_CLOSE"
    assert result["actions"][0]["reason"] == "CANDLE_REJECTION_FULL_EXIT_UNPROTECTED"
    assert broker.closed_positions[0]["volume"] == 1.0
```

Use the existing fake broker class and config helper names in `tests/test_mt5_execution.py`. If they differ, adapt only the names, not the asserted behavior.

- [ ] **Step 2: Add failing test for partial plus break-even when already profitable**

Add:

```python
def test_executor_partially_closes_and_protects_remainder_on_profitable_rejection(tmp_path):
    broker = FakeBroker(
        positions=[
            {
                "ticket": 102,
                "identifier": 102,
                "symbol": "XAUUSD.vx",
                "side": "BUY",
                "volume": 1.0,
                "entry_price": 4337.60,
                "price_current": 4338.20,
                "stop_loss": 4336.90,
                "take_profit": 4338.67,
            }
        ],
        rates={
            "1m": [
                {"timestamp": "2026-06-16T17:37:00+00:00", "open": 4337.6, "high": 4338.4, "low": 4337.5, "close": 4338.3},
                {"timestamp": "2026-06-16T17:38:00+00:00", "open": 4338.4, "high": 4338.5, "low": 4337.9, "close": 4338.05},
            ]
        },
    )
    executor = MT5Executor(
        _mt5_config(),
        tmp_path,
        broker=broker,
        exit_management=MT5ExitManagementConfig(
            candle_rejection_exit_enabled=True,
            candle_rejection_partial_fraction=0.5,
            break_even_trigger_points=0.43,
            break_even_lock_points=0.09,
        ),
    )

    result = executor.manage_open_positions()

    actions = result["actions"]
    assert actions[0]["action"] == "PARTIAL_CLOSE"
    assert actions[1]["action"] == "MOVE_STOP"
    assert actions[1]["reason"] == "CANDLE_REJECTION_PROTECT_REMAINDER"
    assert broker.stop_updates[0]["stop_loss"] == pytest.approx(4337.69)
```

- [ ] **Step 3: Implement unprotected full exit**

In `_candle_rejection_action`, before the partial-close branch, add:

```python
        entry = _first_float(position, "entry_price", "price_open")
        current = _first_float(position, "price_current", "current_price")
        if entry is None or current is None:
            return None
        favorable_points = (
            current - entry if side == "BUY" else entry - current
        )
        if favorable_points <= 0:
            close_result = self.broker.close_position(
                position,
                comment="TA candle rejection full",
            )
            action = {
                "action": "FULL_CLOSE",
                "reason": "CANDLE_REJECTION_FULL_EXIT_UNPROTECTED",
                "ticket": position.get("ticket"),
                "result": close_result,
            }
            self.journal.append("POSITION_CLOSED", action)
            return action
```

- [ ] **Step 4: Protect remainder after profitable partial close**

After the existing partial-close action succeeds, compute break-even stop and update it:

```python
        if close_result.get("ok"):
            entry = _first_float(position, "entry_price", "price_open")
            if entry is not None and management.break_even_lock_points >= 0:
                protected_stop = (
                    entry + management.break_even_lock_points
                    if side == "BUY"
                    else entry - management.break_even_lock_points
                )
                update_result = self.broker.update_stop_loss(
                    position,
                    protected_stop,
                    comment="TA rejection protect",
                )
                action["protect_remainder"] = {
                    "action": "MOVE_STOP",
                    "reason": "CANDLE_REJECTION_PROTECT_REMAINDER",
                    "stop_loss": protected_stop,
                    "result": update_result,
                }
```

If `manage_open_positions` currently flattens one action at a time, return a list action from `_candle_rejection_action` and extend `actions` when the return value is a list. Keep the journal event names explicit.

- [ ] **Step 5: Run MT5 execution tests**

Run:

```powershell
uv run --group dev pytest tests/test_mt5_execution.py::test_executor_fully_closes_unprotected_buy_on_rejection_candle tests/test_mt5_execution.py::test_executor_partially_closes_and_protects_remainder_on_profitable_rejection -q
```

Expected: both pass.

- [ ] **Step 6: Commit**

```powershell
git add tradingagents/brokers/mt5_execution.py tests/test_mt5_execution.py
git commit -m "fix: protect one-minute trades on rejection candles"
```

---

## Task 7: Verify Summary Aggregation for New Trigger Names

**Files:**
- Modify: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Add summary test**

Add:

```python
def test_runner_summary_records_clean_impulse_candidate_triggers(tmp_path):
    summary = RunnerSummary(tmp_path / "summary.json")
    cycle = {
        "telemetry": {
            "candidate_evaluations": [
                {
                    "trigger": "CLEAN_HIGH_IMPULSE_BUY",
                    "approved": True,
                    "rejection_reasons": [],
                },
                {
                    "trigger": "HIGH_BREAK_BUY",
                    "approved": False,
                    "rejection_reasons": ["RAW_BREAK_EXECUTION_DISABLED"],
                },
            ]
        }
    }

    summary.record_cycle(cycle)
    data = summary.snapshot()

    assert data["candidate_strategy_counts"]["CLEAN_HIGH_IMPULSE_BUY"] == 1
    assert data["approved_candidate_strategy_counts"]["CLEAN_HIGH_IMPULSE_BUY"] == 1
    assert data["candidate_rejection_reason_counts"]["RAW_BREAK_EXECUTION_DISABLED"] == 1
    assert data["candidate_rejection_by_strategy_counts"]["HIGH_BREAK_BUY"] == {
        "RAW_BREAK_EXECUTION_DISABLED": 1
    }
```

Use the existing `RunnerSummary` construction pattern in this file if its helper name differs.

- [ ] **Step 2: Run summary test**

Run:

```powershell
uv run --group dev pytest tests/test_mt5_runner_summary.py::test_runner_summary_records_clean_impulse_candidate_triggers -q
```

Expected: pass without production changes. If it fails, fix `runner_summary.py` only to aggregate `trigger` consistently for new names.

- [ ] **Step 3: Commit**

```powershell
git add tradingagents/brokers/runner_summary.py tests/test_mt5_runner_summary.py
git commit -m "test: record clean one-minute impulse trigger summaries"
```

---

## Task 8: Run Full Verification

**Files:**
- No new files.

- [ ] **Step 1: Run targeted one-minute suite**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py tests/test_price_action_engine.py tests/test_engine_decision.py tests/test_mt5_execution.py tests/test_mt5_runner_summary.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full suite**

Run:

```powershell
uv run --group dev pytest
```

Expected: full suite passes with only known skips.

- [ ] **Step 3: Inspect git diff**

Run:

```powershell
git diff -- tradingagents/agents/price_action/one_minute_entry_model.py tradingagents/agents/price_action/decision.py tradingagents/brokers/mt5_execution.py tradingagents/brokers/runner_summary.py tests/test_one_minute_entry_model.py tests/test_price_action_engine.py tests/test_engine_decision.py tests/test_mt5_execution.py tests/test_mt5_runner_summary.py
```

Expected: diff only contains One Minute Scalper memory, clean impulse, quote drift, rejection exit, and tests.

---

## Task 9: Restart Fresh Telemetry Run

**Files:**
- No code changes.
- Runtime output under `results/`.

- [ ] **Step 1: Stop existing runner**

Run:

```powershell
Get-Process | Where-Object { $_.ProcessName -match 'tradingagents|python' } | Stop-Process -Force
```

Expected: only `terminal64` remains for MT5.

- [ ] **Step 2: Start fresh one-minute run**

Run:

```powershell
$stamp = Get-Date -Format "yyyy-MM-dd-HHmmss"
$env:TRADINGAGENTS_RESULTS_DIR = "results\\$stamp-one-minute-candle-story-memory"
$env:TRADINGAGENTS_TRADING_MODE = "ENTRY_ONLY"
$env:TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT = "true"
$env:TRADINGAGENTS_MT5_EXECUTION_MODE = "broker"
$env:TRADINGAGENTS_ENTRY_PROFILE_MODE = "fast_only"
$env:TRADINGAGENTS_FAST_ENTRIES_ENABLED = "true"
$env:TRADINGAGENTS_FAST_TIMEFRAME = "1m"
$env:TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME = "1m"
$env:TRADINGAGENTS_FAST_HISTORY_WINDOW_CANDLES = "60"
$env:TRADINGAGENTS_FAST_MIN_CANDIDATE_SCORE = "8"
$env:TRADINGAGENTS_FAST_MIN_STOP_SPREAD_MULTIPLE = "2"
$env:TRADINGAGENTS_FAST_VOLUME_BOOST_ENABLED = "false"
$env:TRADINGAGENTS_FAST_ACTIVATION_WINDOW_MINUTES = "1"
$env:TRADINGAGENTS_RUNNER_POLL_SECONDS = "5"
$env:TRADINGAGENTS_RUNNER_MAX_SESSION_LOSS = "300"
$env:PYTHONUNBUFFERED = "1"
Start-Process -FilePath ".venv\\Scripts\\tradingagents.exe" -ArgumentList @("mt5-run", "--poll-seconds", "5", "--duration-hours", "2") -WorkingDirectory (Get-Location) -WindowStyle Hidden
```

Expected: new runner starts and writes a fresh `summary.json` and `heartbeat.json`.

- [ ] **Step 3: Verify first heartbeat**

Run:

```powershell
Get-ChildItem results -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
Get-Content -Raw (Get-ChildItem results -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName\\mt5_runner\\heartbeat.json
```

Expected:

```text
trading_mode = ENTRY_ONLY
account_safety.passed = true
health_gate.passed = true
```

- [ ] **Step 4: Verify new telemetry fields**

Run:

```powershell
$run = (Get-ChildItem results -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
Get-ChildItem "$run\\XAUUSD.vx\\engine_telemetry" -File | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
    Get-Content -Raw $_.FullName | ConvertFrom-Json | Select-Object -ExpandProperty market_context | ConvertTo-Json -Depth 8
}
```

Expected: `one_minute_story.latest_candle_relation` and `one_minute_story.active_openings` are present.

- [ ] **Step 5: Verify summary after 10-15 minutes**

Run:

```powershell
$run = (Get-ChildItem results -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
$s = Get-Content -Raw "$run\\mt5_runner\\summary.json" | ConvertFrom-Json
$s.candidate_strategy_counts | ConvertTo-Json -Compress
$s.approved_candidate_strategy_counts | ConvertTo-Json -Compress
$s.trade_history | ConvertTo-Json -Depth 6
```

Expected:

```text
Raw breaks may appear as rejected.
CLEAN_HIGH_IMPULSE_BUY or CLEAN_LOW_IMPULSE_SELL may appear when a true impulse break forms.
No broker rejections.
No simultaneous position/order beyond the existing one-active-trade rule.
```

---

## Self-Review

- Spec coverage: The plan covers candle story memory, high and low symmetry, clean impulse break path, stale live quote protection, fast rejection management, journaling, summary aggregation, tests, and fresh telemetry restart.
- Deferred-work scan: No deferred sections, no open task markers inside prose, no undefined future phase.
- Type consistency: New trigger names are strings carried through candidate telemetry, setup conversion, order proposal metadata, and runner summary.
- Scope check: The plan stays inside the One Minute Scalper and MT5 lifecycle path. It does not touch 15m/30m normal entry, straddle, LLMs, or market orders.
