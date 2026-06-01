# Report 3: Engine-First Two-Hour Gold Forward Test Review

**Report date:** 2026-06-01  
**Market:** Gold  
**Analysis symbol:** GC=F  
**Broker execution symbol:** XAUUSD.vx  
**Broker account:** Valetax MT5 account  
**Run directory:** `C:\Users\Wetende\.tradingagents\logs\live_runs\engine_2h_run_20260601_204922`  
**Run window:** 2026-06-01 20:49 to 22:49 Brisbane time  
**Decision candles reviewed:** 2026-06-01 06:45 to 08:45 New York time  
**Decision path:** deterministic price-action engine first; LLM not used to decide trades  

## 1. Executive Summary

The completed two-hour run was successful as a systems test and useful as a trading-logic test.

The bot stayed connected, read fresh market data, generated telemetry, created order proposals, and monitored MT5 without leaving any open orders or positions. No broker rejection occurred.

The engine did not place a trade. That was not because MT5 failed, and not because the LLM refused a trade. The deterministic engine held because no full A+ M30/M15 setup passed the checklist.

Across the run, the bot saw both bullish and bearish M30 breakout context. It also found candidate setups on several candles. However, the brokerable candidates failed mainly on clean range / risk-to-reward. In plain trading terms: the entry idea existed, but there was not enough clean room to the next opposing zone to justify the trade.

The most important result is that the new engine-first path is working. Daily, 4H, and 1H are now recorded as context, while M30/M15 and risk rules decide whether a trade is valid.

## 2. Run Results

| Metric | Result |
|---|---:|
| Total runner checks | 228 |
| Fresh trade decisions | 9 |
| Repeated candle checks | 219 |
| Saved order proposals | 9 |
| NO_TRADE / HOLD proposals | 9 |
| Broker orders placed | 0 |
| Broker rejections | 0 |
| Open orders after stop | 0 |
| Open positions after stop | 0 |
| Healthy data checks | 228 |
| Unhealthy data checks | 0 |

The runner was later extended with a second two-hour continuation, but that continuation was stopped manually on request. The report above focuses on the completed first two-hour run.

## 3. Broker And Execution State

MT5 remained connected during the run and after the manual stop.

| Item | Status |
|---|---|
| Broker connection | Connected |
| MT5 server | ValetaxGlobal-Live3 |
| Account type reported by MT5 | DEMO |
| Balance / equity after stop | 99,999.62 USD / 99,999.62 USD |
| Open orders after stop | 0 |
| Open positions after stop | 0 |
| Broker rejections | 0 |

No trade was attempted because the engine never emitted a `SETUP_FOUND` proposal. Therefore, the lack of orders is explained by trading logic, not broker failure.

## 4. Data Health

Data health was good throughout the completed run.

| Timeframe | Latest status | Rows available at final check |
|---|---|---:|
| M15 | Fresh | 655 |
| M30 | Fresh | 328 |
| H1 | Fresh | 1107 |
| H4 | Fresh | 300 |
| Daily | Fresh | 252 |

No timeframe was marked as blocking. This matters because earlier runs showed intermittent GC=F warnings. In this two-hour engine-first run, the telemetry did not show bad data as the reason for holding.

## 5. Fresh Trading Decisions

| Candle time ET | Result | M30 context | Candidate setups | Failed reason |
|---|---|---|---:|---|
| 06:45 | HOLD | Bullish breakout | 1 | Clean range / R:R too weak |
| 07:00 | HOLD | Bearish breakout | 1 | Clean range / R:R too weak |
| 07:15 | HOLD | Bullish breakout | 2 | Clean range / R:R too weak |
| 07:30 | HOLD | Bullish breakout | 6 | Clean range / R:R too weak; M30/M15 correlation failed |
| 07:45 | HOLD | Bullish breakout | 0 | Time filter failed |
| 08:00 | HOLD | Bearish breakout | 6 | Clean range / R:R too weak |
| 08:15 | HOLD | Bullish breakout | 6 | Clean range / R:R too weak; M30/M15 correlation failed |
| 08:30 | HOLD | Bearish breakout | 0 | No valid M15 setup |
| 08:45 | HOLD | Bearish breakout | 0 | No valid M15 setup |

This is a good diagnostic result. The bot was not asleep. It saw market context, found candidates, rejected weak trade locations, and stayed out.

## 6. Hold Reason Breakdown

| Hold reason category | Count |
|---|---:|
| Clean range / risk-to-reward too weak | 6 |
| No valid M15 setup | 2 |
| Time filter | 1 |

The biggest practical blocker was `clean_range_to_fill`. The engine repeatedly found possible entries, but the nearest target zone made the reward too small compared with the stop.

The reported R:R values for rejected candidate trades were very low, including approximately `0.66`, `0.30`, `0.14`, `0.02`, `0.02`, and `0.01`. The minimum configured R:R is `1.5`, so these were correctly rejected under the current rules.

## 7. Higher-Timeframe Context

Daily, 4H, and 1H were still read and written into telemetry. They were not used as hard permission blockers.

Observed context included:

- Daily often classified near major support.
- 4H often classified near major support.
- 1H changed between bearish structure, bullish structure, and range during the broader run.
- Higher-timeframe context was recorded as context only when a candidate setup existed.

This matches the revised playbook direction: Daily/4H/1H help describe the market, but the brokerable trade must come from M30 context and M15 entry quality.

## 8. Interpretation

The completed run does not prove the strategy is profitable yet, but it does prove the new decision path is behaving more transparently.

The bot did three important things correctly:

1. It did not force trades.
2. It did not let Daily/4H/1H permission block M30/M15 candidates.
3. It rejected entries when there was not enough clean range to target.

The main question for review is whether the clean-range / target-zone logic is too conservative or whether the market simply did not provide enough room during this window.

That should be reviewed with charts for the rejected candles, especially 07:30, 08:00, and 08:15 ET, where candidate setup counts were high but R:R was extremely weak.

## 9. Recommendations

1. Keep the engine-first execution path.
2. Keep Daily/4H/1H as context, not hard permission.
3. Review the nearest target-zone selection for clean range, because it is now the dominant blocker.
4. Add a visual or tabular rejected-setup report showing entry, stop, nearest target zone, and R:R per candidate.
5. Continue forward testing during London/New York overlap, but do not loosen risk rules just to force a trade.
6. If execution must be confirmed directly, use a controlled manual-test proposal with tiny volume, not a weakened live strategy rule.

## 10. Conclusion

The finished two-hour run was operationally clean and strategically conservative.

No orders were placed, but that was an expected outcome from the engine rules: the market produced context and candidates, but no A+ M30/M15 setup had enough clean range and risk/reward to justify execution.

The next best step is not to force entries. The next best step is to audit the rejected candidate setups visually and confirm whether the engine's target-zone and clean-range calculations match the trading playbook.
