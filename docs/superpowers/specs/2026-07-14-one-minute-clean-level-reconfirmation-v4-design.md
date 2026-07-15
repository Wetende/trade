# One Minute Clean-Level Reconfirmation V4 Design

## Candidate

`ONE_MINUTE_CLEAN_LEVEL_RECONFIRMATION_V4`

Frozen before implementation outcomes or V4 data are inspected.

## Hypothesis

The prior candidates used raw repeated extrema. The authoritative playbook
requires clean levels whose touches are structurally separated and visibly
react. V4 tests that missing rule while retaining V3's causal
validation-retest-reconfirmation execution.

## Clean-Level Detector

Use exactly the latest 60 fully closed M1 candles and the unchanged tolerance:

`T = max(0.20, 0.20 * median positive M1 candle range)`

For highs use candle highs; for lows use candle lows. Extrema within `T` may
belong to one zone. Accept touches greedily in timestamp order only when:

1. The new touch is at least three closed bars after the prior accepted touch,
   or price made an interim excursion at least `2T` away from the level.
2. Between the prior touch and the new touch, at least one closed candle moved
   away from the level by `1.5T`: below a high or above a low.
3. After the last accepted base touch and before the confirmation candle, at
   least one closed candle also moved away by `1.5T`.

Require at least two accepted touches. Calculate the level as the mean of only
accepted touch prices. Consolidate overlapping same-side clean zones using
the existing deterministic newest-touch, touch-count, spread, side, and level
ordering.

Adjacent extrema without a closed reaction are one interaction, not multiple
touches. No touch-count, age, direction, session, or outcome filter is added.

## Signal And Execution

Use all six symmetric playbook families and V3 unchanged for:

- closed-candle confirmation;
- post-close validation after five seconds;
- retest observation;
- five-second delayed stop placement;
- BUY stop at `zone_high + B`, SELL stop at `zone_low - B`;
- later-tick fill only;
- 15-second stop expiry and 90-second absolute state cap;
- structural invalidation, 1.00 maximum stop, 1.20 spread multiple, 1.50R
  target, 0.05R modeled cost, constant volume;
- one active lifecycle, reset, two-loss pause, and protective management.

`B = max(0.05, 0.25T)`.

## Discovery And Walk-Forward Stop

The rule has no fitted thresholds. Report each UTC day as a chronological
fixed-rule fold on the discovery window.

Discovery requires:

- at least 30 fills across at least five UTC days;
- PF at least 1.15 and expectancy at least +0.05R after costs;
- positive net in BUY and SELL;
- at least two positive economic families;
- at least 50% profitable UTC days;
- drawdown no more than 8R and loss streak no more than 6;
- V3 executability gates.

Failure rejects V4. Do not tune the structural multiples or entry rules on
the discovery window.

## Held-Out And Prospective

Held-out and prospective use the previously frozen economic, concentration,
drawdown, session, cost, and V3 executability gates. Held-out requires 100
fills and 10 sessions; prospective requires 60 fills and 10 sessions/days.

Zero tolerance applies to forming candles, lookahead, pre-placement fill,
post-expiry fill, simultaneous lifecycle, state-orphan ordering, broker
mutation in replay/shadow, or any manifest/data-window change.
