# One Minute Scalper Evidence Gate Design

**Date:** 2026-07-03

## Objective

Do not place more DEMO orders until a frozen deterministic strategy variant
demonstrates positive expectancy in both historical replay and prospective
shadow execution.

This phase is an evaluation system, not another direct strategy retune. The
current One Minute Scalper remains the baseline. Candidate changes run beside
it without broker mutation so their rejected signals, simulated orders, fills,
management, and outcomes can be compared on identical market data.

## Evidence motivating the gate

The post-change evidence session stopped at its configured session-loss limit:

- 32 closed trades;
- 11 wins and 21 losses;
- `-622.10` net profit;
- `0.497` profit factor;
- `-19.44` expectancy per trade;
- zero broker rejections;
- healthy MT5 data throughout.

The dominant residual loss was `CLEAN_HIGH_IMPULSE_BUY`: 14 trades, three
wins, eleven losses, and `-493.00`. Sixteen of all 21 losses had zero sampled
MFE, showing that selection usually failed before management had profit to
protect. The emergency exit reduced estimated loss relative to the original
structural stops and is not the primary target of this phase.

The existing impulse-quality gates were active. They rejected 57
insufficient-displacement candidates and 14 weak-body candidates, but the
remaining approved population still had negative expectancy. A further direct
production adjustment without prospective evidence would repeat the same
failure mode.

## Considered approaches

### A. Historical screening plus prospective shadow validation

Evaluate small isolated hypotheses over all reproducible sessions, freeze the
best qualifying variant, and collect future simulated fills with real MT5
quotes but no broker orders.

This is selected because it tests whether a change creates edge instead of
merely slowing losses.

### B. Immediately disable bullish impulses

This would remove the largest loss family from the latest session. The
remaining latest-session trades still lost `-129.10`, however, so the change
does not establish positive expectancy. It also risks deleting valid bullish
continuations based on one market regime.

### C. Add a broad cooldown or lower exposure

This would reduce loss velocity, but it does not repair signal selection.
Changing volume would also make P/L look smaller without changing expectancy.
Neither is selected as the primary correction.

## Safety boundary

The broker-facing execution runner remains stopped during evaluation.

The shadow collector must:

- require a DEMO account;
- use read-only MT5 market and account-safety calls;
- refuse to start when configured for live order submission;
- never construct or call order placement, modification, cancellation, partial
  close, or position close paths;
- emit a startup safety record proving that broker mutation is disabled;
- preserve closed-M1-only analysis and never use the forming candle;
- use 1.0 volume only for counterfactual P/L normalization;
- keep volume boosting disabled;
- never use an LLM for BUY, SELL, HOLD, sizing, or exit decisions.

Existing broker orders or positions are not required for shadow evaluation. If
any are found, the collector records the condition and exits without mutation.

## Baseline

The baseline is the current deterministic One Minute Scalper at commit
`3571367`, including:

- candidate-local repeated-level memory;
- same-side level consolidation;
- minimum impulse entry displacement of `0.80`;
- minimum impulse body ratio of `0.50`;
- guarded near-quote pending continuation entries;
- reaction expiry near 20 seconds;
- impulse expiry near 45 seconds;
- existing spread, structural-stop, quote-drift, account, and broker guards;
- one-active-trade semantics;
- one-second position management;
- current partial, break-even, trailing, emergency, and candle-rejection exits.

The baseline is replayed and shadowed unchanged beside every candidate.

## Pre-registered hypotheses

Each hypothesis is evaluated alone before combinations are considered.

### H1: Impulse touch maturity

Require at least three touches for an `impulse_break` candidate. Respect and
fakeout candidates retain the existing two-touch qualification.

Motivation: all five two-touch impulses in the latest session lost, producing
`-254.00`. This is a screening hypothesis, not yet an approved production
rule.

### H2: Impulse exhaustion

Test a direction-symmetric maximum impulse body ratio of `1.20` relative to the
preceding 12 closed M1 candle ranges. The existing minimum remains `0.50`.

Motivation: losing bullish impulses had a median ratio of `1.19`, versus
`0.74` for bullish winners. The rule must remain symmetric during screening;
a BUY-only threshold would be an unsupported session-specific fit.

### H3: Post-loss cluster suppression

After a simulated closed loss, suppress new entries for five fully elapsed
minutes. Continue evaluating and logging candidates during the interval.

Motivation: 13 latest-session trades occurred within five minutes of the prior
trade and produced four wins, nine losses, and `-372.10`. Non-clustered trades
also lost, so this hypothesis cannot qualify merely by reducing trade count.

### Combination rule

Only hypotheses that independently improve expectancy without violating the
sample-retention rule may be combined. Test pairwise combinations before any
three-way combination. Do not search additional thresholds after seeing
prospective shadow results.

## Historical replay

### Evidence set

Use every safely reproducible One Minute Scalper session currently available,
including the 21-trade initial session, the 18-trade first evidence session,
and the 32-trade post-change session. Include placed-but-unfilled orders and
playbook-valid candidate decisions where the recorded quote data supports
deterministic simulation.

Historical data is screening evidence because all current sessions informed
the hypotheses. It is not treated as an untouched holdout.

### Simulation fidelity

For baseline and every variant, replay:

- the same fully closed M1 windows;
- the recorded decision bid, ask, and spread;
- pending order type and expiry;
- quote-drift and structural-stop guards;
- one-active-trade semantics;
- fill or expiration;
- one-second management samples where available;
- the original deterministic exit rules;
- spread and recorded execution costs.

If a required quote or management sample is missing, mark the simulated trade
`INSUFFICIENT_REPLAY_DATA`; do not infer a favorable fill or outcome.

### Historical screening gate

A candidate may advance only if it:

- has positive net expectancy after spread and recorded costs;
- has aggregate profit factor at least `1.15`;
- is profitable in at least two distinct sessions;
- retains at least 60% of baseline simulated fills;
- does not increase maximum loss streak or maximum session drawdown;
- does not introduce a DEMO, closed-M1, one-active-trade, or determinism
  regression.

Passing historical screening does not authorize broker orders.

## Prospective shadow validation

Freeze one candidate before prospective collection. Record its configuration
and source commit in the session manifest. No threshold or rule may change
during the validation window.

Run the unchanged baseline and frozen candidate over identical future market
data. Each produces an independent shadow ledger containing:

- candidate decision and reason codes;
- simulated pending order and expiry;
- simulated fill or non-fill;
- spread and entry drift;
- stop and target;
- MFE and MAE;
- every simulated management action;
- exit reason and realized counterfactual P/L.

Prospective validation ends only after both conditions are met:

- at least 30 simulated fills for the frozen candidate;
- observations span at least three distinct trading sessions.

The candidate passes only if it has:

- positive net expectancy after spread;
- profit factor at least `1.10`;
- positive aggregate net P/L;
- no worse maximum loss streak than the simultaneous baseline;
- no safety or correctness failure;
- complete telemetry for every simulated fill.

If the candidate fails, do not retune against the same prospective window.
Return to design with a new hypothesis and collect a new future window.

## Outputs

Historical replay writes generated results outside tracked source directories.
Track only:

- deterministic sanitized fixtures needed by tests;
- a sanitized aggregate comparison report;
- the frozen candidate manifest without account metadata;
- the final prospective aggregate report.

Never track account identifiers, broker ticket identifiers, credentials,
terminal paths, populated environment values, or raw private execution state.

## Error handling and correctness

- Any unhealthy or stale market-data interval blocks simulation and is counted.
- Any baseline/candidate data mismatch fails the comparison run.
- Any nondeterministic replay result fails the candidate.
- Any attempted broker mutation terminates the shadow collector and fails the
  safety gate.
- Missing evidence remains missing; it is never converted into a synthetic
  winner, loss, fill, or expiration.
- The known broker-time normalization path must be tested at whole-second and
  millisecond precision before order-wait telemetry is used in comparisons.

## Test requirements

Add deterministic tests for:

- baseline parity with the current engine;
- H1 touch qualification;
- H2 lower and upper body boundaries;
- H3 five-minute elapsed-time boundary and reset;
- isolated and pairwise variant evaluation;
- pending fill and expiration simulation;
- one-active-shadow-trade enforcement;
- one-second management parity;
- spread and quote-drift costs;
- missing-data blocking;
- shadow broker-mutation refusal;
- closed-M1-only enforcement;
- repeatable ranking and replay output;
- sanitized report and manifest schemas.

The complete existing suite must continue to pass.

## Deployment decision

No candidate is deployed merely because it outperforms the losing baseline.
Only a candidate satisfying both the historical and prospective gates may be
presented for a separate production-behavior approval.

Until that approval, the broker execution runner remains stopped and broker
state remains untouched.
