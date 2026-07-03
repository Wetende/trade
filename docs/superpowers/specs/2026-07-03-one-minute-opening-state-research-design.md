# One Minute Opening-State Research Design

**Date:** 2026-07-03

## Objective

Discover whether repeated M1 levels contain a deterministic tradeable opening
when represented as a multi-candle state transition rather than a single
selected confirmation candle.

The current production strategy remains unchanged and stopped. Research uses
read-only MT5 candles and ticks, produces simulated orders only, and cannot
mutate broker state.

## Why the boundary changes

Across 71 recorded fills:

- baseline profit factor was `0.401`;
- all manual restrictive variants remained below `0.48`;
- 3,240 shallow pre-entry selector rules produced no training-eligible rule in
  any leave-one-session-out fold;
- most losses moved adversely immediately.

The available telemetry cannot separate winners after the current engine has
already declared an opening. The next hypothesis must change opening
construction, not stack another filter on the same decision.

## Historical source

Read at least 5,000 M1 bars and matching historical ticks through read-only
MT5 APIs. Store generated raw research data outside tracked source
directories. Track only sanitized small regression fixtures and aggregate
reports.

Partition evidence by UTC trading day. No day may contribute to both training
and held-out metrics in the same fold.

## Repeated-level state machine

Detect repeated highs and lows with the existing closed-M1 level detector.
For each candidate-local level, emit these states without using future data:

```text
APPROACH
TOUCH
CLOSE_INSIDE
CLOSE_BEYOND
RETEST
HOLD_BEYOND
FAIL_BACK_INSIDE
EXPIRED
```

Pre-register four opening templates:

1. `REJECTION`: touch followed by a directional close inside the level.
2. `BREAK_HOLD`: close beyond followed by another close beyond.
3. `BREAK_RETEST_HOLD`: close beyond, retest the level, then close beyond.
4. `FAILED_BREAK`: close beyond followed by a directional close back inside.

Each template has a maximum three-closed-candle lifecycle after the initial
touch or break. No lower-ranked level may replace an expired or failed local
state during that lifecycle.

## Simulated execution

Use recorded ticks to reproduce:

- decision bid, ask, and spread;
- pending continuation or reaction entry;
- 20-second reaction and 45-second continuation expiry;
- fill time and quote drift;
- structural stop with existing spread and maximum-distance guards;
- 1.5 base risk/reward;
- one active simulated order or position;
- one-second MFE and MAE;
- current emergency, partial, break-even, trailing, scalp, and rejection
  management.

If tick evidence is missing or an event order is ambiguous, mark the
opportunity `INSUFFICIENT_TICK_EVIDENCE` and exclude it from P/L. Never resolve
ambiguity favorably.

## Evaluation

First prove simulator parity on the three recorded broker sessions:

- candidate timestamps and directions;
- placed versus expired orders;
- fill prices within recorded quote tolerance;
- management action sequence;
- realized P/L within explicit rounding tolerance.

Then evaluate each opening template alone with leave-one-day-out folds.
Combinations are not allowed in the first screen.

A template advances only with:

- held-out profit factor at least `1.15`;
- positive held-out expectancy and net P/L;
- at least two profitable held-out days;
- at least 60% of the current baseline's eligible opportunity count;
- no worse maximum loss streak or daily drawdown;
- complete deterministic telemetry;
- byte-identical repeated output.

## Prospective boundary

Only a historically passing template may be frozen. It must then run in
read-only prospective shadow mode for at least 30 simulated fills across three
future sessions and satisfy the existing `1.10` shadow profit-factor gate.

No historical result authorizes broker execution.

## Failure behavior

If every template fails, record `NO_OPENING_STATE_EDGE`. Do not lower economic,
retention, session, or drawdown gates. At that point the repeated-level One
Minute Scalper has not demonstrated an acceptable edge in the available
market and should remain stopped.
