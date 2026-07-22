# One Minute Causal Microburst V9

Candidate: `ONE_MINUTE_CAUSAL_MICROBURST_V9_1`

This candidate is independently preregistered after V1-V8 failed. It is not a
repair or retune of any failed candidate. Previous sessions are used only to
form the hypothesis: legacy fills commonly moved adverse immediately, stale
levels and counter-pulse entries lost, and V8's family-zone pressure sequence
was infeasible. No prior outcome is used as an entry-time feature.

## Causal signal

Only 60 fully closed M1 candles are visible. The latest three closes must form
a strict directional staircase with at least two same-direction bodies. The
latest candle must have a range between 0.75 and 1.50 times the prior 30-bar
median range, body fraction at least 0.55, directional close location at least
0.75, total three-bar displacement at least 0.75 median range, and a close at
least 0.05 median range beyond the preceding 12-bar high or low.

After the candle closes, a one-second directional hold arms quote-path
confirmation. Within two seconds collect eight distinct midpoint changes,
including at least four nonzero moves. Require directional pressure at least
0.625, displacement at least the larger of median spread and 0.08R, adverse
movement no more than 0.15R, and median spread no more than 1.15 times the
arm-time spread. Wait two seconds, reject crossed, invalidated, widened-spread,
or moved-away states, then propose one direction-safe stop one tick beyond the
quote-path extreme. Stop distance is at least max(0.35, 1.2 spreads) and no
more than 1.00 price unit; target is 1.5R; pending expiry is 20 seconds.

One arm, pending order, or position is permitted. Two losses require a
persistent 15-minute pause plus a later structural reset. Maximum session
budget is 2R. REAL accounts and volume boosting remain prohibited.

## Frozen evidence order

The implementation, replay, lifecycle, cost model, tests, screening code and
manifest hashes are frozen before any post-cutoff fixture is fetched.

- Discovery folds: 2026-07-19T22:00:00Z–2026-07-20T12:00:00Z,
  2026-07-20T12:00:00Z–2026-07-21T02:00:00Z, and
  2026-07-21T02:00:00Z–2026-07-21T16:00:00Z.
- Held-out: 2026-07-21T16:00:00Z–2026-07-22T17:30:00Z, opened only after
  discovery passes.
- Prospective: begins only after held-out passes and a fresh registration is
  written. It can never be backdated.

Discovery requires at least 30 fills across ten three-hour sessions, positive
BUY and SELL net, positive total net, PF at least 1.15, expectancy at least
+0.05R after 0.05R modeled cost, at least half of sessions and two of three
folds profitable, loss streak no more than six, drawdown no more than 8R,
trigger rate at least 15%, trigger-to-fill success at least 85%, crossed rate
no more than 15%, geometry rejection no more than 5%, and zero safety,
lifecycle, mutation, lookahead, restart, or telemetry failures.

Held-out requires 15 fills across five sessions, positive net, PF at least
1.25, expectancy at least +0.10R, positive net without the best session, and
positive net after an extra 0.05R per fill. Prospective requires 60 fills
across ten sessions, positive net, PF at least 1.20, expectancy at least
+0.08R, at least 60% profitable sessions, and zero operational failures.

Any failed stage retires V9 without threshold changes on that window. Only all
three passing stages may generate a hash-locked 0.01 DEMO promotion record.
