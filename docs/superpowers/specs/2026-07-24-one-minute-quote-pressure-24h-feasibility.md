# M1 Quote-Pressure 24-Hour Feasibility Gate

## Purpose

This read-only gate answers one question before another trading candidate is
built: can the broker feed operationally satisfy the One Minute Scalper's
frozen 20-distinct-mid-change quote-pressure mechanism often enough to support
a strategy?

It is a rapid triage lane, not a promotion stage. A pass permits development of
a separately named V11 candidate. It does not authorize orders, shorten V11's
economic promotion gates, or modify V8-V10.

## Future evidence window

The single future window is `2026-07-26T22:00:00Z` through
`2026-07-27T22:00:00Z`. It begins at the next expected broker market opening so
weekend closure does not consume the requested 24-hour test.

## Unit of analysis

One eligible fully closed M1 candle and the causally subsequent three-second
tick window. Consecutive unchanged mids do not count. Twenty changes therefore
require 21 distinct consecutive mid observations.

## Frozen decision metrics

- At least 1,000 eligible closed-minute windows.
- At least 15% can supply 20 distinct mid changes in three seconds.
- At least 30 windows and at least 5% of all eligible windows pass an optimistic
  upper-bound pressure path:
  - BUY or SELL directional pressure at least 0.60;
  - displacement at least `max(median spread, 0.10)` using the maximum allowed
    one-unit stop as the most permissive reference risk;
  - adverse movement no more than 0.15;
  - median spread no more than 1.10 times starting spread.
- Strictly feasible events appear in at least 75% of three-hour buckets.

## Data-quality guardrails

- Every minute containing ticks must have the matching closed M1 candle with at
  least 99.5% coverage.
- Candle timestamps must be unique.
- The fixture must remain DEMO, read-only, and flat at collection.
- Incomplete recent MT5 history is retried rather than screened.

Any failed guardrail or metric returns `FEED_INFEASIBLE`. Thresholds cannot be
changed after the manifest is frozen.

