# One Minute Impulse-Inside-Pullback V7 Design

## Candidate

`ONE_MINUTE_IMPULSE_INSIDE_PULLBACK_V7`

Frozen before V7 arms, triggers, fills, or outcomes are calculated on any
saved discovery fixture.

## Research basis and limits

The prior direct-impulse strategy lost because it entered continuation without
waiting for a new compact structure; most losses had no meaningful favorable
excursion. V5/V5.1 compression breakouts and V6 shock-reclaim reversal were
also rejected. V7 therefore tests a different market story: directional
information persists, a complete opposing inside candle pauses without
breaking the impulse midpoint, and continuation is admitted only after a new
post-close breakout state.

Primary research documents intraday momentum in high-frequency gold, silver,
and crude-oil ETFs, with stronger predictability on high-volatility and
large-jump days:

- https://doi.org/10.1016/j.resourpol.2020.101830

Broader ETF and international-index research also documents economically
meaningful intraday momentum and links it to volatility, liquidity, and the
gradual processing of information:

- https://doi.org/10.1016/j.jfineco.2018.05.009
- https://doi.org/10.1016/j.finmar.2021.100619

Those studies operate mainly at half-hour horizons and do not validate a
next-minute XAUUSD setup. An inside pullback is a preregistered hypothesis, not
an academic finding or proof of profitability. V7 retains realistic spread,
placement delay, broker-grid geometry, and cost in every result.

## Closed-candle signal

At each decision, use at most the latest 60 fully closed M1 candles. The
latest candle is the pullback `P`; the preceding candle is the impulse `I`.
The 36-candle baseline precedes `I`.

Calculate:

- `M`: median positive range of the 36 baseline candles;
- range, body fraction, and close location for `I`;
- range and body fraction for `P`;
- the midpoint of `I`.

Reject if `M` is unavailable or either signal candle has non-positive range.

### Bullish impulse, inside pullback, BUY

All conditions are required:

1. `I.range >= 1.25 * M`.
2. `I` is bullish and its body is at least 60% of its range.
3. `I.close` is in the upper 25% of its range.
4. `P` is bearish and its body is at least 25% of its range.
5. `P.range <= 0.75 * M`.
6. `P.high <= I.high` and `P.low >= I.low`.
7. `P.close >= midpoint(I)`.

Direction is BUY. The frozen breakout boundary is `P.high` and structural
invalidation is `P.low`.

### Bearish impulse, inside pullback, SELL

Use the exact mirror:

1. `I.range >= 1.25 * M`.
2. `I` is bearish and its body is at least 60% of its range.
3. `I.close` is in the lower 25% of its range.
4. `P` is bullish and its body is at least 25% of its range.
5. `P.range <= 0.75 * M`.
6. `P.high <= I.high` and `P.low >= I.low`.
7. `P.close <= midpoint(I)`.

Direction is SELL. The frozen breakout boundary is `P.low` and structural
invalidation is `P.high`.

No clock, session, news, direction, volume, repeated-level, touch-count,
score, or prior-candidate-outcome filter is allowed.

## Causal post-close execution

1. Arm only when `P` is fully closed and knowable.
2. Wait five seconds after `P` closes.
3. BUY requires two valid, causally ordered quotes with `bid > midpoint(P)`
   and `ask < P.high`, separated by at least one second. SELL requires the
   exact mirror: `ask < midpoint(P)` and `bid > P.low`. A quote outside the
   required state resets the one-second observation.
4. Invalidate BUY if `bid < P.low`; invalidate SELL if `ask > P.high`.
5. At the second qualifying quote, trigger and wait five seconds.
6. At placement, recheck quote validity, structural invalidation, and whether
   the breakout entry has already crossed.
7. Place a simulated future BUY stop one tick above `P.high` or SELL stop one
   tick below `P.low`, snapped directionally away from the boundary. A stop
   must remain strictly beyond the current executable quote.
8. Use `P.low`/`P.high` as the protective stop, expanded outward only when
   required by the `0.35` minimum stop or `1.20` spread multiple. Snap the
   protective stop outward before checking final risk.
9. Reject final broker-grid risk above `1.50` or boundary-to-entry drift above
   `0.15R`.
10. A later tick alone may fill. Cancel after 20 seconds or the 90-second
    absolute lifecycle cap, whichever occurs first.

Use a `1.50R` target snapped conservatively, modeled round-trip cost of
`0.05R`, and constant research volume. Preserve one active lifecycle, durable
reset, two-loss pause, intrabar adverse exit, closed-candle rejection exit,
partial/break-even protection, complete telemetry, and zero broker mutation.

## Discovery folds and stop gate

Replay the same three already-saved chronological discovery folds separately
and aggregate their rows:

- `2026-06-01T00:00:00Z` to `2026-06-08T00:00:00Z`;
- `2026-06-08T00:00:00Z` to `2026-06-15T00:00:00Z`;
- `2026-06-15T00:00:00Z` to `2026-06-22T00:00:00Z`.

These repeatedly studied fixtures may reject V7 but cannot approve trading.
Pass requires all of:

- at least 30 fills across at least 10 UTC sessions;
- net positive, profit factor at least `1.15`, and expectancy at least
  `+0.05R` after cost;
- BUY and SELL both positive and both directional families positive;
- at least 50% profitable sessions;
- at least two of three weekly folds net positive;
- maximum portfolio drawdown no more than `8R`;
- maximum aggregate loss streak no more than six;
- trigger rate at least 40%, placement rate at least 50%, placed-stop fill
  rate at least 40%, crossed-at-placement rate no more than 10%, and geometry
  rejection rate no more than 10%;
- median boundary-to-fill drift no more than `0.15R` and p95 drift no more
  than `0.35R`;
- zero safety failures and zero broker mutation.

Any failure rejects V7 without threshold, target, stop, session, direction,
or subgroup tuning.

## Untouched held-out and prospective

Only after discovery passes may the collector fetch the sealed
`2026-06-22T00:00:00Z` through `2026-06-29T00:00:00Z` range. Held-out requires
at least 15 fills across five sessions, PF `1.25`, expectancy `+0.10R`, net
positive, at least 60% profitable sessions, both directions and families
positive, drawdown no more than `6R`, loss streak no more than five, no more
than 50% of gross profit from one session, no more than 65% from one direction
or family, positive net without the best session, positive net under an extra
`0.05R` per-fill cost, all V7 execution gates, and zero safety failures.

Only after held-out passes may a new future prospective start timestamp be
recorded. Prospective requires at least 60 fills across 10 sessions, PF
`1.20`, expectancy `+0.08R`, net positive, at least 60% profitable sessions,
and the same symmetry, concentration, cost-stress, execution, drawdown,
loss-streak, and safety requirements.

Order-capable DEMO remains forbidden until every stage passes and the user
explicitly approves the smallest-volume DEMO run. LIVE remains disabled.
