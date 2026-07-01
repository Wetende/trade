# One Minute Scalper: New-Chat Handoff

## Start Here

This is the primary context file for the next implementation chat.

The implementation plan is:

```text
docs/superpowers/plans/2026-07-01-one-minute-scalper-signal-reliability.md
```

The original full strategy design remains useful background:

```text
docs/superpowers/specs/2026-06-15-one-minute-scalper-design.md
```

This handoff is authoritative where it clarifies or corrects older documents.
Do not infer the current strategy from old telemetry folders or previous
iterations of the fast model.

## Current Repository State

At handoff time:

```text
branch: main
HEAD: 1f07f42 fix: protect one-minute positions faster
remote: origin/main at the same commit
```

The latest completed change manages active M1 positions every second, uses
spread-aware protection thresholds, supports a confirmed intrabar emergency
exit, and journals MFE/MAE.

The current forward-test session is:

```text
results/2026-07-01-164002-one-minute-active-management
```

The runner was still active when this document was written. The next chat must
inspect broker orders and positions before stopping or restarting it.

Do not commit:

```text
.env
results/
reports/mt5_history_reverse_engineering/
image1.png
```

Never copy MT5 passwords, API keys, or account credentials into documentation,
tests, commits, terminal output, or chat.

## End Goal

Build an isolated deterministic One Minute Scalper that:

```text
reads the last 60 fully closed M1 candles
remembers repeated high and low zones
finds several clean candidate openings
selects the best current opening
executes one trade at a time
protects favorable movement quickly
exits quickly when the candle story rejects the position
journals every candidate, rejection, order, fill, management action, and exit
```

The business target is many small, clean trades and an eventual measured win
rate of at least 60 percent. That target is not a guarantee and must not be
claimed from one short run. Evaluate it only from a meaningful forward-test
sample with spread, slippage, rejected orders, and all losses included.

## Non-Negotiable Safety

```text
No LLM makes live BUY, SELL, HOLD, sizing, or exit decisions.
MT5 execution remains deterministic.
Demo account is required.
One active order or position at a time.
No martingale, grid, recovery sizing, or revenge trading.
Default volume is 1.0.
Volume 1.5 is exceptional, never a loss-recovery mechanism.
Straddle is disabled during this One Minute Scalper phase.
Normal 15m/30m entry is disabled during this focused phase.
```

The expected focused runtime configuration is:

```text
TRADINGAGENTS_TRADING_MODE=ENTRY_ONLY
TRADINGAGENTS_ENTRY_PROFILE_MODE=fast_only
TRADINGAGENTS_FAST_ENTRIES_ENABLED=true
TRADINGAGENTS_FAST_TIMEFRAME=1m
TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME=1m
TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT=true
```

The `FAST_CONFIRMATION_TIMEFRAME=1m` value does not create a second
confirmation model. The One Minute Scalper uses only closed M1 candles.

## Canonical Strategy

### Data

Use the last 60 fully closed one-minute candles.

```text
M1 bar position 0 is forming and must never drive an entry.
Analysis starts from MT5 bar position 1.
The 60 candles are memory, not a fixed directional bias.
The latest fully closed candle is the trigger/confirmation candle.
Triggers may emerge from a recent 2, 3, 5, 10, or longer candle story.
```

The strategy does not use 3m, 15m, or 30m context. Those models must not leak
into this file or its decision path.

### First Question: Where Is the Opening?

The model must not start by asking whether to buy or sell. It asks:

```text
Where are repeated highs?
Where are repeated lows?
Are the touches in one tolerance zone?
Are the touches separated enough to represent a real reaction?
What did the latest closed candle do at or through that zone?
Is invalidation close enough for a scalp?
```

Two touches are valid. A third touch raises priority but is not mandatory.
Tolerance is a price zone derived from recent M1 range, spread, and tick size.
Tiny overlapping highs/lows inside chop are not valid levels.

### Candidate Families

Repeated highs can produce:

```text
HIGH_RESPECT_SELL
HIGH_BREAK_BUY
CLEAN_HIGH_IMPULSE_BUY
FAILED_HIGH_BREAK_SELL
HOLD
```

Repeated lows can produce:

```text
LOW_RESPECT_BUY
LOW_BREAK_SELL
CLEAN_LOW_IMPULSE_SELL
FAILED_LOW_BREAK_BUY
HOLD
```

Raw breaks require a decisive closed candle. Clean impulse breaks are stronger
versions with a strong body and directional close. Wick-only breaks are not
entries.

### Confirmation

Location creates the opening; the candle confirms it.

Accepted confirmation types are:

```text
rejection
engulfing
strong directional close
clean failed break back through the level
```

Engulfing is not a standalone strategy. It matters only at a valid repeated
high/low, failed break, or continuation opening.

Mixed candles, excessive opposite wicks, weak closes, stale signals, and
overlapping chop remain HOLD.

### Direction Changes

The model must be able to sell a valid bearish opening and then buy a fresh
bullish opening when the next closed-candle story confirms that change.

The 60-candle history must not hard-veto a clean current opening merely because
the older net move was bearish or bullish. Long-window pressure may be recorded
and may affect ranking, but the current repeated level plus latest closed
candle determines the actionable direction.

Similarly, memory is a map of openings, not a global conflict switch. An old
high and old low elsewhere in the 60-candle window must not reject a clean
candidate at the current local level.

### Candidate Selection

The analyzer may find many candidates but must select at most one.

Priority should be deterministic:

```text
1. candidate passes data, spread, stop, freshness, and account gates
2. candidate is tied to the latest closed candle and a local repeated level
3. confirmation is clean
4. invalidation is close and structurally correct
5. candidate score is highest
6. if scores tie, prefer the fresher level/reaction
7. if ambiguity remains, HOLD
```

Do not increase trade count by accepting weak candidates. Increase trade count
by removing incorrect vetoes from otherwise valid candidates.

### Entry Semantics

The historical level identifies the opening. The confirmation candle identifies
the entry event.

For respect and failed-break reactions:

```text
enter near the live quote after the confirmation close when risk remains valid
do not automatically wait at the old high/low after price has already confirmed
use a short-lived near-quote continuation pending order through broker guards
reject if the live quote has moved too far from the confirmation close
```

For clean impulse breaks:

```text
enter only while the live quote remains close enough to the confirmation close
use the structural level/wick for invalidation
do not chase an extended quote
```

Entry drift must be measured from the confirmation entry, not blindly from the
historical level. Pending orders must remain short-lived:

```text
reaction pending lifetime: 20 seconds
impulse pending lifetime: 45 seconds
```

These durations are starting values. Do not tune them until order/fill telemetry
shows that expiry, rather than signal quality, is the limiting factor.

### Risk and Volume

Every proposal requires:

```text
entry
stop loss
take profit
risk distance
reward distance
spread status
candidate score
invalidation reason
```

Default volume is `1.0`.

Volume `1.5` is allowed only when all strict high-confidence conditions pass:

```text
clear repeated zone, preferably three touches
clean rejection, engulfing, or failed-break confirmation
strong close in the trade direction
small structural stop
acceptable spread
no chop
no conflicting current local opening
```

The existing environment currently leaves volume boost disabled. Do not enable
it as part of the signal-reliability fix. First prove base-volume behavior.

### Active Management

The latest implemented lifecycle behavior must remain:

```text
manage active positions every second
track MFE and MAE
take partial profit on a genuine move after spread
move the stop to break-even quickly
trail when the move continues
exit on confirmed adverse movement
exit when the next closed candle clearly rejects the position
never open a second trade while one is active
```

Do not use cooldowns or the session loss cap as substitutes for fixing signal
quality. They are safety controls, not entry intelligence.

### Fresh Opening Reset

After trading or expiring a level, do not repeatedly submit the identical stale
opening. A fresh entry requires evidence such as:

```text
price moved away and returned
a new touch formed
a new rejection or engulfing candle closed
a break/fakeout changed the level state
enough new M1 candles formed a new local story
```

## Current Code Map

```text
tradingagents/agents/price_action/one_minute_entry_model.py
    Isolated M1 level memory, candidate construction, scoring, risk, and setup.

tradingagents/agents/price_action/engine.py
    Routes the fast profile to the isolated One Minute Scalper.

tradingagents/dataflows/mt5_price_action.py
    Fetches closed MT5 bars and live symbol/tick metadata.

tradingagents/dataflows/data_health.py
    Computes availability, age, future drift, and blocking timeframes.

tradingagents/brokers/mt5.py
    MT5 connection, closed-bar reads, quote metadata, order and position actions.

tradingagents/brokers/mt5_execution.py
    Proposal execution, one-active-trade guard, stale-order cancellation, and
    one-minute position lifecycle management.

tradingagents/brokers/mt5_runner.py
    Continuous loop, reconciliation, candidate selection, heartbeat, and
    active-trade maintenance cadence.

cli/main.py
    Runtime configuration, profile wiring, MT5 snapshot construction, and runner
    startup.

tradingagents/brokers/runner_summary.py
    Aggregates decisions, health, candidates, broker outcomes, and P/L.

tests/test_one_minute_entry_model.py
tests/test_mt5_broker.py
tests/test_mt5_price_action_dataflow.py
tests/test_price_action_data_health.py
tests/test_mt5_execution.py
tests/test_mt5_runner.py
tests/test_mt5_runner_summary.py
tests/test_cli_mt5_execution.py
    Existing regression coverage that must remain green.
```

## Official MT5 References

Use the official MQL5 Python integration documentation when changing MT5 data
or request semantics:

```text
Python integration index:
https://www.mql5.com/en/docs/python_metatrader5

copy_rates_from_pos (bar position 0 is current/forming):
https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrompos_py

symbol_info_tick:
https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfotick_py

order_check:
https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py

order_send:
https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py

orders_get:
https://www.mql5.com/en/docs/python_metatrader5/mt5ordersget_py

positions_get:
https://www.mql5.com/en/docs/python_metatrader5/mt5positionsget_py

history_deals_get:
https://www.mql5.com/en/docs/python_metatrader5/mt5historydealsget_py
```

## Latest Forward-Test Evidence

At approximately `2026-07-01T21:41Z`, the fresh session showed:

```text
runner process: active
checks: 65
orders placed: 1
orders filled: 0
orders closed: 0
broker rejections: 0
open orders: 0
open positions: 0
```

The one order was:

```text
trigger: HIGH_RESPECT_SELL
order ticket: 95457840
entry: 4034.78
stop: 4035.49
target: 4033.71
result: accepted, unfilled, canceled after about 20 seconds
```

The broker rejected specified expiration, after which the implemented GTC
fallback succeeded. That fallback is expected and was not the trading failure.

## Manual Candle Replay

The MT5 feed labels were approximately 13-14 minutes ahead of the Windows
clock. The times below are broker candle labels.

Replaying the session without the broken data-health block found these notable
openings:

| Broker candle | Candidate | Evidence after close |
| --- | --- | --- |
| 21:03 | CLEAN_LOW_IMPULSE_SELL | Model approved; next candle moved about 4.8 price units favorably. |
| 21:17 | CLEAN_HIGH_IMPULSE_BUY | Repeated-high impulse; next candle offered about 1.25 favorable movement. |
| 21:22 | CLEAN_HIGH_IMPULSE_BUY | Three-touch high break; later continuation reached about 1.9 favorable movement. |
| 21:32-21:34 | HIGH_RESPECT_SELL then CLEAN_LOW_IMPULSE_SELL | Rejection transitioned into a clean bearish continuation. |
| 21:40 | FAILED_HIGH_BREAK_SELL | Next candle offered about 1.16 favorable movement. |
| 21:44 | HIGH_RESPECT_SELL | Next two candles offered about 1.6 favorable movement. |
| 21:50 | CLEAN_HIGH_IMPULSE_BUY | Reached about 1.48 favorable movement before reversing; fast management was essential. |

This is diagnostic replay, not a profitability claim. It demonstrates that
valid playbook-shaped openings existed while the live engine mostly held.

The replay also found an approved `21:45` bearish impulse that was much less
attractive after an extended move. Do not add an exhaustion rule from this
single example. First repair the confirmed blockers, then collect a clean
sample and compare approved-candidate quality.

## Confirmed Problems

### 1. MT5 and Windows Clocks Use Different Effective References

Observed:

```text
Windows UTC: approximately 21:41
MT5 tick UTC: approximately 21:55
latest closed M1 label: approximately 21:53
reported M1 age: -13 minutes
allowed M1 future drift: 3 minutes
```

`data_health.py` therefore marked M1 unhealthy even though the MT5 tick and
closed bars were advancing consistently in the same broker clock domain.

This blocked 41 of the first 65 checks.

Do not solve this by globally allowing arbitrary future candles. MT5 health
must compare MT5 bars to the current MT5 tick timestamp from the same source,
with wall-clock fallback only when broker tick time is unavailable.

### 2. Heartbeat Health Contradicts Engine Health

The engine payload reported:

```text
data_status.healthy = false
blocking_timeframes = ["1m"]
```

The same cycle heartbeat reported:

```text
health_gate.passed = true
```

The runner defaults missing health metadata to success. This hides the actual
reason for HOLD and makes monitoring misleading.

### 3. Memory Conflict Is Too Broad

At the evidence snapshot:

```text
CONFLICTED_ONE_MINUTE_MEMORY: 67 candidate rejections
```

The current global relation can mark a candle as conflicting because it
interacts with unrelated old high and low zones anywhere in 60 candles. That
turns memory into a hard directional veto.

Memory must remain candidate-local. Old remote openings may be journaled but
must not reject a clean current candidate.

### 4. Long-Window Pressure Blocks Valid Direction Changes

The current pressure and active-pulse checks rejected clean bullish openings
after a bearish history and clean bearish openings during transitions.

Examples included broker labels `21:17`, `21:22`, `21:24`, `21:34`, and `21:50`.

The 60-candle net move is context, not authority. It may add or subtract score,
but must not hard-reject a clean local opening confirmed by the latest closed
candle.

### 5. Confirmed Reactions Wait at the Old Level

`LIVE_ENTRY_MOVED_AWAY` rejected several clean reactions because the candle
closed away from the repeated level. That movement is often the confirmation.

The actual accepted order also waited at the historical level and expired
unfilled.

For confirmed respect/fakeout reactions, live drift must be measured from the
confirmation close. The pending entry should be near the current quote and
short-lived, while the stop remains tied to structural invalidation.

### 6. Analysis Broker Is Not Explicitly Shut Down

`cli/main.py::_mt5_runner_engine_analysis_func()` creates and connects an
analysis broker each cycle without a `finally` shutdown. This is not yet proven
to cause missed trades, but it is a confirmed lifecycle defect and should be
fixed while changing the MT5 snapshot path.

## Changes That Are Not Valid Fixes

Do not respond to the current evidence by:

```text
disabling an entire trigger family
raising volume
loosening every score threshold
raising the session loss limit again
adding a loss cooldown and calling the strategy fixed
allowing forming candles
removing spread or stop protection
globally accepting arbitrary future timestamps
adding an LLM decision layer
adding more timeframes to the One Minute Scalper
```

## Required Outcome of the Next Plan

The next implementation must:

```text
use broker tick time for MT5 candle health
make runner health metadata match engine health
keep memory candidate-local
make pressure contextual rather than a global veto
enter confirmed reactions near the live quote without chasing
preserve one-trade-at-a-time and demo-only guards
preserve one-second position management
add deterministic replay regression coverage
run the complete test suite
commit and push main
restart with a fresh telemetry directory
leave the verified runner active
```

## Definition of Success

Engineering success:

```text
No healthy advancing MT5 feed is blocked by wall-clock skew.
No heartbeat says health passed while engine data health failed.
Replay tests recognize the intended clean openings.
Replay tests still reject weak/mixed/chop examples.
One active order or position blocks every new entry.
No forming candle drives a trade.
No broker request bypasses account, spread, stop, or distance guards.
All tests pass.
```

Forward-test success:

```text
Fresh session has healthy candle checks.
Candidate and rejection telemetry is internally consistent.
Orders use the confirmed current opening rather than a stale remote level.
Fills, expirations, partials, break-even moves, and exits are all journaled.
No broker rejection loop appears.
```

Strategy success can be judged only after enough closed trades:

```text
win rate
net P/L after spread
average win
average loss
maximum adverse excursion
maximum favorable excursion captured
missed valid openings
false openings taken
performance by trigger family
```

Use at least 30 closed trades for an early directional review and preferably 50
or more before claiming that the 60 percent target has been reached.
