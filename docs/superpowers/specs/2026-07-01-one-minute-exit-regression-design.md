# One-Minute Exit Regression Design

## Goal

Correct the execution-management regression observed after commit `aad174e`
without changing One Minute Scalper candidate detection, scoring, direction,
or trigger selection.

## Evidence

The pre-change broker-history window closed 18 trades with 9 wins, 9 losses,
and net profit of 59.60. Applying only the 20-second reaction expiry and
45-second impulse expiry to that same window retains all 9 wins, removes 4
stale losses, and leaves a 14-trade counterfactual result of 9 wins, 5 losses,
and 281.60 net profit.

The post-change session closed 10 trades with 0 wins and net loss of 605. Eight
positions used discretionary early-loss exits. Subsequent completed M1 bars
show that three of those positions later reached their original take-profit
level before their stop-loss level. The one-second scheduler caused position
management to evaluate transient price movement more aggressively.

## Design

Keep trigger-aware pending-order expiry unchanged.

Change lightweight one-second maintenance to pending-order cancellation only.
Full position management continues in `MT5Runner.run_once` at the configured
runner cadence.

For proposals with:

```text
timeframe = 1m
position_lifecycle = FAST_PARTIAL_SCALE
```

disable price-only `EARLY_LOSS_EXIT`. These positions remain protected by:

- broker stop loss;
- broker take profit;
- closed-candle rejection management;
- partial close, break-even, and trailing logic when their thresholds pass.

Non-one-minute and legacy execution paths retain their existing price-based
early-loss behavior.

Remove the obsolete one-minute early-loss grace setting and position-age
normalization introduced solely to support that grace. This avoids retaining
configuration that no longer controls behavior.

## Safety

- One active trade remains enforced.
- Demo-account enforcement remains unchanged.
- Session loss limits remain unchanged.
- Pending orders still expire after 20 or 45 seconds and before the next M1
  candle boundary.
- The entry model is not modified.

## Verification

Tests must prove:

- one-minute `FAST_PARTIAL_SCALE` positions ignore price-only early loss;
- normal positions still use configured early loss;
- closed-candle rejection can still close a one-minute position;
- one-second maintenance cancels stale pending orders without managing
  positions;
- normal runner cycles still manage positions;
- trigger-aware pending expiry remains unchanged;
- the complete test suite passes.
