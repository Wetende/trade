# One Minute Shock-Reclaim V6 Design

## Candidate

`ONE_MINUTE_SHOCK_RECLAIM_V6`

Frozen before V6 arms, triggers, fills, or outcomes are calculated on any
saved fixture.

## Research basis and limits

V1 through V4 rejected the symmetric repeated-level post-close population.
V5 and V5.1 rejected compression break and hold execution. The earlier
opening-state continuation candidate also failed realistic prospective
evidence. V6 must therefore test a different market story rather than select a
direction, family, session, or threshold from those outcomes.

Primary research reports short-horizon reversal after some extreme intraday
moves, with faster initial reversals in higher-volatility conditions:

- https://doi.org/10.1016/j.qref.2021.05.004
- https://doi.org/10.3386/w30917

This evidence is not XAUUSD proof. Gold-specific research finds that some
intraday jumps are information-driven, US macroeconomic announcements explain
a material share of them, and gold adjustment after FOMC shocks can continue
for more than five minutes:

- https://doi.org/10.1016/j.irfa.2025.104380
- https://doi.org/10.1016/j.irfa.2024.103486

Accordingly, V6 does not fade every large move. It requires a genuine closed
break, a second fully closed opposite reclaim, and new post-close persistence
inside the reclaimed boundary. Transaction costs and realistic placement are
part of every result. No source establishes that V6 will be profitable.

## Closed-candle signal

At each decision, use at most the latest 60 fully closed M1 candles. The
latest candle is the reclaim candle `R`; the preceding candle is the shock
candle `S`. All baseline and reference candles precede `S`.

Calculate:

- `M`: median positive range of the preceding 36 candles;
- `H`: highest high of the preceding 12 candles;
- `L`: lowest low of the preceding 12 candles;
- shock range and body from `S`;
- reclaim range and body from `R`.

Reject if either signal candle has non-positive range or `M` is unavailable.

### High shock, reclaim, SELL

All conditions are required:

1. `S.range >= 1.50 * M`.
2. `S` is bullish and its body is at least 60% of its range.
3. `S.close >= H + 0.10 * M`.
4. `S.close` is in the upper 20% of `S.range`.
5. `R` is bearish and its body is at least 50% of its range.
6. `R.high >= H` and `R.close <= H - 0.10 * M`.
7. `R.close` is in the lower 30% of `R.range`.

The frozen boundary is `H`. Direction is SELL. Structural invalidation is
`H + 0.10 * M`.

### Low shock, reclaim, BUY

Use the exact mirror:

1. `S.range >= 1.50 * M`.
2. `S` is bearish and its body is at least 60% of its range.
3. `S.close <= L - 0.10 * M`.
4. `S.close` is in the lower 20% of `S.range`.
5. `R` is bullish and its body is at least 50% of its range.
6. `R.low <= L` and `R.close >= L + 0.10 * M`.
7. `R.close` is in the upper 30% of `R.range`.

The frozen boundary is `L`. Direction is BUY. Structural invalidation is
`L - 0.10 * M`.

No clock, session, news, direction, volume, touch-count, score, or earlier
candidate-outcome filter is allowed.

## Causal post-close execution

1. Arm only when `R` is fully closed and knowable.
2. Wait five seconds after `R` closes.
3. SELL requires two valid, causally ordered quotes with `ask < H`, separated
   by at least one second. BUY requires the mirrored `bid > L`. A quote back
   outside the boundary resets the one-second observation.
4. At the second qualifying quote, trigger the setup and wait five seconds.
5. At placement, recheck structural invalidation and current quote validity.
6. Place a simulated future stop one tick below the current bid for SELL or
   one tick above the current ask for BUY. Snap directionally so the stop stays
   strictly beyond the current quote.
7. Use the frozen invalidation, expanded outward only when required by the
   `0.35` minimum stop or `1.20` spread multiple. Snap the protective stop
   outward before checking risk.
8. Reject final broker-grid risk above `1.50` or level-to-entry drift above
   `0.75R`.
9. A later tick alone may fill. Cancel after 20 seconds or the 90-second
   absolute lifecycle cap, whichever occurs first.

Use a `1.50R` target snapped conservatively, modeled round-trip cost of
`0.05R`, and constant research volume. Preserve one active lifecycle, durable
reset, structural invalidation, two-loss pause, intrabar adverse exit,
closed-candle rejection exit, partial/break-even protection, and complete
telemetry. Broker mutation remains disabled.

## Discovery folds and stop gate

Replay the three already-saved chronological weekly folds separately and then
aggregate rows:

- `2026-06-01T00:00:00Z` to `2026-06-08T00:00:00Z`;
- `2026-06-08T00:00:00Z` to `2026-06-15T00:00:00Z`;
- `2026-06-15T00:00:00Z` to `2026-06-22T00:00:00Z`.

These fixtures are prior research data, so discovery can reject V6 but cannot
approve it for trading. Pass requires all of:

- at least 30 fills across at least 10 UTC sessions;
- net positive, profit factor at least `1.15`, and expectancy at least
  `+0.05R` after cost;
- BUY and SELL both positive and both directional families positive;
- at least 50% profitable sessions;
- at least two of three weekly folds net positive;
- maximum portfolio drawdown no more than `8R`;
- maximum aggregate loss streak no more than six;
- trigger rate at least 50%, placement rate at least 60%, placed-stop fill
  rate at least 50%, geometry-rejection rate no more than 10%;
- median drift no more than `0.50R` and p95 drift no more than `0.75R`;
- zero crossed-at-placement or safety failures.

Any failure rejects V6 without threshold, target, session, direction, or
subgroup tuning.

## Untouched held-out and prospective

Only after discovery passes may the collector fetch the still-sealed
`2026-06-22T00:00:00Z` through `2026-06-29T00:00:00Z` range. Held-out requires
at least 15 fills across five sessions, PF `1.25`, expectancy `+0.10R`, net
positive, at least 60% profitable sessions, both directions and families
positive, drawdown no more than `6R`, loss streak no more than five, no more
than 50% of gross profit from one session, no more than 65% from one direction
or family, positive net without the best session, positive net under an extra
`0.05R` per-fill cost, all execution gates, and zero safety failures.

Only after held-out passes may a new future prospective start timestamp be
recorded. Prospective requires at least 60 fills across 10 sessions, PF
`1.20`, expectancy `+0.08R`, net positive, at least 60% profitable sessions,
the same symmetry, concentration, cost-stress, execution, drawdown, loss-
streak, and zero-safety requirements.

Order-capable DEMO remains forbidden until every stage passes and the user
explicitly approves the smallest-volume DEMO run. LIVE remains disabled.

