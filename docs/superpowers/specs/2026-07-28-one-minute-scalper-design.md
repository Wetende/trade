# One Minute Scalper

## Status and scope

`ONE_MINUTE_SCALPER` is the single order-capable M1 research name. It is an
explicitly user-authorized, hash-locked, DEMO-only experiment at fixed volume
0.1. It is not an economically promoted candidate and its completed sessions
remain hypothesis-generation evidence. M15 and M30 behavior is out of scope.

The retired versioned M1 models remain reproducible as historical evidence but
cannot obtain order capability through this lane.

## Causal entry

- Use exactly 60 fully closed M1 candles.
- Detect clean repeated levels with at least two separated touches, a visible
  reaction of 1.5 tolerance units, and an interim excursion of 2.0 tolerance
  units.
- Candle 59 may arm one of the six mirrored families: high/low respect,
  high/low break, or failed high/low break. The arm freezes its level, zone,
  direction, invalidation, timestamp, and family.
- Candle 60 must arrive after the arm and within three minutes. It must retest
  the frozen zone, remain directionally aligned, and close beyond the frozen
  story boundary. Candle 59 already created the classified signal, so candle 60
  is not required to create a second independent rejection, engulfing, or
  strong-close signal. An opposite-direction, late, invalidated, or different
  story is rejected.
- The first fresh bid/ask snapshot after confirmation is used only for
  execution safety. Tick counts are not used, and the system makes no claim of
  true order-flow imbalance because the feed has no depth or traded volume.
- Prefer a continuation stop one tick beyond the confirmation extreme. If its
  structural risk would exceed one price unit, retain the structural stop and
  use a risk-capped pullback entry exactly one unit from that stop only when the
  resulting limit is outside the spread and no farther than the existing
  moved-away allowance. Reject an already crossed, distant, invalidated,
  stale, or malformed quote.
- Rejected stop geometry retains its attempted entry, stop, and risk distance
  in telemetry so the learning ledger can distinguish a near miss from an
  unbounded structure without changing the live rule.

## Geometry and lifecycle

- Structural stop risk: at least the broker minimum and 1.2 current spreads,
  never wider than 1.00 price unit from the effective continuation or pullback
  entry.
- Target: 1.5R.
- Pending expiry: 20 seconds, also bounded by the next M1 candle boundary.
- One arm/order/position lifecycle at a time.
- Fixed volume 0.1; no boost, martingale, grid, straddle, or LLM decision.
- Session risk budget: 20 account-currency units (2R at the one-unit maximum
  stop assumption), reserving broker-calculated proposed stop risk plus a 0.05R
  cost buffer.
- Before pricing that risk, re-establish the MT5 session and retry one transient
  broker-connection failure in-cycle. If both attempts fail, remain fail-closed
  without calling `order_check` or `order_send`, but do not consume the approved
  candle; it may be reconsidered only while the same proposal is still current.
- Two consecutive losses cause a persistent 15-minute cooldown. A fresh
  closed-candle structure is required after cooldown because old proposals are
  expired and duplicate state is durable.
- Each runner session lasts at most three hours. At the deadline it blocks new
  entries, cancels pending orders, manages positions for 120 seconds, closes
  remaining DEMO exposure, and requires repeated fresh flat snapshots before
  terminating.

## Authorization and learning

Before startup, the authorization record hashes the strategy, runner,
execution, state, launcher, supervisor, configuration, tests, design, learning
source registry, and the failed 24-hour quote-pressure report. Startup verifies
every hash, fixed volume, expiry, signal model, pending expiry, cooldown,
DEMO-only account mode, live quote health, and zero initial broker exposure.

Only completed, drained-flat sessions enter the controlled-learning ledger.
Execution, lifecycle, telemetry, data-health, and safety defects may be fixed
between sessions with tests and new hashes. Signal rules are never mutated
during a session or tuned from one failed window, and no automatic promotion is
permitted.

The evidence exporter preserves the legacy research taxonomy without changing
live signals: closed-candle respect families export as `respect`, clean break
families as `impulse_break`, and failed-break families as `fakeout`. Unknown
family/reaction combinations fail closed instead of being silently relabeled.
