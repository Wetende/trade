# One Minute Opening-State Screening

**Date:** 2026-07-03  
**Runner state:** execution runner stopped; no broker mutation performed.  
**Design:** `docs/superpowers/specs/2026-07-03-one-minute-opening-state-research-design.md`

## Data

- Source: read-only MT5 closed M1 bars plus read-only historical tick range.
- M1 bars: `5,000`.
- Tick rows exported: `3,142,268`.
- Valid tick rows used by replay: `2,291,807`.
- Invalid quote rows ignored by replay: `850,461`, primarily historical rows with a zero ask.
- UTC day partitions: `2026-06-29`, `2026-06-30`, `2026-07-01`, `2026-07-02`, `2026-07-03`.
- Sanitization: raw generated fixture/report stayed under ignored `test-artifacts/opening-state/`; no account identifiers, tickets, orders, deals, terminal paths, credentials, or populated environment values are tracked.
- Source fixture hash: `3decfe31de607678de2a76fd94ae4c5fdc805602caefd1521848a6446dbb047e`.

## Gate

- Historical PF gate: `>= 1.15`.
- Expectancy/net gate: positive.
- Session/day gate: at least two profitable held-out days.
- Retention gate: at least 60% of baseline eligible opportunities.
- Drawdown gate: no worse than baseline.

## Aggregate context

The aggregate opening-state baseline, meaning all four pre-registered templates
evaluated together, produced:

- Fills: `4,946`
- Wins/losses: `3,049` / `1,897`
- Net: `2077.98`
- Gross profit/loss: `3411.49` / `-1333.51`
- Profit factor: `2.5583`
- Expectancy: `0.4201`
- Profitable UTC days: `5`
- Max loss streak: `9`
- Max session drawdown: `10.32`

This is useful evidence, but it is not a frozen candidate from this screen
because the pre-registered first pass allowed each template alone only. Template
combinations or all-template families require a separate pre-registered design
before they can be eligible for freezing.

## Result

| Template | Fills | Net | PF | Expectancy | Fill retention | Profitable days | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| REJECTION | 2,841 | 1026.65 | 2.1926 | 0.3614 | 57.44% | 5 | Fail: `FILL_RETENTION_BELOW_0_60` |
| BREAK_HOLD | 1,139 | 807.12 | 6.2972 | 0.7086 | 23.03% | 5 | Fail: `FILL_RETENTION_BELOW_0_60` |
| BREAK_RETEST_HOLD | 395 | 170.35 | 2.6027 | 0.4313 | 7.99% | 4 | Fail: `FILL_RETENTION_BELOW_0_60` |
| FAILED_BREAK | 571 | 73.85 | 1.3451 | 0.1293 | 11.54% | 4 | Fail: `FILL_RETENTION_BELOW_0_60` |

## Decision

`NO_OPENING_STATE_EDGE` for individual opening-state templates.

No individual template may be frozen for prospective shadow validation from
this screen because every template failed the pre-registered 60% baseline
retention gate.

## Evidence-supported next hypothesis

The aggregate all-template baseline was materially stronger than the prior
single-candle scalper evidence and cleared the economic gates. The next
research step should be pre-registered before implementation:

- treat opening state as a deterministic all-template opportunity family;
- enforce one active simulated order or position;
- define deterministic conflict ranking when multiple opening templates are
  present in the same minute or local zone;
- replay with the same tick-level fill, stop, target, and ambiguity rules;
- compare against the same historical and prospective shadow gates.

This is not a gate reduction. It is a new candidate boundary supported by this
screen's aggregate evidence.

## Safety

- No broker orders were placed, modified, or closed.
- No execution runner was started.
- No credentials or account identifiers were tracked.
- Invalid historical tick quotes were ignored rather than repaired or inferred.
