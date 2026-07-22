# One Minute Causal Reclaim V10

## Status and scope

`ONE_MINUTE_CAUSAL_RECLAIM_V10` is a new M1-only candidate. V9.1 remains
retired at commit `e1a083d` and is used only for hypothesis generation. V10
does not alter M15/M30 and cannot place orders without a hash-matched promotion
record.

## Causal hypothesis

The latest fully closed M1 candle must sweep the preceding twelve-candle high
or low and close back inside with a directionally mirrored rejection body and
wick. The closed candle only arms the story. After the close, live quotes must
retest the swept level, reject it in the reclaim direction, and then satisfy
the strict quote-pressure lifecycle.

This tests whether waiting for a failed-break reclaim avoids the immediate
adverse selection seen in older continuation candidates. It is quote pressure,
not true order-flow imbalance; the feed exposes neither depth nor reliable
traded volume.

## Frozen detector

- Use at most 60 fully closed M1 candles.
- Use the prior 30 candles for median-range normalization and the prior 12 for
  the swept extreme.
- Latest range must be `0.60` to `1.60` median ranges.
- Body must be at least `0.30` of range and rejection wick at least `0.25`.
- Sweep must be `0.08` to `0.75` median ranges beyond the reference extreme.
- Close must return at least `0.02` median ranges inside the reference.
- The post-close arm expires after 45 seconds and cannot trigger for one second.
- BUY and SELL rules are exact mirrors.

## Frozen quote-pressure and execution contract

- The level must be retested and rejected after the candle closes.
- Collect 20 distinct mid-price changes in three seconds with at least 10
  nonzero moves.
- Directional pressure is at least `0.60`.
- Directional displacement is at least `max(median spread, 0.10R)`.
- Adverse movement is at most `0.15R`.
- Median spread is at most `1.10x` arm-time spread.
- Wait five seconds, reject invalidated/crossed/moved-away stories, and propose
  a stop one tick beyond the pressure extreme.
- Stop distance is at least broker/spread structure and at most one price unit;
  target is `1.5R`; pending expiry is 20 seconds.
- One arm/order/position, persistent state, `2R` session budget, 15-minute
  two-loss pause, no boost, DEMO only, and drain-to-flat shutdown remain
  mandatory.

## Chronological evidence

Discovery is preregistered before its first candle:

1. `2026-07-22T20:00Z` to `2026-07-23T12:00Z`
2. `2026-07-23T12:00Z` to `2026-07-24T04:00Z`
3. `2026-07-24T04:00Z` to `2026-07-24T20:00Z`

Held-out is unopened unless discovery passes:
`2026-07-26T22:00Z` to `2026-07-28T00:00Z`.

Discovery, held-out, prospective, and initial `0.01` DEMO gates remain the V8
playbook gates. Failure retires V10 without tuning it on the failed window.

