# One Minute V5 Data Ledger

Frozen before V5 outcomes are calculated.

## Discovery

- Reuse the already saved, already studied read-only fixture from
  `2026-06-15T00:00:00Z` inclusive through `2026-06-22T00:00:00Z` exclusive.
- Fixture:
  `test-artifacts/post-close-v4/2026-07-14-discovery/discovery-fixture.json`.
- Frozen fixture SHA-256:
  `29F806CBFA0EC0E1B048CC0E49BB995B3B11FCA939FDA59DAF004FFD4D8B8675`.
- This window is discovery only and cannot approve V5.

## Untouched held-out

- UTC start inclusive: `2026-06-22T00:00:00Z`.
- UTC end exclusive: `2026-06-29T00:00:00Z`.
- Add exactly 60 prior closed M1 bars as context.
- This range remains unfetched and uninspected.
- Do not fetch it unless V5 passes every frozen discovery gate.

## Prospective

- Start only after an untouched held-out pass.
- Record a new future timestamp before collecting any qualifying ticks.
- Historical backfill cannot count as prospective evidence.

## Post-discovery record

V5 was evaluated once on the frozen discovery fixture and failed because it
produced only two fills across two sessions and was not positive in both
directions. Report SHA-256:
`07411D65C5DA112750C2B2FB39BC34E02F3518BAA6B272E403B0FED4DEA28294`.

The untouched held-out range was not fetched or inspected.
