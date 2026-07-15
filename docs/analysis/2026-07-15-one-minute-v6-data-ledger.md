# One Minute V6 Data Ledger

Frozen before V6 detection or outcome calculation.

## Discovery-only sources

The following previously collected read-only folds may be used for V6
discovery only. They cannot approve trading:

1. `2026-06-01T00:00:00Z` inclusive to `2026-06-08T00:00:00Z` exclusive:
   `test-artifacts/post-close-v5-1/2026-07-15-discovery/week-1-fixture.json`,
   SHA-256
   `B6AAD03E368E47DA5E69D0014DE7E7D83813FBAE35CA9756D61A3D8179F8AFD9`.
2. `2026-06-08T00:00:00Z` inclusive to `2026-06-15T00:00:00Z` exclusive:
   `test-artifacts/post-close-v5-1/2026-07-15-discovery/week-2-fixture.json`,
   SHA-256
   `446B0B16961DEFA78CB78C536A1A33C25BF3437A3910CFC1EA8582D93D2795C8`.
3. `2026-06-15T00:00:00Z` inclusive to `2026-06-22T00:00:00Z` exclusive:
   `test-artifacts/post-close-v4/2026-07-14-discovery/discovery-fixture.json`,
   SHA-256
   `29F806CBFA0EC0E1B048CC0E49BB995B3B11FCA939FDA59DAF004FFD4D8B8675`.

Each fold contains exactly 60 earlier closed M1 context bars and uses
start-inclusive/end-exclusive ticks. V6 parameters may not be changed after
its outcomes are calculated.

## Pre-outcome implementation freeze

Recorded after implementation and the full regression suite, but before any
V6 discovery fold was replayed:

- frozen manifest:
  `959E75947B9088C523F287F4DADA8B39FB8C8E20A23C7AEB0A06A0FE2D472F52`;
- signal detector:
  `3F45533C0D8CC4198564FA8158302710150AD2B42B4BA7F51284031EB434D99D`;
- post-close state machine:
  `4A917C0557ED085A698670D060257B9BCFFD21EE8C760064796719DA086B9D83`;
- replay engine:
  `814F38344399770630460D3E8E99712253A294F6B973FB2A3173091EAF586471`;
- evaluation and gates:
  `54FEAFE3736BBEBEA5B85BFAD6899D52D0F3B31293452CBE6C501390B1C5BC91`;
- signal tests:
  `C11EA4BE2A78601DF8DFC1E5AC504EF66EF3DBA362670CC0020DB91853573B05`;
- replay tests:
  `AACD5A363343C5040400D407BBD448B78C78BD49C00B4D18A95DAD76E862DDC4`;
- evaluation tests:
  `D4331338ADA8DD828FECC611E15DC7EF610B7A5E4B2874DFE5643F3DC41D0802`;
- CLI tests:
  `44EF0A97B5683A0D405638D05AD0296EDE78D98F2A3B9D34468F6819FF8EE3D4`.

The pre-outcome command `.venv/Scripts/python.exe -m pytest -q` completed with
`1080 passed`, `4 skipped`, and `75 subtests passed`. All three fixture hashes
were rechecked against this ledger immediately before the discovery run.

## Untouched held-out

- Start inclusive: `2026-06-22T00:00:00Z`.
- End exclusive: `2026-06-29T00:00:00Z`.
- Do not fetch, inspect, or derive V6 outcomes unless every discovery gate
  passes.

## Prospective

- Record a new future start only after untouched held-out passes.
- Historical backfill cannot count as prospective evidence.
- Read-only collection only; broker mutation remains disabled.
