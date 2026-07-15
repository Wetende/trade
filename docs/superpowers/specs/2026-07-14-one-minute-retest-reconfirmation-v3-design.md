# One Minute Retest-Reconfirmation V3 Design

## Candidate

`ONE_MINUTE_RETEST_RECONFIRMATION_V3`

Pre-registered after V2 rejection and before V3 outcome evaluation.

## Hypothesis

V2 showed that the first return to a validated level was usually continuation
against the trade. V3 therefore does not fill the first retest. It requires a
third causal event: directional reconfirmation after that retest.

This changes the event sequence, not family, direction, score, session, touch,
target, stop, or volume filters.

## Frozen Sequence

1. Detect and arm one of the six symmetric playbook families from 60 fully
   closed M1 candles.
2. Require the unchanged V1 post-close validation event.
3. Five seconds later begin waiting for a retest of the frozen zone edge.
4. On a retest, wait another five seconds before simulated broker placement.
5. If reconfirmation has not already crossed, place a stop order:
   - BUY stop at `zone_high + B`.
   - SELL stop at `zone_low - B`.
6. Fill only on a strictly later quote crossing the stop in the intended
   direction.

Here `B = max(0.05, 0.25T)` and
`T = max(0.20, 0.20 * median positive M1 range)`.

The retest is observed when BUY ask is at or below `zone_high`, or SELL bid is
at or above `zone_low`, while structural invalidation remains intact.

At stop-placement time, reject if BUY ask is already at/above the stop or SELL
bid is already at/below it. No chase or retrospective fill is allowed.

## Timing

- Confirmation is knowable at candle timestamp plus 60 seconds.
- Initial post-close validation begins no earlier than close plus five seconds.
- Retest watch begins five seconds after validation.
- Stop placement occurs five seconds after the retest observation.
- Stop expires 15 seconds after placement.
- All state is capped at confirmation close plus 90 seconds.
- Restart never extends a deadline.

## Risk And Management

- Current spread is measured at stop placement.
- Stop uses frozen structural invalidation, expanded only for broker minimum
  and `1.20 * spread`.
- Reject risk above 1.00 price unit.
- Target remains 1.50R.
- Cost remains 0.05R per fill.
- Volume remains constant.
- Preserve current partial, break-even, scalp, candle-rejection, stop, and
  two-observation intrabar adverse protection.
- Preserve one active arm/watch/order/position, reset, and two-loss pause.

## Frozen Discovery Stop Rule

Discovery requires at least 30 fills and must be positive after costs in both
BUY and SELL and in at least two economic families. Aggregate PF must be at
least 1.15 and expectancy at least +0.05R. Otherwise reject V3 and stop
repeated-level post-close research on the studied fixture.

No family, direction, touch, confirmation, session, expiry, target, stop, or
management tuning is permitted after discovery.

## Held-Out And Prospective Gates

Held-out and prospective economic, concentration, drawdown, session, and cost
gates remain the V1/V2 gates.

Executability requires:

- initial validation trigger rate at least 15% of arms;
- retest observation in at least 25% of triggers;
- valid stop placement in at least 60% of retests;
- fill in at least 30% of placed stops;
- crossed-at-placement no more than 20% of retests;
- geometry rejection no more than 5% of triggers;
- median/p95 adverse stop-fill drift no more than 0.05R/0.15R.

Held-out requires at least 100 fills across 10 sessions. Prospective requires
60 fills across 10 independent sessions/days. Any safety failure is terminal.
