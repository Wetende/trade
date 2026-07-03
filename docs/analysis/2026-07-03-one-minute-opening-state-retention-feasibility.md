# One Minute Opening-State Retention Feasibility

**Date:** 2026-07-03  
**Runner state:** execution runner stopped; no broker mutation performed.  
**Fixture:** ignored read-only MT5 opening-state fixture.  
**Source fixture hash:** `3decfe31de607678de2a76fd94ae4c5fdc805602caefd1521848a6446dbb047e`

## Purpose

The previous `OPENING_STATE_FAMILY_V1` candidate passed economic quality gates
but failed fill retention:

- baseline fills: `4,946`;
- candidate fills: `1,748`;
- fill retention: `35.34%`;
- profit factor: `3.1798`;
- expectancy: `0.5120`;
- max loss streak: `6`;
- max session drawdown: `5.90`.

This review checks whether the failure is mainly caused by one-active lifecycle
blocking rather than by poor signal economics.

## Queue-only feasibility check

A broker-free queue scheduler was tested as an exploratory feasibility check.
It kept signal-zone deduplication, allowed no more than one active simulated
order or position, and allowed queued opportunities only until their original
reaction or continuation expiry. It did not change stop, target, volume, or
template definitions.

| Variant | Fills | Retention | Net | PF | Expectancy | Max loss streak | Max session drawdown |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Queue, earliest expiry first | 2,230 | 45.09% | 1009.59 | 2.8019 | 0.4527 | 7 | 6.44 |
| Queue, rank first | 2,076 | 41.97% | 1027.90 | 3.1228 | 0.4951 | 7 | 6.37 |
| Queue, oldest signal first | 2,076 | 41.97% | 1027.90 | 3.1228 | 0.4951 | 7 | 6.37 |

Queueing improves retention versus `OPENING_STATE_FAMILY_V1`, but no queue-only
variant reaches the required `60%` retention gate.

## Immediate-placement non-overlap upper bound

A separate hindsight-only check replayed all `8,514` raw opportunities using
the existing `1.5R` target and selected the maximum count of non-overlapping
closed fills. This is not a tradable rule because it uses future outcomes and
ignores losing or expiring orders when selecting intervals.

- independent closed fills: `4,946`;
- hindsight maximum non-overlapping closed fills: `2,224`;
- retention versus baseline: `44.97%`;
- hindsight maximum non-overlapping profit: `1974.97`.

This shows that immediate-placement one-active scheduling under the current
`1.5R` replay cannot reach the `60%` retention gate.

## Decision

Queue-only opening-state scheduling is rejected. Lowering the retention gate is
also rejected.

The evidence-supported next hypothesis is that the active lifecycle is too long
for this M1 opening-state family. A new candidate may test faster deterministic
trade completion, with the same stop, one-active guard, original signal expiry,
DEMO/read-only safety, no volume increase, and no LLM decisions.

The next candidate must be pre-registered before screening and must compare
against an all-template baseline replayed with the same target configuration so
retention remains an apples-to-apples gate.

## Excluded generated artifacts

The raw exploratory scripts and generated JSON outputs remain ignored under
`test-artifacts/opening-state/`. They contain no credentials, but they are
generated research artifacts and are not required to configure a new machine.
The sanitized aggregate metrics above are the tracked reproducible conclusion.
