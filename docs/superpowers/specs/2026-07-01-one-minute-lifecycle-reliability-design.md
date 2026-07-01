# One-Minute Lifecycle Reliability Design

## Goal

Close the four lifecycle gaps found after the first hardening pass without
changing One Minute Scalper entries, candidate scoring, direction, or volume
selection.

## Broker Acknowledgements

MT5 result `ok` is authoritative. A rejected full close, partial close, or stop
update must:

- remain retryable;
- not advance rejection or partial stage state;
- not move stops as though volume was closed;
- not report a rejected break-even or trailing update as applied;
- journal a management failure;
- return `POSITION_MANAGEMENT_FAILED`.

Only successful broker actions may be recorded as completed exits.

## Stable Execution State

Telemetry remains session-specific. Execution state moves to a stable,
configurable directory:

```text
TRADINGAGENTS_MT5_EXECUTION_STATE_DIR
```

The CLI default is `runtime/mt5_execution_state`, which is gitignored. Fresh
telemetry sessions therefore retain the active proposal, dynamic exit settings,
position identity, and completed partial stages.

The state records both pending-order and active-position tickets. Saved proposal
settings may control a position only when the state ticket matches that broker
position. The `TA|M1|FAST` broker comment remains an additional durable M1
identity signal, but it does not permit stale proposal settings to control an
unrelated position.

When a tracked order is cancelled, disappears without filling, or its tracked
position closes, active trade state is cleared.

## Dynamic Exit Recovery

Position management resolves proposal-specific break-even, partial, trailing,
and scalp settings per broker position. For a tagged M1 position after restart,
the stable state supplies the original proposal values. If no matching state
exists, safe global defaults remain available, but stale proposal overrides are
never applied.

## Broker-Side Pending Expiration

Every M1 request carries the same effective 20/45-second cancellation deadline
as an MT5 `ORDER_TIME_SPECIFIED` expiration. Local cancellation remains as a
second guard. The request is still rejected locally if broker validation leaves
one second or less before expiration.

## Verification

Tests must prove:

- failed partial closes do not move stops or advance stage state;
- failed rejection closes remain retryable;
- fresh telemetry preserves dynamic M1 exit thresholds through stable state;
- stale M1 state cannot manage an unrelated position;
- active-position identity is recorded and later cleared;
- M1 requests carry the effective broker-side expiration;
- normal requests retain their existing expiration behavior;
- the complete test suite passes.
