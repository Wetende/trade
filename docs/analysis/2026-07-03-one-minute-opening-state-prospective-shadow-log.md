# One Minute Scalper Opening-State Prospective Shadow Log

Date: 2026-07-03

This log records sanitized prospective shadow-validation checkpoints for the
frozen `OPENING_STATE_QUEUE_TARGET_GRID_V1` candidate. The shadow path is
read-only: it fetches MT5 candles/ticks, evaluates simulated fills, and does not
place, modify, or close broker orders.

## 2026-07-03T11:25:00Z shadow window

- Frozen manifest:
  `docs/analysis/2026-07-03-one-minute-opening-state-target-grid-frozen-manifest.json`
- Command:
  `python -m cli.main one-minute-opening-target-grid-shadow-step --manifest docs/analysis/2026-07-03-one-minute-opening-state-target-grid-frozen-manifest.json --prospective-start 2026-07-03T11:25:00+00:00 --output test-artifacts/opening-state-shadow/2026-07-03-112500-target-grid-shadow/shadow-report.json`
- Broker mutation enabled: `false`
- DEMO/account safety: passed
- Open broker orders: `0`
- Open broker positions: `0`
- stderr: empty after the MT5 structured-tick fix
- Decision: `COLLECTING_PROSPECTIVE_SHADOW`
- Gate status: not evaluable yet
- Gate reasons:
  - `FEWER_THAN_30_CANDIDATE_FILLS`
  - `FEWER_THAN_3_CANDIDATE_SESSIONS`
- Candidate opportunities after start: `10`
- Raw opportunities after start: `11`
- Candidate simulated fills: `6`
- Candidate session count: `1`
- Candidate wins/losses: `3 / 3`
- Candidate net P/L: `-0.30`
- Candidate profit factor: `0.75`
- Candidate expectancy: `-0.05`
- Baseline simulated fills: `6`
- Baseline net P/L: `-0.30`
- Baseline profit factor: `0.75`

Interpretation: this checkpoint is useful for validating the live read-only data
path, but it is not enough evidence to pass or fail the prospective shadow gate.
The pre-registered gate still requires at least 30 candidate fills across at
least 3 sessions, PF >= 1.10, positive expectancy/net P/L, and no worse loss
streak than the simultaneous baseline.

## 2026-07-03T11:38:20Z shadow checkpoint

Same frozen manifest, same prospective start, same read-only command family.

- Broker mutation enabled: `false`
- DEMO/account safety: passed
- Open broker orders: `0`
- Open broker positions: `0`
- stderr: empty
- Decision: `COLLECTING_PROSPECTIVE_SHADOW`
- Gate status: not evaluable yet
- Gate reasons:
  - `FEWER_THAN_30_CANDIDATE_FILLS`
  - `FEWER_THAN_3_CANDIDATE_SESSIONS`
- Candidate opportunities after start: `15`
- Raw opportunities after start: `16`
- Candidate simulated fills: `10`
- Candidate session count: `1`
- Candidate wins/losses: `6 / 4`
- Candidate net P/L: `+0.20`
- Candidate profit factor: `1.125`
- Candidate expectancy: `+0.02`
- Candidate fill retention versus simultaneous baseline: `90.91%`
- Candidate max loss streak: `2`
- Candidate max session drawdown: `1.00`
- Baseline simulated fills: `11`
- Baseline wins/losses: `6 / 5`
- Baseline net P/L: `-0.20`
- Baseline profit factor: `0.90`
- Baseline expectancy: `-0.0182`
- Baseline max loss streak: `2`
- Baseline max session drawdown: `1.10`

Interpretation: the candidate is positive in the early prospective window and
currently no worse than baseline on loss streak or drawdown, but this remains an
immature sample. The candidate must not be promoted until it has at least 30
simulated fills across at least 3 distinct sessions and still satisfies the
pre-registered PF/expectancy/net and risk gates.

## 2026-07-03T11:46:05Z shadow checkpoint

Same frozen manifest and prospective start, using the hardened live shadow
default of `4320` closed M1 candles. This default is the minimum 3-day M1 window
needed to support the pre-registered 3-session prospective gate without relying
on an operator to remember `--candle-count`.

- Broker mutation enabled: `false`
- DEMO/account safety: passed
- Open broker orders: `0`
- Open broker positions: `0`
- stderr: empty
- Decision: `COLLECTING_PROSPECTIVE_SHADOW`
- Gate status: not evaluable yet
- Gate reasons:
  - `FEWER_THAN_30_CANDIDATE_FILLS`
  - `FEWER_THAN_3_CANDIDATE_SESSIONS`
- Candidate opportunities after start: `27`
- Raw opportunities after start: `28`
- Candidate simulated fills: `20`
- Candidate session count: `1`
- Candidate wins/losses: `12 / 8`
- Candidate net P/L: `+0.40`
- Candidate profit factor: `1.125`
- Candidate expectancy: `+0.02`
- Candidate fill retention versus simultaneous baseline: `90.91%`
- Candidate max loss streak: `3`
- Candidate max session drawdown: `1.20`
- Baseline simulated fills: `22`
- Baseline wins/losses: `10 / 12`
- Baseline net P/L: `-1.80`
- Baseline profit factor: `0.625`
- Baseline expectancy: `-0.0818`
- Baseline max loss streak: `3`
- Baseline max session drawdown: `2.10`

Interpretation: the candidate remains positive and no worse than baseline on
loss streak/drawdown, but it still has only one UTC-date session. It cannot pass
the prospective gate until at least two more distinct sessions are collected.

## 2026-07-03T11:55:16Z shadow checkpoint

Same frozen manifest and prospective start, using the `4320` closed-M1 default.
The CLI also wrote the ignored runtime heartbeat file
`test-artifacts/opening-state-shadow/2026-07-03-112500-target-grid-shadow/shadow-heartbeat.json`
beside the shadow report.

- Broker mutation enabled: `false`
- DEMO/account safety: passed
- Open broker orders: `0`
- Open broker positions: `0`
- stderr: empty
- Decision: `COLLECTING_PROSPECTIVE_SHADOW`
- Gate status: not evaluable yet
- Gate reasons:
  - `FEWER_THAN_3_CANDIDATE_SESSIONS`
- Candidate opportunities after start: `42`
- Raw opportunities after start: `43`
- Candidate simulated fills: `31`
- Candidate session count: `1`
- Candidate wins/losses: `20 / 11`
- Candidate net P/L: `+1.60`
- Candidate profit factor: `1.3636`
- Candidate expectancy: `+0.0516`
- Candidate fill retention versus simultaneous baseline: `88.57%`
- Candidate max loss streak: `3`
- Candidate max session drawdown: `1.80`
- Baseline simulated fills: `35`
- Baseline wins/losses: `19 / 16`
- Baseline net P/L: `-0.70`
- Baseline profit factor: `0.8906`
- Baseline expectancy: `-0.02`
- Baseline max loss streak: `3`
- Baseline max session drawdown: `3.10`

Interpretation: the minimum-fill condition is now met and the candidate is
currently above the prospective PF/expectancy/net thresholds. It still cannot
pass the gate because all fills are from a single UTC-date session. The next
required evidence is at least two more distinct sessions without retuning.

## 2026-07-03T12:14:55Z shadow checkpoint

Same frozen manifest and prospective start, using the `4320` closed-M1 default.

- Broker mutation enabled: `false`
- DEMO/account safety: passed
- Open broker orders: `0`
- Open broker positions: `0`
- stderr: empty
- Decision: `COLLECTING_PROSPECTIVE_SHADOW`
- Gate status: not evaluable yet
- Gate reasons:
  - `FEWER_THAN_3_CANDIDATE_SESSIONS`
- Candidate opportunities after start: `71`
- Raw opportunities after start: `72`
- Candidate simulated fills: `49`
- Candidate session count: `1`
- Candidate wins/losses: `32 / 17`
- Candidate net P/L: `+2.76`
- Candidate profit factor: `1.4017`
- Candidate expectancy: `+0.0563`
- Candidate fill retention versus simultaneous baseline: `85.96%`
- Candidate max loss streak: `3`
- Candidate max session drawdown: `1.80`
- Baseline simulated fills: `57`
- Baseline wins/losses: `35 / 22`
- Baseline net P/L: `+1.67`
- Baseline profit factor: `1.1883`
- Baseline expectancy: `+0.0293`
- Baseline max loss streak: `3`
- Baseline max session drawdown: `3.10`

Interpretation: the candidate remains above the prospective PF/expectancy/net
thresholds and no worse than baseline on max loss streak or max session
drawdown. It still cannot pass because all simulated fills are from one
UTC-date session. No retuning is allowed; the next requirement remains two more
distinct sessions.

## 2026-07-03T12:17:52Z shadow checkpoint

Same frozen manifest and prospective start, using the `4320` closed-M1 default.

- Broker mutation enabled: `false`
- DEMO/account safety: passed
- Open broker orders: `0`
- Open broker positions: `0`
- stderr: empty
- Decision: `COLLECTING_PROSPECTIVE_SHADOW`
- Gate status: not evaluable yet
- Gate reasons:
  - `FEWER_THAN_3_CANDIDATE_SESSIONS`
- Candidate opportunities after start: `74`
- Raw opportunities after start: `75`
- Candidate simulated fills: `51`
- Candidate session count: `1`
- Candidate wins/losses: `34 / 17`
- Candidate net P/L: `+3.41`
- Candidate profit factor: `1.4964`
- Candidate expectancy: `+0.0668`
- Candidate fill retention versus simultaneous baseline: `86.44%`
- Candidate max loss streak: `3`
- Candidate max session drawdown: `1.80`
- Baseline simulated fills: `59`
- Baseline wins/losses: `37 / 22`
- Baseline net P/L: `+2.32`
- Baseline profit factor: `1.2616`
- Baseline expectancy: `+0.0393`
- Baseline max loss streak: `3`
- Baseline max session drawdown: `3.10`

Interpretation: candidate PF, expectancy, net P/L, fill retention, and risk
comparisons remain inside the prospective thresholds. The result is still not
evaluable because the sample has only one UTC-date session.

## 2026-07-03T12:20:32Z shadow checkpoint

Same frozen manifest and prospective start, using the `4320` closed-M1 default.

- Broker mutation enabled: `false`
- DEMO/account safety: passed
- Open broker orders: `0`
- Open broker positions: `0`
- stderr: empty
- Decision: `COLLECTING_PROSPECTIVE_SHADOW`
- Gate status: not evaluable yet
- Gate reasons:
  - `FEWER_THAN_3_CANDIDATE_SESSIONS`
- Candidate opportunities after start: `75`
- Raw opportunities after start: `76`
- Candidate simulated fills: `52`
- Candidate session count: `1`
- Candidate wins/losses: `34 / 18`
- Candidate net P/L: `+2.97`
- Candidate profit factor: `1.4063`
- Candidate expectancy: `+0.0571`
- Candidate fill retention versus simultaneous baseline: `86.67%`
- Candidate max loss streak: `3`
- Candidate max session drawdown: `1.80`
- Baseline simulated fills: `60`
- Baseline wins/losses: `37 / 23`
- Baseline net P/L: `+1.88`
- Baseline profit factor: `1.2019`
- Baseline expectancy: `+0.0313`
- Baseline max loss streak: `3`
- Baseline max session drawdown: `3.10`

Interpretation: candidate remains above the PF, expectancy, net P/L, fill
retention, max loss streak, and drawdown requirements, but it is still not
evaluable because all fills are from one UTC-date session.

## Runtime defect fixed during this checkpoint

The first live shadow attempt failed before writing a report because MT5 returned
tick rows as NumPy structured records. The tick normalizer was reading timestamp
fields only from dict-like rows, so it raised `MT5 tick row missing field: time`.

Safety hardening added with the fix:

- `fetch_ticks_range()` now normalizes NumPy structured tick rows through the
  same field-access path used for other MT5 row formats.
- Typer/Rich CLI pretty exceptions no longer show local variables.
- `MT5ConnectionConfig` no longer includes login, password, expected login,
  terminal path, or execution-state path in its dataclass `repr`.

The generated local shadow report remains under ignored `test-artifacts/`.
This tracked log is the portable sanitized evidence.

## Shadow collection tooling hardening

The live shadow command now defaults to `4320` closed M1 candles, equal to three
UTC days of one-minute candles. This supports the gate's minimum of three
distinct daily sessions by default while preserving the existing read-only,
broker-mutation-disabled behavior. Operators may still pass a larger
`--candle-count` if a longer prospective window must be reconstructed.

The same command now writes `shadow-heartbeat.json` beside the ignored runtime
report. The heartbeat is sanitized and contains only the report path, current
decision, gate summary, aggregate metrics, and open broker order/position
counts. It does not include credentials, account login, account server, terminal
paths, raw ticks, or raw candles.
