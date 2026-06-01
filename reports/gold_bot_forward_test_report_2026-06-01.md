# Gold Trading Bot Forward Test Report

**Report date:** 2026-06-01  
**Market:** Gold  
**Analysis symbol:** GC=F  
**Broker execution symbol:** XAUUSD.vx  
**Broker account:** Valetax demo account on MT5  
**Captured run window:** 2026-05-31 21:30 ET to 2026-06-01 01:30 ET  
**Purpose:** Understand why the bot watched the market but did not place a trade.

## 1. Short Summary

The bot connected to MT5 correctly, read live Gold market data, created logs, created telemetry, and kept the demo account safe. It did not leave any open orders or open positions.

The main issue was not MT5 execution. The main issue was the trading logic.

The bot was using extra higher-timeframe rules that are not part of the main checklist. In simple terms, the bot was saying:

> "Even if M30 and M15 show something interesting, I will still refuse unless 1H, Daily, or 4H also gives permission."

That is too strict for this strategy.

The real trading plan is based on M30 and M15:

- M30 is the main market filter.
- M15 is the entry and confirmation chart.
- Daily, 4H, and 1H can help us understand the bigger picture, but they should not automatically block a trade.

So the next fix is not to add another trading mode. The next fix is to make the main bot logic match the checklist.

## 2. What Happened During The Run

The bot watched Gold during the test window and made 17 fresh trade decisions. Every decision ended as NO TRADE.

The decisions split into two groups:

| Decision result | Count | Meaning |
|---|---:|---|
| Blocked by extra higher-timeframe rules | 9 | The bot saw possible setups, but rejected them because 1H/Daily/4H did not give permission |
| No clean M15 setup | 8 | M30 had context, but M15 did not confirm a proper entry |

The 8 cases with no clean M15 setup are acceptable. If M15 does not confirm, the bot should not trade.

The 9 higher-timeframe blocks are the problem. Those blocks came from rules like:

- `1H must agree with BUY`
- `Daily danger zone blocks SELL`

Those rules made the bot more restrictive than the checklist.

## 3. MT5 And Execution Health

The MT5 side looked healthy during the captured run.

| Item | Result |
|---|---|
| MT5 connected | Yes |
| Demo account connected | Yes |
| Open orders after check | 0 |
| Open positions after check | 0 |
| Broker rejections | 0 |
| Orders placed by this runner | 0 |
| Latest balance/equity checked | 99,999.62 USD / 99,999.62 USD |

This means we should not blame the lack of trades on MT5 first. The better explanation is that the bot's rules were blocking entries before they reached execution.

## 4. What The Market Was Showing

During the captured decision candles, the bot repeatedly saw bullish M30 breakout context.

That matters because M30 is supposed to be the main filter. If M30 is bullish, the bot should then look for a valid bullish M15 entry.

The bot did find candidate moments, but several of them were blocked before becoming brokerable trade proposals.

Examples:

| Time ET | Candidate setups found | M30 context | Why bot still held |
|---|---:|---|---|
| 2026-05-31 21:30 | 5 | Bullish breakout | 1H must agree with BUY |
| 2026-05-31 21:45 | 5 | Bullish breakout | 1H must agree with BUY |
| 2026-05-31 22:15 | 5 | Bullish breakout | 1H must agree with BUY |
| 2026-05-31 22:30 | 3 | Bullish breakout | Daily danger zone blocks SELL |
| 2026-05-31 23:15 | 6 | Bullish breakout | Daily danger zone blocks SELL |
| 2026-06-01 00:15 | 1 | Bullish breakout | 1H must agree with BUY |

This shows the bot was not asleep. It was seeing market structure and candidate setups. The issue is that it was applying extra approval rules before allowing an entry.

## 5. The Correct Checklist

The bot should not trade because one candle looks good. It should only trade when the full checklist agrees.

The correct checklist is:

1. It is the right trading time.
2. A valid playbook setup appears.
3. M30 and M15 agree.
4. There is clean range to target.
5. The candle has closed.
6. Price is not overextended.
7. Wick rules are valid.
8. Risk rules approve the trade.

If any required rule fails, the result should still be NO TRADE.

This is still a safe strategy. We are not removing discipline. We are removing rules that do not belong to the main checklist.

## 6. Timeframe Roles Going Forward

M30 should answer:

- Is Gold bullish, bearish, or unclear?
- Is price near support or resistance?
- Has there been a real breakout?
- Is the move already overextended?
- Is there enough room to target?

M15 should answer:

- Has the setup confirmed?
- Has the candle closed?
- Is there a valid wick for stop-loss?
- Is the entry still fresh?
- Can we place a clean limit order?

Daily, 4H, and 1H should answer:

- What is the bigger market story?
- Are we near a major zone?
- Is there extra caution needed?
- What should we record in the report?

Daily, 4H, and 1H should not automatically say:

- "No trade because 1H does not agree."
- "No trade because Daily is neutral."
- "No trade because 4H did not give permission."

The trade decision should come from the M30/M15 checklist.

## 7. What We Will Change

We will update the main trading logic so the bot follows the M30/M15 checklist directly.

Planned changes:

1. Remove hard blocks such as `1H must agree with BUY`.
2. Remove hard Daily/4H/1H permission gates from the main trade approval path.
3. Keep Daily/4H/1H in the reports as market context, not as automatic trade blockers.
4. Keep M30 as the main filter.
5. Keep M15 as the entry and confirmation chart.
6. Require M30 and M15 to agree before any trade is approved.
7. Keep the session and time filters, including Sunday Asian and last 15 minutes of a 4H candle.
8. Keep candle-close validation so the bot does not trade on forming candles.
9. Keep clean range checks, with at least 1.5R required and 2R preferred.
10. Keep overextension checks so the bot does not chase Gold after the move is mostly gone.
11. Keep wick rules for confirmation and stop-loss placement.
12. Keep limit-order activation timing, so orders are not triggered too late in the M15 candle.
13. Improve telemetry so every NO TRADE decision says exactly which checklist rule failed.

## 8. What We Will Not Change

We will not make the bot force trades.

We will not remove risk management.

We will not let the bot trade from one attractive candle alone.

We will not treat Daily, 4H, and 1H as useless. They will still be useful context, but they will not override the core M30/M15 entry model.

We will not move to live funds. Testing remains on demo until execution and logic are proven.

## 9. Next Test After The Fix

After the logic is corrected, we should run another demo forward test.

The next test should answer these questions:

1. When M30 is bullish, does the bot wait for a valid bullish M15 setup?
2. When M30 is bearish, does the bot wait for a valid bearish M15 setup?
3. When M30 and M15 disagree, does the bot correctly hold?
4. When M15 does not confirm, does the bot correctly hold?
5. When all checklist rules pass, does the bot create a brokerable proposal?
6. Can MT5 place, monitor, cancel, or manage that demo order correctly?
7. Does the report clearly explain every HOLD, proposal, rejection, and order event?

Success does not mean the bot must trade often. Success means the bot only trades when the checklist truly passes, and when it holds, we can clearly see why.

## 10. Final Conclusion

The last run was useful because it showed the difference between a broken execution system and an overly strict decision system.

The execution system looked healthy. MT5 was connected, data was fresh, telemetry was working, and no unwanted orders remained open.

The decision system needs correction. The bot should be centered on the M30/M15 strategy from the checklist. The extra Daily/4H/1H permission rules should be removed from the hard approval path and kept only as market context.

Once that is fixed, the next demo run will give a much cleaner answer: whether the actual M30/M15 strategy can find valid Gold entries and execute them correctly on MT5.

