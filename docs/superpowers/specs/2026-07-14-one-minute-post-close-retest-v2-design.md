# One Minute Post-Close Retest V2 Design

## Status

Pre-registered discovery contract created after V1 was formally rejected and
before V2 outcome evaluation.

## Candidate

`ONE_MINUTE_POST_CLOSE_RETEST_V2`

V1 proved that validating a rejection and then entering at a later market
quote creates excessive structural drift and poor stop geometry. V2 changes
entry construction rather than filtering V1 outcomes.

## Shared Signal State

V2 reuses V1 without modification for:

- 60 fully closed M1 candles;
- repeated-level tolerance and consolidation;
- the six symmetric families;
- closed-candle confirmation;
- confirmation close plus five-second trigger eligibility;
- new post-close zone/hold event;
- invalidation and one-active lifecycle;
- durable reset and two-loss pause;
- protective position management.

## New Entry Construction

The new post-close event validates the market story but does not cause a
market entry. Five seconds after the trigger, V2 submits a simulated retest
limit order:

- BUY intended entry: frozen `zone_high`.
- SELL intended entry: frozen `zone_low`.

At placement BUY ask must still be above the intended entry and SELL bid must
still be below it. Otherwise the retest has already crossed and the order is
rejected. Structural invalidation must still hold.

The pending order becomes fillable only on a strictly later valid tick. BUY
fills when ask is at or below the intended entry; SELL fills when bid is at or
above it. Fill uses the executable ask/bid, capped by the limit price in the
unfavorable direction. No quote before placement can fill the order.

Pending expiry is the earlier of:

- placement plus 20 seconds; or
- confirmation close plus 75 seconds for respect/failed-break and 90 seconds
  for confirmed-break.

Cancel before fill on structural invalidation, expiry, safety failure, or
story change. Expiry remains absolute across restart.

At placement, construct stop from the intended entry and frozen structural
invalidation, expanded only to meet broker minimum and `1.20 * spread`.
Reject above the unchanged 1.00 maximum stop. Target remains 1.50R. Modeled
round-trip cost remains 0.05R. Volume remains constant.

## Drift Semantics

Report two distinct quantities:

- structural entry distance: intended entry minus frozen level, in R;
- execution drift: actual fill minus intended limit price, in R.

Only execution drift is an executability gate. V1 incorrectly used intentional
zone-edge distance as though it were placement slippage.

## Frozen V2 Gates

Economic held-out and prospective gates remain V1's 1.25/1.20 PF,
+0.10R/+0.08R expectancy, positive net, 60% profitable sessions, 8R portfolio
and 3R session drawdown, six-loss streak, and concentration/cost-stress gates.

Executability gates for a deliberately pending retest entry:

- Trigger rate at least 15% of detected arms.
- At least 70% of triggers produce a valid pending placement.
- At least 30% of placed pending orders fill.
- Pending expiry no more than 65% of placed orders.
- Crossed/invalid-at-placement no more than 20% of triggers.
- Broker/geometry rejection no more than 5% of triggers.
- Median execution drift no more than 0.05R; 95th percentile no more than
  0.15R.

Held-out still requires 100 fills and 10 sessions. Prospective still requires
60 fills and 10 independent sessions/days.

## Stop Rule

If V2 is not positive in discovery across both directions and at least two
economic families, or fails realistic timing/executability materially, reject
the post-close retest hypothesis. Do not mine target, expiry, session,
direction, family, touch-count, or confirmation filters against the same
fixture.
