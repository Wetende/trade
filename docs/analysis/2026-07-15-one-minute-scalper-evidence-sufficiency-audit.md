# One Minute Scalper Evidence Sufficiency Audit

**Date:** 2026-07-15
**Repository state reviewed:** `79f8950`
**Decision:** `NO_VALID_V8_ON_REUSED_DISCOVERY`
**Confidence:** high for the stop decision; no confidence claim is made that a
future candidate will be profitable.

## Question

Can V5/V5.1, V6, V7, or a newly selected V8 be made to pass by another repair,
filter, or replay on the evidence already inspected, while preserving the
authoritative One Minute Scalper rules and frozen gates?

No. Correct implementation defects have been repaired, but the remaining
failure is economic. Selecting another rule after observing the same outcomes
would add an undisclosed trial and would not create independent evidence.

## Sources and integrity

This audit reconciles:

- the authoritative playbook in
  `docs/superpowers/specs/2026-06-15-one-minute-scalper-design.md`;
- the original selected-trade forensic and walk-forward reviews;
- the realistic opening-state shadow review and formal prospective failure;
- every frozen V1 through V7 design, data ledger, manifest, and discovery
  review;
- the saved V4/V5.1 discovery fixture hashes and V6/V7 pre-outcome hashes;
- the V5.1 conformance correction and final conformant rerun; and
- the current read-only DEMO connectivity heartbeat.

The V6 and V7 reviews independently reconciled their source hashes, outcome
counts, economics, execution rates, folds, directions, and safety fields. The
full suite at the V7 freeze passed with `1097 passed`, `4 skipped`, and `75`
subtests. No held-out post-close fixture was fetched.

Primary research supports the methodological stop:

- Bailey and Lopez de Prado explain that uncounted trials inflate backtest
  performance through selection bias and multiple testing:
  https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551
- Novy-Marx shows that combining or choosing among many candidate signals can
  create severe overfitting and multiple-testing bias:
  https://www.nber.org/papers/w21329
- Bailey, Borwein, Lopez de Prado, and Zhu provide a framework for measuring
  the probability of backtest overfitting:
  https://doi.org/10.21314/JCF.2016.322

These papers do not decide whether XAUUSD has an edge. They do establish why
the seventh observed failure cannot be answered by silently trying an eighth
story on the same folds and reporting only a survivor.

## Economic evidence

| Candidate | Market story | Fills | Net R | PF | Expectancy R | Frozen decision |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| V1 | six-family post-close validation | 59 | -24.8962 | 0.2087 | -0.4220 | reject |
| V2 | post-validation retest limit | 105 | -62.8782 | 0.0897 | -0.5988 | reject |
| V3 | retest then reconfirmation stop | 51 | -8.4789 | 0.5792 | -0.1663 | reject |
| V4 | clean-level V3 | 48 | -20.4441 | 0.1419 | -0.4259 | reject |
| V5 | compression expansion/retest | 2 | +0.2506 | 1.5487 | +0.1253 | reject: infeasible sample and symmetry |
| V5.1 | compression hold-stop | 17 | -5.2292 | 0.3197 | -0.3076 | reject |
| V6 | shock reclaim | 4 | -1.6014 | 0.3075 | -0.4004 | reject |
| V7 | impulse/inside pullback | 4 | -1.9513 | 0.1216 | -0.4878 | reject |

The table spans repeated-level respect, confirmed-break, and failed-break
families; retest and reconfirmation entry construction; clean levels;
compression continuation; short-horizon shock reversal; and a compact
pullback continuation. V1 through V4 directly covered all six symmetric
playbook families. V5 through V7 tested materially different, independently
motivated price stories.

The older fixed-grammar selector also evaluated 3,240 one- and two-clause
pre-entry rules with leave-one-session-out selection. No rule met training
eligibility in any fold. This rejects another score, spread, touch, cooldown,
or similarly shallow filter as a repair.

## V5.1 debugging disposition

V5.1 did expose implementation mismatches. They were corrected without
changing its signal, target, stop limit, cost, direction, session, gate, or
data:

1. the nonconforming inherited retest-resume trigger was removed;
2. the frozen 180-second cap was applied after a valid hold trigger; and
3. entries, stops, and targets were snapped direction-safely before final
   geometry checks.

The same three fixtures were rerun after each correction. The final conformant
result was 17 fills, four wins, 13 losses, `-5.229206R`, PF `0.319705`, and
expectancy `-0.307600R`. It failed minimum sample, economics, symmetry,
profitable-session, placement, and geometry gates. Making V5.1 "pass" now
would require changing a frozen economic rule after its outcomes were known,
which the playbook forbids.

## Prospective and DEMO disposition

`OPENING_STATE_BUY_CONTINUATION_EXTENDED_V1` reached its 30th prospective fill
and formally recorded `FAIL_PROSPECTIVE_SHADOW`: 14 wins, 16 losses,
`+0.26`, PF `1.0248`, expectancy `+0.0086`, with frozen failures
`WIN_RATE_BELOW_0_60` and `PROFIT_FACTOR_BELOW_1_10`. It remains rejected even
though the shadow infrastructure operated safely.

At this audit the replacement DEMO connectivity monitor is healthy, connected
to a DEMO account, and reports zero open orders and zero open positions.
`broker_mutation_enabled` is `false`. It is a safety monitor, not a strategy
run. No order-capable DEMO restart is authorized.

## Multiple-testing and chronology finding

The post-close research has now observed V1 through V7 on overlapping studied
evidence. V5.1, V6, and V7 all used the same three weekly folds from
`2026-06-01T00:00:00Z` through `2026-06-22T00:00:00Z`. Those folds may reject
a frozen idea but cannot provide fresh confirmation for a V8 chosen after
their outcomes were seen.

The still-unfetched `2026-06-22T00:00:00Z` through
`2026-06-29T00:00:00Z` range remains sealed. It is chronologically valid only
as the held-out range belonging to the already rejected V1-V7 sequence. It
cannot serve as a later held-out test for a candidate whose discovery window
extends beyond June 29.

## Only valid forward protocol

A later candidate may resume research only when it has a materially new,
independently motivated causal premise that still obeys the playbook. Before
any new outcome report is opened:

1. Write the exact design, manifest, detector, lifecycle, cost model, gates,
   and stop rule.
2. Pass causality, determinism, symmetry, restart, one-active-lifecycle,
   tick-grid, execution, accounting, and zero-mutation tests.
3. Record source, manifest, implementation, and test hashes.
4. Formally retire the old June 22-29 reserve before using it as discovery.

The next clean chronological sequence is:

- discovery folds: June 22-29, June 29-July 6, and July 6-13, all
  start-inclusive/end-exclusive with exactly 60 earlier closed M1 context
  bars;
- untouched held-out: July 13-20, fetched once only after discovery passes;
- fresh prospective: a new timestamp recorded only after held-out passes.

The July 13-20 range is not complete until `2026-07-20T00:00:00Z`. Historical
backfill can never count as prospective evidence.

Any future design must use gates at least as strict as the most recent frozen
protocol unless a stricter preregistered rationale is supplied: discovery
requires at least 30 fills across 10 sessions, positive net, PF at least
`1.15`, expectancy at least `+0.05R` after cost, positive BUY and SELL,
positive symmetric families, at least half of sessions profitable, and at
least two positive weekly folds. Held-out requires at least 15 fills across
five sessions, PF `1.25`, expectancy `+0.10R`, concentration and extra-cost
stress passes. Prospective requires at least 60 fills across 10 sessions, PF
`1.20`, expectancy `+0.08R`, the same symmetry/concentration/cost stress, and
zero safety failures throughout.

## Stop decision

There is no evidence-backed code change that can make V5, V5.1, V6, or V7
pass. There is also no statistically valid V8 approval path on the already
reused discovery outcomes. Continued strategy mutation at this point would be
hypothesis fishing, not debugging.

The profitability goal is therefore not achieved. Work is blocked on an
independently motivated new hypothesis within the authorized playbook and the
later external evidence required by the frozen chronology. The correct
current decision is `NO-GO` for order-capable DEMO; retain only the read-only
connectivity monitor.
