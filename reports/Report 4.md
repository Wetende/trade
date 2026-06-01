# Report 4: Strategy Logic Debug - Why No Entry Was Placed

Date: 2026-06-01  
Project: MT5 Gold trading bot  
Symbol flow: `GC=F` for analysis, `XAUUSD.vx` for broker execution  
Main question: Did the market fail to show our strategy, or did our engine fail to recognize/route the strategy into an order?

## Executive Summary

The evidence does **not** support the idea that the market showed none of our strategy.

Across the recent live-run telemetry that was inspected, the engine repeatedly saw M30 breakout context and multiple M15 candidate setups. However, the system still returned HOLD every time because of engine-routing and filtering problems.

The strongest finding is:

**The strategy appears to have occurred, but the current engine is not correctly converting all three core playbook strategies into brokerable proposals.**

The three core strategies from the playbook image are:

1. Breakout
2. Buy/sell off support or resistance
3. Break and retest

The current code handles parts of these, but not in the complete way the playbook expects.

## What The Current Engine Actually Does

The main decision path is in:

`tradingagents/agents/price_action/engine.py`

Current flow:

1. Calculate support/resistance zones from Daily, 4H, 1H, and 30M.
2. Detect M30 breakout context.
3. If M30 context is breakout, look for M15 break-and-retest only.
4. If no break-and-retest is found, look for M15 support/resistance bounce.
5. If candidates exist, evaluate only the first candidate.
6. If that first candidate fails risk/reward or checklist, return HOLD.

Important code behavior:

```text
engine.py lines 295-299:

candidate_setups = []
if m30_direction and market_context["m30_context"] == "BREAKOUT":
    candidate_setups.extend(detect_break_and_retest(m15, m30_zones, direction=m30_direction))
if not candidate_setups:
    candidate_setups.extend(detect_sr_bounce(m15, zones))
```

This means direct M15 breakout is **not** used as a final entry candidate.

The direct breakout detector exists:

```text
setups.py lines 72-87:

detect_breakouts(...)
```

But the engine only uses breakout detection for M30 context. It does not add M15 breakout to the final candidate list.

That is a likely bug because "The Breakout" is one of the three main playbook setups.

## Live Run Evidence

I inspected recent engine telemetry from these run directories:

| Run directory | Engine payloads | Main stages | M30 context | Candidate counts | R:R values seen |
|---|---:|---|---|---|---|
| `m30_m15_core_run_20260601_155624` | 9 | 5 no M15 setup, 4 checklist/risk fail | 7 bullish breakout, 2 bearish breakout | `1,0,7,0,0,2,0,0,1` | `0.16, 0.03, 0.16, 0.62` |
| `engine_2h_run_20260601_192017` | 6 | 3 no M15 setup, 3 checklist/risk fail | 1 bullish breakout, 5 bearish breakout | `3,1,0,0,5,0` | `0.16, 0.31, 0.02` |
| `engine_2h_run_20260601_204922` | 9 | 6 checklist/risk fail, 2 no M15 setup, 1 time filter | 5 bullish breakout, 4 bearish breakout | `1,1,2,6,0,6,6,0,0` | `0.66, 0.14, 0.30, 0.01, 0.02, 0.02` |
| `engine_2h_extension_20260601_224937` | 3 | 2 checklist/risk fail, 1 no M15 setup | 1 bullish breakout, 2 bearish breakout | `4,1,0` | `0.18, 0.33` |

Key interpretation:

1. M30 breakout context appeared repeatedly.
2. Candidate setups appeared repeatedly.
3. Some candles had many candidates, including counts of 6 or 7.
4. The engine still returned HOLD because it either found no accepted M15 setup, failed risk/range, or got blocked by a time filter.

This means the market was not silent. The engine saw structure and candidates, but did not produce an approved order.

## Specific Example: Candidate Short-Circuit

At `2026-06-01 07:30`, telemetry showed:

| Field | Value |
|---|---|
| Candidate count | 6 |
| Saved/evaluated setup count | 1 |
| Saved setup | Support/Resistance Bounce |
| Direction | SELL |
| Zone timeframe | 1D |
| Zone type | Resistance |
| Zone range | `4518.8084` to `4577.2912` |
| Zone score | `56.0` |
| Risk/reward | `0.01` |
| Rejection reason | Clean range below minimum risk-to-reward |

The problem is not only that this setup failed. The problem is that the engine had 6 candidates but only saved/evaluated 1.

So if candidate number 2, 3, 4, 5, or 6 was better, we would not know from telemetry, and the engine would not approve it.

This is a logic problem:

```text
engine.py line 319:

setup = candidate_setups[0]
```

The engine chooses only the first candidate after sorting, then stops.

## Specific Example: Direct Breakout Missing From Final Entry Logic

A one-off diagnostic confirmed the direct breakout problem:

```text
direct_m15_breakouts = 1 Breakout BUY
break_and_retest = 0
sr_bounce = 0
engine_status = NO_SETUP HOLD
engine_stage = no_m15_setup
engine_candidate_count = 0
engine_message = No valid M15 setup. Default to HOLD.
```

Meaning:

1. The M15 candle was a valid direct breakout according to `detect_breakouts`.
2. It was not a break-and-retest.
3. It was not a support/resistance bounce.
4. The engine returned HOLD because it never asked direct M15 breakout to become a final entry candidate.

This directly conflicts with the playbook image where "The Breakout" is one of the three main entry models.

## Root Cause Findings

### 1. Direct M15 breakout is missing from final candidate selection

The code has a breakout detector, but the engine does not use it for final M15 entries.

Current behavior:

```text
M30 breakout context -> only search M15 break-and-retest
If none -> search support/resistance bounce
Never search direct M15 breakout as its own entry model
```

Expected behavior:

```text
Always evaluate the three playbook families:
1. Direct breakout
2. Support/resistance rejection
3. Break and retest
```

### 2. The engine evaluates only the first candidate

When multiple setups are detected, the engine selects `candidate_setups[0]` and ignores the rest.

This is dangerous because the first candidate is sorted by zone score, not by executable quality.

In practice, a wide Daily zone can outrank a cleaner M30/M15 execution zone.

### 3. Telemetry does not record enough candidate detail

Telemetry currently stores:

1. Candidate count
2. Final selected setup
3. Final rejection reason

But it does not store:

1. All candidates found
2. Each candidate's strategy type
3. Each candidate's zone
4. Each candidate's R:R
5. Why each candidate passed or failed

This makes it hard to prove after the run whether the second or third candidate was valid.

### 4. Higher-timeframe zones can dominate execution decisions

At `07:30`, the selected setup came from a 1D resistance zone with a very wide range.

That can be useful for context, but it is risky as an M15 execution edge.

For execution, the bot should prefer tighter and more recent zones from M30/M15, while Daily/4H/1H should mark context, danger areas, and major targets.

### 5. Risk/reward target selection may be too mechanical

The risk engine uses the nearest opposite zone midpoint as target.

If the nearest zone is too close, the setup fails clean range/R:R even if the playbook trader would target a cleaner liquidity area or the next meaningful structure.

This does not mean we should remove R:R checks. It means target-zone selection needs to be more playbook-aware.

## What This Means In Trading Terms

The bot has been acting more like:

```text
Wait for M30 direction.
Only accept one narrow M15 pattern.
Pick the highest-scoring zone candidate.
Reject if that one candidate has bad clean range.
Return HOLD.
```

But the playbook needs it to act more like:

```text
Use Daily/4H/1H to understand the map.
Use M30 to understand the setup environment.
On M15, scan for all three main entry models:
1. Breakout
2. Support/resistance rejection
3. Break and retest
Evaluate every valid candidate.
Choose the best executable candidate.
Only HOLD if every candidate fails for clear reasons.
```

## Recommended Fix Direction

No code fix should be made blindly. The next implementation should be test-driven because this is core trading logic.

### Step 1: Add tests that reproduce the bug

Add failing tests for:

1. M15 direct breakout should produce a setup candidate.
2. If multiple candidates exist and the first fails R:R, the engine should evaluate the next candidate.
3. Telemetry should store every candidate and every rejection reason.

### Step 2: Update candidate collection

Change the engine from "one narrow path" to "three playbook families":

```text
candidate_setups =
    direct M15 breakouts
    + M15 support/resistance bounces
    + M15 break-and-retest setups
```

M30 context should guide scoring and filtering, not erase a valid M15 breakout.

### Step 3: Evaluate all candidates

For every candidate:

1. Check playbook setup validity.
2. Check M30 compatibility.
3. Check wick/entry model requirements.
4. Check clean range/R:R.
5. Store pass/fail reason.

Only return HOLD after every candidate fails.

### Step 4: Improve execution-zone priority

Use Daily/4H/1H as context and danger zones.

Use M30/M15 zones as the primary execution zones.

This matches how a trader reads the chart:

```text
Higher timeframe = map
M30 = setup environment
M15 = execution trigger
```

### Step 5: Upgrade telemetry

Each engine payload should include a candidate audit like:

```json
{
  "all_candidates": [
    {
      "strategy": "Breakout",
      "direction": "BUY",
      "timeframe": "15m",
      "zone_timeframe": "30m",
      "entry": 4524.45,
      "stop": 4521.80,
      "target": 4529.20,
      "risk_reward": 1.63,
      "approved": true,
      "rejection_reason": null
    }
  ]
}
```

That way, after a live run, we can answer:

1. Did breakout occur?
2. Did support/resistance rejection occur?
3. Did break-and-retest occur?
4. Which one was closest to approval?
5. Why exactly did the bot hold?

## Conclusion

Your concern is valid.

Based on the logs and code inspection, it does not make sense to conclude that no strategy appeared in the market. The better conclusion is:

**The current engine is too narrow and too short-circuited. It is seeing some playbook-like conditions, but it is not evaluating all three strategy families as brokerable M15 entries.**

Before the next serious live test, the highest-value fix is to make the engine evaluate the three main playbook strategies directly and log every candidate with a full pass/fail explanation.

