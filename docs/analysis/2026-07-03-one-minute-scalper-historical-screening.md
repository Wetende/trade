# One Minute Scalper Historical Screening

**Date:** 2026-07-03  
**Evidence:** three sanitized sessions, 94 placed orders, 71 fills

## Decision

No pre-registered candidate qualifies for prospective shadow validation.
There is no frozen candidate manifest and broker execution remains stopped.

## Results

| Variant | Fills | W-L | Net P/L | Profit factor | Expectancy | Profitable sessions |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 71 | 23-48 | -1856.90 | 0.401 | -26.15 | 0 |
| H1: three-touch impulse | 63 | 22-41 | -1456.90 | 0.458 | -23.13 | 0 |
| H2: exhaustion ceiling | 48 | 15-33 | -1291.10 | 0.394 | -26.90 | 0 |
| H3: five-minute post-loss delay | 49 | 15-34 | -1238.00 | 0.416 | -25.27 | 0 |
| H1 + H2 | 45 | 15-30 | -1124.10 | 0.428 | -24.98 | 0 |
| H1 + H3 | 46 | 16-30 | -1022.40 | 0.479 | -22.23 | 0 |
| H2 + H3 | 37 | 12-25 | -915.90 | 0.419 | -24.75 | 0 |

H2 variants also fail evidence completeness because the oldest session
predates body-ratio telemetry. Missing values were retained as missing and
were not inferred.

## Gate audit

Every candidate failed all three primary economic requirements:

- expectancy was negative;
- profit factor was below `1.15`;
- zero sessions were profitable.

H2 + H3 also retained less than 60% of baseline fills. No result was promoted
because it lost less money than the baseline.

## Reproducibility and safety

The screening report was generated twice with byte-identical SHA-256:

```text
8969518C58B73ABB032325E0184FC334C4F56E67CB1D0DD14D27C7504AC74B4A
```

The evidence schema contains no account, login, broker ticket, order, deal,
position, credential, server, terminal, or private path fields. The screening
command imports no broker executor and records:

```text
broker_mutation_enabled = false
```

## Conclusion

Touch maturity, a symmetric body ceiling, and post-loss timing reduce exposure
but do not create positive expectancy. These hypotheses are rejected. The next
design must address the residual entry classifier, especially false bullish
impulse continuation, rather than combine or retune these failed thresholds.
