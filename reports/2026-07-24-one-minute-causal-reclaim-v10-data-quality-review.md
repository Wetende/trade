# V10 Discovery Data-Quality Review

## Decision

The first V10 discovery report is not authoritative because its third fixture
was collected before MT5 finished loading the corresponding M1 candle history.
The corrected-data discovery report is authoritative and independently reaches
the same terminal `FAIL` decision. V10 remains retired without tuning or
promotion.

## Evidence

- Original fold 3 SHA-256:
  `4750cd6d9f1571dbde54891fa891b92c03bc186036663c89f312e108ec7be80b`
- Original fold 3 contained 60 context candles plus only 229 in-window candles.
  Its last candle was `2026-07-24T07:48:00Z`, while its 229,482 ticks continued
  through `2026-07-24T19:59:59.918Z`.
- The identical read-only range was recollected without changing V10. The
  recheck SHA-256 is
  `ad77a13d78aa9f05c89e0fe921cd3ad89de13029a3021ef658b08bf25c341b88`.
- The recheck contains 60 context candles plus all 960 in-window M1 candles and
  the same 229,482 ticks.
- Original report SHA-256:
  `980fc5c417087992c89ff7b2c6201123089e99954265380c85488d82a8a6abfb`.
- Corrected report SHA-256:
  `5a3fc7ecb5e41644a23378168f1719b1428793c92a6566f912fe3cbba2a26915`.

## Corrected terminal result

- Arms: 41 (18 BUY, 23 SELL across mirrored failed-break families)
- Valid triggers / placements / fills: 0 / 0 / 0
- Outcomes: 28 arm expiries, 8 pressure-sample timeouts, and 5 structural
  invalidations
- Safety, lifecycle, restart, lookahead, mutation, reconciliation, entry-drift,
  and telemetry failures: 0

The candidate failed feasibility rather than economic performance: it never
created an executable entry. The held-out window must remain unopened.

## Required pipeline hardening

Future candidate collectors should reject a fixture when ticks cover a minute
for which the supposedly closed M1 candle stream has no matching bar. Recent
MT5 partitions should be retried after a short delay before any terminal screen
is allowed. This is tooling/data-health hardening and must not change a frozen
signal rule.
