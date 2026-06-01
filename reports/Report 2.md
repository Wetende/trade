# Report 2: Two-Hour Gold Bot Forward Test Review

**Report date:** 2026-06-01  
**Market:** Gold  
**Analysis symbol:** GC=F  
**Broker execution symbol:** XAUUSD.vx  
**Broker account:** Valetax demo account on MetaTrader 5  
**Run directory:** `C:\Users\Wetende\.tradingagents\logs\live_runs\m30_m15_core_run_20260601_155624`  
**Run window:** 2026-06-01 15:56 to 17:56 Brisbane time  
**Decision candles reviewed:** 2026-06-01 01:45 to 03:45 New York time  
**Purpose:** Check whether the bot can watch live market data, detect valid M30/M15 setups, create proposals, and reach MT5 execution safely.

## 1. Executive Summary

The two-hour forward test was useful because it separated three different questions:

1. Can the bot stay connected and read market data?
2. Can the trading engine explain why it is holding?
3. Can the MT5 execution layer place and cancel a broker order when asked?

The answer to all three is mostly positive, but there is one important design issue to correct before the next longer run.

During the two-hour runner test, the bot completed 135 checks. Most checks were repeated reads of the same already-processed 15-minute candle. There were 9 fresh trade decisions, and all 9 ended as `NO_TRADE` / `NO_SETUP`.

No broker orders were placed by the runner. There were no broker rejections, no open orders, and no open positions left behind.

The telemetry showed that market data was healthy throughout the run. The bot was not blocked by missing GC=F data during this test. The real reason for holding was trading logic: either there was no valid M15 playbook setup, or a candidate setup failed the A+ checklist because the clean range and risk-to-reward were not good enough.

The most important issue found is not the holding decision itself. The important issue is that the order proposal and explanation path can still rely too much on LLM text. That can create confusing wording, for example saying "no price data" even when the telemetry says the data was fresh and healthy. The next engineering step should be to make the deterministic engine and telemetry the trusted source for trade decisions and order proposals.

## 2. Run Results

| Metric | Result |
|---|---:|
| Total runner checks | 135 |
| Fresh trade decisions | 9 |
| Repeated candle checks | 126 |
| Trade proposals created by runner | 0 |
| Broker orders placed by runner | 0 |
| Broker rejections | 0 |
| Open orders after test | 0 |
| Open positions after test | 0 |
| Healthy data checks | 135 |
| Unhealthy data checks | 0 |

The runner stopped because the configured two-hour duration ended. This did not mean MT5 was closed or disconnected. It means the bot process ended normally after reaching its time cap.

## 3. Data Health

Data health was good in this two-hour run.

| Timeframe | Status at latest check | Latest candle age | Rows available |
|---|---|---:|---:|
| M15 | Fresh | 0 minutes | 636 |
| M30 | Fresh | 15 minutes | 318 |
| H1 | Fresh | 45 minutes | 1102 |
| H4 | Fresh | 225 minutes | 298 |
| Daily | Fresh | 225 minutes | 252 |

This is important because an earlier concern was the intermittent `GC=F: possibly delisted; no price data found` warning. In this specific two-hour run, telemetry says all 135 checks were healthy and no timeframe was blocking.

There was still one misleading summary category labeled `data_health`. That came from the proposal/explanation text, not from the real telemetry. The real telemetry showed healthy data. This confirms that the report/proposal layer must trust structured telemetry before trusting LLM wording.

## 4. Fresh Trading Decisions

The runner made one fresh decision per completed 15-minute candle.

| Candle time ET | Result | M30 context | Candidate setups | Failed reason |
|---|---|---|---:|---|
| 01:45 | NO_SETUP | Bullish breakout | 1 | Clean range / R:R too weak |
| 02:00 | NO_SETUP | Bullish breakout | 0 | No valid M15 playbook setup |
| 02:15 | NO_SETUP | Bullish breakout | 7 | Clean range / R:R too weak; timeframe correlation failed |
| 02:30 | NO_SETUP | Bullish breakout | 0 | No valid M15 playbook setup |
| 02:45 | NO_SETUP | Bullish breakout | 0 | No valid M15 playbook setup |
| 03:00 | NO_SETUP | Bullish breakout | 2 | Clean range / R:R too weak |
| 03:15 | NO_SETUP | Bullish breakout | 0 | No valid M15 playbook setup |
| 03:30 | NO_SETUP | Bearish breakout | 0 | No valid M15 playbook setup |
| 03:45 | NO_SETUP | Bearish breakout | 1 | Clean range / R:R too weak |

This tells us the bot was not idle. It was reading structure and finding candidate moments. But no candidate passed enough of the checklist to become a brokerable trade.

## 5. What The Bot Saw

For most of the run, the M30 context was bullish breakout. Near the end of the run, the M30 context changed to bearish breakout. That means the market did move enough for the engine to update its read.

The strongest repeated failure was not higher-timeframe permission. Daily, H4, and H1 were being recorded as context. The failures came from the core checklist:

| Failure category | Count | Trading meaning |
|---|---:|---|
| No valid M15 playbook setup | 5 | M30 had context, but M15 did not give the entry candle required by the strategy |
| A+ checklist failure | 4 | A candidate existed, but one or more required trade-quality checks failed |
| Clean range / R:R too weak | 4 | The entry, stop, and target did not give enough room to justify the trade |
| Timeframe correlation failed | 1 | A candidate direction did not align cleanly with the confirmation context |

The best example is the final candle at 03:45 ET. The engine found a possible Break and Retest SELL, but the risk-to-reward was only 0.62R. That is below the required threshold, so holding was the correct action.

## 6. MT5 Execution Status

The two-hour runner itself did not place any orders because no trade passed the rules.

After the runner, a separate direct demo execution smoke test was performed without relying on market analysis or the LLM. That test proved the MT5 execution layer can place and cancel a pending demo order.

| Execution check | Result |
|---|---|
| MT5 connected | Passed |
| Correct Valetax demo account detected | Passed |
| Broker symbol XAUUSD.vx detected | Passed |
| Pending SELL LIMIT request built | Passed |
| Broker accepted pending order | Passed |
| Broker ticket returned | 73390225 |
| Pending order was visible in MT5 state | Passed |
| Pending order cancelled | Passed |
| Final open orders | 0 |
| Final open positions | 0 |

This means the execution layer is capable of talking to MT5. The main remaining question is not "can MT5 receive an order?" It can. The main question is "when the strategy finds a valid setup, can the full bot send the right proposal to MT5 without the LLM confusing the decision?"

## 7. Main Issue Found

The most important issue is the split between deterministic telemetry and LLM-generated text.

The engine telemetry is structured and reliable. It knows:

- Whether data is healthy.
- Which timeframe was fresh.
- What M30 context was detected.
- How many candidate setups existed.
- Which checklist rule failed.
- Whether risk-to-reward passed.
- Whether the final result was `NO_SETUP` or `SETUP_FOUND`.

The LLM explanation is useful for readable summaries, but it can say something misleading if it receives incomplete text or if the report path is empty. In this run, one proposal reason suggested missing price-action data even though telemetry showed data was healthy.

That mismatch matters because execution should never depend on wording. Execution should depend on structured facts.

## 8. Recommended Next Fix

The next fix should be to make the order proposal and runner execution path trust the deterministic engine first.

Recommended behavior:

1. The engine reads candles and produces telemetry.
2. The engine decides `NO_SETUP` or `SETUP_FOUND`.
3. If `NO_SETUP`, the proposal must say `NO_TRADE` using the engine's failed checklist reason.
4. If `SETUP_FOUND`, the proposal must use the engine's side, entry, stop loss, take profit, setup name, risk-reward, and activation window.
5. The LLM may still write a human explanation, but it should not decide side, levels, or whether a trade exists.
6. The runner summary should categorize holds from telemetry, not from LLM wording.

In short: telemetry should drive execution; the LLM should explain after the fact.

## 9. What Should Stay Strict

The bot should still remain disciplined.

Rules that should stay strict:

- No trade without a valid M15 setup.
- No trade without M30/M15 alignment.
- No trade when the candle has not closed.
- No trade when clean range is too small.
- No trade when R:R is below the minimum.
- No trade when wick rules fail.
- No trade when the order would activate too late in the M15 candle.
- No live account execution while the system is still under demo validation.

This is not about forcing trades. The goal is to remove unreliable decision sources and keep the real checklist strong.

## 10. Next Test Plan

After the deterministic proposal fix, the next test should be another demo forward run.

The next run should confirm:

| Question | Expected proof |
|---|---|
| Does the bot read fresh GC=F data? | Data health is green across M15, M30, H1, H4, Daily |
| Does the engine explain every HOLD? | Telemetry shows the exact failed checklist rule |
| Does the proposal match telemetry? | Proposal reason agrees with engine decision stage |
| Does the bot ignore misleading LLM wording? | Side, levels, and status come from engine data |
| Does MT5 execute when a setup passes? | A demo order is placed only after `SETUP_FOUND` |
| Does risk management stay intact? | No proposal is sent with weak R:R or missing levels |

Success does not mean the bot trades often. Success means every HOLD and every trade proposal can be traced back to the checklist.

## 11. Final Conclusion

The two-hour test did not produce a trade, but it was still a strong diagnostic run.

The market data path worked. The telemetry path worked. The runner stopped normally after its two-hour cap. MT5 remained safe with no open orders or positions. A separate direct execution smoke test confirmed that MT5 can accept and cancel a demo pending order.

The main weakness is the decision handoff between the deterministic engine and the LLM-based proposal/explanation layer. The next engineering step is to make the engine and telemetry the source of truth for execution. Once that is done, the bot can be tested again with more confidence, because a valid M30/M15 setup will produce a deterministic broker proposal instead of passing through uncertain LLM wording.
