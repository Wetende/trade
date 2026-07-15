# One Minute Post-Close Retest V2 Discovery Review

**Candidate:** `ONE_MINUTE_POST_CLOSE_RETEST_V2`
**Stage:** discovery-only on already-studied evidence
**Broker mutation:** disabled
**Decision:** `REJECT_POST_CLOSE_RETEST_HYPOTHESIS`

## Result

| Metric | Result |
| --- | ---: |
| Detected arms | 3,865 |
| Triggers | 615 |
| Trigger rate | 15.91% |
| Valid pending placements | 273 |
| Placement rate | 44.39% |
| Fills | 105 |
| Pending fill rate | 38.46% |
| Wins / losses | 11 / 94 |
| Net | -62.8782R |
| Profit factor | 0.0897 |
| Expectancy | -0.5988R |
| Profitable sessions | 0 / 5 |
| Maximum loss streak | 19 |
| Maximum portfolio drawdown | 62.8782R |
| Pending expiry rate | 61.54% |
| Median / 95th execution drift | 0.0143R / 0.1157R |

Report artifact:
`test-artifacts/post-close-v2/2026-07-14-discovery/discovery-report.json`

Report SHA-256:
`4EB802DA9CD557382435401C927F0CC7996FCE004DC49024EBA30A47CFB94584`

## Interpretation

V2 successfully corrected V1's execution-drift defect. Median and tail drift
met the preregistered V2 limits, and pending fill rate exceeded 30%.

Economics deteriorated. Every family lost:

- `HIGH_RESPECT_SELL`: -21.2375R
- `LOW_RESPECT_BUY`: -22.4434R
- `FAILED_HIGH_BREAK_SELL`: -6.8105R
- `FAILED_LOW_BREAK_BUY`: -3.9633R
- `HIGH_BREAK_BUY`: -4.9537R
- `LOW_BREAK_SELL`: -3.4698R

BUY lost -31.3604R and SELL lost -31.5178R. This is not a concentration or
one-direction issue.

Protective management remained useful: 77 positions used the two-observation
intrabar adverse exit. The negative result does not justify widening stops or
weakening fast protection.

## Stop decision

The frozen V2 stop condition is met. The symmetric post-close repeated-level
retest hypothesis is rejected on discovery evidence.

Do not:

- select only one family or direction;
- tune expiry, target, stop, score, touch count, session, or confirmation;
- lower economic or executability gates;
- begin prospective shadow or order-capable DEMO;
- reuse this fixture to claim another candidate edge.

Further strategy research requires a materially different market hypothesis
and genuinely new untouched data. The implemented causal replay, state,
safety, reset, loss-pause, and telemetry infrastructure remains reusable.
