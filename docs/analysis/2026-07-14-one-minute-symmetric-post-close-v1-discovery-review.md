# One Minute Symmetric Post-Close V1 Discovery Review

**Candidate:** `ONE_MINUTE_SYMMETRIC_POST_CLOSE_STATE_V1`
**Stage:** discovery-only on an already-studied fixture
**Broker mutation:** disabled
**Decision:** `REJECT_V1`

## Evidence

- Candles: `7,200`
- Ticks: `2,780,883`
- Sessions: `5`
- Source fixture: ignored realistic MT5 fixture under `test-artifacts/`
- Report: ignored artifact at
  `test-artifacts/post-close-v1/2026-07-14-discovery/discovery-report.json`
- Report SHA-256:
  `E7D4AE816F1009BCDBB9757DD82FD4DACFCFF17E7B912B44396D02AB75143DA1`

This window was used in prior opening-state research. It cannot approve a
candidate even if positive.

## Result

| Metric | Result |
| --- | ---: |
| Detected arms | 3,865 |
| Post-close triggers | 670 |
| Trigger rate | 17.34% |
| Fills | 59 |
| Fill rate per trigger | 8.81% |
| Wins / losses | 15 / 44 |
| Net | -24.8962R |
| Profit factor | 0.2087 |
| Expectancy | -0.4220R |
| Profitable sessions | 0 / 5 |
| Maximum loss streak | 12 |
| Maximum portfolio drawdown | 25.4177R |
| Median / 95th entry drift | 0.5376R / 0.6322R |

Every filled family and both directions lost. Confirmed-break families
produced no fills.

## Lifecycle diagnosis

Major terminal reasons:

- `ONE_ACTIVE_LIFECYCLE`: 1,562
- `ARM_EXPIRED`: 1,022
- `TWO_LOSS_PAUSE_ACTIVE`: 433
- `STOP_DISTANCE_ABOVE_MAXIMUM`: 375
- crossed at placement: 189
- `SAME_OPENING_RESET_REQUIRED`: 93
- invalidated before placement: 100+

The state and safety controls worked. They did not create an economic edge.
The protective intrabar exit closed 39 of 44 losses and prevented those
positions from waiting for the full structural stop.

## Rejected interpretation

V1 is not close to approval and must not be repaired with family, direction,
touch-count, session, score, spread, or body filters.

The construction also contains a structural inconsistency: a respect trigger
requires price to move away from the zone, then V1 enters at the later market
quote. That necessarily produces material level-to-entry drift and often a
stop wider than the one-minute cap. The observed median drift of 0.5376R is
not an incidental threshold miss; it is a consequence of the entry event.

## Next bounded hypothesis

The only supported next research hypothesis is a new version with materially
different entry construction: use the causal post-close event as validation,
then place a short-lived retest pending entry at the frozen zone edge. The
pending order does not exist before post-close validation and cannot fill
before its simulated placement time.

This is not a V1 threshold change. It is a new V2 candidate. V1 remains
immutable and rejected.
