# One Minute Scalper Current Handoff

Date: 2026-07-13

## Current authority

The active research candidate is the frozen, read-only:

`OPENING_STATE_BUY_CONTINUATION_EXTENDED_V1`

Its manifest is:

`docs/analysis/2026-07-08-one-minute-opening-buy-continuation-shadow-manifest.json`

The old `OPENING_STATE_QUEUE_TARGET_GRID_V1` candidate is retired. Realistic
post-close replay showed that its apparent bar-open edge was not executable.
Do not restart it and do not start a DEMO runner from the July 3 handoff.

## Safety state

- broker mutation: disabled;
- account requirement: DEMO;
- execution runner: stopped;
- shadow watcher: read-only;
- manifest and gate thresholds: frozen;
- no LLM chooses entries, exits, direction, or size.

## Latest cumulative prospective evidence

Official report:

`test-artifacts/opening-state-shadow/2026-07-08-buy-continuation-fresh-shadow/shadow-report.json`

Prospective start:

`2026-07-08T17:22:35.7091920Z`

Checkpoint on 2026-07-13:

| Metric | Value |
| --- | ---: |
| Decision | `COLLECTING_PROSPECTIVE_SHADOW` |
| Sessions | `4` |
| Fills | `25` |
| Wins / losses | `10 / 15` |
| Win rate | `40.00%` |
| Net | `-3.45` |
| Profit factor | `0.6522` |
| Expectancy | `-0.1381` |
| Max loss streak | `4` |
| Open orders / positions | `0 / 0` |

The only current gate reason is `FEWER_THAN_30_CANDIDATE_FILLS`. The gate will
also require win rate `>= 60%`, profit factor `>= 1.10`, positive expectancy,
positive net, at least three sessions, and a loss streak no worse than the
baseline once it becomes evaluable.

At 25 fills and 10 wins, even five consecutive wins would produce only a 50%
win rate at 30 fills. A terminal failure is therefore expected when normal
polling first observes 30 fills. Let the unchanged gate record that result;
do not declare a pass, retune the window, or weaken the thresholds.

## Cumulative evidence repair

The previous watcher requested a fixed 4,320 M1 bars. After more than three
market days, early prospective candles could fall out even though ticks were
still fetched from the fixed start.

The collector now:

- expands the requested M1 history with elapsed time;
- retains pre-start candle context;
- rejects history that does not reach the prospective start;
- records requested, effective, returned, earliest, and latest candle details
  under `evidence_window` in the report;
- keeps the manifest, replay rules, and gate unchanged.

## Resume the read-only watcher

From the repository root:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-opening-state-shadow-watch.ps1 `
  -ProspectiveStart "2026-07-08T17:22:35.7091920Z" `
  -SessionName "2026-07-08-buy-continuation-fresh-shadow" `
  -ManifestPath ".\docs\analysis\2026-07-08-one-minute-opening-buy-continuation-shadow-manifest.json" `
  -CandleCount 4320 `
  -PollSeconds 900 `
  -MaxCycles 192
```

The runtime expands `CandleCount` automatically to preserve the fixed start.
The script stops on `PASS_PROSPECTIVE_SHADOW` or `FAIL_PROSPECTIVE_SHADOW`.

## After the terminal decision

If the expected `FAIL_PROSPECTIVE_SHADOW` is recorded:

1. stop using this candidate and prospective window;
2. write a dated failure review using the final unchanged report;
3. research a genuinely new post-close entry hypothesis on a studied window;
4. freeze the new rule and manifest before collecting new data;
5. start a new read-only prospective shadow from a new timestamp.

Only a future candidate that passes its unchanged prospective gate may advance
to DEMO executor implementation. The current BUY-continuation candidate is
implemented in research/shadow code only and is not DEMO-approved.
