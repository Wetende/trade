# Report 5: Two-Hour Forward Test Findings And Next Fixes

**Report date:** 2026-06-02  
**Market:** Gold  
**Analysis symbol:** GC=F  
**Broker execution symbol:** XAUUSD.vx  
**Run directory:** `C:\Users\Wetende\.tradingagents\logs\live_runs\m15_three_entries_run_fixed_20260602_002914`  
**Run type:** MT5 forward test with deterministic engine decisions  

## 1. Summary

The latest two-hour forward test was useful because it moved us closer to the real goal: proving whether the bot can read live Gold price action, identify our three M15 entry models, and route valid setups into MT5 orders.

The test confirmed that the bot is no longer simply sitting idle. It detected candidate setups from the three core strategy families:

| Strategy family | Observed in telemetry |
|---|---:|
| Breakout | Yes |
| Buy/Sell off support or resistance | Yes |
| Break and retest | Yes |

It also confirmed that MT5 connection, monitoring, order placement, and order cancellation are working at a basic system level.

However, the run exposed execution and reporting problems that must be fixed before the next serious forward test. The most important issue is that the broker adapter treated every valid setup like a limit order, even when a breakout-style entry may require a stop pending order. That can create broker-side `Invalid price` errors or pending orders that are technically accepted but unlikely to behave like the intended playbook entry.

## 2. What Happened During The Run

| Metric | Result |
|---|---:|
| Total runner checks | 230 |
| Healthy data checks | 150 |
| Unhealthy data checks | 0 |
| Saved order proposals | 9 |
| Proposed trades | 4 |
| Broker orders accepted | 4 |
| Broker rejections | 2 |
| Final open orders | 0 |
| Final open positions | 0 |

The accepted orders were pending orders. They did not become open positions. Each pending order was later cancelled after its activation window expired.

That means the system did place orders into MT5, but no trade was filled and no live position remained open after the run.

## 3. Strategy Evidence

The telemetry showed that the market was not silent. The engine evaluated 29 candidate setups across the saved payloads.

| Candidate type | Count |
|---|---:|
| Support/Resistance Bounce | 17 |
| Breakout | 10 |
| Break and Retest | 2 |

The approved candidates were all Breakout candidates.

| Approved candidate type | Count |
|---|---:|
| Breakout | 4 |

Most rejected candidates failed because the clean range to target was too small compared with the stop-loss distance.

| Rejection reason | Count |
|---|---:|
| Clean range below minimum risk-to-reward | 24 |
| Timeframe correlation failed | 1 |

This tells us two things:

1. The engine is now seeing the three playbook families.
2. The next bottleneck is no longer only strategy detection. It is execution quality, target/risk evaluation, and evidence reporting.

## 4. Main Problems Identified

### 4.1 Order type was too simple

The system still treated every approved setup as a limit order.

That is too simple for the playbook.

In practical trading terms:

- A support/resistance rejection or retest often waits for price to pull back into the entry area, so a limit order can make sense.
- A direct breakout often waits for price to continue through a level, so a stop pending order may be the correct MT5 order type.

The bot must not force every strategy into the same broker order shape.

### 4.2 Broker rejections need clearer explanation

Two order attempts were rejected with `Invalid price`.

This likely happened because the order request did not match the current market quote and pending order type rules. The report layer should explain this in trading language, not only as a raw MT5 retcode.

### 4.3 Accepted pending orders did not fill

Four pending orders were accepted by MT5 but later cancelled because price did not trigger them during the activation window.

That is not automatically bad. The playbook says stale pending entries should be cancelled. But we need clearer evidence showing:

- Which setup created the order.
- Which order type was used.
- Where bid/ask was at the time.
- Whether the order was a pullback entry or continuation entry.
- Why it was cancelled.

### 4.4 Clean range remains the biggest strategy filter

Most candidates still failed because the target zone did not give enough reward compared with risk.

This rule should not be removed casually. It protects the account from low-quality trades. But the target-zone selection must be reviewed so the bot does not reject good setups just because it picked the wrong nearby zone as the target.

### 4.5 Data warnings still need better audit visibility

The run telemetry marked data as healthy, but intermittent GC=F/yfinance warnings still appeared around the system.

The bot should keep retrying temporary data gaps and record retry warnings clearly. If data is healthy after retry, the report should say so. If data is not healthy, the bot should hold and explain which timeframe blocked the decision.

## 5. What We Will Fix Next

The next work is focused on making the next forward test cleaner and more meaningful.

| Fix area | Purpose |
|---|---|
| Setup metadata in proposals | Every order must say whether it came from Breakout, Support/Resistance, or Break and Retest. |
| Smart MT5 pending order selection | The bot must choose BUY_LIMIT, SELL_LIMIT, BUY_STOP, or SELL_STOP based on side, entry price, setup type, and current bid/ask. |
| Stale entry skip | If price has already moved and the entry is no longer valid, the bot should skip instead of sending a bad request. |
| Better runner summary | The summary should show placed, rejected, skipped, cancelled, and monitored orders with clear reasons. |
| Better candidate evidence | Reports should show how many candidates appeared per strategy family and why they passed or failed. |
| Better data warning evidence | Temporary yfinance gaps should be visible without confusing them with real unhealthy data. |

## 6. Expected Result After The Fixes

After these fixes, the next forward test should answer the important questions more cleanly:

1. Did the market create one of our three M15 entry models?
2. Did M30 agree with the M15 setup direction?
3. Did the setup have enough clean range to target?
4. If approved, did the bot choose the correct MT5 pending order type?
5. If no order was placed, was the reason strategy-related, price-staleness-related, broker-related, or data-related?
6. If an order was accepted but not filled, was cancellation correct under the activation-window rule?

## 7. Conclusion

The two-hour test was valuable because it showed progress and exposed the next real blockers.

The bot can now observe live Gold data, detect playbook-like candidates, produce proposals, send pending orders to MT5, and cancel stale pending orders. The remaining work is to make the broker order type match the trading setup, improve stale-entry handling, and produce clearer evidence after every run.

The next forward test should not be judged only by whether it opens a position. It should be judged by whether every HOLD, skipped order, rejected order, accepted order, and cancelled order can be explained from the playbook and the live bid/ask at the time.
