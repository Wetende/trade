# Causal Microburst V9 registration retirement

Status: `RETIRED_INVALID_EVIDENCE_WINDOW`

The signal, lifecycle, and tests were frozen before collection. The first
read-only MT5 request returned no M1 candles because the first registered fold
(`2026-07-18T08:38:49.802578Z` through `2026-07-19T12:00:00Z`) fell entirely
inside the weekend market closure. No ticks, trades, outcomes, strategy rows,
or economic metrics were inspected.

V9 is not re-frozen or silently edited. V9.1 retains identical signal and
execution thresholds and changes only the chronological evidence windows to
market-open periods. The original V9 manifest remains preserved at
`docs/analysis/2026-07-22-one-minute-causal-microburst-v9-manifest.json`.
