# One Minute Retest-Reconfirmation V3 Discovery Review

**Candidate:** `ONE_MINUTE_RETEST_RECONFIRMATION_V3`
**Stage:** discovery-only on studied July evidence
**Decision:** `FAIL_DISCOVERY_STOP`
**Broker mutation:** disabled

## Result

| Metric | Result |
| --- | ---: |
| Arms / triggers | 3,865 / 707 |
| Retests / stop placements | 450 / 91 |
| Fills | 51 |
| Wins / losses | 21 / 30 |
| Net | -8.4789R |
| Profit factor | 0.5792 |
| Expectancy | -0.1663R |
| Profitable sessions | 2 / 5 |
| Maximum loss streak | 6 |
| Maximum drawdown | 12.1901R |
| Median / p95 stop-fill drift | 0.0104R / 0.0663R |

Report SHA-256:
`0A4E5572FC4DFE7B4500199C4E9A7C9D04E1F411FAD5A9FDAE6ADD053CD2A317`

V3 improved V2 economics and retained realistic execution, but failed every
frozen discovery requirement. BUY lost -3.2403R, SELL lost -5.2386R, and no
family was positive.

The reserved June V3 held-out range was not fetched or inspected.

## Correctness gap discovered after rejection

The reused equal-level detector groups extrema within tolerance but does not
itself enforce two written playbook requirements:

- touches separated by time or meaningful price movement;
- visible reaction away from the level.

Global chop rejection does not prove those candidate-local properties.
Therefore V1-V3 rejected the implemented raw repeated-extrema population, not
a fully compliant clean-level population.

Any next candidate must version the detector, preregister its structural
definitions, and use new data. V3 remains rejected and may not be repaired by
filters.
