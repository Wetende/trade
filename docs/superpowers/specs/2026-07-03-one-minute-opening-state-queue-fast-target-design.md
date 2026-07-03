# One Minute Opening-State Queue Fast Target Design

**Date:** 2026-07-03

## Objective

Evaluate `OPENING_STATE_QUEUE_FAST_TARGET_V1`, a deterministic broker-free
opening-state family candidate that tests whether shorter active trade
lifecycle can preserve the opening-state edge while satisfying the existing
historical retention gate.

The prior opening-state family candidate had strong simulated economics but
retained only `35.34%` of baseline fills. Queue-only scheduling improved
retention to `45.09%` but still failed. The next isolated hypothesis is that
the `1.5R` terminal target keeps positions active too long for an M1 scalper
family. This candidate uses a `1.0R` target with the same structural stop.

## Candidate definition

The candidate is `OPENING_STATE_QUEUE_FAST_TARGET_V1`.

It includes exactly the existing pre-registered opening-state templates:

1. `REJECTION`
2. `BREAK_HOLD`
3. `BREAK_RETEST_HOLD`
4. `FAILED_BREAK`

It changes only the broker-free research replay and candidate selection
semantics below:

- signal-zone deduplicate simultaneous openings deterministically;
- maintain a deterministic pending queue of still-fresh opportunities;
- place at most one simulated pending order or position at a time;
- keep the original reaction expiry of about `20` seconds and continuation
  expiry of about `45` seconds measured from the original signal timestamp;
- skip queued opportunities whose original expiry has elapsed;
- use a `1.0R` target and the same structural stop in replay.

No extra template, higher-timeframe trigger, LLM decision, live broker order,
recovery sizing, martingale, grid, straddle, volume boost, or DEMO safety
relaxation is allowed.

## Deterministic queue policy

All queue decisions must use only pre-entry information and clock state:

1. Detect opening opportunities from fully closed M1 candles only.
2. Group opportunities by exact signal timestamp.
3. Within each signal timestamp, remove duplicate local-zone opportunities
   with the same side when their levels are within the maximum of their two
   tolerances.
4. A queued opportunity remains eligible only until its original expiry:
   - reaction: `signal_time + 20 seconds`;
   - continuation: `signal_time + 45 seconds`.
5. When no simulated order or position is active, select the eligible queued
   opportunity with earliest original expiry.
6. Break ties by the existing family rank:
   - higher touch count;
   - `BREAK_RETEST_HOLD`, then `FAILED_BREAK`, then `BREAK_HOLD`, then
     `REJECTION`;
   - newer final used candle index;
   - smaller tolerance;
   - side order `high`, then `low`;
   - rounded level price;
   - deterministic direction string.
7. If a selected opportunity expires without fill, the next queued opportunity
   may be considered immediately if it is still inside its original expiry.
8. If a selected opportunity fills, no other opportunity may be accepted until
   that simulated position closes.

This queue policy does not use future tick outcomes to choose candidates.

## Replay semantics

The tick replay must support delayed placement with absolute original expiry:

- `placed_at` is the later of the original signal timestamp and the time the
  one-active slot becomes free;
- `expires_at` remains the original signal timestamp plus the configured
  reaction or continuation expiry;
- a queued candidate is stale if `placed_at >= expires_at`;
- the decision tick must be the first valid quote at or after `placed_at` and
  no later than `expires_at`;
- fills must occur before `expires_at`;
- stop, target, ambiguous-tick, MFE, MAE, and no-exit handling remain
  conservative.

The replay uses `ReplayConfig(risk_reward=1.0)` for both the candidate and its
same-fixture all-template baseline.

## Historical gate

The candidate can be frozen only if historical replay over the same read-only
5,000-bar fixture satisfies all existing gates:

- profit factor at least `1.15`;
- positive net P/L and expectancy;
- at least two profitable UTC sessions;
- at least `60%` retention versus the all-template eligible baseline replayed
  with the same `1.0R` target;
- max loss streak no worse than that baseline;
- max session drawdown no worse than that baseline;
- deterministic repeated output;
- no broker mutation.

If the candidate passes, write a frozen manifest with:

- candidate name;
- source fixture hash;
- queue policy version;
- replay configuration, including `risk_reward=1.0`;
- historical metrics;
- explicit statement that this authorizes prospective read-only shadow only.

## Failure behavior

If the candidate fails historical gates, write
`NO_OPENING_STATE_QUEUE_FAST_TARGET_EDGE`. Do not lower retention, profit
factor, expectancy, session, drawdown, DEMO-only, closed-M1-only, no-LLM, or
one-active-trade rules.

## Safety

Implementation must remain broker-free. It may read sanitized fixtures and
ignored read-only MT5 research artifacts. It must not import MT5 execution
classes, send orders, cancel orders, modify positions, close positions, expose
credentials, or start the MT5 execution runner.

## Tests

Add deterministic tests for:

- delayed tick replay uses `placed_at` and absolute original expiry;
- stale queued opportunities are skipped;
- queued opportunities can be accepted after an expired or closed prior
  opportunity only when still fresh;
- one-active execution is preserved;
- `1.0R` target is applied without changing the structural stop;
- baseline and candidate use the same replay target for retention;
- deterministic report and manifest output;
- broker mutation remains disabled.
