# One Minute Impulse-Inside-Pullback V7 Discovery Review

**Candidate:** `ONE_MINUTE_IMPULSE_INSIDE_PULLBACK_V7`

**Stage:** frozen discovery, `2026-06-01T00:00:00Z` inclusive through
`2026-06-22T00:00:00Z` exclusive

**Decision:** `FAIL_DISCOVERY_STOP`

**Broker mutation:** disabled

## Frozen artifacts

- Manifest SHA-256:
  `969A3BAC5CA3EC23137A9BCDA657B4FD66A602AB2786276BF70428E6199C0812`.
- Signal implementation SHA-256:
  `78DB048E929403108DD7CB3842AE17D2792582B56599EBEE4B156ED1D5A61C6B`.
- State implementation SHA-256:
  `116015BCBC6F585DCA0D877A5158385984C5C54A6B8E79DBD9016053C5D004BF`.
- Replay implementation SHA-256:
  `48AAC67026205D997BB98D49EBD96F44EDFF70BABB36F34E2727D3B2025581EB`.
- Evaluation implementation SHA-256:
  `2F1182A562D93FBF0D93182660DF95A017CAB0D2B0644FAD8BD36D0939881A92`.
- Ordered combined source SHA-256:
  `0383097BB7DCB4AFBD031BBDA78A7F0B24F05B981E66575271A7AF29DEC2351C`.
- Report SHA-256:
  `D79F0266D307776CD114C33C20C7897488A2C7313C22A80078267A04AF8A8653`.
- Ignored report:
  `test-artifacts/post-close-v7/2026-07-15-discovery/discovery-report.json`.

The three preregistered folds contain 20,571 candles and 13,445,550 ticks.
All source hashes match the pre-outcome ledger. The full suite passed with
1,097 tests, four expected platform/live skips, and 75 subtests before
discovery.

## Result

| Metric | Result |
| --- | ---: |
| Arms / triggers | 120 / 37 |
| Stop placements / fills | 15 / 4 |
| Wins / losses | 1 / 3 |
| Net | -1.951266R |
| Profit factor | 0.121552 |
| Expectancy | -0.487816R |
| Profitable sessions | 0 / 3 |
| Positive weekly folds | 0 / 3 |
| Maximum loss streak | 2 |
| Maximum drawdown | 1.951266R |
| Trigger / placement / fill rate | 30.83% / 40.54% / 26.67% |
| Crossed-at-placement rate | 32.43% |
| Geometry-rejection rate | 27.03% |
| Median / p95 boundary-to-fill drift | 0.033709R / 0.069200R |
| Safety failures | 0 |

The fold results were `-1.232347R`, `0.000000R` with no fills, and
`-0.718919R`. BUY produced one loss for `-0.718919R`. SELL produced one win
and two losses for `-1.232347R`, PF `0.179719`, and expectancy `-0.410782R`.
Neither direction or directional family was profitable.

The compact pullback solved V6's excessive boundary drift: median and p95
drift passed comfortably. It did not produce an executable or profitable
population. Seventy-seven arms invalidated before trigger, ten pending orders
invalidated before fill, twelve triggered setups had already crossed at the
five-second placement check, ten exceeded the frozen `1.50` final risk cap,
and only four of 15 legal stops filled. Three of those four fills lost after
cost.

V7 failed the frozen fill-count, session-count, profit-factor, expectancy,
directional-symmetry, family-symmetry, profitable-session, positive-fold,
trigger-rate, placement-rate, stop-fill-rate, crossed-rate, and
geometry-rejection discovery gates.

## Decision

V7 is rejected at discovery. The complete inside pullback and renewed-breakout
hypothesis did not demonstrate a robust edge. Its impulse threshold, pullback
thresholds, five-second delays, stop distance, target, expiry, sessions,
directions, or subgroups must not be changed or selected using this evidence.
Any later candidate must be materially different and independently
preregistered before its outcomes are calculated.

The reserved `2026-06-22T00:00:00Z` through `2026-06-29T00:00:00Z` held-out
range was not fetched or inspected. No V7 prospective or order-capable DEMO
process may start. The existing DEMO connectivity monitor remains read-only,
flat, and separate from the research replay.

## Final validation

The report was independently reconciled before push. The three source hashes,
their ordered combined hash, the manifest hash, and the implementation hashes
match the pre-outcome ledger. One hundred twenty arms reconcile to 120 outcome
rows. Four fills reconcile to one win plus three losses. Fold fills and fold
net R reconcile to the aggregate. Profit factor, expectancy, trigger rate,
placement rate, fill rate, crossed rate, and geometry-rejection rate recompute
within `0.000001` of the report. Broker mutation and safety failures are zero.

Validation assessment: ready to share as an immutable discovery rejection.
It is not evidence for strategy approval, profitability, held-out access,
prospective shadow trading, or order-capable DEMO.
