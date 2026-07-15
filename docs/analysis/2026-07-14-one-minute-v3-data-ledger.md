# One Minute V3 Data Ledger

Frozen before V3 replay.

## Discovery

- Existing studied fixture:
  `test-artifacts/opening-state-research/2026-07-08-read-only-realistic-fixture.json`
- Approximate period: July 3 through July 8, 2026.
- Purpose: implementation diagnostics and discovery stop decision only.
- Never eligible for approval.

## Untouched held-out

- Planned UTC range: `2026-06-15T00:00:00Z` through
  `2026-06-29T00:00:00Z` (exclusive end).
- This predates the June 29-July 3 opening-state fixture and the July 1/2
  recorded sessions used by prior selected-trade analysis.
- Do not fetch or inspect this range unless V3 passes its frozen discovery
  stop rule.
- Once collected, record source hash and evaluate exactly once.

## Prospective

- Start timestamp will be recorded only after an untouched held-out pass.
- Must begin after that decision and use a new read-only cumulative window.
- No historical backfill may be counted as prospective evidence.
