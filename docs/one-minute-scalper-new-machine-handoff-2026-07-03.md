# One Minute Scalper New-Machine Handoff

Date: 2026-07-03

This handoff is for moving the current deterministic One Minute Scalper work to
a different Windows machine. It is intentionally sanitized: do not add account
logins, passwords, API keys, broker server credentials, terminal credential
stores, or populated `.env` values to this document or to git.

## Current objective

Continue validating the frozen deterministic One Minute Scalper variant until it
passes the pre-registered prospective shadow gate:

- historical replay already passed;
- prospective read-only shadow must reach:
  - profit factor `>= 1.10`;
  - positive expectancy;
  - positive net P/L;
  - at least `30` simulated fills;
  - at least `3` distinct UTC-date sessions;
  - max loss streak no worse than baseline;
  - no broker safety failure.

Do not start the MT5 execution runner until the shadow report says
`PASS_PROSPECTIVE_SHADOW`.

## Latest verified runtime state before transfer

Verified at `2026-07-03T12:38:18Z`:

- branch: `main`;
- local `HEAD`: `e4441de979e5a1dc6cbf7e54b366ffdfa34d2e2a`;
- `origin/main`: `e4441de979e5a1dc6cbf7e54b366ffdfa34d2e2a`;
- latest runtime commit before this handoff document:
  `e4441de feat: add opening-state shadow watcher script`;
- working tree: clean;
- old-machine read-only watcher PID: `2208`;
- MT5 execution runner: stopped.

Latest read-only shadow heartbeat on the old machine:

- heartbeat: `2026-07-03T12:24:18.522962+00:00`;
- decision: `COLLECTING_PROSPECTIVE_SHADOW`;
- candidate fills: `54`;
- candidate sessions: `1`;
- profit factor: `1.3713`;
- expectancy: `+0.053`;
- net P/L: `+2.86`;
- gate reason: `FEWER_THAN_3_CANDIDATE_SESSIONS`;
- open orders: `0`;
- open positions: `0`;
- stderr: empty.

Interpretation: the candidate currently satisfies the profit/fill side of the
gate, but it still needs at least two more distinct UTC-date sessions. Do not
retune, weaken the gate, or substitute historical data for prospective shadow
sessions.

## Strategy being tested

Frozen candidate:

`OPENING_STATE_QUEUE_TARGET_GRID_V1`

Core behavior:

- deterministic One Minute Scalper;
- closed M1 candles only;
- no forming candle;
- no LLM BUY/SELL/HOLD, sizing, or exit decisions;
- repeated-level/opening-state structure first;
- candidate-local memory;
- one active simulated candidate/order path;
- target: `0.75R`;
- volume boosting disabled;
- DEMO/account safety preserved;
- no martingale, grid, recovery sizing, revenge trading, or 15m/30m entry logic.

Engulfing candles are only one confirmation type. They do not create a global
bias. The strategy first finds valid structure, then uses the latest closed M1
candle confirmation such as rejection, engulfing, decisive close, or clean
failed break.

## What to copy to the new machine

Safe to copy or zip:

- the repository folder;
- source code;
- tests;
- docs;
- tracked fixtures;
- tracked scripts;
- `.env.example`;
- ignored `test-artifacts/` if you want local continuity of the shadow report
  and heartbeat.

Do not put these into git or public storage:

- `.env` with real values;
- MT5 password;
- account login;
- broker server credential details if private;
- API keys or tokens;
- terminal credential stores;
- raw files containing sensitive account metadata.

If you zip the whole folder manually, understand that `.env` may be included in
your zip even though git ignores it. Treat that zip as sensitive if it contains
`.env` or terminal/account material.

## New-machine setup

1. Install Python and project dependencies:

   ```powershell
   .\scripts\setup-windows.ps1
   ```

2. Create `.env` from the template:

   ```powershell
   Copy-Item .env.example .env
   ```

3. Fill `.env` locally on the new machine. Required names include:

   ```dotenv
   TRADINGAGENTS_MT5_LOGIN=
   TRADINGAGENTS_MT5_PASSWORD=
   TRADINGAGENTS_MT5_SERVER=
   TRADINGAGENTS_MT5_SYMBOL=
   TRADINGAGENTS_MT5_EXPECTED_LOGIN=
   TRADINGAGENTS_MT5_EXPECTED_SERVER=
   TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT=true
   TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS=false
   ```

   Keep actual values out of docs, git, screenshots, and chat.

4. Open/login to the MT5 terminal on the new machine and verify the bridge:

   ```powershell
   .\.venv\Scripts\python.exe -m cli.main broker-probe --json-only
   ```

   Required result:

   ```text
   account_safety.passed = true
   account_safety.trade_mode = DEMO
   open_order_count = 0
   open_position_count = 0
   trade_allowed = true
   tradeapi_disabled = false
   ```

## Resume prospective shadow validation

Start the tracked read-only watcher:

```powershell
.\scripts\start-opening-state-shadow-watch.ps1
```

Default behavior:

- prospective start: `2026-07-03T11:25:00+00:00`;
- session name: `2026-07-03-112500-target-grid-shadow`;
- poll interval: `3600` seconds;
- max cycles: `72`;
- output directory:
  `test-artifacts/opening-state-shadow/2026-07-03-112500-target-grid-shadow`;
- report:
  `test-artifacts/opening-state-shadow/2026-07-03-112500-target-grid-shadow/shadow-report.json`;
- heartbeat:
  `test-artifacts/opening-state-shadow/2026-07-03-112500-target-grid-shadow/shadow-heartbeat.json`.

The watcher only runs:

```powershell
python -m cli.main one-minute-opening-target-grid-shadow-step
```

It does not run `mt5-run`, place orders, modify stops, or close positions. It
stops automatically when the decision becomes `PASS_PROSPECTIVE_SHADOW` or
`FAIL_PROSPECTIVE_SHADOW`.

To stop it manually:

```powershell
New-Item -ItemType File test-artifacts\opening-state-shadow\2026-07-03-112500-target-grid-shadow\shadow-watch.stop
```

## Check progress

Read the latest heartbeat:

```powershell
Get-Content -Raw test-artifacts\opening-state-shadow\2026-07-03-112500-target-grid-shadow\shadow-heartbeat.json
```

Expected while collecting:

```text
decision = COLLECTING_PROSPECTIVE_SHADOW
gate.reasons includes FEWER_THAN_3_CANDIDATE_SESSIONS
```

The goal is not complete until:

```text
decision = PASS_PROSPECTIVE_SHADOW
candidate fills >= 30
candidate sessions >= 3
profit_factor >= 1.10
expectancy > 0
net_profit > 0
open_order_count = 0
open_position_count = 0
```

If the report says `FAIL_PROSPECTIVE_SHADOW`, do not retune the same frozen
prospective window. Document the failure and design a new evidence-supported,
pre-registered hypothesis.

## Verification commands

Run these after restoring the project:

```powershell
git status --short --branch --untracked-files=all
git rev-parse HEAD
git rev-parse origin/main
.\.venv\Scripts\python.exe -m pytest -q
git diff --check
```

Expected verified runtime commit before this handoff document was added:

```text
e4441de979e5a1dc6cbf7e54b366ffdfa34d2e2a
```

If you clone or pull from GitHub after this handoff document is committed,
`origin/main` is expected to be at this commit or a later documentation commit.

If the new machine has additional local changes, inspect them before continuing.
Do not blindly commit generated runtime files or populated secret files.
