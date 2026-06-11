# 1m History Window Design

## Purpose

The 1m entry model should stop depending on a separate 3m confirmation/history gate. It should read the market directly from recent 1m candles and make fast scalp entries only when the 1m playbook is clear.

The goal is many small trades when conditions fit, while avoiding blind overtrading in unclear or opposing microstructure.

## Scope

This design applies only to the fast 1m directional entry model.

It does not change:

- the normal 15m/30m profile
- straddle behavior
- MT5 broker execution guards
- candle-rejection exit management
- partial close and break-even lifecycle rules

## Core Rule

The 1m model works from the last 60 closed 1m candles.

Within that 60-candle working set:

- nearby levels come from the last 60 candles
- structure is inferred from recent 1m price action inside that same set
- the trigger can use as few as 3 candles when the playbook is clean
- the cleanest recent candle story inside the 60-candle history can trigger the trade
- no fixed 10-candle or 13-candle trigger window is required

The model should not require an external 3m context to approve or reject a 1m entry.

## Playbook Behavior

The 1m model can produce a BUY or SELL when one of these patterns appears inside the 60-candle working set:

- two lows are respected and the latest closed candle confirms BUY pressure
- two highs are respected and the latest closed candle confirms SELL pressure
- repeated lows fail and the latest closed candle confirms SELL continuation
- repeated highs fail and the latest closed candle confirms BUY continuation
- a fresh break is confirmed by a directional candle close and logical stop placement

The latest closed candle is the trigger candle. It must confirm the intended direction with body/close quality, not only touch a level.

## Blocking Rules

The 1m model must HOLD when:

- fewer than enough closed 1m candles are available to evaluate the requested pattern
- the last 60 candles do not provide a clear nearby level or repeated high/low structure
- the latest trigger candle rejects the proposed direction
- the 1m structure is unclear or directly opposes the proposed direction
- stop distance or broker execution guards fail
- there is an active order or position
- account safety or market health gates fail

## Journaling

Telemetry and reports should say `1m History`, not `3m Context`, for this fast model.

Each 1m decision should record:

- history window size, default `60`
- minimum trigger candle count, default `3`
- trigger selection mode, `cleanest_recent_story`
- detected microstructure signal
- setup direction
- rejection reason when skipped
- candle quality metrics for the trigger candle

## Configuration

Initial defaults:

- `fast_history_window_candles = 60`
- `fast_min_trigger_candles = 3`

These can be hardcoded in the first implementation if that matches existing code style, but environment/config support is preferred if low-risk.

## Testing

Add tests for:

- 1m fast model no longer needs a 3m history/context gate
- valid BUY from respected lows inside the last 60 1m candles
- valid SELL from respected highs inside the last 60 1m candles
- failed lows can trigger SELL
- failed highs can trigger BUY
- unclear 1m structure holds
- opposite trigger candle holds
- telemetry records `1m History` and window metadata

## Acceptance Criteria

- Fast 1m entries use the last 60 closed 1m candles as their working history.
- 3m is not required to approve or reject the 1m model.
- Triggers are dynamic and can use the cleanest recent story inside the 60-candle history when the playbook fits.
- The latest closed 1m candle must confirm the entry direction.
- Existing normal 15m/30m behavior remains unchanged.
- Existing MT5 safety and lifecycle management remain unchanged.
- Tests pass before restart.
