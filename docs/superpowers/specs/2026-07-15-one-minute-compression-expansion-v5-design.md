# One Minute Compression-Expansion V5 Design

## Candidate

`ONE_MINUTE_COMPRESSION_EXPANSION_V5`

Frozen before V5 outcomes are calculated. V5 is a materially different market
hypothesis from the rejected repeated-level V1-V4 population.

## Research basis

Published intraday research reports time-series momentum across international
markets and stronger effects in volatile/information-rich conditions. Opening
range research likewise tests continuation after unusually large range
breaks, while cautioning that results vary through time. V5 translates those
ideas into a causal, symmetric, friction-aware M1 hypothesis; the literature
is motivation, not evidence that XAUUSD will be profitable.

- Li, Sakkas, and Urquhart, *Intraday Time Series Momentum: Global Evidence
  and Links to Market Characteristics*, DOI `10.2139/ssrn.3460965`.
- Holmberg, Lönnbark, and Lundström, *Assessing the profitability of intraday
  opening range breakout strategies*, DOI `10.1016/j.frl.2012.09.001`.
- Andersen, Bollerslev, Diebold, and Labys, *Modeling and Forecasting Realized
  Volatility*, NBER Working Paper 8160, DOI `10.3386/w8160`.
- Daniel, Jagannathan, and Kim, *Tail Risk in Momentum Strategy Returns*, NBER
  Working Paper 18169, DOI `10.3386/w18169`.

## Causal signal

At each fully closed M1 decision use exactly 49 candles:

- the latest candle is confirmation;
- the preceding 12 candles are the compression box;
- the 36 candles before the box are the volatility baseline.

Let `BR` be the median positive high-low range of the 36 baseline candles and
`CR` the equivalent median for the 12 compression candles.

The box is eligible only when:

1. `CR <= 0.70 * BR`;
2. box high minus box low is no more than `3.0 * BR`;
3. directional efficiency is no more than `0.40`, where efficiency is the
   absolute box open-to-close move divided by the sum of absolute candle-body
   moves.

Let:

- `T = max(0.10, 0.10 * BR)`;
- `B = max(0.05, 0.10 * BR)`.

A BUY confirmation must close above `box_high + T + B`. A SELL confirmation
is the exact mirror below `box_low - T - B`. In either direction:

- body is at least 60% of candle range;
- close is in the directional outer 20% of the candle;
- candle range is at least `1.25 * CR` and no more than `3.0 * BR`.

The confirmation candle is never a fill. It creates one arm at the box
boundary. BUY and SELL definitions are exact mirrors. There are no clock,
session, volume, direction, or outcome filters.

## Post-close execution

Use the already-tested causal reconfirmation lifecycle:

1. Wait five seconds after the confirmation close.
2. Observe that price still holds beyond the broken box.
3. Wait for a post-close retest of the frozen boundary zone.
4. Wait another five seconds.
5. Place a stop at `zone_high + B` for BUY or `zone_low - B` for SELL.
6. Only a later tick may fill the order.

The structural invalidation is `box_high - max(0.20, 0.50*CR)` for BUY and
`box_low + max(0.20, 0.50*CR)` for SELL. The absolute state cap is 180 seconds;
the reconfirmation stop expires after 20 seconds.

Frozen execution and management:

- minimum stop distance `0.35`;
- maximum stop distance `1.50`;
- minimum stop/spread multiple `1.20`;
- target `1.50R`;
- modeled round-trip cost `0.05R` per fill;
- constant research volume;
- one active lifecycle, durable reset, two-loss pause, fast adverse exit,
  partial protection, break-even, candle rejection, and full journaling.

## Gates

Discovery requires at least 30 fills over five UTC sessions, PF at least 1.15,
expectancy at least +0.05R after cost, positive BUY and SELL, both directional
families positive, at least 50% profitable sessions, drawdown no more than 8R,
loss streak no more than six, and the V3 reconfirmation executability gates.

Failure stops V5. Do not tune thresholds, select a direction/session, or open
held-out data after failure.

If discovery passes, evaluate the untouched held-out range once with the
unchanged manifest and code. Held-out and prospective use the frozen V1
economic, concentration, drawdown, cost, session, and executability gates.
Order-capable DEMO remains forbidden unless discovery, held-out, and fresh
prospective evidence all pass and the user explicitly approves it.
