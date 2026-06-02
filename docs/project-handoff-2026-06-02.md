# Project Handoff - 2026-06-02

## Repository State

- Remote repository: `https://github.com/Wetende/trade`
- Branch to continue from: `main`
- Local `main` and `origin/main` were aligned at handoff time.
- The historical Dennis remote was preserved locally as `dennis-origin` during transfer, but the active remote for this repo is now Wetende.

## What Was Confirmed

- All tracked repo files were pushed to `Wetende/trade`.
- The `reports/` directory contents currently in git were included in the pushed history.
- The repo can be cloned on another machine and continued from there.
- The CLI now loads local `.env` at runtime, so MT5 commands use the local
  broker configuration without manual environment injection.

## Local Run Log

On this machine, I verified the repo and tried the MT5 connection path:

- `tradingagents broker-probe` was attempted after installing and importing
  `MetaTrader5`.
- `terminal64.exe` was running and MT5 was opened/logged in.
- The probe still failed with `MT5 initialize failed: (-10005, 'IPC timeout')`.
- I did not reach a successful `mt5-run --once` cycle here, because the same
  MT5 bridge failure would block the runner at the same connection step.

The saved evidence in `reports/broker-probe.log` contains the same IPC timeout.
That means the blocking issue is the MT5 desktop bridge on this machine, not the
Python runner logic.

## Recent Progress

Recent commits already in `main` include:

- `96a58ff` `fix: align mt5 pending orders with strategy entries`
- `6da3dbf` `feat: simplify mt5 broker runner`
- `f461ac1` `fix: build order proposals from engine telemetry`
- `3a77a4e` `feat: add configurable time filter mode`
- `083038c` `fix: harden mt5 runner duration limits`

These changes moved the MT5 execution path toward an engine-first model where:

- the deterministic price-action engine is the source of truth for execution,
- order proposals are built from engine payloads,
- the MT5 runner can run in `engine` or `graph` decision mode,
- telemetry and runner summaries prefer structured engine data over misleading text.

## Current Engine-First Status

The planned engine-first wiring is already present in the codebase:

- `tradingagents/agents/price_action/decision.py`
- `tradingagents/agents/execution/order_proposal.py`
- `tradingagents/brokers/runner_summary.py`
- `tradingagents/brokers/mt5_runner.py`
- `cli/main.py`
- `tradingagents/default_config.py`

Verified during handoff:

- Focused regression suite passed: `43 passed`
- Broader safety suite passed: `67 passed, 72 subtests passed`
- A dry engine-mode runner cycle completed without requiring an LLM

## What Is Still Blocking The Next Engine-Mode Demo Run

The main blocker is not missing code wiring.

The current blocker is runtime data freshness and `as_of` alignment:

- a dry engine-mode run produced `NO_TRADE` because data health failed,
- intraday timeframes showed negative candle ages,
- the runner selected an `as_of` that did not line up cleanly with fetched candle timestamps,
- this caused the engine to safely stop at `decision_stage = data_health`.

This means the next meaningful demo task is to fix the clock/candle freshness mismatch so the runner evaluates live candles on a clean timeline.

## Suggested Next Steps

1. On the Windows machine, confirm MT5 Desktop is fully open, logged in, and
   actually attachable by the Python bridge.
2. Re-run `tradingagents broker-probe` first.
3. If the probe passes, run:
   - `tradingagents mt5-run --once --decision-mode engine`
4. Inspect the generated:
   - `mt5_runner/summary.json`
   - `mt5_runner/cycles.jsonl`
   - `engine_telemetry/`
   - `order_proposals/`
5. If the runner still fails, review the MT5 terminal logs and the account/server
   pairing in `.env`.

## Clone Checklist For Another Machine

After cloning, the next machine still needs its own local setup:

- Python environment and dependencies
- `.env` or environment variables
- GitHub authentication
- MT5 terminal/login
- any provider credentials needed for optional LLM/reporting flows

Those local credentials and machine-specific states are not stored in git.
