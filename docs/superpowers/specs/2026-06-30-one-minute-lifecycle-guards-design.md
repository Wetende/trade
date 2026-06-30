# One-Minute Lifecycle Guards Design

## Goal

Reduce avoidable One Minute Scalper losses without changing its 60-candle
two-high/two-low setup detection, one-trade-at-a-time rule, or deterministic
direction selection.

## Evidence

The 2026-06-29/30 demo run closed 18 trades for +59.60. Four losses filled
25-60 seconds after their opening was detected, often during an opposing
candle. A blanket 20-second expiry would have improved the retrospective
sample but also removed a valid +110 impulse trade. Position management also
closed one fresh SELL for -40 after four seconds although its original target
was reached after eight seconds.

## Selected Design

Use trigger-aware lifecycle policies:

- One-minute `respect` and `fakeout` pending orders expire after 20 seconds.
- One-minute `impulse_break` and `break` pending orders expire after 45 seconds.
- Every one-minute pending order expires before the next M1 candle boundary.
- A one-second maintenance cadence cancels pending orders and manages open
  positions without rerunning or journaling full market analysis each second.
- One-minute positions receive a five-second grace period before discretionary
  early-loss closure. The broker stop loss remains active immediately.
- Existing closed-candle invalidation remains in place.
- Normal 15m/30m proposals retain their existing activation windows and exit
  behavior.

The lifecycle policy is configurable through deterministic environment-backed
settings. Each pending order state records the selected policy and effective
expiry for telemetry and review.

## Rejected Alternatives

1. A blanket 20-second timeout removes a demonstrated valid impulse winner.
2. Synthetic client-side pending orders could confirm rejection after touch,
   but add a larger execution subsystem and increase disconnect risk.
3. Further candidate-score tightening does not address stale fills or
   sub-five-second lifecycle decisions.

## Safety And Failure Handling

- Demo-account enforcement remains unchanged.
- If policy metadata is unavailable, existing activation-window behavior is
  preserved.
- Missing position-open timestamps preserve existing early-loss behavior for
  non-one-minute and legacy integrations.
- Maintenance errors do not bypass the hard broker SL/TP.

## Verification

Tests must demonstrate:

- reaction and fakeout expiry at 20 seconds;
- impulse expiry at 45 seconds;
- expiry before the next candle boundary;
- normal proposals retain minute-based expiry;
- early loss is blocked before five seconds and allowed afterward;
- one-second maintenance runs between five-second analysis cycles;
- full existing test suite remains green.
