# One Minute Scalper Evidence Improvements Design

**Date:** 2026-07-02
**Status:** Approved
**Evidence:** `docs/analysis/2026-07-02-one-minute-scalper-forensic-review.md`

## Objective

Improve correctness, replayability, and portability of the deterministic One
Minute Scalper without fitting new entry filters to one 21-trade session.

The implementation must:

1. persist consumed opening state across runner and telemetry restarts;
2. reject only an identical stale opening, while allowing genuinely new
   candidate-local evidence;
3. preserve decision, submission, fill-observation, excursion, and exit
   evidence;
4. reconcile already-closed management races as idempotent outcomes;
5. remove private account identifiers and metadata from console output,
   journal payloads, heartbeat snapshots, and filesystem paths;
6. emit shadow signal-quality measurements without using them as entry gates.

## Non-goals

This change does not:

- ban BUY, SELL, respect, fakeout, or impulse families;
- add a global score threshold;
- add a touch-count cap;
- require pressure or active-pulse alignment;
- impose a time cooldown;
- widen stops;
- weaken one-second management or emergency exits;
- change volume from 1.0;
- enable volume boosting;
- permit more than one active order or position;
- introduce LLM trade decisions;
- add 15m or 30m entry logic.

## 1. Opening identity and durable reset

### Opening context

Every approved M1 candidate and resulting order proposal carries a structured
opening context:

```text
model_name
direction
trigger
reaction_type
confirmation_type
level
level_side
level_type
tolerance
touch_count
first_touch_timestamp
last_touch_timestamp
confirmation_timestamp
```

The context is derived exclusively from the 60 fully closed M1 candles used by
the deterministic engine. The forming candle is never included.

### Same-zone comparison

Two openings refer to the same candidate-local zone only when:

```text
direction matches
level side matches
absolute level difference <= max(previous tolerance, current tolerance)
```

Trigger and reaction type are evidence state, not part of the geometric zone
comparison. A reaction-state change can re-arm a zone.

### Stale duplicate

A new proposal is stale only when all of the following hold:

```text
same candidate-local zone
same trigger
same reaction type
confirmation timestamp is not newer
last-touch timestamp is not newer
touch count has not increased
```

This blocks re-submission of the identical consumed opening after a runner or
results-directory restart.

### Fresh evidence

A same-zone proposal is fresh when at least one deterministic structural fact
changes:

```text
newer closed confirmation candle
newer touch
higher touch count
changed trigger or reaction state
price structure produces a different level outside the prior tolerance zone
```

This implements the written reset rule without adding an elapsed-time
cooldown. It intentionally would not retroactively reject trade 16 solely
because it occurred three minutes after trade 15: trade 16 had a new closed
confirmation and additional touches. Whether that pattern deserves a stricter
future rule remains a shadow-measurement hypothesis.

### Consumption point and persistence

An opening is consumed only after the broker acknowledges a successfully
placed order. Rejected, invalid, drift-blocked, health-blocked, and
account-safety-blocked proposals do not consume it.

Consumption survives:

- pending-order expiration;
- fill and close;
- fresh telemetry directories;
- runner restarts.

The stable execution state keeps a bounded newest-first list of consumed
openings. Active-trade cleanup preserves that list.

## 2. Shadow signal-quality telemetry

The engine records but does not gate on:

```text
confirmation candle body
confirmation candle range
median range of the preceding 12 closed M1 candles
body / recent median range
direction-opposing wick
opposing wick / candle range
entry distance from repeated level
stop distance / decision spread
first and last touch timestamps
touch age in closed bars
approved-candidate rank and count
```

The metrics appear in candidate telemetry, selected-candidate telemetry, order
proposals, durable state, and local execution evidence. No metric changes
candidate approval in this implementation.

## 3. Execution timeline

Each placed order records:

```text
engine decision timestamp and quote
pre-send observation timestamp and quote
broker submission timestamp
broker acknowledgement timestamp
broker entry price and opened timestamp when history becomes available
first position-observation timestamp and quote
broker exit price and closed timestamp
entry drift from proposed entry
order wait duration
```

Quotes contain only:

```text
observed_at_utc
tick_time_utc
bid
ask
spread_price
```

They must never contain terminal paths, account identifiers, user names,
broker credentials, or tokens.

If MT5 cannot provide an exact historical fill-time bid/ask spread, telemetry
must label the first post-fill quote as an observation rather than claiming it
is the exact fill spread.

## 4. Excursion completion

One-second monitoring remains the source of intratrade MFE and MAE. When the
position disappears:

1. active excursion state is archived before active trade state is cleared;
2. broker reconciliation adds the exact final exit-price movement;
3. MFE is the maximum of sampled favorable movement and exit movement;
4. MAE is the minimum of sampled adverse movement and exit movement;
5. the result identifies excursion data as sampled, not tick-perfect.

Completed excursion records are bounded and keyed by the broker position
identifier. Reconciliation attaches them to filled and closed trade summaries.

## 5. Idempotent close-race reconciliation

For intrabar emergency and partial-close requests:

1. send the close request once;
2. if the broker reports success, preserve existing behavior;
3. if it reports an already-gone or invalid-request race, immediately refresh
   open positions;
4. if the target position is absent, record
   `POSITION_CLOSE_RECONCILED` with `POSITION_ALREADY_CLOSED`;
5. do not count that outcome as a management failure;
6. if the position remains open, preserve the existing failure result and
   journal event.

A reconciled partial-close race must not be reported as a successful partial.
It means the whole position had already closed, normally at broker stop or
target.

No automatic retry is added. A retry could duplicate an action when broker
state is delayed.

## 6. Account-metadata safety

### Safe connection representation

Console output, journal events, runner heartbeat files, and state snapshots may
retain only:

```text
connected
account_safety.require_demo
account_safety.trade_mode
account_safety.passed
account_safety.reason
safe symbol and quote metadata
```

They must omit:

```text
account login
expected login
server and expected server
account holder name
broker company
balance and equity
terminal paths and terminal credential metadata
```

Account mismatch errors state that a configured guard failed without printing
actual or expected identifiers.

### Stable state namespace

Account-specific execution state remains isolated, but its directory name is:

```text
account-<first 16 hexadecimal characters of SHA-256(server + NUL + login)>
```

The raw login and server never appear in the path. This is a namespace, not a
password hash or authentication mechanism.

The old raw-identifier runtime directory is deliberately not migrated. Before
the new runner starts, the broker must be DEMO and flat, so creating the new
hashed namespace cannot abandon active broker state.

## 7. Broker probe

`broker-probe` remains read-only. Its output is reduced to the safe connection
representation and DEMO safety result. It must not print or serialize private
account metadata even on a guard mismatch.

## 8. State and compatibility

- Legacy order proposals without opening context remain loadable.
- Non-M1 proposals are unaffected by consumed-opening checks.
- M1 proposals without context are allowed but journal
  `OPENING_FRESHNESS_UNAVAILABLE`; this preserves safe compatibility while
  making the evidence gap visible.
- Existing active-order and active-position fields retain their meaning.
- Active-trade cleanup preserves consumed and completed telemetry records.
- State writes remain atomic through temporary-file replacement.

## 9. Deterministic rejection and event names

New statuses and reasons:

```text
SKIPPED_STALE_OPENING
STALE_CONSUMED_OPENING
OPENING_FRESHNESS_UNAVAILABLE
POSITION_ALREADY_CLOSED
```

New journal events:

```text
OPENING_CONSUMED
OPENING_SKIPPED_STALE
OPENING_FRESHNESS_UNAVAILABLE
ORDER_EXECUTION_TIMELINE
POSITION_FIRST_OBSERVED
POSITION_CLOSE_RECONCILED
POSITION_EXCURSION_ARCHIVED
```

## 10. Required regression coverage

Tests must prove:

- deterministic opening context comes from closed M1 candles;
- candidate ranking is unchanged;
- known winners remain valid;
- an identical consumed opening is skipped after restart;
- a new confirmation, touch, touch count, reaction state, direction, or
  out-of-zone level re-arms the candidate;
- expired orders remain consumed;
- rejected orders do not become consumed;
- non-M1 and legacy proposals remain compatible;
- spread, structural-stop, quote-drift, one-active-trade, and DEMO guards
  remain first-class safety controls;
- decision/send/fill-observation/exit fields are complete and honestly
  labelled;
- final exit movement is incorporated into excursion summaries;
- already-closed partial and emergency races reconcile idempotently;
- true close failures remain failures;
- `broker-probe`, journals, heartbeats, and stable paths do not expose account
  identifiers;
- one-second active management remains enabled;
- full test and replay suites remain deterministic.
