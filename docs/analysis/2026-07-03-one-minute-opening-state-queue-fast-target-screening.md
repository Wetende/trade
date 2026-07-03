# One Minute Opening-State Queue Fast Target Screening

**Date:** 2026-07-03  
**Candidate:** `OPENING_STATE_QUEUE_FAST_TARGET_V1`  
**Design:** `docs/superpowers/specs/2026-07-03-one-minute-opening-state-queue-fast-target-design.md`  
**Runner state:** execution runner stopped; no broker mutation performed.

## Data

- Source: ignored read-only MT5 research fixture under `test-artifacts/opening-state/`.
- M1 bars: `5,000`.
- Tick rows exported: `3,142,268`.
- Valid tick rows used by prior replay preparation: `2,291,807`.
- Invalid quote rows ignored by replay: `850,461`.
- Source fixture hash: `3decfe31de607678de2a76fd94ae4c5fdc805602caefd1521848a6446dbb047e`.
- Raw generated fixture/report are not tracked.

## Replay configuration

```json
{
  "continuation_expiry_seconds": 45,
  "max_quote_drift": 0.6,
  "minimum_stop_distance": 0.3,
  "reaction_expiry_seconds": 20,
  "risk_reward": 1.0
}
```

The same `1.0R` target configuration was used for the all-template baseline
and for the queued one-active candidate.

## Baseline

Baseline is all raw opening-state template fills before queue selection or
one-active enforcement, replayed with the same `1.0R` target.

| Metric | Value |
| --- | ---: |
| Fills | 4,949 |
| Wins | 3,421 |
| Losses | 1,528 |
| Net | 1504.37 |
| Gross profit | 2556.78 |
| Gross loss | -1052.41 |
| Profit factor | 2.4295 |
| Expectancy | 0.3040 |
| Profitable UTC days | 5 |
| Max loss streak | 11 |
| Max session drawdown | 21.83 |

## Candidate result

`OPENING_STATE_QUEUE_FAST_TARGET_V1` applies deterministic signal-zone
deduplication, earliest-expiry queue selection, one-active simulated execution,
absolute original expiry, and a `1.0R` target.

| Metric | Value |
| --- | ---: |
| Fills | 2,711 |
| Wins | 1,941 |
| Losses | 770 |
| Net | 928.05 |
| Gross profit | 1450.42 |
| Gross loss | -522.37 |
| Profit factor | 2.7766 |
| Expectancy | 0.3423 |
| Fill retention | 54.78% |
| Profitable UTC days | 5 |
| Max loss streak | 5 |
| Max session drawdown | 5.55 |

## Gate

| Gate | Result |
| --- | --- |
| Profit factor `>= 1.15` | Pass |
| Positive net and expectancy | Pass |
| At least two profitable sessions | Pass |
| Fill retention `>= 60%` | Fail: `54.78%` |
| Max loss streak no worse than baseline | Pass |
| Session drawdown no worse than baseline | Pass |

## Decision

`NO_OPENING_STATE_QUEUE_FAST_TARGET_EDGE`

No frozen manifest was created. The candidate materially improved retention
from the prior family candidate (`35.34%`) and queue-only exploratory result
(`45.09%`), but it still failed the pre-registered `60%` retention gate.

## Interpretation

The faster target confirms that active lifecycle duration was part of the
retention problem, but not enough to make this opening-state family acceptable
under the current gate. The next hypothesis should not lower the gate. It must
either find additional deterministic, still-fresh eligible openings without
weakening one-active execution or move to a different signal-construction
family.

## Safety

- No broker orders were placed, modified, or closed.
- No execution runner was started.
- No credentials, account identifiers, broker tickets, or terminal paths were
  tracked.
- Raw generated JSON remains ignored under `test-artifacts/opening-state/`.
