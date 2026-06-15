# One Minute Scalper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an isolated deterministic One Minute Scalper that reads the last 60 fully closed 1m candles, detects and scores multiple two-high/two-low openings, selects one best valid opening, and routes one trade at a time through the existing MT5 guarded execution path with fast protection and full telemetry.

**Architecture:** Keep the public `analyze_playbook` dispatcher, but make `tradingagents/agents/price_action/one_minute_entry_model.py` a true candidate engine instead of a single-trigger detector. The model produces structured candidate evaluations, selects the highest-quality approved candidate, carries strict volume and lifecycle metadata into `OrderProposal`, and relies on existing MT5 runner/executor guards for one-active-trade, partials, break-even, trailing, and candle-rejection exits.

**Tech Stack:** Python 3, dataclasses, Pydantic `OrderProposal`, pytest, existing TradingAgents price-action models, MT5 runner/executor telemetry JSON.

---

## Scope Boundary

This plan changes only the One Minute Scalper phase.

Do change:

- `tradingagents/agents/price_action/one_minute_entry_model.py`
- `tradingagents/agents/execution/order_proposal.py`
- `tradingagents/agents/schemas.py`
- `tradingagents/default_config.py`
- `tests/test_one_minute_entry_model.py`
- `tests/test_price_action_engine.py`
- `tests/test_order_proposal.py`
- focused MT5 execution or runner tests only when they verify existing fast lifecycle behavior still receives proposal metadata

Do not change:

- `tradingagents/agents/price_action/normal_entry_model.py` strategy logic
- `tradingagents/brokers/mt5_straddle.py`
- real-money execution behavior
- LLM live decision paths
- mode-gate behavior outside necessary labels or telemetry compatibility

## Current State To Preserve

- The dispatcher already routes fast 1m sessions through `analyze_one_minute_entry`.
- `MT5Executor` already supports proposal-level `FAST_PARTIAL_SCALE`, partial close targets, break-even, trailing, and 1m candle rejection exits.
- `MT5Runner` already blocks new analysis when an active order or position exists.
- `OrderProposal` already carries volume multiplier and dynamic exit fields.
- Existing dirty files `tradingagents/brokers/mt5.py` and `tests/test_mt5_broker.py` are unrelated; do not revert them.

## Design Decisions Locked For This Phase

- Model name in telemetry: `One Minute Scalper`.
- Input memory: last 60 closed 1m candles.
- Entry source: latest closed candle must confirm one selected candidate.
- Candidate types:
  - `LOW_RESPECT_BUY`
  - `HIGH_RESPECT_SELL`
  - `LOW_BREAK_SELL`
  - `HIGH_BREAK_BUY`
  - `FAILED_LOW_BREAK_BUY`
  - `FAILED_HIGH_BREAK_SELL`
- Two touches are tradable when clean.
- Three touches increase score and priority.
- Default volume remains 1.0 through absence of `volume_multiplier`.
- `volume_multiplier=1.5` is allowed only for strict high-confidence candidates.
- 1m pending activation window default becomes 1 minute.
- One trade at a time remains enforced by runner/executor, not by opening multiple orders in the model.

## Checkpoints

- Checkpoint 1: Failing tests written for candidate telemetry, scoring, strict volume, and activation-window freshness.
- Checkpoint 2: One-minute model refactored to multi-candidate scoring and focused tests passing.
- Checkpoint 3: Proposal freshness and rendered labels updated, compatibility tests passing.
- Checkpoint 4: Full test suite passing.
- Checkpoint 5: Commit/push and fresh demo restart only after verification.

---

### Task 1: Add Failing One Minute Scalper Model Tests

**Files:**

- Modify: `tests/test_one_minute_entry_model.py`

- [ ] **Step 1: Append candidate-helper assertions**

Add these helpers after `_payload`:

```python
def _candidate_by_trigger(payload, trigger_name):
    candidates = payload["telemetry"]["candidate_evaluations"]
    matches = [item for item in candidates if item["trigger"] == trigger_name]
    assert matches, f"Missing candidate {trigger_name}: {candidates}"
    return matches[0]


def _assert_candidate_journal_shape(candidate):
    assert candidate["model_name"] == "One Minute Scalper"
    assert candidate["trigger"]
    assert candidate["direction"] in {"BUY", "SELL"}
    assert candidate["reaction_type"] in {"respect", "break", "fakeout"}
    assert candidate["confirmation_type"] in {
        "rejection",
        "engulfing",
        "strong_close",
        "mixed",
    }
    assert candidate["level_type"] in {"two_touch", "three_touch"}
    assert candidate["touch_count"] >= 2
    assert isinstance(candidate["score"], (int, float))
    assert isinstance(candidate["score_reasons"], list)
    assert isinstance(candidate["rejection_reasons"], list)
    assert candidate["volume_decision"] in {"BASE_1_0", "BOOST_1_5", "REJECTED"}
```

- [ ] **Step 2: Add test for model name and multiple candidate journaling**

Append:

```python
def test_one_minute_scalper_journals_multiple_candidates_and_selects_best_valid_opening():
    candles = [
        _candle(0, 100.0, 100.8, 99.7, 100.1),
        _candle(1, 100.1, 101.0, 99.8, 100.8),
        _candle(2, 100.8, 101.1, 100.1, 100.3),
        _candle(3, 100.3, 101.05, 100.0, 100.6),
        _candle(4, 100.6, 101.0, 99.8, 100.4),
        _candle(5, 100.4, 100.9, 99.2, 99.8),
        _candle(6, 99.8, 100.5, 99.15, 100.0),
        _candle(7, 100.0, 100.4, 99.1, 99.6),
        _candle(8, 99.6, 100.7, 98.7, 100.4),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["market_context"]["one_minute_story"]["model_name"] == "One Minute Scalper"
    assert payload["setups"][0]["name"] == "FAILED_LOW_BREAK_BUY"
    assert payload["telemetry"]["candidate_setup_count"] >= 2
    assert payload["telemetry"]["approved_candidate_count"] >= 1
    assert payload["telemetry"]["selected_candidate"]["trigger"] == "FAILED_LOW_BREAK_BUY"
    for candidate in payload["telemetry"]["candidate_evaluations"]:
        _assert_candidate_journal_shape(candidate)
```

- [ ] **Step 3: Add test for chop rejection**

Append:

```python
def test_one_minute_scalper_rejects_overlapping_chop_candidates():
    candles = [
        _candle(index, 100.0 if index % 2 == 0 else 100.15, 100.45, 99.85, 100.15 if index % 2 == 0 else 100.0)
        for index in range(60)
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["telemetry"]["decision_stage"] == "one_minute_no_approved_candidate"
    assert payload["telemetry"]["candidate_setup_count"] >= 1
    assert any(
        "OVERLAPPING_CHOP" in item["rejection_reasons"]
        for item in payload["telemetry"]["candidate_evaluations"]
    )
```

- [ ] **Step 4: Add tests for strict volume**

Append:

```python
def test_one_minute_scalper_uses_base_volume_for_medium_two_touch_setup():
    candles = _base_history() + [
        _candle(57, 100.4, 100.8, 99.0, 99.7),
        _candle(58, 99.8, 100.4, 99.05, 99.4),
        _candle(59, 99.3, 100.6, 99.10, 100.2),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == "LOW_RESPECT_BUY"
    assert "volume_multiplier" not in payload["risk"]
    assert payload["telemetry"]["selected_candidate"]["volume_decision"] == "BASE_1_0"


def test_one_minute_scalper_allows_boost_only_for_strict_high_confidence_candidate():
    candles = _base_history() + [
        _candle(56, 100.4, 100.8, 99.0, 99.7),
        _candle(57, 99.8, 100.3, 99.05, 99.4),
        _candle(58, 99.5, 100.2, 99.02, 99.3),
        _candle(59, 99.2, 101.0, 98.45, 100.8),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == "FAILED_LOW_BREAK_BUY"
    assert payload["market_context"]["one_minute_story"]["touch_count"] >= 3
    assert payload["risk"]["volume_multiplier"] == 1.5
    assert payload["telemetry"]["selected_candidate"]["volume_decision"] == "BOOST_1_5"
```

- [ ] **Step 5: Add test for latest closed candle confirmation**

Append:

```python
def test_one_minute_scalper_only_executes_when_latest_closed_candle_confirms_candidate():
    candles = _base_history() + [
        _candle(57, 99.8, 101.0, 99.4, 100.4),
        _candle(58, 100.2, 100.95, 99.9, 100.6),
        _candle(59, 100.5, 101.05, 99.9, 100.55),
    ]

    payload = _payload(candles, minimum_stop_distance_price=0.25)

    assert payload["status"] == "NO_SETUP"
    assert payload["recommendation"] == "HOLD"
    assert payload["telemetry"]["candidate_setup_count"] >= 1
    assert payload["telemetry"]["approved_candidate_count"] == 0
    assert all(
        "LATEST_CANDLE_NOT_CONFIRMING" in item["rejection_reasons"]
        or "MIXED_CONFIRMATION" in item["rejection_reasons"]
        for item in payload["telemetry"]["candidate_evaluations"]
    )
```

- [ ] **Step 6: Run failing tests**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py -q
```

Expected: the new tests fail because `candidate_evaluations`, `selected_candidate`, stricter volume logic, and `one_minute_no_approved_candidate` are not implemented yet.

- [ ] **Step 7: Commit failing tests only**

Run:

```powershell
git add tests/test_one_minute_entry_model.py
git commit -m "test: specify one minute scalper candidate scoring"
```

---

### Task 2: Refactor One Minute Model Into Candidate Engine

**Files:**

- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Test: `tests/test_one_minute_entry_model.py`

- [ ] **Step 1: Add focused candidate dataclasses**

In `one_minute_entry_model.py`, add these dataclasses near the constants:

```python
from dataclasses import asdict, dataclass, field
```

```python
MODEL_NAME = "One Minute Scalper"
TWO_TOUCH = "two_touch"
THREE_TOUCH = "three_touch"


@dataclass(frozen=True)
class OneMinuteLevel:
    side: str
    level: float
    touch_count: int
    first_touch_index: int
    last_touch_index: int
    spread: float
    tolerance: float

    @property
    def level_type(self) -> str:
        return THREE_TOUCH if self.touch_count >= 3 else TWO_TOUCH


@dataclass
class OneMinuteCandidate:
    trigger: str
    direction: str
    reaction_type: str
    confirmation_type: str
    level: OneMinuteLevel
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_distance: float
    reward_distance: float
    score: float = 0.0
    approved: bool = False
    score_reasons: list[str] = field(default_factory=list)
    rejection_reasons: list[str] = field(default_factory=list)
    volume_decision: str = "REJECTED"
    volume_multiplier: float | None = None
```

- [ ] **Step 2: Replace single-trigger selection with level detection**

Keep `_recent_tolerance` and replace `_cluster_levels_with_recency` with a function returning `OneMinuteLevel` objects:

```python
def _detect_equal_levels(
    candles: list[Candle],
    tolerance: float,
    *,
    side: str,
) -> list[OneMinuteLevel]:
    prices = [float(candle.high if side == "high" else candle.low) for candle in candles]
    levels: list[OneMinuteLevel] = []
    for index, price in enumerate(prices):
        touches = [
            (touch_index, candidate)
            for touch_index, candidate in enumerate(prices)
            if abs(candidate - price) <= tolerance
        ]
        if len(touches) < 2:
            continue
        level = sum(candidate for _touch_index, candidate in touches) / len(touches)
        if any(abs(existing.level - level) <= tolerance for existing in levels):
            continue
        touch_prices = [candidate for _touch_index, candidate in touches]
        levels.append(
            OneMinuteLevel(
                side=side,
                level=level,
                touch_count=len(touches),
                first_touch_index=min(touch_index for touch_index, _price in touches),
                last_touch_index=max(touch_index for touch_index, _price in touches),
                spread=max(touch_prices) - min(touch_prices),
                tolerance=tolerance,
            )
        )
    return sorted(
        levels,
        key=lambda item: (-item.touch_count, -item.last_touch_index, item.spread),
    )
```

- [ ] **Step 3: Add candle confirmation helpers**

Add helpers that classify the latest closed candle:

```python
def _body_size(candle: Candle) -> float:
    return abs(float(candle.close) - float(candle.open))


def _body_top(candle: Candle) -> float:
    return max(float(candle.open), float(candle.close))


def _body_bottom(candle: Candle) -> float:
    return min(float(candle.open), float(candle.close))


def _close_position(candle: Candle) -> float:
    total = candle_range(candle)
    if total <= 0:
        return 0.5
    return (float(candle.close) - float(candle.low)) / total


def _bullish_engulfing(previous: Candle, latest: Candle) -> bool:
    return (
        is_bearish(previous)
        and is_bullish(latest)
        and _body_bottom(latest) <= _body_bottom(previous)
        and _body_top(latest) >= _body_top(previous)
        and _close_position(latest) >= 0.65
    )


def _bearish_engulfing(previous: Candle, latest: Candle) -> bool:
    return (
        is_bullish(previous)
        and is_bearish(latest)
        and _body_top(latest) >= _body_top(previous)
        and _body_bottom(latest) <= _body_bottom(previous)
        and _close_position(latest) <= 0.35
    )


def _strong_bullish_close(candle: Candle) -> bool:
    total = candle_range(candle)
    return total > 0 and is_bullish(candle) and _body_size(candle) >= total * 0.45 and _close_position(candle) >= 0.70


def _strong_bearish_close(candle: Candle) -> bool:
    total = candle_range(candle)
    return total > 0 and is_bearish(candle) and _body_size(candle) >= total * 0.45 and _close_position(candle) <= 0.30
```

- [ ] **Step 4: Add chop detection**

Add:

```python
def _is_overlapping_chop(candles: list[Candle]) -> bool:
    if len(candles) < 8:
        return False
    recent = candles[-8:]
    highs = [float(candle.high) for candle in recent]
    lows = [float(candle.low) for candle in recent]
    closes = [float(candle.close) for candle in recent]
    total_range = max(highs) - min(lows)
    median_range = median(
        candle_range(candle) for candle in recent if candle_range(candle) > 0
    )
    alternating = sum(
        1
        for left, right in zip(recent, recent[1:])
        if (is_bullish(left) and is_bearish(right)) or (is_bearish(left) and is_bullish(right))
    )
    close_range = max(closes) - min(closes)
    return alternating >= 5 and total_range <= median_range * 2.2 and close_range <= median_range * 0.8
```

- [ ] **Step 5: Add candidate builders**

Implement `_candidate_from_level` to create respect, break, and fakeout candidates from the latest closed candle:

```python
def _candidate_from_level(
    level: OneMinuteLevel,
    previous: Candle,
    latest: Candle,
    *,
    tolerance: float,
    minimum_stop_distance: float,
    max_stop_distance: float,
    boost_max_stop_distance: float,
    risk_reward: float,
) -> OneMinuteCandidate | None:
    break_margin = max(0.05, tolerance * 0.25)
    if level.side == "low":
        if float(latest.low) < level.level - break_margin and float(latest.close) > level.level:
            trigger = FAILED_LOW_BREAK_BUY
            direction = "BUY"
            reaction_type = "fakeout"
        elif float(latest.close) < level.level - break_margin:
            trigger = LOW_BREAK_SELL
            direction = "SELL"
            reaction_type = "break"
        elif abs(float(latest.low) - level.level) <= tolerance and float(latest.close) > level.level:
            trigger = LOW_RESPECT_BUY
            direction = "BUY"
            reaction_type = "respect"
        else:
            return None
    else:
        if float(latest.high) > level.level + break_margin and float(latest.close) < level.level:
            trigger = FAILED_HIGH_BREAK_SELL
            direction = "SELL"
            reaction_type = "fakeout"
        elif float(latest.close) > level.level + break_margin:
            trigger = HIGH_BREAK_BUY
            direction = "BUY"
            reaction_type = "break"
        elif abs(float(latest.high) - level.level) <= tolerance and float(latest.close) < level.level:
            trigger = HIGH_RESPECT_SELL
            direction = "SELL"
            reaction_type = "respect"
        else:
            return None

    risk = _risk_for_trigger(
        {"name": trigger, "direction": direction, "level": level.level, "level_type": "support" if level.side == "low" else "resistance", "touches": level.touch_count},
        latest,
        tolerance=tolerance,
        minimum_stop_distance=minimum_stop_distance,
        max_stop_distance=max_stop_distance,
        boost_max_stop_distance=boost_max_stop_distance,
        risk_reward=risk_reward,
    )
    if not risk.get("approved"):
        candidate = OneMinuteCandidate(
            trigger=trigger,
            direction=direction,
            reaction_type=reaction_type,
            confirmation_type="mixed",
            level=level,
            entry_price=float(latest.close),
            stop_loss=float(latest.close),
            take_profit=float(latest.close),
            risk_distance=0.0,
            reward_distance=0.0,
        )
        candidate.rejection_reasons.append(str(risk.get("reason") or "RISK_REJECTED"))
        return candidate

    confirmation_type = _confirmation_type(trigger, previous, latest)
    return OneMinuteCandidate(
        trigger=trigger,
        direction=direction,
        reaction_type=reaction_type,
        confirmation_type=confirmation_type,
        level=level,
        entry_price=float(risk["entry_price"]),
        stop_loss=float(risk["stop_loss"]),
        take_profit=float(risk["take_profit"]),
        risk_distance=float(risk["risk_distance"]),
        reward_distance=float(risk["reward_distance"]),
    )
```

Add `_confirmation_type`:

```python
def _confirmation_type(trigger: str, previous: Candle, latest: Candle) -> str:
    if trigger in {LOW_RESPECT_BUY, FAILED_LOW_BREAK_BUY}:
        if _bullish_engulfing(previous, latest):
            return "engulfing"
        if _bullish_rejection(latest):
            return "rejection"
        if _strong_bullish_close(latest):
            return "strong_close"
        return "mixed"
    if trigger in {HIGH_RESPECT_SELL, FAILED_HIGH_BREAK_SELL}:
        if _bearish_engulfing(previous, latest):
            return "engulfing"
        if _bearish_rejection(latest):
            return "rejection"
        if _strong_bearish_close(latest):
            return "strong_close"
        return "mixed"
    if trigger == HIGH_BREAK_BUY and _strong_bullish_close(latest):
        return "strong_close"
    if trigger == LOW_BREAK_SELL and _strong_bearish_close(latest):
        return "strong_close"
    return "mixed"
```

- [ ] **Step 6: Add scoring and strict approval**

Add:

```python
def _score_candidate(candidate: OneMinuteCandidate, *, is_chop: bool, boost_max_stop_distance: float) -> OneMinuteCandidate:
    candidate.score = 0.0
    candidate.score_reasons.clear()
    candidate.rejection_reasons.clear()

    candidate.score += 2
    candidate.score_reasons.append("TWO_TOUCH_LEVEL")
    if candidate.level.touch_count >= 3:
        candidate.score += 2
        candidate.score_reasons.append("THIRD_TOUCH_PRIORITY")
    if candidate.confirmation_type == "rejection":
        candidate.score += 2
        candidate.score_reasons.append("CLEAN_REJECTION")
    if candidate.confirmation_type == "engulfing":
        candidate.score += 2
        candidate.score_reasons.append("ENGULFING_CONFIRMATION")
    if candidate.confirmation_type == "strong_close":
        candidate.score += 2
        candidate.score_reasons.append("STRONG_CLOSE")
    if candidate.risk_distance > 0 and candidate.risk_distance <= boost_max_stop_distance:
        candidate.score += 2
        candidate.score_reasons.append("CLOSE_INVALIDATION")

    if candidate.confirmation_type == "mixed":
        candidate.score -= 3
        candidate.rejection_reasons.append("LATEST_CANDLE_NOT_CONFIRMING")
        candidate.rejection_reasons.append("MIXED_CONFIRMATION")
    if is_chop:
        candidate.score -= 3
        candidate.rejection_reasons.append("OVERLAPPING_CHOP")
    if candidate.risk_distance <= 0:
        candidate.rejection_reasons.append("INVALID_STOP_DISTANCE")

    candidate.approved = candidate.score >= 6 and not candidate.rejection_reasons
    if not candidate.approved:
        candidate.volume_decision = "REJECTED"
        return candidate

    high_confidence = (
        candidate.score >= 8
        and candidate.level.touch_count >= 3
        and candidate.confirmation_type in {"engulfing", "rejection"}
        and candidate.risk_distance <= boost_max_stop_distance
        and candidate.trigger in HIGH_CONFIDENCE_ONE_MINUTE_TRIGGERS
    )
    if high_confidence:
        candidate.volume_decision = "BOOST_1_5"
        candidate.volume_multiplier = 1.5
    else:
        candidate.volume_decision = "BASE_1_0"
    return candidate
```

- [ ] **Step 7: Select the best current candidate**

Add:

```python
def _build_candidates(
    history: list[Candle],
    *,
    tolerance: float,
    minimum_stop_distance: float,
    max_stop_distance: float,
    boost_max_stop_distance: float,
    risk_reward: float,
) -> list[OneMinuteCandidate]:
    latest = history[-1]
    previous = history[-2]
    prior = history[:-1]
    levels = [
        *_detect_equal_levels(prior, tolerance, side="low"),
        *_detect_equal_levels(prior, tolerance, side="high"),
    ]
    is_chop = _is_overlapping_chop(history)
    candidates: list[OneMinuteCandidate] = []
    for level in levels:
        candidate = _candidate_from_level(
            level,
            previous,
            latest,
            tolerance=tolerance,
            minimum_stop_distance=minimum_stop_distance,
            max_stop_distance=max_stop_distance,
            boost_max_stop_distance=boost_max_stop_distance,
            risk_reward=risk_reward,
        )
        if candidate is None:
            continue
        candidates.append(
            _score_candidate(
                candidate,
                is_chop=is_chop,
                boost_max_stop_distance=boost_max_stop_distance,
            )
        )
    return sorted(
        candidates,
        key=lambda item: (
            item.approved,
            item.score,
            item.level.touch_count,
            item.level.last_touch_index,
            -item.risk_distance,
        ),
        reverse=True,
    )
```

- [ ] **Step 8: Add candidate telemetry serialization**

Add:

```python
def _candidate_to_telemetry(candidate: OneMinuteCandidate) -> dict[str, Any]:
    return {
        "model_name": MODEL_NAME,
        "trigger": candidate.trigger,
        "direction": candidate.direction,
        "reaction_type": candidate.reaction_type,
        "confirmation_type": candidate.confirmation_type,
        "level": round(candidate.level.level, 4),
        "level_side": candidate.level.side,
        "level_type": candidate.level.level_type,
        "touch_count": candidate.level.touch_count,
        "score": round(candidate.score, 2),
        "approved": candidate.approved,
        "score_reasons": list(candidate.score_reasons),
        "rejection_reasons": list(candidate.rejection_reasons),
        "entry_price": round(candidate.entry_price, 4),
        "stop_loss": round(candidate.stop_loss, 4),
        "take_profit": round(candidate.take_profit, 4),
        "risk_distance": round(candidate.risk_distance, 4),
        "reward_distance": round(candidate.reward_distance, 4),
        "volume_decision": candidate.volume_decision,
        "volume_multiplier": candidate.volume_multiplier,
    }
```

- [ ] **Step 9: Update payload and setup creation**

Update `_payload` to accept `candidate_evaluations` and `selected_candidate`, and include these telemetry fields:

```python
"model_name": MODEL_NAME,
"candidate_setup_count": len(candidate_evaluations or []),
"approved_candidate_count": sum(1 for item in candidate_evaluations or [] if item.get("approved")),
"candidate_evaluations": candidate_evaluations or [],
"selected_candidate": selected_candidate,
```

Update story fields for selected setup:

```python
story.update(
    {
        "model_name": MODEL_NAME,
        "classification": selected.trigger,
        "direction": selected.direction,
        "level": round(selected.level.level, 4),
        "touch_count": selected.level.touch_count,
        "level_type": selected.level.level_type,
        "reaction_type": selected.reaction_type,
        "confirmation_type": selected.confirmation_type,
        "score": round(selected.score, 2),
        "trigger_candle": latest.timestamp,
    }
)
```

Create setup/risk from `OneMinuteCandidate` so `volume_multiplier` appears only when `candidate.volume_multiplier` is set.

- [ ] **Step 10: Update no-approved-candidate behavior**

When candidates exist but none is approved, return:

```python
status="NO_SETUP"
recommendation="HOLD"
message="One Minute Scalper found candidates but none passed scoring."
decision_stage="one_minute_no_approved_candidate"
```

- [ ] **Step 11: Run focused one-minute tests**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py -q
```

Expected: all tests in `tests/test_one_minute_entry_model.py` pass.

- [ ] **Step 12: Commit model refactor**

Run:

```powershell
git add tradingagents/agents/price_action/one_minute_entry_model.py tests/test_one_minute_entry_model.py
git commit -m "feat: score one minute scalper candidates"
```

---

### Task 3: Remove Old 1m/3m Wording And Tighten Activation Freshness

**Files:**

- Modify: `tradingagents/default_config.py`
- Modify: `tradingagents/agents/schemas.py`
- Modify: `tests/test_price_action_engine.py`
- Modify: `tests/test_order_proposal.py`
- Modify: `tests/test_env_overrides.py`
- Modify: `tests/test_engine_decision.py`
- Modify: `tests/test_price_action_profiles.py`

- [ ] **Step 1: Change fast activation default**

In `tradingagents/default_config.py`, change:

```python
"fast_activation_window_minutes": 6,
```

to:

```python
"fast_activation_window_minutes": 1,
```

- [ ] **Step 2: Update render label for 1m proposals**

In `tradingagents/agents/schemas.py`, change the 1m secondary label block to use a scalper-memory label:

```python
secondary_timeframe_label = (
    "Scalper Memory"
    if str(proposal.timeframe).strip().lower() == "1m"
    else "Confirmation Timeframe"
)
```

- [ ] **Step 3: Update tests that expect six-minute fast activation**

Replace fast-profile expected activation values from `6` to `1` only where the test relies on defaults. Leave tests that explicitly pass `activation_window_minutes=6` unchanged if their purpose is explicit override behavior.

Update expected rendered timestamps:

```python
assert proposal["activation_window_minutes"] == 1
assert proposal["cancel_if_not_triggered_after"] == "2026-06-03 08:16 EDT"
```

Update label test:

```python
assert "**Scalper Memory**: 1m" in rendered
assert "Confirmation Timeframe" not in rendered
```

- [ ] **Step 4: Update one-minute engine tests to pass `confirmation_timeframe="1m"`**

In tests that still pass fast profile context as `3m`, change the fast session config to:

```python
"entry_profile": "fast",
"timeframe": "1m",
"confirmation_timeframe": "1m",
"zone_timeframes": ("1m",),
"context_timeframes": ("1m",),
"governing_timeframes": ("1m",),
```

This preserves the user decision that the One Minute Scalper uses 1m history as memory, not 3m confirmation.

- [ ] **Step 5: Run compatibility tests**

Run:

```powershell
uv run --group dev pytest tests/test_price_action_engine.py tests/test_order_proposal.py tests/test_env_overrides.py tests/test_engine_decision.py tests/test_price_action_profiles.py -q
```

Expected: tests pass with 1m scalper wording and one-minute default activation.

- [ ] **Step 6: Commit freshness and wording**

Run:

```powershell
git add tradingagents/default_config.py tradingagents/agents/schemas.py tests/test_price_action_engine.py tests/test_order_proposal.py tests/test_env_overrides.py tests/test_engine_decision.py tests/test_price_action_profiles.py
git commit -m "fix: expire one minute scalper entries quickly"
```

---

### Task 4: Carry Candidate Journal Details Into Proposals

**Files:**

- Modify: `tradingagents/agents/schemas.py`
- Modify: `tradingagents/agents/execution/order_proposal.py`
- Modify: `tests/test_order_proposal.py`

- [ ] **Step 1: Add proposal journal fields**

In `OrderProposal`, add optional fields after `strategy_type`:

```python
trigger_name: Optional[str] = None
reaction_type: Optional[str] = None
confirmation_type: Optional[str] = None
touch_count: Optional[int] = None
candidate_score: Optional[float] = None
volume_decision: Optional[str] = None
```

In `default_broker_symbol`, validate:

```python
if self.touch_count is not None and self.touch_count < 0:
    raise ValueError("touch_count must be non-negative when provided")
if self.candidate_score is not None and self.candidate_score < 0:
    raise ValueError("candidate_score must be non-negative when provided")
```

- [ ] **Step 2: Render proposal journal fields**

In `render_order_proposal`, after strategy type, render:

```python
for label, value in (
    ("Trigger Name", proposal.trigger_name),
    ("Reaction Type", proposal.reaction_type),
    ("Confirmation Type", proposal.confirmation_type),
    ("Touch Count", proposal.touch_count),
    ("Candidate Score", proposal.candidate_score),
    ("Volume Decision", proposal.volume_decision),
):
    if value is not None:
        parts.extend(["", f"**{label}**: {value}"])
```

- [ ] **Step 3: Populate proposal fields from selected candidate telemetry**

In `_proposal_from_engine_payload`, after `risk = payload.get("risk") or {}`, add:

```python
telemetry = payload.get("telemetry") or {}
selected_candidate = telemetry.get("selected_candidate") or {}
```

Pass into `OrderProposal`:

```python
trigger_name=str(selected_candidate.get("trigger") or setup_name or "").strip() or None,
reaction_type=str(selected_candidate.get("reaction_type") or "").strip() or None,
confirmation_type=str(selected_candidate.get("confirmation_type") or "").strip() or None,
touch_count=(
    int(selected_candidate["touch_count"])
    if selected_candidate.get("touch_count") is not None
    else None
),
candidate_score=(
    float(selected_candidate["score"])
    if selected_candidate.get("score") is not None
    else None
),
volume_decision=str(selected_candidate.get("volume_decision") or "").strip() or None,
```

- [ ] **Step 4: Add proposal test**

Append to `tests/test_order_proposal.py`:

```python
@pytest.mark.unit
def test_one_minute_scalper_proposal_carries_selected_candidate_journal_fields(tmp_path):
    state = {
        "company_of_interest": "XAUUSD.vx",
        "broker_symbol": "XAUUSD.vx",
        "as_of": "2026-06-03 08:15",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "market_timezone": "America/New_York",
        "engine_payload": {
            "status": "SETUP_FOUND",
            "recommendation": "SELL",
            "entry_profile": "fast",
            "activation_window_minutes": 1,
            "message": "One Minute Scalper selected a candidate.",
            "setups": [
                {
                    "name": "FAILED_HIGH_BREAK_SELL",
                    "direction": "SELL",
                    "entry_price": 4075.17,
                    "stop_loss": 4076.82,
                    "take_profit": 4072.70,
                    "setup_grade": "A_PLUS",
                }
            ],
            "risk": {
                "take_profit": 4072.70,
                "volume_multiplier": 1.5,
                "position_lifecycle": "FAST_PARTIAL_SCALE",
            },
            "telemetry": {
                "selected_candidate": {
                    "trigger": "FAILED_HIGH_BREAK_SELL",
                    "reaction_type": "fakeout",
                    "confirmation_type": "engulfing",
                    "touch_count": 3,
                    "score": 10,
                    "volume_decision": "BOOST_1_5",
                },
                "candidate_setup_count": 2,
            },
        },
    }

    proposal_state = create_order_proposal_executor({"results_dir": tmp_path})(state)
    proposal = json.loads(Path(proposal_state["order_proposal_path"]).read_text())

    assert proposal["trigger_name"] == "FAILED_HIGH_BREAK_SELL"
    assert proposal["reaction_type"] == "fakeout"
    assert proposal["confirmation_type"] == "engulfing"
    assert proposal["touch_count"] == 3
    assert proposal["candidate_score"] == 10
    assert proposal["volume_decision"] == "BOOST_1_5"
```

- [ ] **Step 5: Run proposal tests**

Run:

```powershell
uv run --group dev pytest tests/test_order_proposal.py -q
```

Expected: all proposal tests pass.

- [ ] **Step 6: Commit proposal journaling**

Run:

```powershell
git add tradingagents/agents/schemas.py tradingagents/agents/execution/order_proposal.py tests/test_order_proposal.py
git commit -m "feat: journal one minute scalper candidate details"
```

---

### Task 5: Verify Fast Lifecycle Is Still Wired For One Minute Scalper

**Files:**

- Modify: `tests/test_mt5_execution.py`

- [ ] **Step 1: Add a narrow lifecycle regression test if missing**

If no existing test proves proposal-level fast lifecycle is used for 1m proposals, add:

```python
def test_executor_uses_one_minute_scalper_dynamic_exit_fields_for_open_position(tmp_path):
    # Use the existing fake broker/test helpers in tests/test_mt5_execution.py.
    # Build a proposal state with timeframe="1m", position_lifecycle="FAST_PARTIAL_SCALE",
    # partial_first_trigger_points=0.5, partial_first_target_volume=1.0,
    # break_even_trigger_points=0.5, break_even_lock_points=0.1.
    # Seed an open BUY position with volume 1.5, entry 100.0, current 100.7, stop 99.0, tp 102.0.
    # Assert manage_open_positions returns POSITION_PARTIALLY_CLOSED and closes 0.5 volume.
    # Assert the action includes stop_management_action == "MOVE_TO_BREAK_EVEN".
```

Use existing helpers in the file rather than building a new fake broker class.

- [ ] **Step 2: Run MT5 execution lifecycle tests**

Run:

```powershell
uv run --group dev pytest tests/test_mt5_execution.py -q
```

Expected: tests pass.

- [ ] **Step 3: Commit only if code or tests changed**

Run when files changed:

```powershell
git add tests/test_mt5_execution.py
git commit -m "test: preserve one minute scalper lifecycle wiring"
```

If no file changed because coverage already exists, record that in the checkpoint and do not commit.

---

### Task 6: Full Verification

**Files:**

- No planned code changes

- [ ] **Step 1: Run focused suite**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py tests/test_price_action_engine.py tests/test_order_proposal.py tests/test_mt5_execution.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run full suite**

Run:

```powershell
uv run --group dev pytest
```

Expected: full suite passes.

- [ ] **Step 3: Inspect working tree**

Run:

```powershell
git status --short --branch
```

Expected:

- branch is `main`
- only intentional One Minute Scalper changes are staged or committed
- pre-existing unrelated dirty files may still be present

- [ ] **Step 4: Push commits**

Run:

```powershell
git push
```

Expected: new commits are pushed to the configured remote.

---

### Task 7: Fresh Demo Restart And First Telemetry Check

**Files:**

- May modify `.env` only if needed for runtime settings
- Read/write runtime telemetry under configured `TRADINGAGENTS_RESULTS_DIR`

- [ ] **Step 1: Stop any existing runner**

Use a non-destructive process check:

```powershell
Get-Process | Where-Object { $_.ProcessName -like "*python*" -and $_.Path -like "*trade*" }
```

Stop only the known bot runner process if it is still running. Do not stop unrelated Python processes without checking the command line.

- [ ] **Step 2: Start fresh One Minute Scalper telemetry**

Set runtime intent explicitly:

```powershell
$env:TRADINGAGENTS_TRADING_MODE="ENTRY_ONLY"
$env:TRADINGAGENTS_FAST_ENTRIES_ENABLED="true"
$env:TRADINGAGENTS_TIMEFRAME="1m"
$env:TRADINGAGENTS_CONFIRMATION_TIMEFRAME="1m"
$env:TRADINGAGENTS_FAST_TIMEFRAME="1m"
$env:TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME="1m"
$env:TRADINGAGENTS_FAST_HISTORY_WINDOW_CANDLES="60"
$env:TRADINGAGENTS_FAST_ACTIVATION_WINDOW_MINUTES="1"
$env:TRADINGAGENTS_RUNNER_POLL_SECONDS="5"
$env:TRADINGAGENTS_RUNNER_LOSS_STREAK_COOLDOWN_COUNT="2"
$env:TRADINGAGENTS_RUNNER_LOSS_STREAK_COOLDOWN_SECONDS="300"
$env:TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT="true"
```

Start the existing MT5 runner command used by this repo. If a documented script is present, use it. If not, use the same command already used for the prior live runner, with a new results folder named like:

```text
2026-06-15-one-minute-scalper-v1
```

- [ ] **Step 3: Confirm first heartbeat and cycle telemetry**

Check:

```powershell
Get-ChildItem -Recurse results | Where-Object { $_.Name -in @("heartbeat.json", "summary.json", "cycles.jsonl") } | Sort-Object LastWriteTime -Descending | Select-Object -First 10 FullName,LastWriteTime
```

Open the newest heartbeat and summary. Confirm:

- `trading_mode` is `ENTRY_ONLY`
- status is not an account-safety failure on the demo account
- One Minute Scalper telemetry appears when analysis runs
- `candidate_evaluations` and `selected_candidate` appear in engine payloads
- no straddle execution runs
- active trade blocks new entries when an order or position exists

- [ ] **Step 4: Report first telemetry checkpoint**

Report:

- latest heartbeat status
- latest cycle status
- candidate count
- selected trigger or hold reason
- whether any order was placed
- whether stale activation is 1 minute
- whether exit lifecycle fields are present in order proposals

---

## Self-Review

Spec coverage:

- 60 closed 1m candles: Task 2 and existing history-window tests.
- Multiple candidate openings: Task 1 and Task 2.
- Best candidate selection: Task 1 and Task 2.
- Two-touch and third-touch behavior: Task 1 and Task 2.
- Respect, break, fakeout, rejection, engulfing: Task 2.
- Strict 1.0 versus 1.5 volume: Task 1 and Task 2.
- Stale 1m expiry: Task 3.
- Proposal journaling: Task 4.
- Fast protection wiring: Task 5.
- One trade at a time: preserved by runner/executor and verified in runtime checkpoint.
- No straddle/15m changes: scope boundary.

Placeholder scan:

- No forbidden placeholder tokens or unnamed placeholder tasks are used.
- The only conditional step is Task 5, where existing coverage may already satisfy the requirement; it has an explicit action when no change is needed.

Type consistency:

- Candidate telemetry field names match proposal fields: `trigger`, `reaction_type`, `confirmation_type`, `touch_count`, `score`, `volume_decision`.
- Proposal fields use Pydantic optional scalar types.
- Model public entry point remains `analyze_one_minute_entry`.
