# Opening-State Buy Continuation Research

**Date:** 2026-07-08  
**Candidate:** `OPENING_STATE_BUY_CONTINUATION_EXTENDED_V1`  
**Broker mutation:** disabled  
**Execution runner:** not started

## Candidate

This candidate keeps the realistic closed-candle shadow contract and narrows the
opening-state family to post-close BUY continuation entries only:

- templates: `BREAK_HOLD`, `BREAK_RETEST_HOLD`;
- direction: `BUY`;
- entry policy: existing fixed pending entry from the opening-state replay;
- orderable after the signal M1 candle closes;
- placement delay: `5s`;
- crossed-entry chase: disabled;
- target: `0.90R`;
- continuation pending expiry: `120s`.

## Research Window

The read-only fixture came from MT5 closed M1 candles and ticks from
`2026-07-03T11:25:00+00:00` through the July 8, 2026 checkpoint. The fixture is
ignored under `test-artifacts/` and is not tracked.

Result on that already-studied window:

| Metric | Value |
| --- | ---: |
| Fills | `31` |
| Sessions | `5` |
| Wins / losses | `20 / 11` |
| Win rate | `64.52%` |
| Net | `+5.00` |
| Profit factor | `1.5025` |
| Expectancy | `+0.1613` |
| Max loss streak | `3` |

## Decision

This is not DEMO-approved. The candidate was discovered while studying the same
window, so that window cannot serve as clean prospective proof.

The rule is frozen in:

`docs/analysis/2026-07-08-one-minute-opening-buy-continuation-shadow-manifest.json`

Next step is a fresh read-only prospective shadow from a new start timestamp.
Only if the unchanged manifest passes the same gate on fresh data should it be
considered for DEMO execution.
