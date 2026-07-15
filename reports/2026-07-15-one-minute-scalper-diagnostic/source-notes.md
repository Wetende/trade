# One Minute Scalper diagnostic source notes

## Audience and delivery

- Audience: technical.
- Delivery: portable HTML selected only after Data Analytics MCP artifact tools were not available in this Codex Desktop session.
- The report uses the canonical artifact contract and packaged portable builder.

## Required-structure mapping

1. Title: artifact title plus first markdown block.
2. Technical summary: `technical_summary`.
3. Key findings with visual evidence: `latest_run_finding`, `setup_net_chart`, `setup_interpretation`, and `setup_detail_table`.
4. Scope, data, and definitions: `scope_definitions`.
5. Methodology: `methodology`.
6. Limitations, uncertainty, and robustness: `limitations`.
7. Recommended next steps: `next_steps`.
8. Further questions: `further_questions`.

The supervised manual experiment is placed after methodology because it is a separate user-authorized DEMO test, not evidence that the deterministic engine passed.

## Chart contract

- Section: setup-family loss contribution.
- Analytical question: which deterministic setup groups contributed the latest realized loss?
- Takeaway: every filled group was negative; `HIGH_RESPECT_SELL` was the largest contributor.
- Family and type: comparison, horizontal bar.
- Data sufficiency: four comparable setup groups and 11 fills. This is sufficient for a compact categorical comparison but not for a trend or inferential chart.
- Fields: setup label, net P/L, trades, wins, losses, zero-MFE losses.
- Palette: single-root preferred with neutral zero reference; signed labels carry meaning without green/red reliance.
- Final surface: native artifact chart inside the portable HTML report.

## Omitted visuals and caveats

- No time-series chart: 11 irregular trade timestamps do not support a meaningful performance trend.
- No scatter: 11 observations are too sparse, and sampled MFE/MAE are lower bounds.
- Exact setup outcomes are retained in a table for audit lookup.
- The three pooled volume-1 sessions are a descriptive comparison, not one frozen statistical experiment.
