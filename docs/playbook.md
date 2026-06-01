# Gold AI Rule Plan: Top-Down Price Action

## Core Principle

The bot should not trade because one candle looks good.

It should only trade when:

1. It is the right trading time.
2. A playbook setup appears.
3. Higher timeframes do not block the trade.
4. M30 and M15 agree.
5. There is clean range to target.
6. The candle has closed.
7. Price is not overextended.
8. Wick rules are valid.
9. Risk rules approve the trade.

If any rule fails, the answer is:

```text
NO TRADE
```

## A+ Setup Checklist

Use this checklist to confirm every rule is met before entering a trade.

- [ ] Is it volume time?
- [ ] Is it a playbook setup?
- [ ] Do you have higher-timeframe/lower-timeframe correlation?
- [ ] Do you have a clean range to fill?
- [ ] Has the candle closed?
- [ ] Is it overextended? Is TP already filled? If yes, do not take the trade.
- [ ] Is it the last 15 minutes of a 4H candle? If yes, do not take the trade.
- [ ] Is it 15 minutes before a major session opens? If yes, do not take the trade.
- [ ] Is it a Sunday Asian session? If yes, do not take the trade.
- [ ] Does the confirmation candle have a top and bottom wick?
- [ ] Does the trading candle have a bottom/top wick for stop-loss placement?
- [ ] After placing the limit order, confirm it cannot be activated in the last 5 minutes of the M15 candle.

Once every checklist item passes, the trade can move into trade management.

## System Philosophy

The system exists to remove emotional manual decisions.

Manual trading can lead to:

- Closing winning trades too early because of fear.
- Entering too early before the full setup appears.
- Missing clean setups because the trader is slow or distracted.
- Ignoring rules after a loss or after a strong candle.

The bot should behave like a rule engine:

- Accept small losses when the setup fails.
- Protect capital quickly when the trade moves into profit.
- Let large winning trades develop when market structure supports them.
- Never force a trade outside the playbook.

The system is intended for demo-account testing first, but the rules should be written as production-ready trading logic. Demo mode validates the strategy without risking real money; it should not make the bot sloppy, permissive, or experimental in its trade decisions.

## Broker and Execution Assumptions

The current execution target is a demo account first.

The user is based in Kenya, so U.S.-resident restrictions are not the primary blocker for the broker choice. The broker still must be verified during onboarding and checked against local rules before any real-money use.

The preferred broker path is:

```text
Trading engine -> local trade proposal -> broker adapter -> demo execution -> later live execution
```

The broker layer must be generic. Valetax is only a testing candidate because it supports metals and MetaTrader platforms. It must not become a hard dependency.

The system should support adding other XAUUSD brokers through adapters, especially brokers that provide:

- XAUUSD or broker-specific Gold symbols.
- Demo accounts.
- MT4, MT5, or another automation-friendly platform/API.
- Reliable order placement, order cancellation, and order modification.
- Clear trading specifications for spread, tick size, lot size, stop levels, and server time.

Each broker adapter should translate the same internal trade proposal into that broker's exact order format.

Internal proposal:

```text
symbol
side
entry_price
stop_loss
take_profit
order_type
valid_until
timeframe
reason
```

Broker adapter responsibilities:

- Map internal symbol to broker symbol, such as `XAUUSD`, `XAUUSDm`, or another broker-specific code.
- Convert Gold points/pips using the broker's tick size.
- Validate minimum lot size and order constraints.
- Place limit orders in demo mode.
- Cancel stale limit orders.
- Modify stop-loss for break-even.
- Trail stop-loss behind M15 structure.
- Report fills, cancellations, and errors back to the trading engine.

Before broker integration, confirm:

- Demo account is available.
- XAUUSD or the broker-specific Gold symbol is available.
- MT5 or MT4 is available for automated execution.
- Broker server timezone.
- Gold pip/point size.
- Tick size.
- Contract size.
- Minimum lot size.
- Maximum lot size.
- Typical spread during Asian, London, and New York sessions.
- Stop-level and freeze-level rules.
- Limit order expiration rules.
- Whether the broker supports order modification for break-even and trailing stop logic.

Alpaca is not the target broker for the XAUUSD strategy because the playbook is built around Gold/metal CFD-style trading and MetaTrader-style execution.

## Timeframe Roles

### Daily Chart

The Daily chart is the major bias and danger-zone filter.

It answers:

- Is Gold near a major daily support or resistance zone?
- Is the bigger move bullish, bearish, ranging, or unclear?
- Is price too extended on the daily chart?
- Should buys, sells, both, or no trades be allowed today?

Daily should not create the entry. It only gives permission or blocks the trade.

Daily permission rule:

- Daily may agree, be neutral, or block.
- If Daily clearly blocks the planned direction, the answer is `NO TRADE`.
- If Daily is neutral, the bot can continue only if 4H, 1H, M30, and M15 align.

### 4-Hour Chart

The 4H chart is the main market-structure filter.

It answers:

- Is Gold trending or ranging?
- Where are the important 4H support and resistance zones?
- Has 4H rejected a major level?
- Has 4H broken structure?
- Is price near a major 4H support or resistance area?
- Is the trade happening in the final 15 minutes of a 4H candle?

The 4H chart is context, not the final permission gate. It should help the report describe the bigger structure and danger zones, but the trade approval path is still driven by the M30/M15 checklist.

4H context rule:

- Record whether 4H is bullish, bearish, ranging, unclear, or near a major zone.
- Do not automatically block a valid M30/M15 setup just because 4H does not agree.
- The final 15 minutes of a 4H candle remain blocked for new entries because that is a timing/volatility rule.

### 1-Hour Chart

The 1H chart is an intraday context layer between the bigger structure and execution.

It answers:

- Is intraday momentum bullish, bearish, or unclear?
- Is price approaching a 1H support or resistance zone for context?
- Is there enough room before the next 1H level?
- Would the M30/M15 setup be moving with or against recent intraday momentum?

The 1H chart should be recorded for context and caution, but it should not override a valid M30/M15 setup by itself.

1H context rule:

- Record whether 1H is bullish, bearish, ranging, or unclear.
- Do not automatically block a valid M30/M15 setup just because 1H is unclear or pointing the other way.
- If 1H context is risky, surface it clearly in the report and telemetry.

### 30-Minute Chart

The 30M chart is the setup context filter.

It answers:

- Is Gold bullish, bearish, or unclear?
- Is price near support or resistance?
- Has there been a real breakout?
- Is the move already overextended?
- Is there room to target?
- Is price ranging, breaking out, retesting, or sitting in the middle?

M30 determines the final trading bias. M15 confirms the entry.

### 15-Minute Chart

The 15M chart is the entry and confirmation chart. Actual entries are always confirmed on M15.

It answers:

- Has the setup confirmed?
- Has the candle closed?
- Is there a valid wick for stop-loss?
- Is the entry still fresh?
- Can we place a clean limit order?

## M15/M30 Correlation Rule

A trade is valid only if:

```text
M30 direction = M15 setup direction
```

Examples:

- M30 bullish + M15 buy setup = valid
- M30 bearish + M15 sell setup = valid
- M30 bullish + M15 sell setup = no trade
- M30 unclear + M15 buy/sell setup = no trade

This should be one of the strongest rules in the bot.

Higher-timeframe context rule:

```text
M30 direction must equal M15 setup direction.
Daily, 4H, and 1H are recorded as context.
```

If M30 and M15 do not match, the answer is always `NO TRADE`.

### Current Structure-Aware Context Model

The engine should not decide trade permission from Daily, 4H, or 1H alone. It should classify those timeframes first, then record them as context for the report.

Current structure labels:

- `BULLISH_STRUCTURE`
- `BEARISH_STRUCTURE`
- `RANGE`
- `NEAR_MAJOR_SUPPORT`
- `NEAR_MAJOR_RESISTANCE`
- `BREAK_OF_STRUCTURE_UP`
- `BREAK_OF_STRUCTURE_DOWN`
- `UNCLEAR`

Context behavior:

- Daily may be bullish, bearish, neutral, or near a major zone.
- 4H may be bullish, bearish, neutral, or near a major zone.
- 1H may be bullish, bearish, ranging, or unclear.
- These higher timeframes are recorded in telemetry and reports as context.
- M30 and M15 decide whether the actual playbook setup exists and whether the entry is valid.

This means a 4-hour live run is not the same thing as a 4H-only strategy. During the run, the bot repeatedly asks whether the current M15 setup is valid under the M30/M15 checklist while still recording Daily, 4H, and 1H context.

## Support and Resistance Zone Detection

The bot should use all detected zones for testing and production-readiness. It should not discard zone types too early just because the first version is simpler. Instead, every detected zone should be recorded, scored, and tested so the strategy can be improved with evidence.

Zones should be detected automatically from price action. Manual zone input is not required for the core system. The bot should look at the higher timeframes the same way a trader would: identify where price previously rejected, bounced, broke, retested, or repeatedly respected an area.

The bot should detect support and resistance zones from:

- Daily swing highs and swing lows.
- 4H swing highs and swing lows.
- 1H swing highs and swing lows.
- M30 range highs and range lows.
- Broken levels that may become inverted support/resistance.
- Rejection wick zones.
- Previous range boundaries.

The strongest zones usually come from higher timeframes, repeated reactions, and clean moves away from the level.

Every zone can produce different behavior:

- Price can reject from the zone.
- Price can break through the zone.
- Price can break and retest the zone.
- Price can give both fakeout and rejection behavior before the real move.

The bot should record the zone behavior for backtesting instead of assuming one zone type is always best.

### Zone Scoring

Every zone should receive a score instead of being accepted blindly.

Suggested scoring:

- Daily origin: `+5`
- 4H origin: `+4`
- 1H origin: `+3`
- M30 origin: `+2`
- Each clean reaction from the zone: `+2`
- Recent reaction: `+1`
- Broken and retested level: `+2`
- Clear rejection wick from the zone: `+2`
- Messy fakeouts or repeated unclear closes through the zone: `-2`

The bot can still log and test all zones, but trade approval should prefer higher-scoring zones.

### Zone Tolerance

Support and resistance should be treated as zones, not exact single-price lines.

The recommended tolerance is volatility-based:

```text
zone_tolerance = max(fixed_min_points, ATR(timeframe) * multiplier)
```

Starting multipliers:

- Daily zone width: `0.25` to `0.35 x Daily ATR`
- 4H zone width: `0.20` to `0.30 x 4H ATR`
- 1H zone width: `0.15` to `0.25 x 1H ATR`
- M30/M15 entry tolerance: `0.10` to `0.15 x ATR`

The bot confirms a zone by waiting for price to approach it and form a fully closed M15 confirmation candle with wick rejection. A zone touch alone is not enough.

### Ranging Market

A ranging market means price is moving sideways with roughly equal highs and roughly equal lows inside the same area.

For coding, a range is confirmed when:

- Price has at least two reactions from support.
- Price has at least two reactions from resistance.
- The support reactions cluster inside the same support zone.
- The resistance reactions cluster inside the same resistance zone.
- Most candle closes remain inside the range.
- Price is not making clear higher-high/higher-low or lower-low/lower-high structure.

In a range, the bot should identify:

- Range support.
- Range resistance.
- Middle of range.
- Breakout outside the range.
- Retest of the broken range boundary.

The bot should avoid trading in the middle of the range. When the market is classified as a clear box range, the preferred model is to wait for a decisive breakout from the box, then a valid retest.

## Rule 1: Is It Volume Time?

For Gold, the AI should only scan during high-volume windows.

Recommended sessions:

- Asian session
- London session
- New York session
- London/New York overlap

For the bot, define this as:

- Trade only during approved session windows.
- Ignore low-volume periods.
- Avoid Sunday Asian session.
- On Monday, prefer London and New York session conditions before accepting new trades.
- Block new entries 15 minutes before any approved session opens.
- Exact session hours must be configured from the broker/server timezone.

## Rule 2: Is It a Playbook Setup?

The AI should only trade the exact setups:

1. Breakout
2. Buy/Sell off support or resistance
3. Break and retest
4. Impulse
5. Inverted support/resistance
6. Impulse break and retest

For initial production-ready testing, start with these three because they are easiest to define, code, and backtest cleanly:

1. Break and retest
2. Buy/Sell off support or resistance
3. Breakout

Leave pure impulse entries for later because they can cause chasing.

The core playbook can be grouped into three practical strategy types:

- Support and resistance reversals.
- Break and retest.
- Market-structure continuation.

### Support and Resistance Reversals

Higher timeframes mark the major zones.

The bot should:

- Mark support and resistance from Daily, 4H, and 1H first.
- Wait for price to approach one of those zones.
- Avoid trading just because price touched the zone.
- Require M15 rejection and confirmation before entry.

### Break and Retest

This is used when price breaks out of a range or consolidation.

The bot should:

- Identify the old range boundary.
- Confirm that price has broken the boundary with a closed candle.
- Wait for price to return and retest the broken level.
- Require M15 rejection and confirmation in the breakout direction.

Breakout confirmation:

- One closed candle outside the zone is required for the Breakout model.
- The bot must never use a forming candle to confirm a breakout.
- M15 and M30 must both be fully closed before the setup is evaluated.

Retest validity:

- A small wick through the old zone is allowed.
- The M15 candle must pull back to the broken level and then close in the intended trade direction.
- If the candle closes fully back inside the old zone, the retest is invalid.
- If the close back inside the zone breaks M15/M30 directional agreement, the answer is `NO TRADE`.

### Market-Structure Continuation

This is used when price is trending cleanly.

For a downtrend, the bot tracks:

- Lower lows.
- Lower highs.
- Pullbacks into resistance.

For an uptrend, the bot tracks:

- Higher highs.
- Higher lows.
- Pullbacks into support.

The bot can hold or trail a trade while structure continues. If the market changes character, the bot should protect or exit the position.

## Rule 3: M30 and M15 Correlation

This is the main idea.

### Buy Correlation

A buy setup is valid only if:

- 30M shows bullish context.
- 15M shows bullish confirmation.

Examples:

- 30M broke resistance upward.
- 15M retested the level and closed bullish.
- 30M rejected support.
- 15M formed a bullish confirmation candle.
- 30M created bullish impulse.
- 15M pulled back and continued upward.

### Sell Correlation

A sell setup is valid only if:

- 30M shows bearish context.
- 15M shows bearish confirmation.

Examples:

- 30M broke support downward.
- 15M retested the level and closed bearish.
- 30M rejected resistance.
- 15M formed a bearish confirmation candle.
- 30M created bearish impulse.
- 15M pulled back and continued downward.

## Rule 4: Do You Have a Clean Range to Fill?

This means the trade has enough room before the next major level.

For coding, define it like this:

- There must be at least `1.5R` to the nearest target.
- Ideal range is `2R` or more.

Example:

```text
Entry: 2350
Stop-loss: 2346
Risk: 4 points
Minimum target distance for 2R: 8 points
Target must be at least 2358
```

If the nearest resistance is at `2354`, the trade is not good because the target is too close.

Rule:

- If clean range `< 1.5R` = `NO TRADE`
- If clean range `>= 1.5R` = acceptable
- If clean range `>= 2R` = ideal

Before approving a trade, the bot must calculate:

- Entry price.
- Stop-loss.
- Take-profit.
- Risk distance.
- Reward distance.
- Risk-to-reward ratio.

If the calculated clean range does not offer at least `1.5R`, the trade is rejected.

## Rule 5: Has the Candle Closed?

This should be strict.

The AI should never confirm a setup on a forming candle.

Valid:

- Last closed M15 candle confirms setup.
- Last closed M30 candle supports the same direction.

Invalid:

- Current M15 candle is still forming.
- Current M30 candle is still forming.

Rule:

- Only evaluate after candle close.

For example:

- M15 closes at `10:00`, `10:15`, `10:30`, and `10:45`.
- M30 closes at `10:00` and `10:30`.

The strongest scan times are when both close together:

- `10:00`
- `10:30`
- `11:00`
- `11:30`

At those moments, both M15 and M30 are confirmed.

## Rule 6: Is It Overextended?

The bot must avoid chasing Gold.

A move is overextended if:

- Price has already moved too far from the breakout, retest, support, or resistance level.
- Price is already close to TP.
- The candle is too large compared to recent candles.

Initial measurable rule:

- No trade if the confirmation candle is larger than `1.5x` the average of the last 10 candles.
- No trade if price has already travelled more than `50%` of the clean range.
- No trade if entry is too far from the level.

Example:

```text
Breakout level: 2350
Current price: 2358
Target: 2360
```

That is bad. Most of the move is already gone.

Production-ready testing rule:

- Keep this rule configurable and backtest multiple thresholds.
- Record whether each rejected setup failed because of candle size, target proximity, or distance from the zone.
- Do not loosen this rule live until backtesting proves the change improves results.

## Rule 7: Last 15 Minutes of 4H Candle

Even though the system is based on M15/M30, this time filter can still remain.

The rule means:

- Do not enter during the final 15 minutes before a 4H candle closes.

Why?

- 4H candle closes can cause volatility, fake moves, or reversals.

Rule:

- If current time is within the last 15 minutes of a 4H candle cycle = `NO TRADE`

## Rule 8: 15 Minutes Before Market or Session Open

If it is 15 minutes before a market or session opens, do not take the trade.

The bot should block entries before major session opens.

Rule:

- No new trades 15 minutes before Asian open.
- No new trades 15 minutes before London open.
- No new trades 15 minutes before New York open.

Reason:

- Price often manipulates liquidity before the real session move.

## Rule 9: Sunday Asian Session

This should be an automatic block.

Rule:

- No XAUUSD trades during Sunday Asian session.

Reason:

- Low liquidity, wider spreads, unreliable movement.

## Rule 10: Confirmation Candle Has Top and Bottom Wick

For the checklist, the confirmation candle should not be a wickless candle.

Valid confirmation candle:

- Has a top wick.
- Has a bottom wick.
- Has closed in the trade direction.

For buy:

- Bullish confirmation candle.
- Has top wick and bottom wick.
- Close is above support/retest level.

For sell:

- Bearish confirmation candle.
- Has top wick and bottom wick.
- Close is below resistance/retest level.

This avoids entering on an unstable candle with no proper structure.

## Rule 10A: Wick Rejection Quality

The wick must show that price ran out of strength in the wrong direction.

For a buy rejection:

- Price taps or pierces support/retest zone.
- The candle has a lower wick.
- The lower wick rejects back away from the zone.
- The candle closes bullish, closes above the zone, or is followed by a strong bullish confirmation candle.
- Stop-loss can be placed below the rejection wick.

For a sell rejection:

- Price taps or pierces resistance/retest zone.
- The candle has an upper wick.
- The upper wick rejects back away from the zone.
- The candle closes bearish, closes below the zone, or is followed by a strong bearish confirmation candle.
- Stop-loss can be placed above the rejection wick.

Suggested measurable wick test:

- Wick in the stop-loss direction must exist.
- Wick in the stop-loss direction should be at least `30%` of the full candle range.
- Close should reject away from the zone, preferably beyond the candle midpoint.
- Confirmation candle should close in the intended trade direction.

If there is no wick for stop-loss placement, the answer is always `NO TRADE`.

## Rule 11: Trading Candle Has Wick for Stop-Loss

This is important for limit order and stop-loss placement.

### Buy Rule

For a buy trade:

- The trading/confirmation candle must have a bottom wick.
- Stop-loss goes below the bottom wick.

### Sell Rule

For a sell trade:

- The trading/confirmation candle must have a top wick.
- Stop-loss goes above the top wick.

If there is no wick for stop-loss:

```text
NO TRADE
```

## Rule 12: Limit Order Activation Timing

After placing the limit order, ensure it is not activated in the last 5 minutes of the 15-minute candle.

For the bot:

- If the limit order is not triggered within the first 10 minutes of the M15 candle, cancel it.

Example:

```text
M15 candle opens at 10:00
Limit order can trigger between 10:00 and 10:10
If not triggered by 10:10, cancel
Do not allow activation from 10:10 to 10:15
```

This prevents late entries when the candle is about to close.

## Rule 13: Exact M15 Entry Model

The bot must not enter simply because price reached a line or zone.

The exact entry model requires:

1. Price reaches a valid higher-timeframe zone.
2. Price shows rejection with a wick.
3. M15 closes in the intended trade direction.
4. A strong confirmation candle appears, ideally an engulfing candle.
5. Stop-loss can be placed cleanly beyond the rejection wick.

The M15 confirmation candle must be a strong directional close. This can be:

- A bullish or bearish engulfing candle.
- A very strong directional step candle.
- A candle that clearly closes away from the zone after rejection.

The entry order is a limit order placed at the wick/retest price of the closed candle. The bot should not chase market price after the confirmation candle has already moved too far.

### Sell Entry Model

A sell entry is valid when:

- Price reaches resistance or a retested broken support.
- Price shows rejection with an upper wick.
- M15 closes bearish.
- A bearish engulfing or strong bearish confirmation candle appears.
- Stop-loss can go just above the rejection wick with a spread-adjusted buffer.

If price touches resistance but does not show rejection and bearish confirmation, the answer is `NO TRADE`.

### Buy Entry Model

A buy entry is valid when:

- Price reaches support or a retested broken resistance.
- Price shows rejection with a lower wick.
- M15 closes bullish.
- A bullish engulfing or strong bullish confirmation candle appears.
- Stop-loss can go just below the rejection wick with a spread-adjusted buffer.

If price touches support but does not show rejection and bullish confirmation, the answer is `NO TRADE`.

### Stop-Loss Buffer

The stop-loss should be placed:

- Just below the bottom wick for buys.
- Just above the top wick for sells.

The exact buffer should be configurable. A spread-adjusted buffer such as `1` to `2` Gold points is a practical starting value for bot testing.

## Rule 14: Trade Management

The strategy should protect capital aggressively once a trade is active.

### Gold Pip/Point Conversion

For this playbook, a move from `2350.00` to `2355.00` equals `50` pips.

This means:

```text
1.00 Gold point = 10 pips
5.00 Gold points = 50 pips
```

The bot should use this conversion when applying fixed break-even and trailing thresholds.

### Break Even

When price moves sufficiently into profit, move stop-loss to the entry price.

Configurable break-even options:

- Move to break even after a fixed Gold move, such as `50` to `100` pips/points, depending on broker pricing.
- Optional test mode: move to break even after `1R`.

Primary rule:

- Break even is based on a fixed Gold pip/point move, not only on `1R`.
- The fixed break-even threshold should be configurable and tested, starting around `50` to `100` pips/points depending on broker pricing.

Once stop-loss is at entry, the trade is risk-free except for spread and slippage.

### Risk Approval

Risk approval means the bot must calculate trade structure before accepting the setup.

Before approving a trade, the bot must know:

- Entry price.
- Stop-loss price.
- Take-profit price.
- Risk distance.
- Reward distance.
- Risk-to-reward ratio.

If any of these cannot be calculated, the answer is `NO TRADE`.

Position sizing can be added later. The current core requirement is that no trade is approved without valid SL, TP, and R:R.

### Trailing Stop-Loss

After break even, the bot should trail stop-loss behind market structure.

Trailing should follow M15 structure because M15 is the entry timeframe.

For a sell trade:

- Trail stop-loss above new lower highs.
- Keep holding while price continues making lower lows and lower highs.
- Protect or exit if price breaks the previous lower high.

For a buy trade:

- Trail stop-loss below new higher lows.
- Keep holding while price continues making higher highs and higher lows.
- Protect or exit if price breaks the previous higher low.

### Change of Character Exit

The bot should treat a structure break as a warning.

For a sell:

- If price breaks above the previous lower high, the downtrend may be changing character.

For a buy:

- If price breaks below the previous higher low, the uptrend may be changing character.

When change of character appears, the bot should either:

- Tighten stop-loss.
- Close partials.
- Close the full trade.

The exact action should be configurable and backtested.

### Risk-to-Reward Targets

For production-ready testing, the system should support fixed target modes:

- `1:2`
- `1:3`
- `1:4`
- `1:5`

The preferred high-quality target is `1:3` or `1:4` when the setup is strong and the clean range supports it.

The bot can also be configured to:

- Close automatically at `1:4`.
- Take partial profit at an earlier target and trail the rest.
- Hold while market structure continues.

## Rule 15: Automation and Backtesting Discipline

The bot should execute the rule system exactly, without emotion.

Automation goals:

- Monitor M15 continuously during approved trading windows.
- Detect and record all higher-timeframe zones before price reaches them.
- Score all zones so backtesting can prove which zone types are strongest.
- Wait patiently for the exact M15 entry model.
- Place only valid limit orders.
- Cancel stale orders according to the activation timing rule.
- Move stop-loss to break even when the rule is met.
- Trail stop-loss according to market structure.

The system is tested on demo accounts first, but the implementation should be production-ready. Before any real-money use, the full rule set must be backtested against historical data and forward-tested on demo.

Backtesting should measure:

- Win rate.
- Average win.
- Average loss.
- Maximum drawdown.
- Best and worst session windows.
- Best and worst playbook setups.
- Best and worst zone types.
- Performance by timeframe origin: Daily, 4H, 1H, and M30.
- Performance by target mode, such as `1:2`, `1:3`, `1:4`, and `1:5`.
- Performance of all zone scores, not only the highest-scoring zones.

No rule should be trusted live until it has been tested.

## Data Quality and Run Evidence

The bot should treat bad or stale market data as a trading risk. If required timeframe data is missing or stale, the decision should default to `NO TRADE` instead of guessing.

Current data-quality behavior:

- The top-down snapshot records `data_status` for Daily, 4H, 1H, 30M, and 15M.
- Required stale or missing timeframes block trading and produce a HOLD/NO_TRADE payload.
- YFinance history calls retry intermittent empty responses before accepting a gap.
- The raw engine payload is saved under `<results_dir>/<symbol>/engine_telemetry/`.
- The MT5 runner summary is saved under `<results_dir>/mt5_runner/summary.json`.

After every demo test, review the summary and telemetry before deciding whether a HOLD was correct, a valid setup was missed, or execution should be tested again.

## Recommended Trade Decision Flow

1. Check session/time filter.
2. Check Sunday Asian filter.
3. Check last 15 of 4H filter.
4. Check 15 minutes before session open filter.
5. Wait for candle close.
6. Mark Daily support/resistance and danger zones.
7. Determine Daily permission.
8. Mark 4H structure and support/resistance zones.
9. Determine 4H permission.
10. Mark 1H structure and support/resistance zones.
11. Determine 1H permission.
12. Determine M30 context.
13. Detect M15 playbook setup.
14. Confirm M15/M30 correlation.
15. Confirm higher-timeframe permission.
16. Check clean range to target.
17. Check overextension.
18. Check wick rules.
19. Calculate SL, TP, and risk/reward.
20. Approve or reject trade.

## Active Trade Management Flow

1. Place valid limit order only during the allowed activation window.
2. Cancel the order if it is not triggered within the first 10 minutes of the M15 candle.
3. If triggered, monitor price movement toward the first risk milestone.
4. Move stop-loss to break even once the break-even rule is met.
5. Trail stop-loss behind valid market structure.
6. Take profit at the configured R:R target or continue trailing if structure remains clean.
7. Exit or protect the trade when change of character appears.
