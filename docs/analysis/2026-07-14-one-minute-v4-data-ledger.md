# One Minute V4 Data Ledger

Frozen before either V4 window is fetched or inspected.

## Discovery and fixed-rule walk-forward

- UTC start inclusive: `2026-06-15T00:00:00Z`
- UTC end exclusive: `2026-06-22T00:00:00Z`
- Add 60 closed M1 candles before the start only as causal context.
- Each UTC day is reported as a fixed-rule chronological fold.
- This window has not been used by prior opening-state or selected-trade
  outcome reports.

## Untouched held-out

- UTC start inclusive: `2026-06-22T00:00:00Z`
- UTC end exclusive: `2026-06-29T00:00:00Z`
- Add 60 closed M1 candles before the start only as causal context.
- Do not fetch or inspect unless discovery passes.
- Evaluate once with the unchanged manifest and code hash.

## Prospective

- Start only after an untouched held-out pass.
- Record a new future timestamp and cumulative read-only evidence window.
- Historical backfill cannot count as prospective evidence.

## Post-collection record

The discovery range was collected read-only on `2026-07-14` after this ledger
and the V4 manifest were frozen.

- Fixture: `test-artifacts/post-close-v4/2026-07-14-discovery/discovery-fixture.json`
- Fixture SHA-256:
  `29F806CBFA0EC0E1B048CC0E49BB995B3B11FCA939FDA59DAF004FFD4D8B8675`
- Closed M1 candles: 6,701, including exactly 60 pre-window context bars.
- In-window ticks: 3,871,955.
- Boundary semantics: start inclusive, end exclusive.
- Broker mutation: disabled.

V4 failed discovery. The untouched held-out range was not fetched or
inspected.
