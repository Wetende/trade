# One Minute V7 Data Ledger

Frozen before V7 detection or outcome calculation.

## Discovery-only sources

The following previously collected read-only folds may be used for V7
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

Each fold has 60 earlier closed M1 context bars and start-inclusive,
end-exclusive ticks. The fixtures have been examined by prior candidates, so
they may reject V7 but cannot approve it. V7 parameters may not change after
outcomes are calculated.

## Pre-outcome implementation freeze

Recorded after implementation and the full regression suite, but before any
V7 discovery fold was replayed:

- frozen manifest:
  `969A3BAC5CA3EC23137A9BCDA657B4FD66A602AB2786276BF70428E6199C0812`;
- signal detector:
  `78DB048E929403108DD7CB3842AE17D2792582B56599EBEE4B156ED1D5A61C6B`;
- post-close state machine:
  `116015BCBC6F585DCA0D877A5158385984C5C54A6B8E79DBD9016053C5D004BF`;
- replay engine:
  `48AAC67026205D997BB98D49EBD96F44EDFF70BABB36F34E2727D3B2025581EB`;
- evaluation and gates:
  `2F1182A562D93FBF0D93182660DF95A017CAB0D2B0644FAD8BD36D0939881A92`;
- signal tests:
  `65E468CC22C884080010976E0E18D9BF2BE3650A457CE13037C7B2A9E8C53637`;
- replay tests:
  `0610B7C4E7CAA2286332C1CC05D040E1D00DBE73931F1DA2B57DBA5507C6E32F`;
- evaluation tests:
  `CC49621B5B9A576B545AED441DC9D2EE64688A436762FDEBAEC08B696739A7A2`;
- CLI tests:
  `044938AC04984454E8881560488ACCC74D931F72C3331CA816DD63BB3011D702`.

The pre-outcome command `.venv/Scripts/python.exe -m pytest -q` completed with
`1097 passed`, `4 skipped`, and `75 subtests passed`. All three fixture hashes
were rechecked against this ledger immediately before the discovery run.

## Untouched held-out

- Start inclusive: `2026-06-22T00:00:00Z`.
- End exclusive: `2026-06-29T00:00:00Z`.
- Do not fetch, inspect, or derive V7 outcomes unless every discovery gate
  passes.

## Prospective

- Record a new future start only after untouched held-out passes.
- Historical backfill cannot count as prospective evidence.
- Read-only collection only; broker mutation remains disabled.
