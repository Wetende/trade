# Opening-State Realistic Shadow Review

**Date:** 2026-07-08  
**Scope:** `OPENING_STATE_QUEUE_TARGET_GRID_V1`, read-only MT5 shadow, DEMO safety  
**Broker mutation:** disabled  
**Execution runner:** not started

## Why this review was needed

The prior opening-state shadow passed with a high simulated win rate, but it
treated the candle timestamp as immediately orderable. MT5 M1 candle timestamps
are bar-open labels. A closed-candle strategy can only act after that candle
closes, so the pre-demo shadow now models:

- orderability at `candle timestamp + 60s`;
- optional broker placement delay;
- absolute original pending expiry after the close-confirmed signal;
- no chase when the intended entry is already crossed at placement;
- configured broker stop-distance, spread-multiple, and max-entry-distance
  constraints.

## Strict realistic run

Runtime report:

`test-artifacts/opening-state-shadow/2026-07-08-realistic-pre-demo-opening-state-shadow/shadow-report.json`

Replay config:

- candle close delay: `60s`
- placement delay: `5s`
- absolute pending expiry: `true`
- skip crossed entry: `true`
- reaction expiry: `20s`
- continuation expiry: `45s`
- target: `0.75R`
- minimum stop distance: `0.35`
- minimum stop/spread multiple: `1.2`

Candidate result:

| Metric | Value |
| --- | ---: |
| Decision | `FAIL_PROSPECTIVE_SHADOW` |
| Sessions | `5` |
| Fills | `354` |
| Wins / losses | `148 / 206` |
| Win rate | `41.81%` |
| Net | `-73.06` |
| Profit factor | `0.5415` |
| Expectancy | `-0.2064` |
| Max loss streak | `11` |

Gate failures:

- `WIN_RATE_BELOW_0_60`
- `PROFIT_FACTOR_BELOW_1_10`
- `NON_POSITIVE_EXPECTANCY`
- `NON_POSITIVE_NET_PROFIT`

## Zero-placement-delay control

Runtime report:

`test-artifacts/opening-state-shadow/2026-07-08-realistic-post-close-zero-delay-shadow/shadow-report.json`

This kept the closed-candle `+60s` orderability rule but removed the extra
placement delay.

| Metric | Value |
| --- | ---: |
| Decision | `FAIL_PROSPECTIVE_SHADOW` |
| Sessions | `5` |
| Fills | `316` |
| Wins / losses | `120 / 196` |
| Win rate | `37.97%` |
| Net | `-71.19` |
| Profit factor | `0.5146` |
| Expectancy | `-0.2253` |

## Conclusion

The previous high win rate is not liftable into DEMO execution as-is. The
realistic replay indicates the edge was mostly gone by the time a closed-M1
confirmation could be acted on. The five-second placement delay is not the main
cause; the closed-candle orderability correction alone is enough to invalidate
the candidate.

Do not start a DEMO runner for `OPENING_STATE_QUEUE_TARGET_GRID_V1` until a
new realistic shadow candidate passes the pre-demo gate.

The next research step should keep the realistic replay contract and redesign
the entry construction around post-close orderability, rather than relaxing the
gate or reverting to bar-open fills.
