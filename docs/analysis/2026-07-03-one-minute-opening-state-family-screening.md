# One Minute Opening-State Family Screening

**Date:** 2026-07-03  
**Candidate:** `OPENING_STATE_FAMILY_V1`  
**Design:** `docs/superpowers/specs/2026-07-03-one-minute-opening-state-family-design.md`  
**Runner state:** execution runner stopped; no broker mutation performed.

## Data

- Source: ignored read-only MT5 research fixture under `test-artifacts/opening-state/`.
- M1 bars: `5,000`.
- Tick rows exported: `3,142,268`.
- Valid tick rows used by replay: `2,291,807`.
- Invalid quote rows ignored by replay: `850,461`.
- UTC day partitions: `2026-06-29`, `2026-06-30`, `2026-07-01`, `2026-07-02`, `2026-07-03`.
- Raw generated fixture/report are not tracked.

## Baseline

Baseline is all raw opening-state template fills before one-active family
selection:

- Fills: `4,946`
- Wins/losses: `3,049` / `1,897`
- Net: `2077.98`
- Profit factor: `2.5583`
- Expectancy: `0.4201`
- Profitable UTC days: `5`
- Max loss streak: `9`
- Max session drawdown: `10.32`

## Candidate result

`OPENING_STATE_FAMILY_V1` applies deterministic per-minute/local-zone ranking
and one-active simulated execution.

| Metric | Value |
| --- | ---: |
| Fills | 1,748 |
| Wins | 1,160 |
| Losses | 588 |
| Net | 894.96 |
| Gross profit | 1305.53 |
| Gross loss | -410.57 |
| Profit factor | 3.1798 |
| Expectancy | 0.5120 |
| Fill retention | 35.34% |
| Profitable UTC days | 5 |
| Max loss streak | 6 |
| Max session drawdown | 5.90 |

## Gate

| Gate | Result |
| --- | --- |
| Profit factor `>= 1.15` | Pass |
| Positive net and expectancy | Pass |
| At least two profitable sessions | Pass |
| Fill retention `>= 60%` | Fail: `35.34%` |
| Max loss streak no worse than baseline | Pass |
| Session drawdown no worse than baseline | Pass |

## Decision

`NO_OPENING_STATE_FAMILY_EDGE`

No frozen manifest was created. The candidate improved economic quality but
failed the pre-registered 60% baseline retention gate after enforcing one
active simulated order or position.

## Interpretation

The evidence says the opening-state idea has positive simulated edge, but the
current deterministic one-active ranking discards too many baseline fills.
This failure should not be fixed by lowering the retention gate. The next
hypothesis needs to preserve the one-active guard while increasing eligible
fill retention through better pre-entry scheduling or conflict resolution.

## Safety

- No broker orders were placed, modified, or closed.
- No execution runner was started.
- No credentials or account identifiers were tracked.
- Invalid historical tick quotes were ignored rather than repaired or inferred.
