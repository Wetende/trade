# MT5 AutoGate Design

## Goal

Build a deterministic MT5 AutoGate that scans both directional profiles and the separate straddle method, then allows exactly one demo MT5 execution path at a time.

The goal is not to add more AI. The goal is:

```text
Method discipline + smarter filters + better risk/lifecycle management.
```

AutoGate must make the existing system stricter, easier to reason about, and easier to review from journals.

## Non-Negotiables

- No LLM decides live trade direction.
- No LLM overrides deterministic strategy output.
- MT5 demo execution is the only broker execution path for this phase.
- Real-money execution is refused by default.
- One active order or position blocks all new entries.
- The fast directional profile is not straddle.
- The straddle method is not directional profile 3.
- No martingale, grid recovery, multi-strategy voting, news-sentiment trading, or AI confidence selector.

## Methods And Profiles

The system has two methods and two directional profiles.

### Method 1: Directional Entry

Directional entry has two independent executable profiles.

`ENTRY_FAST`:

- Entry timeframe: 1m.
- Confirmation timeframe: 3m.
- Governing context: 15m and 30m.
- Purpose: frequent small directional trades.
- It can scan every cycle, but AutoGate must reject it when 15m/30m context clearly blocks the direction.

`ENTRY_NORMAL`:

- Entry timeframe: 15m.
- Confirmation timeframe: 30m.
- Governing context: 1h, 4h, and 1d.
- Purpose: cleaner directional trades with higher-timeframe context.
- It remains an independent execution profile and is not replaced by the fast profile.

### Method 2: Straddle Breakout

`STRADDLE` is a separate non-directional breakout method.

- It detects a clean consolidation box.
- It prepares a `BUY_STOP` above the box and a `SELL_STOP` below the box.
- It cancels or reconciles the opposite leg once one side triggers.
- It uses box quality, spread, cooldown, break-even, trailing, early-loss, and scalp-profit controls.

## Inspiration Mapping

AutoGate borrows deterministic patterns, not secret logic:

- Forex Fury: patience, trading windows, avoid rollover/dead/high-spread markets, one trade at a time.
- Forex Robotron: broker-aware execution, stale-entry rejection, stop-level checks, spread-aware stop validation, break-even, trailing, broker rejection tracking.
- Capitalise.ai: readable config-driven rules, no black-box live decision layer.
- BulkQuant: risk budget, loss-streak pauses, no revenge trading, no continuous re-entry after losses.
- SigmaVue: clear modules with one job each, implemented as deterministic code rather than LLM agents.
- Trendsetter / Infinity Algo: journal every accepted and rejected signal so the bot can be improved from evidence.
- Straddle AI: two-leg breakout structure with stronger box, spread, cooldown, and exit controls.

## Trading Modes

Add a strict trading mode enum:

```python
class TradingMode(str, Enum):
    OFF = "OFF"
    ENTRY_ONLY = "ENTRY_ONLY"
    STRADDLE_ONLY = "STRADDLE_ONLY"
    AUTO_GATED = "AUTO_GATED"
```

Configuration:

```text
TRADINGAGENTS_TRADING_MODE=OFF
TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT=true
```

Missing mode defaults to `OFF`. Invalid mode fails startup clearly. Demo account is required by default.

Mode behavior:

- `OFF`: heartbeat/status only, no analysis, no order placement.
- `ENTRY_ONLY`: run only directional entry selection from `ENTRY_FAST` and `ENTRY_NORMAL`.
- `STRADDLE_ONLY`: run only straddle breakout scanning and management.
- `AUTO_GATED`: run the deterministic controller across `ENTRY_FAST`, `ENTRY_NORMAL`, and `STRADDLE`.

This design intentionally changes the older brief where `AUTO_GATED` was future-only. The current goal is to implement `AUTO_GATED` now, but keep it deterministic and demo-only.

## AutoGate Decision Flow

Every cycle follows the same priority:

```text
1. Connect and inspect account/symbol safety.
   If require_demo_account is true and account is not DEMO:
       refuse broker mutation.

2. Snapshot active orders and positions.
   If any active order or position exists:
       manage lifecycle only.
       do not search for new entries.

3. Reconcile session trade history and risk budget.
   If session loss or cooldown gate blocks trading:
       HOLD.

4. Build directional candidates.
   ENTRY_FAST scans 1m/3m with 15m/30m context.
   ENTRY_NORMAL scans 15m/30m with 1h/4h/1d context.

5. Build straddle candidate only if the active-trade gate passes.
   Straddle must pass box quality, spread, and regime cooldown checks.

6. Apply health and conflict gates.
   Reject stale data, bad spread, duplicate candles, invalid stop geometry,
   broker constraint failures, and directional conflict.

7. Select exactly one method.
```

Selection rules:

```text
If ENTRY_FAST and ENTRY_NORMAL both qualify and agree:
    choose the better executable scalp/entry quality using explicit scoring.

If ENTRY_FAST and ENTRY_NORMAL both qualify but conflict:
    HOLD.

If only ENTRY_FAST qualifies:
    execute ENTRY_FAST only if 15m/30m context permits the direction.

If only ENTRY_NORMAL qualifies:
    execute ENTRY_NORMAL.

If no directional profile qualifies and STRADDLE qualifies:
    execute STRADDLE.

If none qualify:
    HOLD.
```

Scoring must remain simple and deterministic. Initial scoring can prefer:

- valid broker geometry,
- tighter stop distance within configured bounds,
- acceptable spread,
- higher setup grade,
- better available risk/reward,
- fresher closed candle,
- no context conflict.

## Health And Safety Gates

Before any order is sent, AutoGate records and applies:

- active trade check,
- demo account safety,
- account login/server/symbol validation,
- data health,
- spread check,
- session/time filter,
- rollover/dead-market avoidance where already available,
- duplicate candle check,
- session loss or cooldown check,
- broker stop-level check,
- entry-near-quote check,
- stop-distance and spread-multiple check.

Some checks are already implemented in different layers. AutoGate should not duplicate every rule. It should normalize their outcomes into clear gate metadata and prevent execution when a required gate fails.

## Lifecycle Management

Position management stays deterministic:

- break-even movement,
- trailing stop,
- early-loss exit,
- scalp-profit exit,
- stale pending-order cancellation,
- opposite straddle leg reconciliation,
- trade history reconciliation.

Lifecycle management runs before new entries. If a trade is active, AutoGate must not place a new order in another method.

## Journaling And Summary

Every cycle must write enough metadata to explain the decision without reading code:

```json
{
  "trading_mode": "AUTO_GATED",
  "selected_method": "ENTRY_FAST",
  "selected_profile": "fast",
  "mode_decision": "ENTRY_FAST_SELECTED",
  "mode_rejection_reason": null,
  "candidate_methods": {
    "ENTRY_FAST": {"status": "PROPOSED", "reason": null},
    "ENTRY_NORMAL": {"status": "NO_TRADE", "reason": "NO_SETUP"},
    "STRADDLE": {"status": "SKIPPED", "reason": "DIRECTIONAL_CANDIDATE_SELECTED"}
  },
  "health_gate": {
    "passed": true,
    "reasons": []
  },
  "account_safety": {
    "require_demo": true,
    "trade_mode": "DEMO",
    "passed": true
  }
}
```

For holds and skips, the journal must show the selected method as `HOLD` and list rejection reasons per candidate.

Runner summary should continue tracking existing status counts, profile status counts, hold reasons, data health, execution skips, broker rejections, candidate strategy counts, approved candidate strategy counts, filled trades, closed trades, wins, losses, and net profit. It should also expose latest mode decision and method selection.

## Current Code Impact

Expected implementation areas:

- `tradingagents/default_config.py`: add trading mode and demo-account safety config/env overrides.
- `cli/main.py`: load the new settings, reject live graph decisions in MT5 execution, and route/gate commands by mode.
- `tradingagents/brokers/mt5.py`: add strict demo-only broker mutation guard.
- `tradingagents/brokers/mt5_runner.py`: support explicit method/profile selection, AutoGate metadata, and directional candidate conflict rules.
- `tradingagents/brokers/mt5_execution.py`: journal account safety and execution gate metadata.
- `tradingagents/brokers/mt5_straddle.py`: add mode metadata and ensure demo run paths use real MT5 execution when allowed.
- `tradingagents/brokers/runner_summary.py`: aggregate mode and method metadata.
- Tests: add mode, account-safety, AutoGate selection, conflict, and journal coverage while preserving existing behavior where still valid.

## Testing Requirements

Required tests:

- missing trading mode defaults to `OFF`,
- invalid trading mode is rejected,
- `OFF` places no orders,
- `ENTRY_ONLY` never invokes straddle,
- `STRADDLE_ONLY` never invokes directional entry,
- `AUTO_GATED` can select `ENTRY_FAST`,
- `AUTO_GATED` can select `ENTRY_NORMAL`,
- `AUTO_GATED` can select `STRADDLE`,
- `AUTO_GATED` holds on conflicting directional candidates,
- demo-only guard rejects real account mutation,
- demo-only guard allows demo account mutation,
- live MT5 runner rejects graph/LLM decision mode,
- active trade blocks new entries across all methods,
- journal contains trading mode, selected method, selected profile, health gate, and account safety,
- runner summary records latest mode decision,
- straddle execution path uses live demo broker execution when gates pass.

Verification command:

```bash
uv run --group dev pytest
```

## Success Criteria

The work is complete when:

- `AUTO_GATED` is implemented as a deterministic demo-only controller.
- `ENTRY_FAST` scans 1m/3m under 15m/30m context.
- `ENTRY_NORMAL` scans 15m/30m under 1h/4h/1d context.
- `STRADDLE` remains a separate breakout method.
- Exactly one method can place an order per cycle.
- Active trades block new entries in every method.
- Real accounts are refused while demo-only safety is enabled.
- LLM/graph live execution is disabled for MT5 order placement.
- Every cycle explains selected and rejected methods.
- Existing tests and new AutoGate tests pass.
