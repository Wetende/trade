# One Minute Compression Hold V5.1 Design

## Candidate

`ONE_MINUTE_COMPRESSION_HOLD_V5_1`

Frozen before either new V5.1 discovery week is fetched or any V5.1 outcome is
calculated.

## Repair scope

Frozen V5 detected only 26 arms in its seven-day discovery window, making its
30-fill gate mathematically unreachable. Its retest lifecycle then allowed
only two fills: 13 triggered states expired waiting for a retest and three
placed stops expired. This is an execution-feasibility failure, not permission
to weaken the gate or promote the two-trade result.

V5.1 keeps the V5 compression-expansion signal unchanged and tests the market
story that an expansion should continue after a causally observed post-close
hold. It does not select a direction, session, or V5 outcome subgroup.

## Signal

Use V5 unchanged:

- 36-bar volatility baseline;
- 12-bar compression box;
- compression median range no more than 70% of baseline median range;
- box width no more than 3.0 baseline median ranges;
- directional efficiency no more than 0.40;
- confirmation body at least 60% of range;
- directional close in the outer 20%;
- confirmation range between 1.25 compression median ranges and 3.0 baseline
  median ranges;
- exact BUY/SELL symmetry;
- no session, clock, volume, direction, or outcome filter.

## Causal hold-stop execution

1. The expansion confirmation candle must be fully closed.
2. Wait five seconds.
3. Require price to remain beyond the frozen box boundary for at least one
   second using two causally ordered quotes.
4. Wait another five seconds.
5. Place a future stop one tick beyond the current ask for BUY or current bid
   for SELL, but never inside the original frozen breakout threshold.
6. A later tick alone may fill the stop.
7. Cancel the stop after 20 seconds or the 180-second absolute state cap,
   whichever comes first.

Structural invalidation, minimum stop `0.35`, maximum stop `1.50`, minimum
stop/spread multiple `1.20`, target `1.50R`, modeled round-trip cost `0.05R`,
constant volume, one active lifecycle, durable reset, two-loss pause, and all
protective management remain unchanged.

Reject placement when structural entry drift exceeds `0.75R`. This fixed
limit prevents turning the repair into an unrestricted chase.

## Discovery

Evaluate three fixed weekly folds separately and aggregate their chronological
rows:

- `2026-06-01T00:00:00Z` to `2026-06-08T00:00:00Z`;
- `2026-06-08T00:00:00Z` to `2026-06-15T00:00:00Z`;
- `2026-06-15T00:00:00Z` to `2026-06-22T00:00:00Z`.

The third fold reuses the frozen saved fixture. Fetch the first two read-only
only after this document and manifest are written. Weekly boundaries occur
over the market weekend; each fold starts with exactly 60 causal context bars.

Discovery requires:

- at least 30 fills across at least 10 UTC trading sessions;
- PF at least 1.15 and expectancy at least +0.05R after cost;
- positive BUY and SELL and both directional families positive;
- at least 50% profitable sessions;
- maximum portfolio drawdown no more than 8R;
- maximum loss streak no more than six;
- trigger rate at least 15%, placement rate at least 60%, pending stop fill
  rate at least 50%, crossed-placement rate no more than 5%, geometry reject
  rate no more than 10%, median drift no more than 0.50R, and p95 drift no more
  than 0.75R.

Failure rejects V5.1 without threshold tuning.

## Held-out and prospective

Only after a full discovery pass, fetch the untouched
`2026-06-22T00:00:00Z` through `2026-06-29T00:00:00Z` range once. Because that
sealed window contains five trading sessions and the unchanged signal produces
roughly a few dozen weekly arms, its feasible frozen minimum is 15 fills over
five sessions. It must still meet PF 1.25, expectancy +0.10R, 60% profitable
sessions, both-direction positivity, concentration, drawdown, loss-streak,
extra-cost, and hold-execution gates. These held-out counts were fixed before
the range was fetched.

Prospective begins at a newly recorded future timestamp only after held-out
passes and requires 60 fills across at least 10 sessions, PF 1.20, expectancy
+0.08R, and all frozen concentration, drawdown, cost, symmetry, and execution
gates.

Order-capable DEMO remains forbidden until discovery, untouched held-out, and
fresh prospective evidence all pass and the user explicitly approves it.
