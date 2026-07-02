# One Minute Scalper Impulse Loss Review

**Evidence session:** `2026-07-02-054425-one-minute-scalper-evidence`  
**Comparison session:** `2026-07-01-182530-one-minute-signal-reliability`  
**Scope:** deterministic closed-M1 One Minute Scalper, DEMO, volume 1.0

## Executive finding

The evidence improvements worked as correctness and observability changes, but
they intentionally did not materially restrict signal admission. The second
session therefore repeated the original strategy's dominant failure:
directional impulse candles were treated as clean continuation even when the
same closed candle showed two-sided structural breaks.

The primary defect is signal classification. Execution and active management
were not the dominant cause.

## Evidence-session results

| Metric | Result |
|---|---:|
| Closed trades | 18 |
| Wins / losses / break-even | 5 / 13 / 0 |
| Win rate | 27.78% |
| Net P/L | -630.80 |
| Gross profit / gross loss | 193.20 / -824.00 |
| Profit factor | 0.2345 |
| Average win / loss | 38.64 / -63.38 |
| Orders placed / filled / expired | 23 / 18 / 5 |
| Broker request rejections | 1 transient invalid-price response |
| Health failures | 0 |

The broker rejection did not lose an opening. The same still-valid opening was
checked again, accepted, filled, and later reconciled. Fill drift was
negligible.

## Two-session comparison

| Group | Trades | W-L | Net |
|---|---:|---:|---:|
| All | 39 | 12-27 | -1,234.80 |
| Impulse | 27 | 8-19 | -923.00 |
| Fakeout | 4 | 0-4 | -304.00 |
| Respect | 8 | 4-4 | -7.80 |
| Impulse with both high and low zones broken | 19 | 5-14 | -655.00 |

The combined expectancy was `-31.66` per trade and profit factor was `0.3368`.
Impulse trades accounted for 74.7% of the total loss.

## Why the new guards did not prevent the losses

The consumed-opening guard blocks a previously submitted opening only when its
zone, direction, trigger family, reaction type, confirmation timestamp, last
touch, and touch count do not contain newer structural evidence.

The evidence session produced:

```text
23 consumed openings
23 unique full opening contexts
23 unique confirmation timestamps
0 stale-opening skips
```

This is correct under the approved semantics. Every new order came from a new
closed M1 confirmation. The guard prevented exact restart resubmission; it was
not designed as a generic cooldown or a ban on new levels.

Signal-quality fields were deliberately shadow telemetry. They measured the
problem but did not reject a trade.

## Signal-selection failure

Sixteen of 18 fills were impulse breaks. They produced four wins, twelve
losses, and `-616.80`.

The global two-sided relation was negative but included remote opening memory,
so it is not a valid hard veto under candidate-local semantics. Direct review
showed a more precise defect: after the highest-touch local level failed an
impulse-quality gate, the engine could select an economically overlapping
lower-touch level from the same candle and place essentially the same trade.

Across both sessions, 15 impulse trades entered less than `0.80` from their
selected repeated level. They produced four wins, eleven losses, and
`-687.00`. The 12 impulses displaced by at least `0.80` produced four wins,
eight losses, and `-236.00`.

Three documented impulse losses across the sessions had confirmation bodies
below `0.50` of the preceding 12-candle median range. A candle can close near
one end of its own small range and pass the existing decisive-close test while
still being economically weak relative to current M1 movement.

## Frequency

Across both sessions, 15 trades occurred no more than three minutes after the
previous trade. They produced four wins, eleven losses, and `-607.00`.

The evidence-session subset was nine trades, two wins, seven losses, and
`-423.00`. However, the non-rapid trades also lost. A generic cooldown would
reduce exposure but would not repair the continuation classifier, so it is not
the selected correction.

## Execution and management audit

Twelve of thirteen evidence-session losses recorded zero sampled MFE. The
remaining loss recorded only `0.12` favorable movement. The entries were wrong
before management had meaningful profit to protect.

Ten one-second adverse exits realized `-602.00`. Their original structural
stops represented approximately `-762.78`, so the emergency exits saved an
estimated `160.78`.

Using later closed M1 bars only for management evaluation:

| Post-exit result within five minutes | Trades |
|---|---:|
| Original stop reached before original target | 7 |
| Original target reached before original stop | 2 |
| Both crossed in the same candle | 1 |

Emergency management was imperfect but materially reduced loss overall. No
management threshold change is supported.

## Supported correction

For impulse candidates only:

1. Consolidate economically overlapping same-side repeated levels and retain
   the freshest, highest-touch deterministic representative.
2. Reject when entry displacement from that representative is below `0.80`.
3. Reject when its body is below `0.50` of the prior 12 closed candles' median
   range.

Keep pressure and active pulse contextual. Keep every trigger family. Do not
add a generic cooldown, score increase, spread retune, volume change, or
management change. Keep remote two-sided memory diagnostic rather than a veto.

## Safety state

The runner stopped at the configured session-loss limit. The final broker
inspection showed a DEMO account, enabled trading, zero open orders, and zero
open positions. No broker state was abandoned.
