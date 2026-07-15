# One Minute Scalper controlled learning runbook

## Purpose

The M1 system keeps a deterministic offline memory of completed DEMO runs and
retired-candidate evidence. It may identify repeatable failure patterns and
generate research hypotheses. It never changes the live strategy, contacts the
broker, creates a promotion record, or authorizes DEMO/REAL order capability.

This is controlled improvement, not online reinforcement learning. A completed
run can change what the research queue investigates; it cannot change what a
running trader does.

## Knowledge-time boundary

Candidate entry rules may use only data that existed at decision time. Fill
latency is a lifecycle diagnostic. MFE, MAE, P/L, and exit reason are outcome
diagnostics. They can explain a failure cluster but cannot become entry-time
features.

The learner records descriptive exclusion results only as hypotheses. Removing
a losing group in the same observed sample is not causal evidence and is never
a promotion pass.

## Source registry and isolation

The explicit M1 source registry is:

`docs/analysis/2026-07-15-one-minute-learning-sources.json`

Every required session summary, cycle journal, retired-candidate report, and
referenced manifest/report hash is recorded in the ledger. These hashes are
quarantined as hypothesis-generation sources. A future candidate must:

1. use a new candidate name;
2. be preregistered and frozen before inspecting new outcomes;
3. start evidence strictly after the ledger cutoff;
4. use no source hash present in the hypothesis ledger;
5. pass the unchanged discovery, held-out, prospective, safety, lifecycle, and
   DEMO-volume promotion gates.

A retired candidate cannot be tuned or revived on its failed window. M15/M30
remain out of scope.

## Update the ledger once

```powershell
.\.venv\Scripts\python.exe -m cli.main one-minute-learn `
  --source-manifest .\docs\analysis\2026-07-15-one-minute-learning-sources.json `
  --output .\runtime\one-minute-learning\ledger.json
```

## Run the continuous offline watcher

```powershell
.\scripts\start-one-minute-learning-watch.ps1 `
  -PollSeconds 300 `
  -MaxCycles 2016
```

The watcher recomputes only the research ledger. It has explicit false
permissions for broker mutation, live-rule mutation, automatic promotion, DEMO
authorization, and REAL authorization. Add a completed session to the source
registry only after broker reconciliation and verified-flat shutdown.

## Current binding lesson

The registered sources contain 54 filled legacy trades: 15 wins, 39 losses,
net `-1963.10`, and profit factor `0.2761`. All six observed trigger groups are
negative. Of 22 losses with sampled MFE, 18 recorded zero MFE; older sessions
have incomplete MFE coverage, and the samples are not tick-complete.

V8 is independently retired: 10,936 detected arms produced zero valid triggers,
placements, or fills. These results support a separately named, causal,
feasibility-first research hypothesis. They do not authorize another legacy
restart, a V8 adjustment, or an order-capable DEMO run.
