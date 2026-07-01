# One Minute Scalper Signal Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore valid One Minute Scalper entries by fixing MT5 clock-domain health, candidate-local memory, contextual pressure, and confirmed near-quote entry semantics without weakening broker or risk safety.

**Architecture:** Keep the isolated deterministic model and existing MT5 execution lane. Normalize health decisions around the broker tick clock, make history a candidate map rather than a global veto, and submit short-lived continuation entries near the confirmed close while structural invalidation remains authoritative.

**Tech Stack:** Python 3.13+, MetaTrader5 Python bridge, pytest, JSON telemetry/state, Typer CLI, existing deterministic TradingAgents engine.

---

## Mandatory Context

Read this file completely before editing:

```text
docs/one-minute-scalper-handoff-2026-07-01.md
```

Also inspect:

```text
docs/superpowers/specs/2026-06-15-one-minute-scalper-design.md
docs/superpowers/specs/2026-07-01-one-minute-active-management-design.md
docs/superpowers/plans/2026-07-01-one-minute-active-management.md
```

Do not change normal 15m/30m strategy logic or straddle behavior in this plan.

## File Structure

**Create:**

```text
tests/fixtures/one_minute/2026-07-01-signal-window.json
tests/test_one_minute_signal_replay.py
```

**Modify:**

```text
tradingagents/dataflows/mt5_price_action.py
cli/main.py
tradingagents/brokers/mt5_runner.py
tradingagents/agents/price_action/one_minute_entry_model.py
tests/test_mt5_price_action_dataflow.py
tests/test_cli_mt5_execution.py
tests/test_mt5_runner.py
tests/test_mt5_runner_summary.py
tests/test_one_minute_entry_model.py
tests/test_mt5_execution.py
```

**Modify only if a failing test proves it necessary:**

```text
tradingagents/dataflows/data_health.py
tradingagents/brokers/mt5_execution.py
```

Do not solve source-clock skew by weakening global data-health limits.

### Task 0: Preserve Evidence and Stop the Old Worker Safely

**Files:**
- Read: `.env`
- Read: `results/2026-07-01-164002-one-minute-active-management/mt5_runner/summary.json`
- Read: `results/2026-07-01-164002-one-minute-active-management/mt5_runner/heartbeat.json`
- Read: `results/2026-07-01-164002-one-minute-active-management/XAUUSD.vx/execution_journal/mt5_events.jsonl`

- [ ] **Step 1: Verify repository and runner identity**

Run:

```powershell
git status --short
git log -3 --oneline
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match 'python|uv' -and
    $_.CommandLine -match [regex]::Escape((Resolve-Path .).Path) -and
    $_.CommandLine -match 'mt5-run'
  } |
  Select-Object ProcessId, CreationDate, CommandLine
```

Expected:

```text
main is at or ahead of 1f07f42
only the intended workspace runner processes are selected
```

- [ ] **Step 2: Verify broker state before stopping**

Use the existing read-only MT5 monitor path or a short `MT5Broker` script to
print only counts and tickets:

```text
open orders
open positions
account trade mode
symbol
```

Expected before stopping automatically:

```text
DEMO account
zero open orders
zero open positions
```

If an order or position exists, do not close it automatically. Continue
monitoring or ask the user for an explicit close instruction.

- [ ] **Step 3: Stop only the verified workspace runner**

After Step 2 proves broker state is empty:

```powershell
$root = (Resolve-Path .).Path
$workers = Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -match 'python|uv' -and
    $_.CommandLine -match [regex]::Escape($root) -and
    $_.CommandLine -match 'mt5-run'
  }
$workers | ForEach-Object { Stop-Process -Id $_.ProcessId }
```

Expected:

```text
no matching workspace mt5-run process remains
```

- [ ] **Step 4: Record the baseline without modifying generated results**

Capture in implementation notes:

```text
session path
checks
healthy/unhealthy checks
candidate rejection counts
orders placed/filled/closed
broker rejections
P/L
```

Do not add `results/` to git.

### Task 1: Create a Deterministic Session Replay Fixture

**Files:**
- Create: `tests/fixtures/one_minute/2026-07-01-signal-window.json`
- Create: `tests/test_one_minute_signal_replay.py`

- [ ] **Step 1: Extract a static, credential-free fixture**

Create a JSON fixture containing the closed M1 OHLC and spread rows covering
broker labels `2026-07-01T20:34:00+00:00` through
`2026-07-01T21:53:00+00:00`.

The fixture schema must be:

```json
{
  "symbol": "XAUUSD.vx",
  "source": "MT5 closed M1 bars captured 2026-07-01",
  "bars": [
    {
      "timestamp": "2026-07-01T20:34:00+00:00",
      "open": 4057.15,
      "high": 4057.27,
      "low": 4056.01,
      "close": 4056.44,
      "spread": 29.0,
      "volume": 336.0
    }
  ]
}
```

Continue the array with every captured closed bar through `21:53`. Do not
include account, terminal, order, or credential fields.

- [ ] **Step 2: Add the replay helper**

Add:

```python
import json
from pathlib import Path

from tradingagents.agents.price_action.one_minute_entry_model import (
    analyze_one_minute_entry,
)
from tradingagents.default_config import DEFAULT_CONFIG


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "one_minute"
    / "2026-07-01-signal-window.json"
)


def _bars():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["bars"]


def _decision_at(timestamp: str):
    bars = _bars()
    index = next(
        index for index, bar in enumerate(bars)
        if bar["timestamp"] == timestamp
    )
    current = bars[index]
    spread = max(0.01, float(current["spread"]) * 0.01)
    config = {
        **DEFAULT_CONFIG["price_action"],
        "current_spread_price": spread,
        "current_bid_price": float(current["close"]),
        "current_ask_price": float(current["close"]) + spread,
    }
    return analyze_one_minute_entry(
        "XAUUSD.vx",
        timestamp,
        {"1m": bars[: index + 1]},
        session_config=config,
    )
```

- [ ] **Step 3: Write failing opportunity-regression tests**

Add parameterized assertions:

```python
import pytest


@pytest.mark.parametrize(
    ("timestamp", "expected_trigger"),
    [
        ("2026-07-01T21:03:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:17:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:22:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:34:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:40:00+00:00", "FAILED_HIGH_BREAK_SELL"),
        ("2026-07-01T21:44:00+00:00", "HIGH_RESPECT_SELL"),
        ("2026-07-01T21:50:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
    ],
)
def test_replay_exposes_clean_current_opening(timestamp, expected_trigger):
    payload = _decision_at(timestamp)
    candidates = payload["telemetry"]["candidate_evaluations"]
    matching = [
        candidate for candidate in candidates
        if candidate["trigger"] == expected_trigger
    ]
    assert matching
    assert matching[0]["confirmation_type"] in {
        "rejection",
        "engulfing",
        "strong_close",
    }
```

These tests initially document candidate recognition. Later tasks add approval
assertions only after each confirmed blocker is removed.

- [ ] **Step 4: Add control cases**

Add:

```python
@pytest.mark.parametrize(
    "timestamp",
    [
        "2026-07-01T21:07:00+00:00",
        "2026-07-01T21:13:00+00:00",
        "2026-07-01T21:36:00+00:00",
    ],
)
def test_replay_does_not_approve_mixed_confirmation(timestamp):
    payload = _decision_at(timestamp)
    approved = [
        candidate
        for candidate in payload["telemetry"]["candidate_evaluations"]
        if candidate["approved"]
    ]
    assert approved == []
```

- [ ] **Step 5: Run and commit the evidence fixture**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_signal_replay.py -v
```

Expected:

```text
candidate-recognition and mixed-control tests pass
no live MT5 connection is required
```

Commit:

```powershell
git add tests/fixtures/one_minute/2026-07-01-signal-window.json tests/test_one_minute_signal_replay.py
git commit -m "test: preserve one-minute signal replay"
```

### Task 2: Use the MT5 Tick Clock for MT5 Data Health

**Files:**
- Modify: `tradingagents/dataflows/mt5_price_action.py`
- Modify: `cli/main.py`
- Test: `tests/test_mt5_price_action_dataflow.py`
- Test: `tests/test_cli_mt5_execution.py`

- [ ] **Step 1: Write the failing snapshot clock-domain test**

Add a fake broker whose wall-clock `as_of` is `21:40`, current MT5 tick is
`21:55`, and last closed M1 bar is `21:54`.

```python
def test_mt5_snapshot_uses_tick_time_for_candle_freshness():
    broker = FutureClockFakeBroker(
        tick_time_utc="2026-07-01T21:55:00+00:00",
        latest_m1_timestamp="2026-07-01T21:54:00+00:00",
    )

    snapshot = fetch_mt5_price_action_snapshot(
        broker,
        as_of="2026-07-01T17:40:00-04:00",
        market_timezone="America/New_York",
    )

    assert snapshot.data_status["healthy"] is True
    assert snapshot.data_status["timeframes"]["1m"]["latest_age_minutes"] == 1
    assert snapshot.data_status["reference_source"] == "mt5_tick"
```

- [ ] **Step 2: Verify the test fails for the current wall-clock comparison**

Run:

```powershell
uv run --group dev pytest tests/test_mt5_price_action_dataflow.py::test_mt5_snapshot_uses_tick_time_for_candle_freshness -v
```

Expected:

```text
FAIL because latest_age_minutes is negative and M1 is blocked
```

- [ ] **Step 3: Add an explicit MT5 health reference helper**

Implement in `mt5_price_action.py`:

```python
def mt5_health_reference(
    market_metadata: dict[str, Any],
    fallback_as_of: str,
) -> tuple[str, str]:
    tick = market_metadata.get("tick") or {}
    tick_time = tick.get("time_utc")
    if tick_time:
        return str(tick_time), "mt5_tick"
    return fallback_as_of, "runner_clock"
```

Fetch metadata before building status. Build MT5 data health with the returned
reference and add:

```python
data_status["reference_timestamp"] = health_as_of
data_status["reference_source"] = reference_source
```

Do not change `MAX_FUTURE_DRIFT_MINUTES`.

- [ ] **Step 4: Use the same reference when rebuilding profile status**

In `cli/main.py`, derive `health_as_of` from
`profile_snapshot.market_metadata` before each `build_data_status()` call:

```python
health_as_of, reference_source = mt5_health_reference(
    snapshot.market_metadata,
    profile_as_of,
)
profile_data_status = build_data_status(
    snapshot.candles,
    health_as_of,
    market_timezone,
    required_timeframes=required_timeframes,
    trading_timeframe=profile.timeframe,
    confirmation_timeframe=profile.confirmation_timeframe,
)
profile_data_status["reference_timestamp"] = health_as_of
profile_data_status["reference_source"] = reference_source
```

- [ ] **Step 5: Close the analysis broker deterministically**

Replace the unguarded connection block with:

```python
analysis_broker = MT5Broker(mt5_config)
try:
    analysis_broker.connect()
    snapshot = fetch_mt5_price_action_snapshot(
        analysis_broker,
        as_of=selections["as_of"],
        market_timezone=selections.get(
            "market_timezone",
            DEFAULT_CONFIG["market_timezone"],
        ),
    )
finally:
    analysis_broker.shutdown()
```

Add a CLI test proving `shutdown()` is called when snapshot fetching succeeds
and when it raises.

- [ ] **Step 6: Verify focused suites**

Run:

```powershell
uv run --group dev pytest tests/test_mt5_price_action_dataflow.py tests/test_price_action_data_health.py tests/test_cli_mt5_execution.py -v
```

Expected:

```text
all tests pass
wall-clock data sources retain their existing drift protection
MT5 snapshots report reference_source=mt5_tick
```

- [ ] **Step 7: Commit**

```powershell
git add tradingagents/dataflows/mt5_price_action.py cli/main.py tests/test_mt5_price_action_dataflow.py tests/test_cli_mt5_execution.py
git commit -m "fix: align MT5 data health with broker tick"
```

### Task 3: Make Runner Health Metadata Match Engine Health

**Files:**
- Modify: `tradingagents/brokers/mt5_runner.py`
- Test: `tests/test_mt5_runner.py`
- Test: `tests/test_mt5_runner_summary.py`

- [ ] **Step 1: Write a failing unhealthy-analysis heartbeat test**

Add:

```python
def test_runner_propagates_engine_data_health_to_health_gate(tmp_path):
    runner = _runner(
        tmp_path,
        analysis_result=_analysis_result(
            proposal_status="NO_TRADE",
            data_status={
                "healthy": False,
                "blocking_timeframes": ["1m"],
            },
        ),
    )

    result = runner.run_once()

    assert result["health_gate"] == {
        "passed": False,
        "reasons": ["data_health:1m"],
    }
```

Use the existing runner fixtures/helpers rather than creating a second fake
runner framework.

- [ ] **Step 2: Verify it fails**

Run:

```powershell
uv run --group dev pytest tests/test_mt5_runner.py::test_runner_propagates_engine_data_health_to_health_gate -v
```

Expected:

```text
FAIL because _write_heartbeat defaults a missing gate to passed
```

- [ ] **Step 3: Add one health aggregation method**

Implement:

```python
@staticmethod
def _analysis_health_gate(processed_rows: list[tuple]) -> dict:
    blocking: list[str] = []
    for _profile, _as_of, _proposal, analysis, _status in processed_rows:
        data_status = analysis.get("data_status") or {}
        if data_status.get("healthy") is False:
            blocking.extend(
                f"data_health:{timeframe}"
                for timeframe in data_status.get("blocking_timeframes") or []
            )
    reasons = list(dict.fromkeys(blocking))
    return health_gate(not reasons, reasons)
```

Attach this gate to all post-analysis heartbeat outcomes, including
`NO_TRADE`, conflicts, selected execution, and profile summaries.

- [ ] **Step 4: Add summary consistency coverage**

Assert that the same cycle records:

```python
assert latest_cycle["health_gate"]["passed"] is False
assert latest_cycle["analysis"]["data_status"]["healthy"] is False
assert summary["hold_reason_counts"]["data_health"] >= 1
```

- [ ] **Step 5: Verify and commit**

Run:

```powershell
uv run --group dev pytest tests/test_mt5_runner.py tests/test_mt5_runner_summary.py -v
```

Commit:

```powershell
git add tradingagents/brokers/mt5_runner.py tests/test_mt5_runner.py tests/test_mt5_runner_summary.py
git commit -m "fix: report engine health through runner gate"
```

### Task 4: Make Opening Memory Candidate-Local

**Files:**
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Modify: `tests/test_one_minute_entry_model.py`
- Modify: `tests/test_one_minute_signal_replay.py`

- [ ] **Step 1: Add failing replay approval tests for local reactions**

Add:

```python
@pytest.mark.parametrize(
    ("timestamp", "expected_trigger"),
    [
        ("2026-07-01T21:34:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:40:00+00:00", "FAILED_HIGH_BREAK_SELL"),
        ("2026-07-01T21:44:00+00:00", "HIGH_RESPECT_SELL"),
    ],
)
def test_remote_memory_does_not_veto_clean_local_opening(
    timestamp,
    expected_trigger,
):
    payload = _decision_at(timestamp)
    candidate = next(
        item
        for item in payload["telemetry"]["candidate_evaluations"]
        if item["trigger"] == expected_trigger
    )
    assert "CONFLICTED_ONE_MINUTE_MEMORY" not in candidate["rejection_reasons"]
```

- [ ] **Step 2: Retain a real local-conflict test**

Construct candles where the same local zone produces ambiguous two-sided
behavior and the latest candle has a mixed close:

```python
def test_same_local_zone_with_mixed_confirmation_remains_rejected():
    payload = analyze_one_minute_entry(
        "XAUUSD.vx",
        "2026-07-01T10:10:00+00:00",
        {"1m": _local_ambiguous_zone_candles()},
        session_config=_session_config(),
    )

    assert payload["status"] == "NO_SETUP"
    assert all(
        not item["approved"]
        for item in payload["telemetry"]["candidate_evaluations"]
    )
```

- [ ] **Step 3: Remove global memory as an approval veto**

Refactor relation handling so:

```text
candidate reaction is evaluated against candidate.level
remote active openings remain in one_minute_story.active_openings
global broke-high-and-broke-low state is telemetry only
mixed confirmation remains a rejection
RESPECT_ENTRY_CONFLICTS_WITH_LATEST_RELATION remains candidate-specific
```

Do not merely delete telemetry. Replace the global hard rejection with:

```python
candidate.risk["fast_trigger_quality"]["memory_context"] = {
    "global_relation": asdict(latest_relation),
    "candidate_level": round(candidate.level.level, 4),
    "candidate_side": candidate.level.side,
    "hard_veto": False,
}
```

- [ ] **Step 4: Verify old and new tests**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py tests/test_one_minute_signal_replay.py -v
```

Expected:

```text
clean local candidates no longer carry CONFLICTED_ONE_MINUTE_MEMORY
mixed and candidate-specific contradictory reactions remain rejected
```

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/price_action/one_minute_entry_model.py tests/test_one_minute_entry_model.py tests/test_one_minute_signal_replay.py
git commit -m "fix: keep one-minute memory candidate-local"
```

### Task 5: Make Historical Pressure Contextual, Not Authoritative

**Files:**
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Modify: `tests/test_one_minute_entry_model.py`
- Modify: `tests/test_one_minute_signal_replay.py`

- [ ] **Step 1: Add failing direction-change replay tests**

Add:

```python
@pytest.mark.parametrize(
    ("timestamp", "expected_trigger"),
    [
        ("2026-07-01T21:17:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:22:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:50:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
    ],
)
def test_clean_current_impulse_can_reverse_old_pressure(
    timestamp,
    expected_trigger,
):
    payload = _decision_at(timestamp)
    candidate = next(
        item
        for item in payload["telemetry"]["candidate_evaluations"]
        if item["trigger"] == expected_trigger
    )
    assert "ONE_MINUTE_PRESSURE_CONFLICT" not in candidate["rejection_reasons"]
    assert (
        "ONE_MINUTE_ACTIVE_PULSE_NOT_ALIGNED"
        not in candidate["rejection_reasons"]
    )
```

- [ ] **Step 2: Add a weak counterpressure control**

Use a repeated-high zone followed by a small indecisive bullish candle during
strong bearish pressure:

```python
def test_weak_counterpressure_candle_is_not_approved():
    payload = analyze_one_minute_entry(
        "XAUUSD.vx",
        "2026-07-01T11:00:00+00:00",
        {"1m": _weak_counterpressure_candles()},
        session_config=_session_config(),
    )

    assert payload["status"] == "NO_SETUP"
```

- [ ] **Step 3: Convert pressure conflicts to score context**

Use deterministic scoring:

```python
if pressure_direction in {"bullish", "bearish"}:
    expected = "BUY" if pressure_direction == "bullish" else "SELL"
    if candidate.direction == expected:
        candidate.score += 1
        candidate.score_reasons.append("ONE_MINUTE_PRESSURE_ALIGNED")
    else:
        candidate.score -= 1
        candidate.score_reasons.append("ONE_MINUTE_PRESSURE_COUNTER")
```

For active pulse:

```python
if active_pulse.direction in {"bullish", "bearish"}:
    expected = "BUY" if active_pulse.direction == "bullish" else "SELL"
    if candidate.direction == expected:
        candidate.score += 1
        candidate.score_reasons.append("ONE_MINUTE_ACTIVE_PULSE_ALIGNED")
    else:
        candidate.score_reasons.append("ONE_MINUTE_ACTIVE_PULSE_COUNTER")
```

Do not append `ONE_MINUTE_PRESSURE_CONFLICT` or
`ONE_MINUTE_ACTIVE_PULSE_NOT_ALIGNED` as hard rejection reasons for a candidate
that already has clean local confirmation. Weak candidates still fail score,
mixed confirmation, risk, or chop gates.

- [ ] **Step 4: Verify**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py tests/test_one_minute_signal_replay.py -v
```

Expected:

```text
direction-change candidates are no longer globally vetoed
weak/mixed counterpressure controls remain NO_SETUP
```

- [ ] **Step 5: Commit**

```powershell
git add tradingagents/agents/price_action/one_minute_entry_model.py tests/test_one_minute_entry_model.py tests/test_one_minute_signal_replay.py
git commit -m "fix: let current M1 opening override old pressure"
```

### Task 6: Enter Confirmed Reactions Near the Live Quote

**Files:**
- Modify: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Modify only if required: `tradingagents/brokers/mt5_execution.py`
- Modify: `tests/test_one_minute_entry_model.py`
- Modify: `tests/test_mt5_execution.py`
- Modify: `tests/test_one_minute_signal_replay.py`

- [ ] **Step 1: Write a failing confirmed-reaction repricing test**

Add a high-respect sell where:

```text
repeated high = 4034.78
confirmation close = 4033.89
live bid = 4033.87
spread = 0.29
structural stop remains above the rejection high
```

Assert:

```python
assert candidate["approved"] is True
assert candidate["entry_price"] < 4034.78
assert abs(candidate["entry_price"] - 4033.87) <= 0.35
assert candidate["stop_loss"] > candidate["entry_price"]
assert candidate["risk_distance"] <= 1.0
```

- [ ] **Step 2: Write a stale-quote control**

With the same confirmation candle but a live bid more than the configured
drift beyond the confirmation close:

```python
assert candidate["approved"] is False
assert "LIVE_ENTRY_MOVED_AWAY" in candidate["rejection_reasons"]
```

- [ ] **Step 3: Reprice from the confirmation event**

For `RESPECT_ONE_MINUTE_TRIGGERS` and `FAKEOUT_ONE_MINUTE_TRIGGERS`:

```text
reference drift = abs(live quote - latest.close)
structural stop = beyond candidate level/rejection wick
entry = near live quote with spread/broker buffer
target = recomputed from repriced risk
reject if structural risk exceeds max stop
reject if structural risk is below spread-safe minimum
reject if quote drift from latest.close exceeds configured maximum
```

Reuse `_reprice_risk_to_live_quote()` rather than creating a second risk
calculator. Record:

```python
{
    "live_repriced": True,
    "live_reprice_reason": "confirmed_reaction",
    "live_reference_close": round(float(latest.close), 4),
    "live_quote": round(quote, 4),
    "live_entry_drift": round(abs(quote - float(latest.close)), 4),
}
```

- [ ] **Step 4: Verify the broker request is a near-quote continuation order**

Add an executor test asserting the repriced proposal resolves to the correct
pending direction:

```text
BUY confirmation -> BUY_STOP above ask
SELL confirmation -> SELL_STOP below bid
```

The order must remain pending and broker-guarded. Do not add an unguarded market
entry path.

- [ ] **Step 5: Promote replay approval assertions**

After Tasks 4-6, update selected replay cases:

```python
@pytest.mark.parametrize(
    ("timestamp", "expected_trigger"),
    [
        ("2026-07-01T21:03:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:17:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
        ("2026-07-01T21:34:00+00:00", "CLEAN_LOW_IMPULSE_SELL"),
        ("2026-07-01T21:40:00+00:00", "FAILED_HIGH_BREAK_SELL"),
        ("2026-07-01T21:44:00+00:00", "HIGH_RESPECT_SELL"),
        ("2026-07-01T21:50:00+00:00", "CLEAN_HIGH_IMPULSE_BUY"),
    ],
)
def test_replay_approves_clean_current_opening(timestamp, expected_trigger):
    payload = _decision_at(timestamp)
    assert payload["status"] == "SETUP_FOUND"
    assert payload["setups"][0]["name"] == expected_trigger
```

If a case remains rejected by a valid spread or structural-stop rule, do not
weaken that rule to force this test. Document the exact reason and remove that
case from the approval list while retaining candidate-recognition coverage.

- [ ] **Step 6: Verify and commit**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_entry_model.py tests/test_one_minute_signal_replay.py tests/test_mt5_execution.py -v
```

Commit:

```powershell
git add tradingagents/agents/price_action/one_minute_entry_model.py tradingagents/brokers/mt5_execution.py tests/test_one_minute_entry_model.py tests/test_one_minute_signal_replay.py tests/test_mt5_execution.py
git commit -m "fix: enter confirmed M1 reactions near quote"
```

Omit `tradingagents/brokers/mt5_execution.py` from `git add` if it did not
change.

### Task 7: Verify Candidate Ranking Without Adding an Unproven Filter

**Files:**
- Modify only if tests expose a defect: `tradingagents/agents/price_action/one_minute_entry_model.py`
- Modify: `tests/test_one_minute_signal_replay.py`

- [ ] **Step 1: Assert deterministic best-candidate selection**

For every replay timestamp:

```python
def test_replay_selects_at_most_one_approved_candidate_per_candle():
    for bar in _bars()[60:]:
        payload = _decision_at(bar["timestamp"])
        approved = [
            candidate
            for candidate in payload["telemetry"]["candidate_evaluations"]
            if candidate["approved"]
        ]
        assert len(approved) <= 1
```

If the analyzer intentionally retains multiple approved candidates before final
selection, assert instead that exactly one `selected_candidate` exists and its
sort key is deterministic:

```text
approved first
higher score
more recent touch
more touches
smaller structural risk
stable trigger name tie-break
```

- [ ] **Step 2: Keep the late-impulse observation diagnostic**

Add telemetry assertions for the broker-label `21:45` candidate:

```text
candle body relative to recent median range
distance from repeated level
candidate risk
active pulse
```

Do not reject it with a new fixed exhaustion threshold in this plan. The earlier
active-management design correctly noted that one winner was more extended
than one loser. Collect fresh evidence after correctness fixes.

- [ ] **Step 3: Verify**

Run:

```powershell
uv run --group dev pytest tests/test_one_minute_signal_replay.py tests/test_one_minute_entry_model.py -v
```

Expected:

```text
selection is deterministic
no unproven strategy filter was added
```

- [ ] **Step 4: Commit only if code or tests changed**

```powershell
git add tradingagents/agents/price_action/one_minute_entry_model.py tests/test_one_minute_signal_replay.py
git commit -m "test: lock deterministic M1 candidate ranking"
```

### Task 8: Run Complete Verification and Review

**Files:**
- Modify only if verification proves a scoped defect.

- [ ] **Step 1: Run focused integration suites**

```powershell
uv run --group dev pytest tests/test_mt5_broker.py tests/test_mt5_price_action_dataflow.py tests/test_price_action_data_health.py tests/test_one_minute_entry_model.py tests/test_one_minute_signal_replay.py tests/test_mt5_execution.py tests/test_mt5_runner.py tests/test_mt5_runner_summary.py tests/test_cli_mt5_execution.py -v
```

Expected:

```text
all focused tests pass
```

- [ ] **Step 2: Run the complete suite**

```powershell
uv run --group dev pytest
```

Expected baseline from the previous commit:

```text
794 passed, 4 skipped, 75 subtests
```

The new total will be higher. Any failure must be investigated before restart.

- [ ] **Step 3: Review source and repository hygiene**

```powershell
git diff --check
git status --short
git log --oneline --decorate -8
```

Confirm:

```text
no .env or credential file staged
no results directory staged
no unrelated user files staged
no dead 3m/15m/30m dependency added to One Minute Scalper
one-active-trade and demo guards remain intact
```

- [ ] **Step 4: Perform a requirements review**

Check every requirement in:

```text
docs/one-minute-scalper-handoff-2026-07-01.md
```

Specifically verify:

```text
closed M1 only
60-candle memory
two-high/two-low opening first
current candle controls direction
one trade at a time
near-quote confirmed entry
one-second management preserved
health metadata consistent
```

- [ ] **Step 5: Commit any final scoped correction**

Use a specific message describing the correction. Do not squash away the
test-first checkpoints unless the user explicitly requests it.

### Task 9: Push and Start a Fresh Demo Session

**Files:**
- Modify locally, never commit: `.env`
- Create generated output, never commit: `results/<fresh-session>/`

- [ ] **Step 1: Push verified main**

```powershell
git push origin main
```

Expected:

```text
origin/main advances to verified HEAD
```

- [ ] **Step 2: Create a fresh telemetry path**

Use:

```powershell
$stamp = Get-Date -Format 'yyyy-MM-dd-HHmmss'
$session = "C:\Users\Administrator\Desktop\trade\results\$stamp-one-minute-signal-reliability"
```

Update only:

```text
TRADINGAGENTS_RESULTS_DIR=<fresh session path>
TRADINGAGENTS_TRADING_MODE=ENTRY_ONLY
TRADINGAGENTS_ENTRY_PROFILE_MODE=fast_only
TRADINGAGENTS_FAST_ENTRIES_ENABLED=true
TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT=true
TRADINGAGENTS_RUNNER_MAX_SESSION_LOSS=600
```

Keep base volume at `1.0` and keep volume boost disabled.

- [ ] **Step 3: Start one hidden worker**

Use the repository virtual environment and redirect logs into the fresh
session:

```powershell
$stdout = Join-Path $session 'runner.stdout.log'
$stderr = Join-Path $session 'runner.stderr.log'
New-Item -ItemType Directory -Force -Path $session | Out-Null
Start-Process `
  -FilePath (Resolve-Path '.\.venv\Scripts\python.exe') `
  -ArgumentList '-m','cli.main','mt5-run','--poll-seconds','5','--decision-mode','engine' `
  -WorkingDirectory (Resolve-Path '.').Path `
  -RedirectStandardOutput $stdout `
  -RedirectStandardError $stderr `
  -WindowStyle Hidden
```

- [ ] **Step 4: Verify the first heartbeat**

Wait for the heartbeat and assert:

```text
process exists
account_safety.require_demo = true
account_safety.trade_mode = DEMO
account_safety.passed = true
trading_mode = ENTRY_ONLY
profile is fast or no candidate has yet been selected
data_status.reference_source = mt5_tick
data_status.healthy = true when tick and candles advance
health_gate agrees with data_status
stderr is empty
```

- [ ] **Step 5: Verify broker state**

Read MT5:

```text
open orders
open positions
latest tick age
symbol spread
trade permission
```

Do not manually force a trade. Let the deterministic strategy wait for a valid
opening.

- [ ] **Step 6: Leave the verified worker active**

Report:

```text
fresh session path
worker PID
heartbeat timestamp
current status
open order/position counts
latest candidate and rejection reason
commit pushed
test totals
```

## Post-Restart Review Protocol

Do not tune again after one or two outcomes.

First review after:

```text
at least 10 closed trades for execution defects
at least 30 closed trades for early strategy direction
preferably 50 or more for the 60 percent win-rate target
```

For every review calculate:

```text
wins, losses, break-even
net P/L after spread
average win and average loss
MFE captured versus MFE available
MAE and exit reason
results by trigger
orders placed but not filled
valid openings missed
invalid openings taken
broker rejection count
health-block count
```

Fix correctness defects immediately. Change scoring or strategy thresholds only
when the sample identifies a repeatable pattern rather than one memorable
trade.
