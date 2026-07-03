# One Minute Opening-State Target Grid Screening

**Date:** 2026-07-03  
**Candidate:** `OPENING_STATE_QUEUE_TARGET_GRID_V1`  
**Design:** `docs/superpowers/specs/2026-07-03-one-minute-opening-state-target-grid-design.md`  
**Manifest:** `docs/analysis/2026-07-03-one-minute-opening-state-target-grid-frozen-manifest.json`  
**Runner state:** execution runner stopped; no broker mutation performed.

## Data

- Source: ignored read-only MT5 research fixture under `test-artifacts/opening-state/`.
- M1 bars: `5,000`.
- Tick rows exported: `3,142,268`.
- Valid tick rows used by prior replay preparation: `2,291,807`.
- Invalid quote rows ignored by replay: `850,461`.
- Source fixture hash: `3decfe31de607678de2a76fd94ae4c5fdc805602caefd1521848a6446dbb047e`.
- Raw generated fixture/report are not tracked.

## Pre-registered target grid

```text
risk_reward = 0.60, 0.75, 0.90, 1.00
```

Each fold selected a target using only the other four UTC days, then applied
the selected target once to the held-out day. The same selected target was used
for the held-out candidate and held-out baseline.

## Fold selections

| Held-out day | Selected target | Held-out fills | Held-out net | Held-out PF | Held-out retention |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-06-29 | 0.60R | 231 | 13.12 | 1.4242 | 67.54% |
| 2026-06-30 | 0.75R | 122 | 17.33 | 2.2239 | 29.12% |
| 2026-07-01 | 0.60R | 1,209 | 243.10 | 2.3149 | 67.58% |
| 2026-07-02 | 0.60R | 1,194 | 288.95 | 2.6047 | 65.42% |
| 2026-07-03 | 0.60R | 376 | 69.02 | 2.1925 | 65.39% |

The weak-retention held-out day on `2026-06-30` did not prevent the combined
held-out result from passing the pre-registered aggregate gate.

## Combined held-out baseline

Baseline is the combined held-out all-template replay using each fold's
selected target.

| Metric | Value |
| --- | ---: |
| Fills | 4,950 |
| Wins | 3,747 |
| Losses | 1,203 |
| Net | 885.55 |
| Gross profit | 1699.24 |
| Gross loss | -813.69 |
| Profit factor | 2.0883 |
| Expectancy | 0.1789 |
| Profitable UTC days | 5 |
| Max loss streak | 11 |
| Max session drawdown | 28.62 |

## Combined held-out candidate

`OPENING_STATE_QUEUE_TARGET_GRID_V1` applies deterministic signal-zone
deduplication, earliest-expiry queue selection, one-active simulated execution,
absolute original expiry, and fold-selected fixed targets from the grid.

| Metric | Value |
| --- | ---: |
| Fills | 3,132 |
| Wins | 2,431 |
| Losses | 701 |
| Net | 631.52 |
| Gross profit | 1099.44 |
| Gross loss | -467.92 |
| Profit factor | 2.3496 |
| Expectancy | 0.2016 |
| Fill retention | 63.27% |
| Profitable UTC days | 5 |
| Max loss streak | 5 |
| Max session drawdown | 5.66 |

## Gate

| Gate | Result |
| --- | --- |
| Profit factor `>= 1.15` | Pass: `2.3496` |
| Positive net and expectancy | Pass: `631.52`, `0.2016` |
| At least two profitable sessions | Pass: `5` |
| Fill retention `>= 60%` | Pass: `63.27%` |
| Max loss streak no worse than baseline | Pass: `5 <= 11` |
| Session drawdown no worse than baseline | Pass: `5.66 <= 28.62` |
| Every fold selects a target | Pass |
| Broker mutation disabled | Pass |

## Decision

`FREEZE_OPENING_STATE_QUEUE_TARGET_GRID`

The frozen all-days target for prospective read-only shadow is `0.75R`. The
historical result authorizes read-only prospective shadow only. It does not
authorize broker orders or restarting the MT5 execution runner.

## Safety

- No broker orders were placed, modified, or closed.
- No execution runner was started.
- No credentials, account identifiers, broker tickets, or terminal paths were
  tracked.
- Raw generated JSON remains ignored under `test-artifacts/opening-state/`.
