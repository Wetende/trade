# One Minute Compression-Expansion V5 Discovery Review

**Candidate:** `ONE_MINUTE_COMPRESSION_EXPANSION_V5`
**Stage:** discovery only
**Decision:** `FAIL_DISCOVERY_STOP`
**Broker mutation:** disabled

## Frozen artifacts

- Manifest SHA-256:
  `4C72B634A00EAA37BAE49537889315DAF8372D46BC9477368BB16767D2DFB6CF`
- Signal implementation SHA-256 before replay:
  `009EFA356A77CA1EA9C4CDA0F05AAE7F1B2B097D455FEF8543A8DD7FDFB3AE88`
- Source fixture SHA-256:
  `29F806CBFA0EC0E1B048CC0E49BB995B3B11FCA939FDA59DAF004FFD4D8B8675`
- Report SHA-256:
  `07411D65C5DA112750C2B2FB39BC34E02F3518BAA6B272E403B0FED4DEA28294`
- Report:
  `test-artifacts/post-close-v5/2026-07-15-discovery/discovery-report.json`

## Result

| Metric | Result |
| --- | ---: |
| Arms / triggers | 26 / 25 |
| Retests / stop placements | 11 / 8 |
| Fills | 2 |
| Wins / losses | 1 / 1 |
| Net | +0.2506R |
| Profit factor | 1.5487 |
| Expectancy | +0.1253R |
| Profitable sessions | 1 / 2 |
| Maximum drawdown | 0.4568R |
| Median / p95 fill drift | 0.0233R / 0.0291R |

The two-fill aggregate is positive but is not evidence of a robust edge. V5
failed the frozen minimum of 30 fills across five sessions. BUY produced one
loss (`-0.4568R`) and SELL produced one win (`+0.7074R`), so it also failed
the positive-both-directions and two-positive-families requirements. Stop fill
rate was 25%, below the 30% executability gate.

## Decision

V5 is rejected at discovery. The positive aggregate cannot be promoted,
annualized, or used to weaken the sample-size gate. Thresholds, expiry,
direction, retest behavior, and box definitions must not be tuned on these
outcomes.

The reserved `2026-06-22T00:00:00Z` through `2026-06-29T00:00:00Z` held-out
range was not fetched or inspected. No V5 prospective or order-capable DEMO
process may start.

The reusable deliverables are the causal compression detector, deterministic
replay integration, frozen evaluation, and safety-tested read-only DEMO
connectivity monitor. That monitor observes connection and flat-account state
only; it does not run V5 or call execution APIs.
