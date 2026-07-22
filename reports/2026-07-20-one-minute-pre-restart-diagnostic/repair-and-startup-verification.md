# One Minute Scalper repair and startup verification

Checked at: 2026-07-20T09:24:45.4781507+00:00

## Implemented repairs

- Controlled-learning evidence now assigns each broker order to exactly one placing session, deduplicates overlapping history snapshots, selects the timestamp row nearest the owner submission, and fails closed on foreign or unclosed fills.
- MT5 server-time inference now accepts only whole-hour offsets backed by a tick within five minutes and otherwise retains the last verified offset (or zero when none exists).
- M1 pending stops are validated against a fresh quote after `order_check`; a crossed request receives one bounded reprice and a second `order_check`, never a market-order fallback.
- Runner summaries now separate all non-placements, broker rejections, and order-check rejections and persist retcode histograms.

## Verification

- Focused suites: 351 passed.
- Complete repository suite: 1,189 passed, 4 skipped, 75 subtests passed.
- Corrected controlled-learning ledger: 20 sessions, 92 fills, 30 wins, 62 losses, net -2010.5, profit factor 0.2981, expectancy -21.8533, zero unmatched closes.
- Corrected ledger SHA-256: `c50c72bdc4163bcdd0101e36150ddc883a3982389b525c64f52badf078211c2c`.
- The omitted boundary session `2026-07-16-143608-one-minute-experimental-learning-vol01` now owns 6 fills and has zero unmatched closes.

## Broker and startup result

- Account proof: connected, safety passed, `DEMO`.
- XAUUSD.vx proof: trade allowed, API enabled, fresh tick at 2026-07-20T09:24:44.978000+00:00.
- Exposure proof after the startup attempt: zero open orders, zero open positions, zero runner processes.
- The approved launcher was invoked with the frozen V8 manifest and expected 0.01 promotion path. It stopped before process creation because `reports/v8-promotion-0.01.json` does not exist.
- No promotion record can legitimately be generated: frozen V8 was retired after its discovery trigger-feasibility gate failed, and the legacy experimental authorization expired at 2026-07-18T08:38:41.813488+00:00.
- No order was sent or placed during this repair/startup attempt.

The safe runtime state is therefore repaired but blocked from order capability pending a separately named, preregistered candidate that passes frozen evidence gates and produces a valid hash-locked promotion record.
