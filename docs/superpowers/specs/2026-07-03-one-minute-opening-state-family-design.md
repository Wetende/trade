# One Minute Opening-State Family Design

**Date:** 2026-07-03

## Objective

Evaluate a frozen deterministic candidate that treats the four pre-registered
M1 opening-state templates as one opportunity family rather than as isolated
single-template filters.

This is a new research boundary, not a relaxation of the gate. The prior
individual-template screen failed because every individual template retained
less than 60% of baseline fills. The aggregate family of all four templates,
however, produced positive evidence over 5,000 M1 bars and read-only ticks:

- fills: `4,946`;
- net: `2077.98`;
- profit factor: `2.5583`;
- expectancy: `0.4201`;
- profitable UTC days: `5`;
- max loss streak: `9`;
- max session drawdown: `10.32`.

## Candidate definition

The candidate is `OPENING_STATE_FAMILY_V1`.

It includes exactly these templates:

1. `REJECTION`
2. `BREAK_HOLD`
3. `BREAK_RETEST_HOLD`
4. `FAILED_BREAK`

No extra template, higher-timeframe trigger, LLM decision, recovery sizing,
martingale, grid, straddle, or volume boost is allowed.

## Deterministic selection

The family may emit multiple opportunities in the same minute or local zone.
Selection must be deterministic and pre-entry only.

For each signal timestamp:

1. Group opportunities by UTC minute.
2. Remove duplicate local-zone opportunities with the same side when their
   levels are within that signal's tolerance.
3. Rank remaining opportunities by:
   - higher touch count;
   - more specific lifecycle priority:
     `BREAK_RETEST_HOLD`, then `FAILED_BREAK`, then `BREAK_HOLD`, then
     `REJECTION`;
   - newer final used candle index;
   - smaller tolerance;
   - deterministic side order `high`, then `low`;
   - rounded level price.
4. Select at most one opportunity per minute.

This ranking does not use future tick outcomes or later candles.

## One-active simulated execution

Historical replay must preserve the practical execution constraint:

- at most one active simulated pending order or position;
- no new opportunity may be accepted while an order is pending or a position is
  open;
- reaction entries expire after 20 seconds;
- continuation entries expire after 45 seconds;
- invalid tick quotes are ignored;
- ambiguous stop/target ticks are marked `INSUFFICIENT_TICK_EVIDENCE`;
- entries, fills, stop, target, MFE, MAE, and exit reasons are recorded.

The one-active rule is applied to accepted family opportunities, not to every
raw detected opening. A skipped opportunity remains evidence for opportunity
pressure but cannot contribute P/L.

## Historical gate

The candidate can be frozen only if historical replay over the same read-only
5,000-bar fixture satisfies all existing gates:

- profit factor at least `1.15`;
- positive net P/L and expectancy;
- at least two profitable UTC sessions;
- at least 60% retention versus the all-template eligible baseline;
- max loss streak no worse than the all-template baseline;
- max session drawdown no worse than the all-template baseline;
- deterministic repeated output;
- no broker mutation.

If the candidate passes, write a frozen manifest with:

- candidate name;
- source fixture hash;
- candidate report hash;
- ranking version;
- replay configuration;
- historical metrics;
- explicit statement that this authorizes prospective read-only shadow only.

## Prospective boundary

Only a historically passing `OPENING_STATE_FAMILY_V1` may enter prospective
shadow validation.

Prospective shadow must remain read-only and satisfy:

- at least 30 simulated fills;
- at least three distinct future trading sessions;
- profit factor at least `1.10`;
- positive expectancy and net P/L;
- no broker orders or positions placed, modified, or closed.

## Failure behavior

If `OPENING_STATE_FAMILY_V1` fails historical gates, report
`NO_OPENING_STATE_FAMILY_EDGE`. Do not lower retention, profit factor,
expectancy, session, drawdown, DEMO-only, closed-M1-only, no-LLM, or
one-active-trade rules.

## Safety

Implementation must remain broker-free. It may read sanitized fixtures and
ignored read-only MT5 research artifacts. It must not import MT5 execution
classes, send orders, cancel orders, modify positions, or close positions.
