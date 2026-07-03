# One Minute Opening-State Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a broker-free opening-state research harness that detects repeated-level M1 openings, simulates deterministic pending-entry outcomes with tick evidence, evaluates pre-registered templates leave-one-day-out, and reports whether any template qualifies for prospective shadow validation.

**Architecture:** Keep research code separate from MT5 execution code. Use small pure modules for state detection, tick replay, and day-fold evaluation; use CLI commands only to read sanitized fixture files or explicitly exported read-only data. The execution runner remains stopped, and this feature must not import or call order-placement, order-modification, or position-closing code.

**Tech Stack:** Python 3, Pydantic models, Typer CLI, pytest, existing `tradingagents.agents.price_action` candle/risk helpers.

---

## File Structure

- Create `tradingagents/agents/price_action/opening_state.py`
  - Owns opening-state enums, sanitized candle/tick/opportunity models, repeated-level lifecycle detection, and template completion.
- Create `tradingagents/agents/price_action/opening_tick_replay.py`
  - Owns deterministic pending-order simulation from sanitized ticks: decision quote, expiry, fill, quote drift, stop/target, MFE/MAE, and conservative ambiguity handling.
- Create `tradingagents/agents/price_action/opening_state_screening.py`
  - Owns leave-one-day-out evaluation, template metrics, historical gates, deterministic report hashing, and `NO_OPENING_STATE_EDGE` failure reporting.
- Create `tests/test_one_minute_opening_state.py`
  - Unit tests for closed-candle lifecycle state transitions and template detection.
- Create `tests/test_one_minute_opening_tick_replay.py`
  - Unit tests for fill/expiry/ambiguous-tick simulation behavior.
- Create `tests/test_one_minute_opening_screening.py`
  - Unit tests for leave-one-day-out gates, deterministic output, and no broker mutation metadata.
- Create `tests/test_one_minute_opening_state_cli.py`
  - CLI test for writing the same deterministic report as the Python API.
- Create `tests/fixtures/one_minute/opening_state/sample-openings.json`
  - Small sanitized fixture containing candles and ticks only; no account, ticket, order, deal, login, terminal path, server, password, or token keys.
- Modify `cli/main.py`
  - Add `one-minute-opening-state-screen --fixture --output`.
- Optionally modify `tradingagents/agents/price_action/__init__.py`
  - Export public opening-state APIs only if existing import patterns need it.
- Add `docs/analysis/2026-07-03-one-minute-opening-state-screening.md`
  - Record actual screening result after the first deterministic screen.

---

### Task 1: Opening-state models and template lifecycle

**Files:**
- Create: `tradingagents/agents/price_action/opening_state.py`
- Create: `tests/test_one_minute_opening_state.py`

- [ ] **Step 1: Write the failing state-transition tests**

Add this test file:

```python
from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_state import (
    OpeningTemplate,
    detect_opening_opportunities,
)


START = datetime(2026, 7, 1, tzinfo=timezone.utc)


def _candle(index, open_, high, low, close):
    return Candle(
        timestamp=(START + timedelta(minutes=index)).isoformat(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


def _seed_high_level():
    return [
        _candle(0, 100.0, 101.0, 99.5, 100.5),
        _candle(1, 100.4, 101.02, 100.0, 100.2),
        _candle(2, 100.1, 100.6, 99.9, 100.1),
    ]


def test_rejection_template_uses_latest_closed_candle_only():
    candles = _seed_high_level() + [
        _candle(3, 100.4, 101.03, 100.0, 100.05),
        _candle(4, 100.0, 102.0, 99.0, 101.9),
    ]

    opportunities = detect_opening_opportunities(candles[:-1], lookback=10)

    assert len(opportunities) == 1
    opportunity = opportunities[0]
    assert opportunity.template == OpeningTemplate.REJECTION
    assert opportunity.direction == "SELL"
    assert opportunity.signal_time == candles[3].timestamp
    assert opportunity.level_side == "high"
    assert opportunity.used_candle_indexes == (3,)


def test_break_hold_requires_second_closed_candle_beyond_level():
    candles = _seed_high_level() + [
        _candle(3, 100.5, 101.8, 100.4, 101.35),
        _candle(4, 101.3, 101.7, 101.1, 101.45),
    ]

    opportunities = detect_opening_opportunities(candles, lookback=10)

    assert len(opportunities) == 1
    assert opportunities[0].template == OpeningTemplate.BREAK_HOLD
    assert opportunities[0].direction == "BUY"
    assert opportunities[0].signal_time == candles[4].timestamp
    assert opportunities[0].used_candle_indexes == (3, 4)


def test_failed_break_completes_only_after_close_back_inside():
    candles = _seed_high_level() + [
        _candle(3, 100.5, 101.8, 100.4, 101.35),
        _candle(4, 101.3, 101.4, 100.2, 100.45),
    ]

    opportunities = detect_opening_opportunities(candles, lookback=10)

    assert len(opportunities) == 1
    assert opportunities[0].template == OpeningTemplate.FAILED_BREAK
    assert opportunities[0].direction == "SELL"
    assert opportunities[0].signal_time == candles[4].timestamp
    assert opportunities[0].used_candle_indexes == (3, 4)


def test_break_retest_hold_uses_three_closed_candle_lifecycle():
    candles = _seed_high_level() + [
        _candle(3, 100.5, 101.8, 100.4, 101.35),
        _candle(4, 101.3, 101.5, 100.98, 101.25),
        _candle(5, 101.2, 101.9, 101.1, 101.55),
    ]

    opportunities = detect_opening_opportunities(candles, lookback=10)

    assert len(opportunities) == 1
    assert opportunities[0].template == OpeningTemplate.BREAK_RETEST_HOLD
    assert opportunities[0].direction == "BUY"
    assert opportunities[0].signal_time == candles[5].timestamp
    assert opportunities[0].used_candle_indexes == (3, 4, 5)
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state.py -q
```

Expected: FAIL because `tradingagents.agents.price_action.opening_state` does not exist.

- [ ] **Step 3: Implement the minimal opening-state detector**

Create `tradingagents/agents/price_action/opening_state.py` with:

```python
"""Broker-free M1 repeated-level opening-state research."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    _consolidate_candidate_levels,
    _detect_equal_levels,
    _recent_tolerance,
)


class OpeningTemplate(StrEnum):
    REJECTION = "REJECTION"
    BREAK_HOLD = "BREAK_HOLD"
    BREAK_RETEST_HOLD = "BREAK_RETEST_HOLD"
    FAILED_BREAK = "FAILED_BREAK"


class OpeningOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template: OpeningTemplate
    direction: Literal["BUY", "SELL"]
    signal_time: str
    level_side: Literal["high", "low"]
    level: float
    touch_count: int = Field(ge=2)
    tolerance: float = Field(ge=0)
    used_candle_indexes: tuple[int, ...]
    entry_kind: Literal["reaction", "continuation"]


def _margin(tolerance: float) -> float:
    return max(0.05, tolerance * 0.25)


def _is_beyond(candle: Candle, *, side: str, level: float, tolerance: float) -> bool:
    margin = _margin(tolerance)
    if side == "high":
        return float(candle.close) > level + margin
    return float(candle.close) < level - margin


def _is_inside(candle: Candle, *, side: str, level: float, tolerance: float) -> bool:
    margin = _margin(tolerance)
    if side == "high":
        return float(candle.close) <= level + margin
    return float(candle.close) >= level - margin


def _touches(candle: Candle, *, side: str, level: float, tolerance: float) -> bool:
    price = float(candle.high if side == "high" else candle.low)
    return abs(price - level) <= tolerance or (
        side == "high" and price >= level
    ) or (side == "low" and price <= level)


def _direction(template: OpeningTemplate, side: str) -> Literal["BUY", "SELL"]:
    if template in {OpeningTemplate.BREAK_HOLD, OpeningTemplate.BREAK_RETEST_HOLD}:
        return "BUY" if side == "high" else "SELL"
    return "SELL" if side == "high" else "BUY"


def _entry_kind(template: OpeningTemplate) -> Literal["reaction", "continuation"]:
    if template in {OpeningTemplate.REJECTION, OpeningTemplate.FAILED_BREAK}:
        return "reaction"
    return "continuation"


def _rank_opportunities(items: list[OpeningOpportunity]) -> list[OpeningOpportunity]:
    return sorted(
        items,
        key=lambda item: (
            datetime.fromisoformat(item.signal_time),
            -item.touch_count,
            item.template.value,
            item.level_side,
            round(item.level, 4),
        ),
    )


def detect_opening_opportunities(
    candles: list[Candle] | tuple[Candle, ...],
    *,
    lookback: int = 60,
) -> tuple[OpeningOpportunity, ...]:
    closed = list(candles)
    if len(closed) < 3:
        return ()
    opportunities: list[OpeningOpportunity] = []
    for signal_index in range(2, len(closed)):
        start = max(0, signal_index - lookback)
        history = closed[start : signal_index + 1]
        tolerance = _recent_tolerance(history)
        prior = history[:-1]
        levels = _consolidate_candidate_levels(
            [
                *_detect_equal_levels(prior, tolerance, side="low"),
                *_detect_equal_levels(prior, tolerance, side="high"),
            ],
            tolerance=tolerance,
            current_spread_price=0.0,
        )
        latest = history[-1]
        for level in levels:
            side = level.side
            absolute_index = signal_index
            if _touches(latest, side=side, level=level.level, tolerance=tolerance) and _is_inside(
                latest, side=side, level=level.level, tolerance=tolerance
            ):
                template = OpeningTemplate.REJECTION
                opportunities.append(
                    OpeningOpportunity(
                        template=template,
                        direction=_direction(template, side),
                        signal_time=str(latest.timestamp),
                        level_side=side,
                        level=round(float(level.level), 4),
                        touch_count=int(level.touch_count),
                        tolerance=round(float(tolerance), 4),
                        used_candle_indexes=(absolute_index,),
                        entry_kind=_entry_kind(template),
                    )
                )
            if signal_index < 3:
                continue
            first = closed[signal_index - 1]
            second = closed[signal_index]
            if _is_beyond(first, side=side, level=level.level, tolerance=tolerance):
                if _is_beyond(second, side=side, level=level.level, tolerance=tolerance):
                    template = OpeningTemplate.BREAK_HOLD
                    opportunities.append(
                        OpeningOpportunity(
                            template=template,
                            direction=_direction(template, side),
                            signal_time=str(second.timestamp),
                            level_side=side,
                            level=round(float(level.level), 4),
                            touch_count=int(level.touch_count),
                            tolerance=round(float(tolerance), 4),
                            used_candle_indexes=(signal_index - 1, signal_index),
                            entry_kind=_entry_kind(template),
                        )
                    )
                elif _is_inside(second, side=side, level=level.level, tolerance=tolerance):
                    template = OpeningTemplate.FAILED_BREAK
                    opportunities.append(
                        OpeningOpportunity(
                            template=template,
                            direction=_direction(template, side),
                            signal_time=str(second.timestamp),
                            level_side=side,
                            level=round(float(level.level), 4),
                            touch_count=int(level.touch_count),
                            tolerance=round(float(tolerance), 4),
                            used_candle_indexes=(signal_index - 1, signal_index),
                            entry_kind=_entry_kind(template),
                        )
                    )
            if signal_index < 4:
                continue
            first = closed[signal_index - 2]
            retest = closed[signal_index - 1]
            hold = closed[signal_index]
            if (
                _is_beyond(first, side=side, level=level.level, tolerance=tolerance)
                and _touches(retest, side=side, level=level.level, tolerance=tolerance)
                and _is_beyond(hold, side=side, level=level.level, tolerance=tolerance)
            ):
                template = OpeningTemplate.BREAK_RETEST_HOLD
                opportunities.append(
                    OpeningOpportunity(
                        template=template,
                        direction=_direction(template, side),
                        signal_time=str(hold.timestamp),
                        level_side=side,
                        level=round(float(level.level), 4),
                        touch_count=int(level.touch_count),
                        tolerance=round(float(tolerance), 4),
                        used_candle_indexes=(signal_index - 2, signal_index - 1, signal_index),
                        entry_kind=_entry_kind(template),
                    )
                )
    unique = {item.model_dump_json(): item for item in opportunities}
    return tuple(_rank_opportunities(list(unique.values())))
```

- [ ] **Step 4: Run the opening-state tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/price_action/opening_state.py tests/test_one_minute_opening_state.py
git commit -m "feat: detect scalper opening-state templates"
```

---

### Task 2: Tick replay and conservative simulated execution

**Files:**
- Create: `tradingagents/agents/price_action/opening_tick_replay.py`
- Create: `tests/test_one_minute_opening_tick_replay.py`

- [ ] **Step 1: Write failing tick-replay tests**

Add this test file:

```python
from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
)
from tradingagents.agents.price_action.opening_tick_replay import (
    MarketTick,
    ReplayConfig,
    simulate_opportunity,
)


START = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def _tick(seconds, bid, ask):
    return MarketTick(
        time=(START + timedelta(seconds=seconds)).isoformat(),
        bid=bid,
        ask=ask,
    )


def _buy_opportunity():
    return OpeningOpportunity(
        template=OpeningTemplate.BREAK_HOLD,
        direction="BUY",
        signal_time=START.isoformat(),
        level_side="high",
        level=100.0,
        touch_count=3,
        tolerance=0.2,
        used_candle_indexes=(10, 11),
        entry_kind="continuation",
    )


def test_continuation_order_fills_until_target_with_mfe_and_mae():
    ticks = [
        _tick(0, 100.05, 100.25),
        _tick(2, 100.35, 100.55),
        _tick(5, 100.80, 101.00),
        _tick(7, 101.50, 101.70),
    ]

    result = simulate_opportunity(_buy_opportunity(), ticks, ReplayConfig())

    assert result.status == "CLOSED"
    assert result.exit_reason == "TARGET"
    assert result.filled_at == ticks[0].time
    assert result.profit > 0
    assert result.mfe > 0
    assert result.mae <= 0


def test_reaction_order_expires_after_20_seconds_without_fill():
    opportunity = _buy_opportunity().model_copy(update={"entry_kind": "reaction"})
    ticks = [_tick(0, 99.70, 99.90), _tick(21, 99.75, 99.95)]

    result = simulate_opportunity(opportunity, ticks, ReplayConfig())

    assert result.status == "EXPIRED"
    assert result.filled_at is None
    assert result.profit is None


def test_missing_decision_tick_is_insufficient_evidence():
    result = simulate_opportunity(_buy_opportunity(), [], ReplayConfig())

    assert result.status == "INSUFFICIENT_TICK_EVIDENCE"
    assert result.reason == "NO_DECISION_TICK"


def test_ambiguous_stop_and_target_same_tick_is_excluded():
    ticks = [
        _tick(0, 100.05, 100.25),
        MarketTick(time=(START + timedelta(seconds=1)).isoformat(), bid=98.0, ask=102.0),
    ]

    result = simulate_opportunity(_buy_opportunity(), ticks, ReplayConfig())

    assert result.status == "INSUFFICIENT_TICK_EVIDENCE"
    assert result.reason == "AMBIGUOUS_STOP_AND_TARGET"
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_tick_replay.py -q
```

Expected: FAIL because `opening_tick_replay` does not exist.

- [ ] **Step 3: Implement minimal deterministic replay**

Create `tradingagents/agents/price_action/opening_tick_replay.py` with:

```python
"""Broker-free tick replay for M1 opening-state research."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from tradingagents.agents.price_action.opening_state import OpeningOpportunity


class MarketTick(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    time: str
    bid: float
    ask: float


class ReplayConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reaction_expiry_seconds: int = 20
    continuation_expiry_seconds: int = 45
    risk_reward: float = 1.5
    minimum_stop_distance: float = 0.30
    max_quote_drift: float = 0.60


class SimulatedOpeningTrade(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["CLOSED", "EXPIRED", "INSUFFICIENT_TICK_EVIDENCE"]
    reason: str | None = None
    direction: Literal["BUY", "SELL"]
    placed_at: str
    filled_at: str | None
    closed_at: str | None
    entry_price: float | None
    stop_loss: float | None
    take_profit: float | None
    exit_reason: str | None
    profit: float | None
    mfe: float | None
    mae: float | None
    spread_at_decision: float | None


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _side_price(direction: str, tick: MarketTick) -> float:
    return float(tick.ask if direction == "BUY" else tick.bid)


def _mark_price(direction: str, tick: MarketTick) -> float:
    return float(tick.bid if direction == "BUY" else tick.ask)


def _risk(opportunity: OpeningOpportunity, entry: float, config: ReplayConfig) -> float:
    structural = abs(entry - float(opportunity.level)) + float(opportunity.tolerance)
    return max(structural, float(config.minimum_stop_distance))


def _levels(opportunity: OpeningOpportunity, entry: float, config: ReplayConfig) -> tuple[float, float]:
    risk = _risk(opportunity, entry, config)
    if opportunity.direction == "BUY":
        return round(entry - risk, 4), round(entry + risk * config.risk_reward, 4)
    return round(entry + risk, 4), round(entry - risk * config.risk_reward, 4)


def _profit(direction: str, entry: float, exit_price: float) -> float:
    if direction == "BUY":
        return round(exit_price - entry, 4)
    return round(entry - exit_price, 4)


def simulate_opportunity(
    opportunity: OpeningOpportunity,
    ticks: list[MarketTick] | tuple[MarketTick, ...],
    config: ReplayConfig,
) -> SimulatedOpeningTrade:
    ordered = sorted(ticks, key=lambda item: _parse(item.time))
    decision_time = _parse(opportunity.signal_time)
    usable = [tick for tick in ordered if _parse(tick.time) >= decision_time]
    if not usable:
        return SimulatedOpeningTrade(
            status="INSUFFICIENT_TICK_EVIDENCE",
            reason="NO_DECISION_TICK",
            direction=opportunity.direction,
            placed_at=opportunity.signal_time,
            filled_at=None,
            closed_at=None,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            exit_reason=None,
            profit=None,
            mfe=None,
            mae=None,
            spread_at_decision=None,
        )
    decision_tick = usable[0]
    entry = _side_price(opportunity.direction, decision_tick)
    stop, target = _levels(opportunity, entry, config)
    expiry = decision_time + timedelta(
        seconds=(
            config.reaction_expiry_seconds
            if opportunity.entry_kind == "reaction"
            else config.continuation_expiry_seconds
        )
    )
    fill: MarketTick | None = None
    for tick in usable:
        if _parse(tick.time) > expiry:
            break
        if abs(_side_price(opportunity.direction, tick) - entry) <= config.max_quote_drift:
            fill = tick
            break
    if fill is None:
        return SimulatedOpeningTrade(
            status="EXPIRED",
            reason="ENTRY_NOT_TOUCHED_BEFORE_EXPIRY",
            direction=opportunity.direction,
            placed_at=opportunity.signal_time,
            filled_at=None,
            closed_at=None,
            entry_price=round(entry, 4),
            stop_loss=stop,
            take_profit=target,
            exit_reason=None,
            profit=None,
            mfe=None,
            mae=None,
            spread_at_decision=round(float(decision_tick.ask) - float(decision_tick.bid), 4),
        )
    mfe = 0.0
    mae = 0.0
    for tick in usable[usable.index(fill) :]:
        mark = _mark_price(opportunity.direction, tick)
        favorable = _profit(opportunity.direction, entry, mark)
        mfe = max(mfe, favorable)
        mae = min(mae, favorable)
        hit_target = mark >= target if opportunity.direction == "BUY" else mark <= target
        hit_stop = mark <= stop if opportunity.direction == "BUY" else mark >= stop
        if hit_target and hit_stop:
            return SimulatedOpeningTrade(
                status="INSUFFICIENT_TICK_EVIDENCE",
                reason="AMBIGUOUS_STOP_AND_TARGET",
                direction=opportunity.direction,
                placed_at=opportunity.signal_time,
                filled_at=fill.time,
                closed_at=None,
                entry_price=round(entry, 4),
                stop_loss=stop,
                take_profit=target,
                exit_reason=None,
                profit=None,
                mfe=round(mfe, 4),
                mae=round(mae, 4),
                spread_at_decision=round(float(decision_tick.ask) - float(decision_tick.bid), 4),
            )
        if hit_target or hit_stop:
            exit_reason = "TARGET" if hit_target else "STOP"
            exit_price = target if hit_target else stop
            return SimulatedOpeningTrade(
                status="CLOSED",
                reason=None,
                direction=opportunity.direction,
                placed_at=opportunity.signal_time,
                filled_at=fill.time,
                closed_at=tick.time,
                entry_price=round(entry, 4),
                stop_loss=stop,
                take_profit=target,
                exit_reason=exit_reason,
                profit=_profit(opportunity.direction, entry, exit_price),
                mfe=round(mfe, 4),
                mae=round(mae, 4),
                spread_at_decision=round(float(decision_tick.ask) - float(decision_tick.bid), 4),
            )
    return SimulatedOpeningTrade(
        status="INSUFFICIENT_TICK_EVIDENCE",
        reason="NO_EXIT_TICK",
        direction=opportunity.direction,
        placed_at=opportunity.signal_time,
        filled_at=fill.time,
        closed_at=None,
        entry_price=round(entry, 4),
        stop_loss=stop,
        take_profit=target,
        exit_reason=None,
        profit=None,
        mfe=round(mfe, 4),
        mae=round(mae, 4),
        spread_at_decision=round(float(decision_tick.ask) - float(decision_tick.bid), 4),
    )
```

- [ ] **Step 4: Run tick-replay tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_tick_replay.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/price_action/opening_tick_replay.py tests/test_one_minute_opening_tick_replay.py
git commit -m "feat: replay scalper opening-state ticks"
```

---

### Task 3: Leave-one-day-out screening and gates

**Files:**
- Create: `tradingagents/agents/price_action/opening_state_screening.py`
- Create: `tests/test_one_minute_opening_screening.py`

- [ ] **Step 1: Write failing screening tests**

Add this test file:

```python
from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_tick_replay import MarketTick
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
    screen_opening_fixture,
)


START = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def _candle(day, index, open_, high, low, close):
    return Candle(
        timestamp=(START + timedelta(days=day, minutes=index)).isoformat(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


def _tick(day, seconds, bid, ask):
    return MarketTick(
        time=(START + timedelta(days=day, minutes=5, seconds=seconds)).isoformat(),
        bid=bid,
        ask=ask,
    )


def _day(day, profitable=True):
    candles = [
        _candle(day, 0, 100, 101, 99.5, 100.5),
        _candle(day, 1, 100.4, 101.02, 100.0, 100.2),
        _candle(day, 2, 100.1, 100.6, 99.9, 100.1),
        _candle(day, 3, 100.5, 101.8, 100.4, 101.35),
        _candle(day, 4, 101.3, 101.7, 101.1, 101.45),
    ]
    ticks = (
        [_tick(day, 0, 101.40, 101.60), _tick(day, 2, 102.60, 102.80)]
        if profitable
        else [_tick(day, 0, 101.40, 101.60), _tick(day, 2, 100.70, 100.90)]
    )
    return candles, ticks


def test_opening_screen_is_deterministic_and_broker_free():
    candles = []
    ticks = []
    for day in range(3):
        day_candles, day_ticks = _day(day, profitable=True)
        candles.extend(day_candles)
        ticks.extend(day_ticks)
    fixture = OpeningResearchFixture(schema_version=1, candles=candles, ticks=ticks)

    first = screen_opening_fixture(fixture)
    second = screen_opening_fixture(fixture)

    assert first == second
    assert first["broker_mutation_enabled"] is False
    assert first["decision"] == "FREEZE_OPENING_TEMPLATE"
    assert first["qualifying_templates"] == ["BREAK_HOLD"]


def test_opening_screen_reports_no_edge_when_all_templates_fail_gate():
    candles = []
    ticks = []
    for day in range(3):
        day_candles, day_ticks = _day(day, profitable=False)
        candles.extend(day_candles)
        ticks.extend(day_ticks)
    fixture = OpeningResearchFixture(schema_version=1, candles=candles, ticks=ticks)

    report = screen_opening_fixture(fixture)

    assert report["decision"] == "NO_OPENING_STATE_EDGE"
    assert report["qualifying_templates"] == []
    assert "NON_POSITIVE_EXPECTANCY" in report["templates"]["BREAK_HOLD"]["gate"]["reasons"]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_screening.py -q
```

Expected: FAIL because `opening_state_screening` does not exist.

- [ ] **Step 3: Implement screening API**

Create `tradingagents/agents/price_action/opening_state_screening.py` with:

```python
"""Leave-one-day-out opening-state template screening."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from tradingagents.agents.price_action.evidence_gate import ScreeningRow
from tradingagents.agents.price_action.evidence_metrics import (
    evaluate_historical_gate,
    summarize_variant,
)
from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_state import (
    OpeningTemplate,
    detect_opening_opportunities,
)
from tradingagents.agents.price_action.opening_tick_replay import (
    MarketTick,
    ReplayConfig,
    simulate_opportunity,
)


class OpeningResearchFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int
    candles: tuple[Candle, ...]
    ticks: tuple[MarketTick, ...]


def _day(value: str) -> str:
    return datetime.fromisoformat(value).date().isoformat()


def _rows_for_template(
    fixture: OpeningResearchFixture,
    template: OpeningTemplate,
) -> tuple[ScreeningRow, ...]:
    opportunities = [
        item
        for item in detect_opening_opportunities(fixture.candles)
        if item.template == template
    ]
    rows: list[ScreeningRow] = []
    for index, opportunity in enumerate(opportunities):
        result = simulate_opportunity(opportunity, fixture.ticks, ReplayConfig())
        rows.append(
            ScreeningRow(
                session_id=_day(opportunity.signal_time),
                decision_index=index,
                accepted=True,
                filled=result.status == "CLOSED",
                profit=result.profit if result.status == "CLOSED" else None,
                reasons=(() if result.status == "CLOSED" else (result.reason or result.status,)),
            )
        )
    return tuple(rows)


def _baseline_rows(fixture: OpeningResearchFixture) -> tuple[ScreeningRow, ...]:
    rows: list[ScreeningRow] = []
    for template in OpeningTemplate:
        rows.extend(_rows_for_template(fixture, template))
    return tuple(rows)


def _source_hash(fixture: OpeningResearchFixture) -> str:
    payload = fixture.model_dump(mode="json")
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def screen_opening_fixture(fixture: OpeningResearchFixture) -> dict[str, Any]:
    baseline = summarize_variant(
        "opening_state_baseline",
        _baseline_rows(fixture),
        baseline_fill_count=max(1, len(_baseline_rows(fixture))),
    )
    templates: dict[str, Any] = {}
    qualifying: list[str] = []
    for template in OpeningTemplate:
        rows = _rows_for_template(fixture, template)
        metrics = summarize_variant(
            template.value,
            rows,
            baseline_fill_count=max(1, baseline.fills),
        )
        gate = evaluate_historical_gate(metrics, baseline)
        templates[template.value] = {
            "metrics": metrics.model_dump(mode="json"),
            "gate": gate.model_dump(mode="json"),
        }
        if gate.passed:
            qualifying.append(template.value)
    return {
        "schema_version": 1,
        "broker_mutation_enabled": False,
        "source_fixture_hash": _source_hash(fixture),
        "baseline": baseline.model_dump(mode="json"),
        "templates": templates,
        "qualifying_templates": qualifying,
        "decision": (
            "FREEZE_OPENING_TEMPLATE"
            if qualifying
            else "NO_OPENING_STATE_EDGE"
        ),
    }


def screen_opening_fixture_path(path: str | Path) -> dict[str, Any]:
    fixture = OpeningResearchFixture.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
    return screen_opening_fixture(fixture)
```

- [ ] **Step 4: Run screening tests and verify GREEN**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_screening.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/price_action/opening_state_screening.py tests/test_one_minute_opening_screening.py
git commit -m "feat: screen scalper opening-state templates"
```

---

### Task 4: CLI command and sanitized fixture

**Files:**
- Create: `tests/fixtures/one_minute/opening_state/sample-openings.json`
- Create: `tests/test_one_minute_opening_state_cli.py`
- Modify: `cli/main.py`

- [ ] **Step 1: Write failing CLI test**

Add this test file:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app
from tradingagents.agents.price_action.opening_state_screening import (
    screen_opening_fixture_path,
)


FIXTURE = Path("tests/fixtures/one_minute/opening_state/sample-openings.json")


def test_opening_state_cli_writes_deterministic_broker_free_report(tmp_path):
    output = tmp_path / "opening-screen.json"

    result = CliRunner().invoke(
        app,
        [
            "one-minute-opening-state-screen",
            "--fixture",
            str(FIXTURE),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload == screen_opening_fixture_path(FIXTURE)
    assert payload["broker_mutation_enabled"] is False
```

- [ ] **Step 2: Add the minimal fixture**

Create `tests/fixtures/one_minute/opening_state/sample-openings.json` with sanitized candles/ticks. Use only:

```json
{
  "schema_version": 1,
  "candles": [
    {"timestamp": "2026-07-01T12:00:00+00:00", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 100.0},
    {"timestamp": "2026-07-01T12:01:00+00:00", "open": 100.4, "high": 101.02, "low": 100.0, "close": 100.2, "volume": 100.0},
    {"timestamp": "2026-07-01T12:02:00+00:00", "open": 100.1, "high": 100.6, "low": 99.9, "close": 100.1, "volume": 100.0},
    {"timestamp": "2026-07-01T12:03:00+00:00", "open": 100.5, "high": 101.8, "low": 100.4, "close": 101.35, "volume": 100.0},
    {"timestamp": "2026-07-01T12:04:00+00:00", "open": 101.3, "high": 101.7, "low": 101.1, "close": 101.45, "volume": 100.0},
    {"timestamp": "2026-07-02T12:00:00+00:00", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 100.0},
    {"timestamp": "2026-07-02T12:01:00+00:00", "open": 100.4, "high": 101.02, "low": 100.0, "close": 100.2, "volume": 100.0},
    {"timestamp": "2026-07-02T12:02:00+00:00", "open": 100.1, "high": 100.6, "low": 99.9, "close": 100.1, "volume": 100.0},
    {"timestamp": "2026-07-02T12:03:00+00:00", "open": 100.5, "high": 101.8, "low": 100.4, "close": 101.35, "volume": 100.0},
    {"timestamp": "2026-07-02T12:04:00+00:00", "open": 101.3, "high": 101.7, "low": 101.1, "close": 101.45, "volume": 100.0},
    {"timestamp": "2026-07-03T12:00:00+00:00", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 100.0},
    {"timestamp": "2026-07-03T12:01:00+00:00", "open": 100.4, "high": 101.02, "low": 100.0, "close": 100.2, "volume": 100.0},
    {"timestamp": "2026-07-03T12:02:00+00:00", "open": 100.1, "high": 100.6, "low": 99.9, "close": 100.1, "volume": 100.0},
    {"timestamp": "2026-07-03T12:03:00+00:00", "open": 100.5, "high": 101.8, "low": 100.4, "close": 101.35, "volume": 100.0},
    {"timestamp": "2026-07-03T12:04:00+00:00", "open": 101.3, "high": 101.7, "low": 101.1, "close": 101.45, "volume": 100.0}
  ],
  "ticks": [
    {"time": "2026-07-01T12:05:00+00:00", "bid": 101.4, "ask": 101.6},
    {"time": "2026-07-01T12:05:02+00:00", "bid": 102.6, "ask": 102.8},
    {"time": "2026-07-02T12:05:00+00:00", "bid": 101.4, "ask": 101.6},
    {"time": "2026-07-02T12:05:02+00:00", "bid": 102.6, "ask": 102.8},
    {"time": "2026-07-03T12:05:00+00:00", "bid": 101.4, "ask": 101.6},
    {"time": "2026-07-03T12:05:02+00:00", "bid": 102.6, "ask": 102.8}
  ]
}
```

- [ ] **Step 3: Run the CLI test and verify RED**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state_cli.py -q
```

Expected: FAIL because the Typer command is not registered.

- [ ] **Step 4: Add the CLI command**

In `cli/main.py`, add after `one_minute_walk_forward`:

```python
@app.command("one-minute-opening-state-screen")
def one_minute_opening_state_screen(
    fixture: Path = typer.Option(..., "--fixture"),
    output: Path = typer.Option(..., "--output"),
):
    """Run broker-free opening-state template screening on sanitized evidence."""
    from tradingagents.agents.price_action.opening_state_screening import (
        screen_opening_fixture_path,
    )

    report = screen_opening_fixture_path(fixture)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    console.print(json.dumps(report, indent=2, sort_keys=True))
```

- [ ] **Step 5: Run CLI and related tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state_cli.py tests/test_one_minute_opening_screening.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Secret-key scan the fixture**

Run:

```powershell
rg -n "account|login|password|server|terminal|ticket|order|deal|position_id|token|key|secret" tests/fixtures/one_minute/opening_state
```

Expected: no output.

- [ ] **Step 7: Commit**

```powershell
git add cli/main.py tests/test_one_minute_opening_state_cli.py tests/fixtures/one_minute/opening_state/sample-openings.json
git commit -m "feat: add scalper opening-state screening CLI"
```

---

### Task 5: Actual historical screen report

**Files:**
- Create: `docs/analysis/2026-07-03-one-minute-opening-state-screening.md`
- Generated but not tracked unless sanitized and small: `test-artifacts/opening-state/*.json`

- [ ] **Step 1: Run deterministic fixture screening**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state.py tests/test_one_minute_opening_tick_replay.py tests/test_one_minute_opening_screening.py tests/test_one_minute_opening_state_cli.py -q
```

Expected: all opening-state tests pass.

- [ ] **Step 2: If read-only MT5 historical export is available, produce a local untracked research fixture**

Use only read-only MT5 candle/tick APIs. Store raw output under `test-artifacts/opening-state/`, not under `results/` and not in tracked source. Do not print or write account IDs, server names, logins, terminal paths, tickets, order IDs, deal IDs, credentials, API keys, tokens, or populated `.env` values.

If the MT5 tick API is unavailable or returns fewer than the required bars/ticks, write the report with `INSUFFICIENT_READ_ONLY_TICK_HISTORY` and keep the goal active.

- [ ] **Step 3: Write the analysis report**

The report must include:

```markdown
# One Minute Opening-State Screening

**Date:** 2026-07-03
**Runner state:** execution runner stopped; no broker mutation performed.
**Design:** `docs/superpowers/specs/2026-07-03-one-minute-opening-state-research-design.md`

## Data

- Source:
- M1 bars:
- Tick rows:
- UTC day partitions:
- Sanitization:

## Gate

- Historical PF gate: `>= 1.15`
- Expectancy/net gate: positive
- Session/day gate: at least two profitable held-out days
- Retention gate: at least 60% of baseline eligible opportunities
- Drawdown gate: no worse than baseline

## Result

| Template | Fills | Net | PF | Expectancy | Profitable days | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| REJECTION | | | | | | |
| BREAK_HOLD | | | | | | |
| BREAK_RETEST_HOLD | | | | | | |
| FAILED_BREAK | | | | | | |

## Decision

`FREEZE_OPENING_TEMPLATE` or `NO_OPENING_STATE_EDGE` or `INSUFFICIENT_READ_ONLY_TICK_HISTORY`

## Safety

- No broker orders placed, modified, or closed.
- No execution runner started.
- No credentials or account identifiers tracked.
```

- [ ] **Step 4: Commit report**

```powershell
git add docs/analysis/2026-07-03-one-minute-opening-state-screening.md
git commit -m "docs: report scalper opening-state screening"
```

---

### Task 6: Verification, push, and goal-status update

**Files:**
- All files from Tasks 1-5.

- [ ] **Step 1: Run focused opening-state tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_opening_state.py tests/test_one_minute_opening_tick_replay.py tests/test_one_minute_opening_screening.py tests/test_one_minute_opening_state_cli.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run related scalper evidence regression tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_one_minute_evidence_gate.py tests/test_one_minute_evidence_metrics.py tests/test_one_minute_historical_screening.py tests/test_one_minute_walk_forward_selector.py tests/test_one_minute_walk_forward_cli.py tests/test_one_minute_signal_replay.py tests/test_one_minute_entry_model.py -q
```

Expected: all related tests pass.

- [ ] **Step 3: Run complete pytest suite**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Expected: all tests pass, with only known skips.

- [ ] **Step 4: Run diff whitespace check**

Run:

```powershell
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 5: Inspect status and staged files**

Run:

```powershell
git status --short --branch
git ls-files docs/superpowers/plans/2026-07-03-one-minute-opening-state-research.md docs/superpowers/specs/2026-07-03-one-minute-opening-state-research-design.md
```

Expected: clean branch after commits; both docs are tracked.

- [ ] **Step 6: Secret scan tracked changes**

Run:

```powershell
git grep -n "TRADINGAGENTS_MT5_PASSWORD\\|TRADINGAGENTS_MT5_LOGIN=.*[0-9]\\|password\\s*[:=]\\s*['\\\"]\\|api[_-]*key\\s*[:=]\\s*['\\\"]\\|token\\s*[:=]\\s*['\\\"]" HEAD
```

Expected: no populated secrets. Placeholder names in `.env.example` or docs are acceptable only if no values are present.

- [ ] **Step 7: Push**

Run:

```powershell
git push origin main
git rev-parse HEAD
git rev-parse origin/main
```

Expected: push succeeds and local HEAD equals `origin/main`.

- [ ] **Step 8: Verify runner remains stopped**

Run:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -or $_.Name -like 'tradingagents*' } | Select-Object ProcessId,Name,CreationDate,CommandLine
```

Expected: no `mt5-run` process. If unrelated Python processes appear, inspect command line and do not stop them unless they are the execution runner.

---

## Self-Review

- Spec coverage:
  - Repeated-level state machine: Task 1.
  - Four pre-registered templates: Task 1 and Task 3.
  - Recorded tick simulation: Task 2.
  - Leave-one-day-out evaluation and historical gates: Task 3.
  - Sanitized fixture and CLI: Task 4.
  - Actual screening report: Task 5.
  - No broker mutation and runner stopped: Tasks 3, 4, 5, and 6.
- Placeholder scan: no unfinished placeholder markers or open-ended implementation
  placeholders remain.
- Type consistency:
  - `OpeningOpportunity`, `MarketTick`, `ReplayConfig`, `SimulatedOpeningTrade`, and `OpeningResearchFixture` are introduced before later tasks use them.
  - CLI command calls `screen_opening_fixture_path`, which Task 3 defines.
- Known limitation:
  - Task 2 implements the smallest conservative tick replay needed to establish deterministic infrastructure. If parity against recorded broker sessions reveals a mismatch, add a failing parity test before changing replay behavior.
