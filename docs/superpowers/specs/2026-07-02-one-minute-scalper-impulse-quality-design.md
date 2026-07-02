# One Minute Scalper Impulse Quality Design

## Objective

Reduce repeatable false-continuation losses without changing the deterministic
One Minute Scalper into a different strategy. Preserve closed-M1 decisions,
candidate-local memory, all trigger families, one active trade, DEMO-only
execution, volume 1.0, and the existing active-position management.

## Evidence

The first reliability session closed 21 trades for `-604.00`. The evidence
session closed 18 trades for `-630.80`. Combined:

| Group | Trades | W-L | Net |
|---|---:|---:|---:|
| All trades | 39 | 12-27 | -1,234.80 |
| Impulse | 27 | 8-19 | -923.00 |
| Fakeout | 4 | 0-4 | -304.00 |
| Respect | 8 | 4-4 | -7.80 |
| Impulse less than 0.80 from its repeated level | 15 | 4-11 | -687.00 |

In the evidence session, 12 of 13 losses recorded zero sampled MFE. Fill drift
was negligible. Ten one-second adverse exits lost `-602.00` versus an
estimated `-762.78` at their original structural stops, saving approximately
`160.78`. Seven of those ten trades subsequently reached the original stop
before the original target, two reached the target first, and one crossed both
in the same M1 candle. Signal admission, not execution or management latency,
is the primary failure.

The durable consumed-opening guard worked as specified: 23 placed openings had
23 unique full contexts, so no exact stale opening was resubmitted. It did not
and should not treat every new candle at every new level as the same opening.

## Considered approaches

### A. Candidate-local consolidation and impulse quality gates

Consolidate economically overlapping same-side levels, then reject only
impulse candidates whose displacement from that representative level or whose
body is too small. This preserves every trigger family and candidate-local
memory while directly testing the dominant failure.

### B. Quarantine impulse and fakeout families

This maximizes immediate loss avoidance in the two observed sessions but
removes families that still produced valid winners. It is too broad for 39
trades.

### C. Add generic time or loss-streak cooldowns

Trades within three minutes of the prior trade were weak across both sessions,
but non-rapid trades also lost. A cooldown reduces frequency without correcting
the false-continuation classification.

Approach A is selected.

## Deterministic behavior

### Candidate-local level consolidation

Before candidate construction, consolidate repeated levels on the same side
when their distance is no greater than:

```text
level tolerance + current spread
```

Retain one deterministic representative in this order:

1. fresher last touch;
2. greater touch count;
3. narrower observed level spread;
4. stable numeric level order.

This prevents a rejected high-priority level from being replaced by an
economically indistinguishable lower-touch level. Opposite-side and remote
levels remain independent.

### Minimum impulse displacement

For `impulse_break` candidates only, require the proposed entry to be at least
`0.80` from the representative repeated level. Reject with
`IMPULSE_INSUFFICIENT_DISPLACEMENT` below that threshold.

The existing maximum-extension guard remains. Its minimum upper bound is the
`0.80` displacement threshold plus current spread so bid/ask quote selection
cannot make the valid displacement interval impossible.

Across the two reviewed sessions, 15 impulses below `0.80` produced four wins,
eleven losses, and `-687.00`. Impulses at or above `0.80` produced four wins,
eight losses, and `-236.00`. The threshold is specific to the current XAUUSD
One Minute Scalper.

### Decisive body

For `impulse_break` candidates only:

1. Calculate the absolute body of the latest closed M1 candle.
2. Calculate the median range of the preceding 12 fully closed M1 candles.
3. Divide body by that median range.
4. Reject with `WEAK_IMPULSE_BODY` when the ratio is below `0.50`.

The threshold is trigger-specific. Rejection and engulfing confirmations retain
their existing semantics. The forming candle is never used.

### Telemetry

Every candidate continues to emit `signal_quality`. Add these explicit fields:

- `impulse_min_body_to_recent_median_range`
- `impulse_min_entry_distance_from_level`

Rejected candidates retain their score and ranking telemetry and include the
new reason codes. At most one approved candidate remains possible.

## Rules deliberately unchanged

- Remote or global opening memory cannot veto a candidate.
- The global two-sided relation remains diagnostic telemetry only.
- No global pressure or active-pulse veto.
- No trigger-family ban.
- No generic cooldown.
- No score-floor increase.
- No spread threshold change.
- No stop, target, partial, break-even, trailing, or emergency-exit change.
- No sizing change.
- No LLM decision.

## Verification

Add deterministic tests and replay coverage proving:

- an impulse below minimum displacement is rejected;
- an impulse above minimum displacement remains valid;
- a weak-body impulse is rejected;
- overlapping same-side levels cannot bypass a rejection;
- respect and fakeout candidates are not subject to the new impulse gates;
- current clean/mixed controls remain stable;
- closed-M1-only behavior remains intact;
- candidate ranking remains deterministic;
- telemetry includes both new fields and reason codes;
- focused and complete suites pass.

Create a sanitized closed-M1 replay fixture from the evidence session
containing at least one losing insufficient-displacement impulse, one losing
weak-body impulse, and one winning sufficiently displaced impulse. The fixture
contains market bars only, with no account, order, deal, path, or terminal
metadata.

## Deployment

After tests, secret inspection, and push:

1. Confirm DEMO, enabled trading, fresh tick, zero orders, and zero positions.
2. Create a new timestamped session.
3. Start one hidden `ENTRY_ONLY`, `fast_only`, M1 worker with volume 1.0 and the
   600 session-loss guard.
4. Verify heartbeat advancement, engine/runner health agreement, `mt5_tick`,
   empty stderr, and internally consistent broker state.
