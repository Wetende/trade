# One Minute Opening-State Prospective Shadow Design

**Date:** 2026-07-03

## Objective

Collect prospective read-only shadow evidence for the frozen
`OPENING_STATE_QUEUE_TARGET_GRID_V1` candidate.

Historical screening passed on the read-only fixture:

- final frozen target: `0.75R`;
- held-out fills: `3,132`;
- profit factor: `2.3496`;
- expectancy: `0.2016`;
- fill retention: `63.27%`;
- profitable sessions: `5`;
- max loss streak: `5`;
- max session drawdown: `5.66`.

This historical result authorizes prospective read-only shadow only. It does
not authorize broker orders, position changes, or restarting the execution
runner.

## Frozen candidate

Prospective shadow uses the tracked frozen manifest:

`docs/analysis/2026-07-03-one-minute-opening-state-target-grid-frozen-manifest.json`

The frozen runtime parameters are:

- candidate: `OPENING_STATE_QUEUE_TARGET_GRID_V1`;
- final target: `0.75R`;
- target grid version: `1`;
- queue policy version: `1`;
- source fixture hash:
  `3decfe31de607678de2a76fd94ae4c5fdc805602caefd1521848a6446dbb047e`.

No target, queue rule, template, stop, or expiry may change during the
prospective window.

## Safety boundary

The collector must:

- use read-only MT5 calls only;
- require `allow_real_orders == False`;
- require a DEMO account when `require_demo_account` is true;
- exit without mutation if any open order or position exists;
- never import `MT5Executor`, `MT5Runner`, `MT5AutoGateRunner`,
  `MT5StraddleExecutor`, or order request builders;
- never call order placement, order check, cancellation, stop modification, or
  position close methods;
- sanitize output so no account login, server, account name, terminal path,
  credentials, order tickets, position tickets, or raw private metadata are
  written to tracked files.

## Data flow

1. Connect to MT5 using `MT5ConnectionConfig.from_env()` and `MT5Broker`.
2. Read a sanitized startup safety snapshot:
   - account safety result;
   - symbol name, digits, point, spread, tick timestamp;
   - open order count;
   - open position count.
3. Fetch recent fully closed M1 candles only. Never use the forming candle.
4. Fetch read-only ticks from the prospective start timestamp through the
   latest closed candle boundary.
5. Build an `OpeningResearchFixture` with context candles and tick rows.
6. Detect raw and queued opening opportunities.
7. Keep only opportunities with `signal_time >= prospective_start`.
8. Replay:
   - all-template same-target baseline with `risk_reward=0.75`;
   - frozen queued one-active candidate with `risk_reward=0.75`.
9. Write a JSON report atomically to an ignored results directory.

The collector may be run repeatedly over the same prospective start time. Each
run recomputes the aggregate report deterministically from read-only market
data rather than appending duplicate rows.

## Prospective gate

The candidate passes prospective validation only after all are true:

- at least `30` simulated candidate fills;
- fills span at least `3` distinct UTC sessions;
- profit factor at least `1.10`;
- positive expectancy;
- positive net P/L;
- candidate max loss streak no worse than simultaneous same-target baseline;
- broker mutation disabled;
- no open broker orders or positions at collection start;
- no data-health or replay correctness failure.

If the report is not yet evaluable, it must say `COLLECTING_PROSPECTIVE_SHADOW`
and continue later without retuning. If evaluable and failed, it must say
`FAIL_PROSPECTIVE_SHADOW` and the same prospective window must not be retuned.
If evaluable and passed, it must say `PASS_PROSPECTIVE_SHADOW`.

## Outputs

Ignored runtime output:

- `test-artifacts/opening-state-shadow/<session>/shadow-report.json`;
- `test-artifacts/opening-state-shadow/<session>/shadow-heartbeat.json`;
- stdout/stderr logs.

Tracked output only after validation is evaluable:

- sanitized aggregate report under `docs/analysis/`;
- no raw ticks or candles;
- no account identifiers or private terminal metadata.

## Tests

Add deterministic tests for:

- MT5 tick-range normalization is read-only;
- shadow report refuses `allow_real_orders`;
- shadow report exits when open orders or positions exist;
- closed-M1-only fixture construction;
- opportunities before prospective start are excluded;
- frozen target `0.75R` is applied to baseline and candidate;
- collecting/pass/fail gate states;
- CLI writes deterministic JSON and imports no execution modules.
