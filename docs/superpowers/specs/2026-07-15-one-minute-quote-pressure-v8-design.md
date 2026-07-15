# One Minute Quote Pressure V8 — frozen design

Status: implementation freeze candidate  
Candidate: `ONE_MINUTE_QUOTE_PRESSURE_V8`  
Scope: M1 only; M15 and M30 behavior is out of scope  
Broker scope: DEMO only after promotion; REAL is always refused

## Purpose and interpretation

V8 tests whether a symmetric, causal best-quote pressure gate can improve the execution quality of the six existing M1 structural stories. It does not claim to observe true order-flow imbalance. The MT5 feed used here has best bid/ask changes but no dependable market depth or exchange traded-volume series, so the implementation and telemetry use the term **quote pressure**.

The preregistered external motivation is the short-horizon relationship between best-quote/order-flow changes and price movement described by Cont, Kukanov and Stoikov, [The Price Impact of Order Book Events](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1712822). That paper motivates measuring short-horizon pressure; it does not validate this feed proxy or this trading rule.

## Causal detector and state machine

Only the latest 60 fully closed M1 candles may arm a setup. The closed candle can create an arm but cannot create an entry. V8 retains the mirrored families `HIGH_BREAK_BUY` / `LOW_BREAK_SELL`, `HIGH_RESPECT_SELL` / `LOW_RESPECT_BUY`, and `FAILED_HIGH_BREAK_SELL` / `FAILED_LOW_BREAK_BUY`.

The family-specific post-close structural test runs first. When it passes, V8 starts a fixed three-second quote-pressure window. The triggering quote is the baseline. Exact duplicate ticks and unchanged mid prices cannot inflate the sample. Twenty distinct mid-price changes must arrive inside the window, with at least ten nonzero moves.

For BUY, a positive mid-price change is directional; for SELL, a negative change is directional. Directional pressure is directional nonzero changes divided by all nonzero changes. The frozen gates are:

- directional pressure at least 0.60;
- directional displacement at least `max(median spread, 0.10R)`;
- maximum adverse excursion no greater than `0.15R`;
- pressure-window median spread no greater than `1.10 ×` arm-time spread.

Here `R` is the structural stop distance for a direction-safe stop order one tick beyond the frozen pressure extreme, after broker stop/freeze minimums are applied. Invalid stop geometry or risk above one price unit rejects the story.

After pressure passes, V8 waits five additional seconds. A crossed entry, structural invalidation, or adverse moved-away story rejects the setup. A BUY uses `BUY_STOP` one tick above the maximum pressure-window ask; a SELL uses `SELL_STOP` one tick below the minimum pressure-window bid. Prices snap outward to the broker tick grid. The stop is structural and at least the maximum of the configured minimum, `1.2 ×` current spread, broker stop distance, and broker freeze distance. Maximum stop distance is 1.00 price unit, the target is 1.5R, and the pending order expires after 20 seconds.

The durable phases are `ARMED`, `PRESSURE`, `WAITING`, `PLACED`, and terminal `INVALIDATED`, `EXPIRED`, `REJECTED`, or `CONSUMED`. Every accepted transition is atomically persisted. Absolute arm, pressure, placement, pending, cooldown, runtime, and drain deadlines survive restart unchanged. Only one arm, pending order, or position may exist.

## MT5 execution contract

Before proposal construction, the runner reads `expiration_mode`, `order_mode`, `filling_mode`, `trade_exemode`, `trade_stops_level`, and `trade_freeze_level`. Pending orders always request `ORDER_FILLING_RETURN`, matching the [MQL5 order property guidance for pending orders](https://www.mql5.com/en/docs/constants/tradingconstants/orderproperties). `ORDER_TIME_SPECIFIED` is used only when the symbol capability flags prove it is supported; otherwise V8 starts with GTC and enforces its durable local 20-second cancellation deadline. This removes reject-first expiration discovery from the normal path.

Stop loss is estimated in account currency with MT5 [`order_calc_profit`](https://www.mql5.com/en/docs/python_metatrader5/mt5ordercalcprofit_py). One R is frozen at session startup as the larger account-currency loss of a BUY or SELL one-price-unit stop at the configured fixed volume. The session budget is `max_session_r × R`, default 2R. A proposal is allowed only when:

`max(0, -realized net) + reserved exposure + proposed stop risk + 0.05R <= session budget`.

Missing or unpriceable exposure fails closed. Volume is exact and fixed; `volume_multiplier` is unset and all boosting is disabled. Two consecutive closed losses persist a 15-minute pause. Entry resumes only for a newly closed structural arm after the pause timestamp.

For prospective DEMO promotion, the runner reconciles each acknowledged pending-order ticket to its MT5 entry deal and closed position. Allowed live entry drift is frozen at the larger of one tick or the pressure-window median spread. Every submission, fill, close, account-currency result, normalized R result, and drift decision is retained in the atomic runtime evidence ledger.

At the durable runtime deadline, the runner enters `DRAINING`. It blocks all new arms and entries, cancels pending orders, and manages positions for the configured grace period (default 120 seconds). After the grace period it repeatedly attempts to close remaining DEMO positions. The process cannot report completion until three fresh DEMO broker snapshots prove zero orders and zero positions. It never sends a mutation to a REAL account.

The capability fields follow the official [MQL5 symbol properties](https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants), and every proposal still passes MT5 `order_check` before `order_send`.

## Frozen evidence protocol

No V8 outcome may be inspected before the design, detector, replay, lifecycle, cost model, tests, and their SHA-256 hashes are frozen in the candidate manifest.

Collected MT5 quote files are consumed as monotonic streams. The screener never loads or re-sorts a full multi-million-quote fold in memory, rejects a non-monotonic source, and applies each fold's start-inclusive/end-exclusive boundary before replay. This changes storage behavior only; it does not sample, aggregate, or discard quotes.

Discovery consists only of three chronological folds:

1. 2026-06-22 00:00 UTC through 2026-06-29 00:00 UTC;
2. 2026-06-29 00:00 UTC through 2026-07-06 00:00 UTC;
3. 2026-07-06 00:00 UTC through 2026-07-13 00:00 UTC.

Discovery requires at least 30 fills across ten sessions; positive net; PF at least 1.15; expectancy at least +0.05R after the frozen 0.05R cost; positive BUY and SELL; two positive mirrored categories; at least half of sessions and two folds profitable; maximum loss streak six; portfolio drawdown at most 8R; session drawdown at most 3R; trigger rate at least 15%; valid-trigger placement/fill at least 85%; crossed rate at most 15%; and geometry rejection at most 5%.

Only after discovery passes and the window is complete may one held-out fixture for 2026-07-13 through 2026-07-20 be opened. It requires 15 fills across five sessions, positive net, PF at least 1.25, expectancy at least +0.10R, positive net after removing the best session, and positive net after adding another 0.05R cost to every fill.

Only a passing held-out report can create a hash-locked prospective registration. Prospective evidence cannot predate that registration. It requires 60 fills across ten sessions, positive net, PF at least 1.20, expectancy at least +0.08R, at least 60% profitable sessions, and zero lookahead, mutation, lifecycle, restart, account-safety, or telemetry failures.

Any failed stage sets `retired=true` and `RETIRED_WITHOUT_TUNING`. The failed window cannot be used to tune V8, and no promotion record may be generated.

## Promotion and runnable states

Order capability requires both the frozen manifest and a DEMO-only promotion record whose manifest, implementation, test, and evidence-report hashes match the current files. A record approving 0.01 volume requires passing discovery, held-out, and prospective reports. A record approving 1.0 additionally requires 30 closed 0.01 DEMO trades across five sessions, positive net and expectancy, PF at least 1.10, drawdown at most 3R, zero safety failures, complete reconciliation, and compliant entry drift.

Until those gates pass, the correct runnable state is broker-free replay/read-only collection. After promotion, the same code is immediately runnable with:

```powershell
.\scripts\start-one-minute-demo.ps1 `
  -CandidateManifest .\docs\analysis\2026-07-15-one-minute-quote-pressure-v8-manifest.json `
  -PromotionRecord <approved-promotion-record.json> `
  -Volume 0.01 `
  -DurationHours 3 `
  -MaxSessionR 2 `
  -ShutdownGraceSeconds 120
```

The launcher proves DEMO mode and zero initial exposure before spawning the hidden worker. A missing, failed, retired, mismatched, or over-volume promotion fails before order capability.

## Implementation map

- detector/state: `tradingagents/agents/price_action/one_minute_quote_pressure_v8.py`
- deterministic replay: `tradingagents/agents/price_action/one_minute_quote_pressure_v8_replay.py`
- gates: `tradingagents/agents/price_action/one_minute_quote_pressure_v8_evidence.py`
- chronological screen/registration: `tradingagents/agents/price_action/one_minute_quote_pressure_v8_screening.py`
- promotion: `tradingagents/agents/price_action/one_minute_quote_pressure_v8_promotion.py`
- 0.01 DEMO audit: `tradingagents/agents/price_action/one_minute_quote_pressure_v8_demo_audit.py`
- account-currency budget: `tradingagents/brokers/mt5_one_minute_v8_risk.py`
- live DEMO lifecycle/drain: `tradingagents/brokers/mt5_one_minute_v8_runner.py`
- launcher: `scripts/start-one-minute-demo.ps1`

M15/M30 detector, dispatcher, strategy, and configuration behavior is not modified by this candidate.
