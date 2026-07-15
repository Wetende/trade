# One Minute Shock-Reclaim V6 Discovery Review

**Candidate:** `ONE_MINUTE_SHOCK_RECLAIM_V6`

**Stage:** frozen discovery, `2026-06-01T00:00:00Z` inclusive through
`2026-06-22T00:00:00Z` exclusive

**Decision:** `FAIL_DISCOVERY_STOP`

**Broker mutation:** disabled

## Frozen artifacts

- Manifest SHA-256:
  `959E75947B9088C523F287F4DADA8B39FB8C8E20A23C7AEB0A06A0FE2D472F52`.
- Signal implementation SHA-256:
  `3F45533C0D8CC4198564FA8158302710150AD2B42B4BA7F51284031EB434D99D`.
- State implementation SHA-256:
  `4A917C0557ED085A698670D060257B9BCFFD21EE8C760064796719DA086B9D83`.
- Replay implementation SHA-256:
  `814F38344399770630460D3E8E99712253A294F6B973FB2A3173091EAF586471`.
- Evaluation implementation SHA-256:
  `54FEAFE3736BBEBEA5B85BFAD6899D52D0F3B31293452CBE6C501390B1C5BC91`.
- Ordered combined source SHA-256:
  `0383097BB7DCB4AFBD031BBDA78A7F0B24F05B981E66575271A7AF29DEC2351C`.
- Report SHA-256:
  `25E748312045BEAC564A2B012E5D1277A7061A629039B78348D1584D635FD0A3`.
- Ignored report:
  `test-artifacts/post-close-v6/2026-07-15-discovery/discovery-report.json`.

The three preregistered folds contain 20,571 candles and 13,445,550 ticks.
All fixture hashes match the pre-outcome data ledger. The full suite passed
with 1,080 tests, four platform/live skips, and 75 subtests before discovery.

## Result

| Metric | Result |
| --- | ---: |
| Arms / triggers | 94 / 85 |
| Stop placements / fills | 4 / 4 |
| Wins / losses | 1 / 3 |
| Net | -1.601446R |
| Profit factor | 0.307545 |
| Expectancy | -0.400361R |
| Profitable sessions | 0 / 3 |
| Positive weekly folds | 0 / 3 |
| Maximum loss streak | 2 |
| Maximum drawdown | 1.601446R |
| Trigger / placement / fill rate | 90.43% / 4.71% / 100.00% |
| Geometry-rejection rate | 92.94% |
| Median / p95 level-to-fill drift | 0.651351R / 0.740215R |
| Crossed placements / safety failures | 0 / 0 |

Every discovery fold was net negative: `-0.803846R`, `-0.047600R`, and
`-0.750000R`. BUY produced one loss for `-0.750000R`. SELL produced one win
and two losses for `-0.851446R`, profit factor `0.455147`, and expectancy
`-0.283815R`. Neither direction or directional family was profitable.

Execution held the reclaimed side often enough to trigger 85 of 94 arms, but
only four states could place a stop under the frozen geometry. Fifty-four
triggered states exceeded the `1.50` maximum stop distance and 25 exceeded the
`0.75R` level-to-entry drift limit. Two more were structurally invalidated at
placement. This is a market-structure/risk mismatch, not a software failure:
the safety controls rejected the orders as designed.

V6 failed the frozen fill-count, session-count, profit-factor, expectancy,
directional-symmetry, family-symmetry, profitable-session, positive-fold,
placement-rate, geometry-rejection, and median-drift discovery gates.

## Decision

V6 is rejected at discovery. The research hypothesis did not demonstrate a
profitable or executable edge after realistic costs. Its stop cap, drift cap,
signal thresholds, directions, sessions, target, exits, or losing subgroups
must not be changed or selected on this evidence. Any later candidate must be
materially different and independently preregistered before its outcomes are
calculated.

The reserved `2026-06-22T00:00:00Z` through `2026-06-29T00:00:00Z` held-out
range was not fetched or inspected. No V6 prospective or order-capable DEMO
process may start. The DEMO connectivity monitor may run only in read-only,
flat-account mode.

## Final validation

The report was independently reconciled before push. The three source hashes,
their ordered combined hash, the frozen manifest hash, and all implementation
hashes match the pre-outcome ledger. Ninety-four arms reconcile to 94 outcome
rows. Four fills reconcile to one win plus three losses. Fold fills and net R
reconcile to aggregate fills and net R. Profit factor, expectancy, placement
rate, fill rate, and geometry-rejection rate recompute within `0.000001` of
the saved report. Broker mutation, crossed placements, and safety failures are
all zero.

Validation assessment: ready to share as an immutable discovery rejection.
It is not evidence for strategy approval, profitability, held-out access,
prospective shadow trading, or order-capable DEMO.
