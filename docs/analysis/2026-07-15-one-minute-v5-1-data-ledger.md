# One Minute V5.1 Data Ledger

Frozen before the first two discovery folds are fetched or V5.1 outcomes are
calculated.

## Discovery folds

1. `2026-06-01T00:00:00Z` inclusive to `2026-06-08T00:00:00Z` exclusive.
2. `2026-06-08T00:00:00Z` inclusive to `2026-06-15T00:00:00Z` exclusive.
3. `2026-06-15T00:00:00Z` inclusive to `2026-06-22T00:00:00Z` exclusive.

Each fold includes exactly 60 earlier closed M1 context bars and uses
start-inclusive/end-exclusive ticks. Fold three reuses:

`test-artifacts/post-close-v4/2026-07-14-discovery/discovery-fixture.json`

with SHA-256
`29F806CBFA0EC0E1B048CC0E49BB995B3B11FCA939FDA59DAF004FFD4D8B8675`.

The first two folds are discovery data and may have overlap with old runtime
operations, but have not been fetched or inspected for V5.1 before this
ledger. Discovery cannot approve order-capable DEMO.

## Untouched held-out

- Start inclusive: `2026-06-22T00:00:00Z`.
- End exclusive: `2026-06-29T00:00:00Z`.
- Do not fetch or inspect unless every aggregated discovery gate passes.

## Prospective

- Record a new future start only after held-out passes.
- Historical backfill cannot count as prospective evidence.

## Post-discovery record

Recorded after the frozen three-fold replay completed:

- Week 1 fixture SHA-256:
  `B6AAD03E368E47DA5E69D0014DE7E7D83813FBAE35CA9756D61A3D8179F8AFD9`.
- Week 2 fixture SHA-256:
  `446B0B16961DEFA78CB78C536A1A33C25BF3437A3910CFC1EA8582D93D2795C8`.
- Week 3 fixture SHA-256:
  `29F806CBFA0EC0E1B048CC0E49BB995B3B11FCA939FDA59DAF004FFD4D8B8675`.
- Combined source SHA-256:
  `0383097BB7DCB4AFBD031BBDA78A7F0B24F05B981E66575271A7AF29DEC2351C`.
- Discovery report SHA-256:
  `A22C4EEF33E227C3C5DEEC638656466B297B6F019FAE5FC23A9C590EEC13DBBC`.
- Decision: `FAIL_DISCOVERY_STOP`.

V5.1 lost `-5.229206R` across 17 fills with profit factor `0.319705` and
expectancy `-0.307600R`. This is the final conformant rerun described in
`docs/analysis/2026-07-15-one-minute-v5-1-conformance-correction.md`; the
earlier nonconformant report is superseded. The held-out range was not fetched
or inspected.
