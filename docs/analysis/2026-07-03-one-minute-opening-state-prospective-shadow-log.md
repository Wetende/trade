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
