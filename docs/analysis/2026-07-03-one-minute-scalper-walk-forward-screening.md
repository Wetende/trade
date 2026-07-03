# One Minute Scalper Walk-Forward Screening

**Date:** 2026-07-03  
**Decision:** `NO_WALK_FORWARD_CANDIDATE`

## Method

Three sanitized sessions were evaluated with leave-one-session-out selection.
The pre-registered grammar generated 3,240 unique one- and two-clause rules
from pre-entry telemetry only. Each fold trained on two sessions and reserved
the third for one-time held-out scoring.

Training eligibility required:

- at least 60% fill retention;
- positive expectancy;
- no missing evidence required by the rule.

## Result

No rule met the training eligibility requirements in any fold.

| Held-out session | Eligible frozen rule | Held-out fills |
|---|---|---:|
| Initial 21-trade session | None | 0 |
| First 18-trade evidence session | None | 0 |
| Post-change 32-trade session | None | 0 |

Because no rule was frozen, held-out P/L was not manufactured from a
lower-ranked or retrospectively selected rule. The aggregate gate correctly
failed with:

```text
NON_POSITIVE_EXPECTANCY
PROFIT_FACTOR_BELOW_1_15
FEWER_THAN_TWO_PROFITABLE_SESSIONS
FILL_RETENTION_BELOW_0_60
NO_RULE_FOR_FOLD
```

## Reproducibility

Two independent outputs were byte-identical:

```text
SHA-256 2C0B5003D7571F1BE0793D11CCD3FF28EDA120D760F70E98C09B4A4E247A1E08
```

The result contains sanitized fixture hashes, fixed grid version, fold
results, metrics, and `broker_mutation_enabled: false`.

## Conclusion

The current signal's recorded pre-entry fields cannot support an acceptable
selector at the required retention level. Manual threshold tuning and shallow
feature conjunctions are rejected.

No candidate advances to prospective shadow validation. Execution remains
stopped. The next hypothesis must alter how an opening is confirmed or
constructed, then be replayed prospectively; filtering the current selected
trade population is insufficient.
