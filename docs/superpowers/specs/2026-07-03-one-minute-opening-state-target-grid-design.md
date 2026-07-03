# One Minute Opening-State Target Grid Design

**Date:** 2026-07-03

## Objective

Evaluate `OPENING_STATE_QUEUE_TARGET_GRID_V1`, a deterministic walk-forward
target-selection candidate for the queued opening-state family.

The prior queued `1.0R` target candidate produced positive economics but failed
retention at `54.78%`. This design tests whether a shorter fixed scalp target
can reach retention without hand-picking a target on the full fixture.

## Candidate boundary

The candidate preserves:

- the four existing opening-state templates;
- fully closed M1 candles only;
- signal-zone deduplication;
- earliest-expiry queue selection;
- original reaction and continuation expiries;
- one active simulated order or position only;
- structural stop, quote-drift, invalid-tick, and ambiguity guards;
- broker-free read-only replay;
- no LLM decision, no volume change, no martingale, no grid, no straddle.

Only the replay target is selected from this fixed pre-registered grid:

```text
risk_reward = 0.60, 0.75, 0.90, 1.00
```

No value may be added after screening starts.

## Walk-forward selection

Use UTC-day leave-one-out selection over the same read-only 5,000-bar fixture.

For each held-out day:

1. Replay every grid target on the four training days.
2. For each target, compute:
   - all-template baseline with that same target;
   - queued one-active candidate with that same target.
3. A target is training-eligible only if it passes:
   - profit factor at least `1.15`;
   - positive net P/L and expectancy;
   - at least two profitable training sessions;
   - at least `60%` retention versus the same-target training baseline;
   - max loss streak no worse than same-target training baseline;
   - max session drawdown no worse than same-target training baseline.
4. Rank eligible targets by:
   - higher training profit factor;
   - higher training expectancy;
   - higher retained training fills;
   - higher target value;
   - deterministic numeric target order.
5. Freeze the top-ranked target for that fold.
6. Apply it once to the held-out day.

Combined held-out rows are the historical result. Training rows never
contribute to reported out-of-sample P/L.

## Historical gate

`OPENING_STATE_QUEUE_TARGET_GRID_V1` can be frozen only if the combined held-out
result satisfies all existing gates:

- profit factor at least `1.15`;
- positive net P/L and expectancy;
- at least two profitable held-out sessions;
- at least `60%` retention versus the combined same-target held-out baselines;
- max loss streak no worse than the combined held-out baselines;
- max session drawdown no worse than the combined held-out baselines;
- every fold selects a target;
- deterministic repeated output;
- no broker mutation.

If the walk-forward result passes, run the same ranking on all days to freeze
one final target for prospective read-only shadow. The manifest must include:

- candidate name;
- target grid;
- selected fold targets;
- final all-days target;
- queue policy version;
- source fixture hash;
- historical held-out metrics;
- statement that the manifest authorizes only read-only prospective shadow.

## Failure behavior

If any fold has no eligible target or the combined held-out result fails, write
`NO_OPENING_STATE_QUEUE_TARGET_GRID_EDGE`. Do not lower the retention,
profit-factor, session-count, drawdown, DEMO-only, closed-M1-only, no-LLM, or
one-active rules.

## Safety

Implementation must remain broker-free. It may read sanitized fixtures and
ignored read-only MT5 research artifacts. It must not import broker execution
classes, send orders, cancel orders, modify or close positions, start a runner,
or expose credentials.

## Tests

Add deterministic tests for:

- fixed target grid exposure;
- training target eligibility and ranking;
- no-fold-selection failure;
- combined held-out gate calculation;
- final manifest only after passing held-out gates;
- same-target baseline retention;
- deterministic CLI output;
- broker mutation disabled.
