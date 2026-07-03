# One Minute Scalper Walk-Forward Selector Design

**Date:** 2026-07-03

## Objective

Determine whether any small deterministic pre-entry rule can separate the
current One Minute Scalper's valid trades from its immediate failures without
outcome leakage, sparse cherry-picking, or broker execution.

This is a research selector. It may only return `TAKE_BASELINE_SIGNAL` or
`SKIP_BASELINE_SIGNAL`; it cannot reverse direction, change sizing, modify
stops or targets, or create a new setup.

## Motivation

The first pre-registered screen evaluated 71 fills across three sessions.
Every manual variant had negative expectancy and profit factor below `0.48`.
Additional read-only checks of one-candle follow-through, delayed failed
breaks, and post-confirmation stop entries also remained materially negative.
Another manually selected threshold would be outcome-driven overfitting.

## Evidence schema

Extend sanitized decisions with these pre-entry fields when recorded:

- trigger and reaction family;
- direction and confirmation type;
- candidate score;
- touch count and touch age;
- level type;
- body-to-recent-range ratio;
- entry distance from repeated level;
- opposing-wick ratio;
- stop-to-spread ratio;
- pressure relationship: aligned, opposed, or neutral;
- active-pulse relationship: aligned, opposed, or neutral;
- UTC hour bucket.

Missing legacy values remain `None`. A rule requiring a missing feature skips
that observation and records insufficient evidence; it never imputes a
favorable value.

No broker, account, ticket, order, deal, position, credential, terminal, or
private path field is permitted.

## Allowed rule grammar

Rules have maximum depth two and are conjunctions of at most two clauses.
Each clause is one of:

- equality or inequality on trigger, reaction, direction, confirmation, level
  type, pressure relationship, or pulse relationship;
- lower or upper bound on score, touch count, touch age, body ratio, entry
  distance, opposing-wick ratio, stop-to-spread ratio, or UTC hour.

Numeric thresholds come only from this fixed grid:

```text
score: 8, 9, 10, 11, 12, 13, 14
touch_count: 2, 3, 4, 5, 6, 7, 8
touch_age: 1, 2, 3, 5, 8
body_ratio: 0.50, 0.80, 1.00, 1.20, 1.50
entry_distance: 0.80, 1.00, 1.20, 1.50
opposing_wick_ratio: 0.05, 0.10, 0.20, 0.30
stop_to_spread_ratio: 2.0, 2.5, 3.0
UTC hour: 0, 6, 12, 18
```

The search cannot add thresholds after viewing results. Equivalent rules are
canonicalized and deduplicated. Simpler rules win every tie.

## Walk-forward evaluation

Use leave-one-session-out evaluation:

1. Train on two sessions.
2. Discard every rule retaining less than 60% of training fills.
3. Discard every rule with non-positive training expectancy.
4. Rank remaining rules by profit factor, expectancy, retained fills, then
   canonical rule text.
5. Freeze the highest-ranked rule for that fold.
6. Apply it once to the untouched session.
7. Repeat for all three held-out sessions.

The combined held-out rows are the historical result. Training rows never
contribute to reported out-of-sample P/L.

The selector passes historical screening only if:

- combined held-out profit factor is at least `1.15`;
- combined held-out expectancy and net P/L are positive;
- at least two held-out sessions are profitable;
- combined held-out fill retention is at least 60%;
- maximum loss streak and session drawdown do not exceed baseline;
- every fold produces a rule without missing required evidence;
- the process is byte-for-byte deterministic.

## Frozen candidate

If walk-forward screening passes, run the same deterministic search on all
three sessions and freeze one final rule. Its manifest contains:

- canonical rule;
- fixed threshold grid version;
- source fixture hashes;
- training metrics;
- held-out walk-forward metrics;
- source commit;
- `broker_mutation_enabled: false`.

Passing historical screening does not authorize execution. The frozen rule
must then pass the existing prospective shadow gate: at least 30 simulated
fills over three sessions, profit factor at least `1.10`, positive expectancy
and net P/L, and no worse loss streak than simultaneous baseline.

## Failure behavior

If no rule passes, write `NO_WALK_FORWARD_CANDIDATE`. Do not lower retention,
profit factor, session-count, or drawdown requirements. Do not start a shadow
candidate or execution runner. The conclusion must state that the available
pre-entry telemetry has not demonstrated a tradeable edge.

## Safety

Evaluation reads only tracked sanitized fixtures. It imports no broker module
and performs no external mutation. The MT5 execution runner remains stopped.
