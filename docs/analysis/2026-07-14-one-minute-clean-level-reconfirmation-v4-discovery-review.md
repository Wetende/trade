# One Minute Clean-Level Reconfirmation V4 Discovery Review

**Candidate:** `ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4`
**Stage:** frozen discovery, `2026-06-15T00:00:00Z` inclusive through
`2026-06-22T00:00:00Z` exclusive
**Decision:** `FAIL_DISCOVERY_STOP`
**Broker mutation:** disabled

## Evidence integrity

- Candles: 6,701, including exactly 60 pre-window closed M1 context bars.
- Ticks: 3,871,955, filtered start-inclusive and end-exclusive.
- Fixture SHA-256:
  `29F806CBFA0EC0E1B048CC0E49BB995B3B11FCA939FDA59DAF004FFD4D8B8675`
- Report SHA-256:
  `43FB7EB4247967E0EB3A9AC2DA7AC1C0F066DE3E37BB1DFA90A568CB5E7A7F81`
- Report:
  `test-artifacts/post-close-v4/2026-07-14-discovery/discovery-report.json`

The collector connected under demo-only, real-orders-disabled safeguards and
used only MT5 historical range, open-order, and open-position reads. The
fixture records `broker_mutation_enabled: false`.

## Result

| Metric | Result |
| --- | ---: |
| Arms / triggers | 2,081 / 701 |
| Retests / stop placements | 419 / 106 |
| Fills | 48 |
| Wins / losses | 11 / 37 |
| Net | -20.4441R |
| Profit factor | 0.1419 |
| Expectancy | -0.4259R |
| Profitable sessions | 0 / 5 |
| Maximum loss streak | 8 |
| Maximum drawdown | 20.5150R |
| Median / p95 stop-fill drift | 0.0120R / 0.1116R |

BUY lost `-10.8158R`; SELL lost `-9.6284R`. No family was profitable. V4
therefore failed the frozen profit-factor, expectancy, symmetry, family
breadth, profitable-session, drawdown, and loss-streak gates. It also failed
the retest-placement and geometry-rejection executability gates.

## Decision

The clean-level correction made the detector comply with the playbook's
separated-touch and visible-reaction requirements. It did not create positive
expectancy. The full symmetric repeated-level, post-close reconfirmation
hypothesis is rejected on discovery evidence.

The untouched `2026-06-22` through `2026-06-29` range was not fetched or
inspected. No prospective shadow or order-capable DEMO process may start.

Do not repair V4 by selecting its tiny positive confirmation subgroup or by
tuning direction, family, touch count, session, target, stop, score, expiry,
or structural thresholds on this window. The written project history already
shows that shallow filters do not repair this losing population. Any further
candidate needs a materially different, preregistered market hypothesis and
new untouched discovery data.
