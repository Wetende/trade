# One Minute Compression Hold V5.1 Discovery Review

**Candidate:** `ONE_MINUTE_COMPRESSION_HOLD_V5_1`
**Stage:** frozen discovery, `2026-06-01T00:00:00Z` inclusive through
`2026-06-22T00:00:00Z` exclusive
**Decision:** `FAIL_DISCOVERY_STOP`
**Broker mutation:** disabled

## Frozen artifacts

- Manifest SHA-256:
  `C70A257A35021949540BE72EE7DD78C875C95981561A7BFE36B6AD2B6CB33340`
- State implementation SHA-256 before final conformant rerun:
  `36300DD0DE9EB2FD528FE018DB8CBD9C233258A468E29FC44DD916E5055154A3`
- Replay implementation SHA-256 before final conformant rerun:
  `30ECFE6603A81D74A6622EE6147CC9C81B0C6FB4C2493ED161A5D88BA61DE566`
- Evaluation implementation SHA-256 before final conformant rerun:
  `32AE78607F31A74B9FCE2E2617804DD5B4538E5434C3D68FA0E088D426DFB296`
- Combined source SHA-256:
  `0383097BB7DCB4AFBD031BBDA78A7F0B24F05B981E66575271A7AF29DEC2351C`
- Report SHA-256:
  `A22C4EEF33E227C3C5DEEC638656466B297B6F019FAE5FC23A9C590EEC13DBBC`
- Report:
  `test-artifacts/post-close-v5-1/2026-07-15-discovery/discovery-report.json`

The three preregistered folds contain 20,571 candles and 13,445,550 ticks.
Every fixture records `broker_mutation_enabled: false`.

## Result

| Metric | Result |
| --- | ---: |
| Arms / triggers | 77 / 72 |
| Stop placements / fills | 19 / 17 |
| Wins / losses | 4 / 13 |
| Net | -5.2292R |
| Profit factor | 0.3197 |
| Expectancy | -0.3076R |
| Profitable sessions | 2 / 10 |
| Maximum loss streak | 5 |
| Maximum drawdown | 5.2292R |
| Placement / fill rate | 26.39% / 89.47% |
| Geometry-rejection rate | 73.61% |
| Median / p95 fill drift | 0.0000R / 0.0363R |

BUY produced seven losses from seven fills for `-4.4105R`. SELL produced four
wins and six losses for `-0.8187R`, profit factor `0.7501`, and expectancy
`-0.0819R`. Neither direction or directional family was profitable.

Fifty-three triggered states were rejected because their structurally valid
stop distance exceeded the frozen `1.50` maximum. This made placement
infeasible under the risk policy, but the 18 fills that did fit the policy
were also decisively negative. Widening the stop after observing these
outcomes would be post-hoc risk tuning and cannot convert this run to a pass.

V5.1 failed the frozen minimum-fill, profit-factor, expectancy,
both-directions, family-breadth, profitable-session, placement-rate, and
geometry-rejection gates.

## Conformance rerun

The first output, SHA-256
`B19A345C156CD3BF9B321B63491989D660B70B633D302489A071F217634DA3B9`,
was superseded after an audit found that V5.1 could inherit the older
retest-resume trigger and apply the signal's 120-second armed timer to an
already triggered lifecycle. The correction was recorded before rerun in
`docs/analysis/2026-07-15-one-minute-v5-1-conformance-correction.md` and made
no economic or gate change. The same saved fixtures were replayed. The
result with SHA-256
`C878EAA2EB1D9424641DBE606FBABA6EFBF4D3BF54BE571DDEF141AB77F852A8`
removed one nonconforming SELL win, then was superseded when a final safety
audit required direction-safe broker tick-grid snapping before geometry was
checked. The same fixtures were replayed again. The `A22C...` report above is
the only V5.1 discovery result eligible for review.

## Decision

V5.1 is rejected at discovery. The hold-continuation repair improved trigger
and placed-stop fill rates but did not demonstrate a profitable or robust
edge. Its thresholds, direction, stop distance, sessions, target, exit logic,
or losing trades must not be selected or tuned on this evidence.

The reserved `2026-06-22T00:00:00Z` through `2026-06-29T00:00:00Z` held-out
range was not fetched or inspected. No V5.1 prospective or order-capable DEMO
process may start. The existing DEMO connectivity monitor remains read-only
and is not a trading process.

## Final validation

The final report was independently reconciled before push. All three source
fixture hashes, their ordered combined hash, and the frozen manifest hash
match the report. Arms reconcile to outcome counts. Fills reconcile to wins
plus losses, and net R, profit factor, expectancy, win rate, profitable-session
ratio, placement rate, fill rate, and geometry-rejection rate recompute within
`0.000001` of the saved values.

Validation assessment: ready to share as a discovery rejection. It is not
evidence for strategy approval, profitability, prospective shadow trading, or
order-capable DEMO.
