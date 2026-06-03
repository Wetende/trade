# Report 6: Overnight MT5 Forward Test And Price Feed Mismatch

**Report date:** 2026-06-03  
**Market:** Gold  
**Analysis symbol used during run:** GC=F  
**Broker execution symbol:** XAUUSD.vx  
**Run directory:** `C:\Users\Administrator\.tradingagents\sessions\2026-06-02-overnight-b-plus`  
**Run type:** MT5 forward test with deterministic engine decisions and B+ enabled  
**Run window observed in logs:** 2026-06-02 15:04 to 23:13 New York time  

## 1. Executive Summary

The overnight forward test was successful as a systems test, but it was not a valid execution-quality test because the analysis price feed and broker execution price feed were not the same instrument.

The bot ran, generated fresh telemetry, detected tradeable A+ setups, built MT5 requests, placed three pending orders, monitored them, and cancelled them after the activation window expired. There were no broker rejections and the account ended flat with no open orders or positions.

The reason the trades did not fill is now clear: the engine calculated Gold entries from Yahoo `GC=F`, then sent those raw prices to MT5 for `XAUUSD.vx`. At the moments of order placement, the proposed entries were about 24 to 41 points away from the live MT5 quote. With a 10-minute activation window, those orders were very unlikely to trigger.

This means the main bug is not MT5 connectivity, not auto-trading permission, and not the order type logic. The main bug is the live execution data basis.

## 2. Run Results

| Metric | Result |
|---|---:|
| Real runner checks | 93 |
| NO_TRADE decisions | 30 |
| ORDER_PLACED events | 3 |
| ACTIVE_TRADE_MONITORED events | 60 |
| Broker rejections | 0 |
| Broker skipped executions | 0 |
| Open orders after stop | 0 |
| Open positions after stop | 0 |
| Healthy fresh checks | 31 |
| Unhealthy fresh checks | 2 |

The bot did more than idle. It made decisions, submitted orders, and monitored the broker. The missing fill is explained by the distance between `GC=F`-based levels and the live `XAUUSD.vx` market.

## 3. Orders Placed

| New York time | Side | Setup | Grade | Entry | Stop | Target | MT5 type | Order | Outcome |
|---|---|---|---|---:|---:|---:|---|---:|---|
| 2026-06-02 19:15 | SELL | Breakout | A_PLUS | 4517.4708 | 4517.9101 | 4516.1529 | SELL_LIMIT | 77700611 | Accepted, then cancelled after activation window |
| 2026-06-02 22:15 | SELL | Breakout | A_PLUS | 4503.7660 | 4504.4748 | 4501.6396 | SELL_LIMIT | 77949137 | Accepted, then cancelled after activation window |
| 2026-06-02 22:45 | BUY | Support/Resistance Bounce | A_PLUS | 4503.2716 | 4502.4652 | 4505.6908 | BUY_STOP | 77987318 | Accepted, then cancelled after activation window |

All three orders were valid enough for MT5 to accept. None became live positions.

## 4. Why The Trades Did Not Fill

At placement time, the live MT5 quote for `XAUUSD.vx` was far below the engine's proposed entry price. The gap was too large for a short activation window.

| New York time | Order type | Engine entry | MT5 quote at placement | Approximate distance |
|---|---|---:|---|---:|
| 2026-06-02 19:15 | SELL_LIMIT | 4517.47 | 4476.39 / 4476.72 | +41 points |
| 2026-06-02 22:15 | SELL_LIMIT | 4503.77 | 4479.57 / 4479.86 | +24 points |
| 2026-06-02 22:45 | BUY_STOP | 4503.27 | 4477.09 / 4477.38 | +26 points |

For a pending order to fill, market price must trade into the pending entry. These entries were not sitting near the broker's live Gold price. They were levels from a different price feed.

The 10-minute cancellation behavior worked as intended. It removed stale pending orders instead of leaving old orders in the market overnight.

## 5. Root Cause

The live runner was configured with:

| Setting | Value |
|---|---|
| `TRADINGAGENTS_ANALYSIS_SYMBOL` | `GC=F` |
| `TRADINGAGENTS_BROKER_SYMBOL` | `XAUUSD.vx` |
| `TRADINGAGENTS_MT5_SYMBOL` | `XAUUSD.vx` |

The deterministic engine fetched candle data for `GC=F`, then built exact entry, stop, and target prices from that feed. The MT5 execution path then used those exact levels on `XAUUSD.vx`.

That is unsafe for live execution because futures-like Yahoo Gold pricing and the broker CFD symbol are not guaranteed to match point-for-point. The test proved they were not matching during this run.

## 6. B+ Review

B+ grading was enabled during the run, but it did not affect execution.

| Grade | Filled candidates | Placed orders |
|---|---:|---:|
| A_PLUS | 3 | 3 |
| B_PLUS | 0 | 0 |

This is useful evidence. The B+ code path did not create low-quality trades overnight. The three orders came from A+ candidates, but they still failed to fill because the price basis was wrong.

## 7. What Worked

The following parts of the system behaved correctly:

- Fresh telemetry session isolation worked.
- Duplicate processed-candle checks no longer inflated the summary.
- MT5 connection and account verification worked.
- The broker accepted pending orders.
- Active trade monitoring worked.
- Stale pending order cancellation worked.
- B+ grading did not accidentally overtrade.

This means the execution framework is close. The next blocker is feeding the engine with the same price source used for execution.

## 8. What Must Change Before The Next Overnight Run

The live MT5 runner should stop using `GC=F` as the execution analysis feed.

The safer design is:

1. Fetch `XAUUSD.vx` candles directly from MT5.
2. Build the same 15m, 30m, 1h, 4h, and daily snapshot the deterministic engine already expects.
3. Run the same engine against that MT5 snapshot.
4. Place orders only when the proposed entry is near the current MT5 bid/ask.
5. Keep `GC=F` only for non-execution reports or separate comparison research.

The order type logic does not need to be the first fix. It already selected stop or limit pending orders based on the live quote. The bigger issue is that the entry price itself came from the wrong market.

## 9. Recommended Next Test

After implementing the MT5-native data feed:

1. Run `broker-probe` and confirm the account, server, and `XAUUSD.vx` quote.
2. Run one engine cycle only.
3. Confirm the engine payload says the data source is MT5.
4. Confirm proposal `symbol`, `broker_symbol`, and MT5 symbol all point to `XAUUSD.vx`.
5. Confirm proposed entry is within the configured maximum distance from MT5 bid/ask.
6. Start a new fresh telemetry directory for the next overnight session.

## 10. Conclusion

The bot did not fail because it could not trade. It failed to fill because it traded levels calculated from `GC=F` while executing on `XAUUSD.vx`.

The next serious overnight test should not begin until the engine is fed by MT5 candles for `XAUUSD.vx` and the executor has a price-distance guard that blocks proposals too far from the broker quote.
