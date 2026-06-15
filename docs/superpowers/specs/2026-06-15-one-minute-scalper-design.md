# One Minute Scalper Design

## Purpose

The One Minute Scalper is an isolated deterministic MT5 demo scalping model. It reads the last 60 fully closed 1-minute candles, detects multiple clean two-high and two-low candidate openings, scores them, selects only the best current valid opening, and executes one trade at a time with fast protection and full journaling.

The model must stop behaving like a single perfect-signal hunter. It should find several possible small openings inside the 60-candle memory, reject noisy openings, and trade only the cleanest current setup.

## Core Philosophy

The model must not begin with:

```text
Should I buy or sell?
```

It must begin with:

```text
Where are the two highs or two lows?
Are those levels clean enough?
Did price respect, reject, break, or fake out the level?
Is this a fresh opening?
Did the latest closed candle confirm the direction?
Is stop/invalidation close?
Can the bot scalp quickly?
Should this be executed, skipped, or only watched?
```

## Scope

This design applies only to the fast one-minute entry model in:

```text
tradingagents/agents/price_action/one_minute_entry_model.py
```

It does not change the normal 15m/30m model, the straddle executor, MT5 account safety, broker order guards, or the one-active-trade execution rule.

## Non-Goals

Do not add:

```text
LLM live trade decisions
martingale or grid recovery
multiple simultaneous trades
volume increases after losses
straddle execution in this phase
15m/30m execution in this phase
AUTO_GATED live execution in this phase
```

## Data Rules

The model uses:

```text
last 60 closed 1m candles
latest candle must be fully closed
no entry from a live/unclosed candle
60 candles are the full memory/context
entry comes from the most recent clean opening
```

Triggers may form from 2, 3, 5, 10, or more candles. There is no fixed trigger-window candle count. The 60-candle set is the memory, and the scoring layer decides whether a recent opening is clean enough to trade.

## Level Detection

The model always looks for two highs or two lows first.

Two highs create a resistance opening. Two lows create a support opening. These are tradable when candle confirmation is clean. The third touch is not required, but it is a higher-priority pressure point.

A valid level must have:

```text
at least two touches in the same price zone
a tolerance zone, not exact-price matching
touches separated by time or price movement
visible reaction from the level
latest closed candle confirming direction
close invalidation
```

The model must avoid treating tiny chop highs/lows as real levels.

Tolerance may use:

```text
recent median 1m candle range
spread
tick size
minimum fixed tolerance
```

## Candidate Types

Each detected opening becomes a candidate first. A candidate records level type, touch count, reaction type, confirmation type, direction, score, risk, volume decision, and approval or rejection reason.

### Two Highs

Two highs in the same price zone can produce:

```text
HIGH_RESPECT_SELL
HIGH_BREAK_BUY
FAILED_HIGH_BREAK_SELL
HOLD
```

`HIGH_RESPECT_SELL` requires price to return to the high zone and reject down with a bearish close, upper-wick rejection, close near candle low, or bearish engulfing near the level.

`HIGH_BREAK_BUY` requires a strong bullish candle close above the high zone, close near candle high, enough body strength, no immediate close back below, and entry not too late.

`FAILED_HIGH_BREAK_SELL` requires price to break above the high zone, fail to hold, and close back below with bearish rejection or bearish engulfing.

If the candle is mixed, overlapping, or unclear, the candidate is held or rejected.

### Two Lows

Two lows in the same price zone can produce:

```text
LOW_RESPECT_BUY
LOW_BREAK_SELL
FAILED_LOW_BREAK_BUY
HOLD
```

`LOW_RESPECT_BUY` requires price to return to the low zone and reject upward with a bullish close, lower-wick rejection, close near candle high, or bullish engulfing near the level.

`LOW_BREAK_SELL` requires a strong bearish candle close below the low zone, close near candle low, enough body strength, no immediate close back above, and entry not too late.

`FAILED_LOW_BREAK_BUY` requires price to break below the low zone, fail to hold, and close back above with bullish rejection or bullish engulfing.

If the candle is mixed, overlapping, or unclear, the candidate is held or rejected.

## Third Touch Rule

The model should still trade valid two-touch setups. It must not force a third touch.

Third touch behavior:

```text
2 touches = valid scalp opening
3 touches = stronger pressure / possible impulse opening
candle confirmation decides direction
```

For a third high touch:

```text
rejection down = higher-confidence sell
strong break above = higher-confidence buy
break above then close back below = high-quality fakeout sell
```

For a third low touch:

```text
rejection up = higher-confidence buy
strong break below = higher-confidence sell
break below then close back above = high-quality fakeout buy
```

## Confirmation Rules

Engulfing is confirmation, not a standalone strategy.

Bullish engulfing for buy requires:

```text
previous candle bearish
latest candle bullish
latest bullish body engulfs previous bearish body
latest candle closes near high
pattern occurs near valid low/support/fakeout/retest area
```

Bearish engulfing for sell requires:

```text
previous candle bullish
latest candle bearish
latest bearish body engulfs previous bullish body
latest candle closes near low
pattern occurs near valid high/resistance/fakeout/retest area
```

Rejection confirmation for buy requires:

```text
bullish close
lower wick rejection
close near candle high
upper wick not too large
candle forms near repeated lows, failed low, or support
```

Rejection confirmation for sell requires:

```text
bearish close
upper wick rejection
close near candle low
lower wick not too large
candle forms near repeated highs, failed high, or resistance
```

Breaks must be confirmed by candle close. Wick-only breaks are not valid entries.

## Candidate Scoring

The model should score candidates before execution.

Positive scoring factors:

```text
two-touch level exists
third touch present
clean rejection wick
engulfing confirmation
strong close in direction
entry close to invalidation
target space available
spread acceptable
not in chop
```

Negative scoring factors:

```text
overlapping chop
alternating candles with no direction
entry far from invalidation
large opposite wick
wide spread
stop too large
two back-to-back losses
stale signal
```

Suggested outcome:

```text
low score = skip
medium score = normal scalp
high score = high-confidence scalp
```

The exact numeric score can be implemented conservatively, but the journal must expose the score inputs and rejection reason.

## Volume Rules

Default volume remains:

```text
1.0
```

High-confidence volume remains:

```text
1.5
```

The model may use 1.5 only when all of these are true:

```text
setup is clean
two-touch or three-touch level is clear
fakeout, engulfing, or strong rejection confirmation is present
candle closes strongly in direction
wick supports direction
stop distance is small
spread is acceptable
market is not choppy
```

The model must not increase volume because it is trying to recover losses or force more trades.

## Execution Rules

The model may detect many candidate openings, but execution remains one trade at a time.

Process:

```text
detect candidates
score candidates
reject noisy or stale candidates
select best current valid candidate
execute one pending order or market-compatible proposal through existing MT5 guards
do not open another trade while an order or position exists
journal the decision
```

Pending 1m entries must expire quickly enough to remain tied to the candle story that created them. A stale 1m signal must not survive long enough to fill under a different market story.

## Trade Management

The strategy is designed for many small trades, so management must be fast.

Required behavior:

```text
partial close at small profit
move to break-even quickly once price moves enough
exit if the next closed candle rejects the trade direction
exit fast if candle story changes
do not wait for full stop if rejection is obvious
pause after two back-to-back losses
```

For BUY:

```text
bearish candle after entry is warning
bearish engulfing against position is stronger warning
strong failure after entry should trigger fast exit
```

For SELL:

```text
bullish candle after entry is warning
bullish engulfing against position is stronger warning
strong failure after entry should trigger fast exit
```

## Reset Rule

After trading a level, the model must not keep taking the same level repeatedly unless a fresh opening forms.

A fresh opening requires one or more of:

```text
price moves away and returns
new two-touch or three-touch structure forms
new rejection candle appears
new engulfing candle appears
new break/fakeout happens
enough new candles build a new mini-story
```

This prevents overtrading one messy zone.

## No-Trade Conditions

The model must skip when:

```text
candles are overlapping
price is inside tight chop
candles alternate bullish/bearish with no direction
no clean two-high or two-low level exists
latest candle does not confirm direction
spread is too wide
stop distance is too large
entry is far from invalidation
target is too close
two losses happen back to back
signal is stale
candle rejects against the trade
active order or active position exists
```

## Telemetry And Journaling

The model must not only return BUY, SELL, or HOLD.

For every candidate, journal:

```text
detected level
level type: two-touch or three-touch
touch count
direction considered
reaction type: respect, break, fakeout, engulfing, rejection
approval or rejection reason
candle confirmation
score inputs
stop distance
spread status
volume decision
freshness status
```

For every executed trade, journal:

```text
trigger name
direction
entry
stop loss
take profit
touch count
confirmation type
volume used
why 1.0 or 1.5 was used
```

For every exit, journal:

```text
partial close
break-even move
rejection exit
fast loss exit
candle story change
full stop loss
trailing exit
```

## Testing Requirements

Add or update tests to prove:

```text
60 closed 1m candles are used as memory
live/unclosed candles are not used
multiple candidates can be detected in one pass
only the best current valid candidate is selected
two-touch high respect can sell
two-touch low respect can buy
two-touch high break can buy
two-touch low break can sell
failed high break can sell
failed low break can buy
third touch increases priority/confidence
chop candidates are rejected
1.5 volume is strict and never used for weak setups
stale 1m entries expire quickly
same-level repeat trades require a fresh opening
one active order or position blocks new entries
candidate telemetry explains approval and rejection
exit telemetry records partial, break-even, rejection, and fast-loss actions
```

## Acceptance Criteria

The phase is complete when:

```text
One Minute Scalper is the explicit model name in docs and telemetry.
The 1m model reads only closed 1m candles.
The 1m model evaluates the last 60 closed 1m candles.
The 1m model creates candidate openings before choosing a trade.
The 1m model can find multiple candidates but select only one best valid candidate.
The 1m model executes one trade at a time through existing MT5 guards.
The 1m model skips chop and unclear candle stories.
The 1m model uses 1.0 by default and 1.5 only for strict high-confidence setups.
The 1m model expires stale entries quickly.
The runner proves fast protection actions in telemetry.
Focused tests pass.
Full test suite passes.
Fresh demo telemetry is collected only after tests pass and user approves restart.
```

## Implementation Boundary

This design should be implemented by improving the existing isolated one-minute model rather than creating another competing fast model.

Primary file:

```text
tradingagents/agents/price_action/one_minute_entry_model.py
```

Likely supporting files:

```text
tradingagents/brokers/mt5_runner.py
tradingagents/brokers/mt5_execution.py
tests/test_one_minute_entry_model.py
tests/test_price_action_engine.py
tests/test_mt5_execution.py
tests/test_mt5_runner.py
```

Do not modify straddle behavior or normal 15m/30m strategy behavior for this phase unless a shared interface must expose One Minute Scalper telemetry cleanly.
