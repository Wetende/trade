# One Minute Symmetric Post-Close V1 Design

## Status

Pre-registered implementation and evaluation contract. This document is
frozen before outcome evaluation. Any economic behavior change creates a new
candidate version and requires new untouched evidence.

## Candidate

`ONE_MINUTE_SYMMETRIC_POST_CLOSE_STATE_V1`

The hypothesis is that a repeated-level story has executable edge only when a
new quote event after the confirmation candle has closed validates that story.
The confirmation candle arms a setup; it never creates a historical fill.

## Safety Boundary

- Use only the latest 60 fully closed M1 candles.
- Treat an M1 timestamp as its open time. The candle is knowable only 60
  seconds later.
- Require a valid post-close quote event before a trigger.
- Require another five seconds before simulated placement.
- Permit one armed setup, pending order, or position globally.
- Research, replay, and prospective shadow are broker read-only.
- Do not enable order-capable DEMO without a frozen prospective pass and
  explicit user approval.
- Keep existing account, spread, stop, stale-order, fast-loss, partial,
  break-even, trailing, rejection-exit, and consumed-opening protections.

## Shared Formulas

- Memory: latest 60 fully closed M1 candles.
- Level tolerance `T`: `max(0.20, 0.20 * median positive M1 range)`.
- Zone: `[level - T, level + T]`.
- Break margin `B`: `max(0.05, 0.25 * T)`.
- Trigger eligibility: confirmation close plus five seconds.
- Simulated placement: trigger plus five seconds.
- Arm expiry: confirmation close plus 45 seconds for respect/failed-break;
  plus 60 seconds for confirmed-break.
- Minimum initial risk: maximum of broker/configured minimum stop and
  `1.20 * current spread`.
- Maximum initial stop: 1.00 price unit.
- Maximum entry drift from the frozen level: `min(3T, 2R)`.
- Volume is constant in research. No confidence or loss-recovery boost.

## Stage A: Closed-Candle Detection And Arming

Consolidate repeated high and low zones from closed candles. Two touches are
eligible; a third touch affects deterministic rank but is not mandatory.
Reject overlapping eight-candle chop. Generate the six symmetric families:

- `HIGH_RESPECT_SELL`
- `HIGH_BREAK_BUY`
- `FAILED_HIGH_BREAK_SELL`
- `LOW_RESPECT_BUY`
- `LOW_BREAK_SELL`
- `FAILED_LOW_BREAK_BUY`

Respect and failed-break confirmations require a non-mixed rejection,
engulfing, or strong directional close. Confirmed breaks require a decisive
directional close. Wick-only breaks do not qualify.

Rank candidates deterministically by confirmation quality, newest structural
touch, touch count, then stable family/side/level tie breakers. Freeze only the
best candidate with its level, zone, family, direction, confirmation candle,
structural invalidation, trigger rule, and absolute expiry.

## Stage B: New Post-Close Trigger

All observations must be valid bid/ask quotes at or after trigger eligibility.

- High-respect sell: ask observes the zone, then bid trades below
  `zone_low - B` before ask breaches invalidation.
- Low-respect buy: bid observes the zone, then ask trades above
  `zone_high + B` before bid breaches invalidation.
- High-break buy: bid remains above `zone_high` in two observations at least
  one second apart, or price retests the zone and ask resumes above
  `zone_high + B`.
- Low-break sell: ask remains below `zone_low` in two observations at least
  one second apart, or price retests the zone and bid resumes below
  `zone_low - B`.
- Failed-high-break sell: after a post-close zone observation, bid trades
  below `zone_low - B` without ask regaining invalidation.
- Failed-low-break buy: after a post-close zone observation, ask trades above
  `zone_high + B` without bid regaining invalidation.

Respect/failed-high sell invalidation is above the greater of confirmation
high and `zone_high + B`; the buy mirror is below the lesser of confirmation
low and `zone_low - B`. Break invalidation is through the opposite zone edge
plus `B`.

## Placement

At simulated placement, use current ask for BUY and current bid for SELL.
Recheck expiry, safety, quote validity, drift, spread/risk, maximum stop,
broker distance, and structural invalidation. Reject rather than reprice into
a chase. A fill cannot precede confirmation close, trigger, or placement.

## Management And Reset

Keep current protective management unchanged for V1. Report every result in
initial R after spread and modeled slippage.

Consume an armed fingerprint after placement, rejection, invalidation, or
expiry. The same zone may re-arm only after price moved at least `2T` fully
away and returned, a new two-touch structure formed with later structural
timestamps, or a different closed break/reclaim family formed.

After two consecutive filled-trade losses, block new arms until 15 minutes
have elapsed and a structural reset has completed. Restart cannot clear the
pause or extend expiry.

## Frozen Evaluation Gates

Held-out requires at least 100 fills and 10 independent sessions; prospective
requires at least 60 fills and 10 independent sessions/days.

Held-out/prospective gates respectively:

- Profit factor at least 1.25 / 1.20 after costs.
- Expectancy at least +0.10R / +0.08R after costs.
- Positive net R.
- At least 60% profitable sessions.
- Portfolio drawdown no more than 8R; session drawdown no more than 3R.
- Maximum loss streak no more than 6.
- Best session no more than 30% / 35% of gross profit.
- Best family no more than 50% / 60%; best direction no more than 65% / 70%.
- Trigger rate at least 15% of armed setups.
- Placement/fill success at least 85% of valid triggers.
- Expiry no more than 50% of arms; crossed-at-send no more than 15% of
  triggers; broker/geometry rejects no more than 5% of triggers.
- Median/95th placement drift no more than 0.15R / 0.35R.
- Median/95th slippage no more than 0.05R / 0.15R.
- Remains profitable after removing the best session and after adding 0.05R
  cost per fill.

Zero tolerance: forming-candle use, bar-timestamp lookahead, post-expiry
entry, simultaneous lifecycle, broker mutation in research/shadow, non-DEMO
order-capable execution, orphan state capable of ordering, restart extending
expiry, incomplete decision/send/fill/exit quote evidence, or a changed
manifest/start/code hash during a frozen window.

## Stop Rule

Failure of a primary economic, concentration, executability, or safety gate
rejects V1. Do not repair V1 by adding filters. A materially different
hypothesis must be versioned and evaluated on new untouched evidence.
