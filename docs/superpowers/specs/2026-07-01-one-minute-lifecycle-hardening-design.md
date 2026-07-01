# One-Minute Lifecycle Hardening Design

## Goal

Correct the five execution and observability defects found during review of the
One Minute Scalper lifecycle changes without changing candidate direction,
trigger detection, or scoring.

## Design

### Closed-Candle Timing

MT5 candle timestamps identify candle open time. Rejection evaluation must
derive candle close time from the configured timeframe and compare that close
time with the broker position's `opened_at_utc`. The local order placement time
is only a fallback when broker position time is unavailable.

This permits the first candle that closes after a fill to invalidate the trade,
while excluding candles that fully closed before the position opened.

### Durable Lifecycle Identity

One-minute `FAST_PARTIAL_SCALE` orders use the broker comment:

```text
TA|M1|FAST
```

Normal orders retain the existing `TradingAgents` comment. Position management
recognizes the M1 lifecycle from either persisted proposal state or the broker
position comment. This preserves safe behavior after a process restart or a
fresh telemetry directory.

### Pre-Submission Lifetime Gate

Compute the pending-order policy immediately before broker order checking and
placement. Reject an M1 order when its effective cancellation deadline leaves
one second or less of usable lifetime. Persist the same policy timestamp after
successful placement.

### Truthful Exit Telemetry

The One Minute Scalper emits `early_loss_exit_points = 0.0`, matching execution
behavior. Normal profiles retain their configured early-loss settings.

### Base-Volume Partial Close

The first partial stage keeps its existing configured target of 1.0 for boosted
1.5-volume positions. When current position volume is already less than or
equal to that target, the first stage instead retains half the current volume.
Thus:

```text
1.5 initial -> 1.0 remaining
1.0 initial -> 0.5 remaining
```

The second partial stage remains unchanged.

## Safety

- Broker SL/TP remain active immediately.
- Closed-candle rejection remains deterministic.
- One active trade remains enforced.
- Demo-account enforcement and the session loss cap remain unchanged.
- Pending expiry stays at 20 seconds for reactions and 45 seconds for impulses.
- No entry-model direction or score logic changes.

## Verification

Tests must prove:

- the first M1 candle closing after position open can trigger rejection exit;
- a candle closed before position open is ignored;
- lifecycle survives missing local state through the broker comment;
- normal comments and normal early-loss behavior remain unchanged;
- an M1 order with one second or less remaining is never sent;
- M1 telemetry reports zero price-only early loss;
- first partial leaves 0.5 from base 1.0 and 1.0 from boosted 1.5;
- the full test suite passes.
