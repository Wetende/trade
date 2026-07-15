# One Minute Quote Pressure V8 implementation status

V8 implementation is complete, but the candidate is retired and remains read-only. No promotion record was generated and no V8 DEMO runner was started.

## Verification

- Final manifest SHA-256: `89b5887119ec7a00e7b3c5fe8342eb5bbfdbc9298bee12425857cd4f423a84e4`
- Full repository: 1,158 passed, 4 environment-specific skips, 75 subtests passed
- PowerShell launcher parser: passed
- M15/M30 implementation files changed: none
- Final broker proof: DEMO, zero orders, zero positions, zero active runners, stop orders supported

## Binding discovery result

The read-only gate processed the exact three frozen folds: 20,571 candles and 12,708,961 quotes. It detected 10,936 arms but produced zero valid pressure triggers, placements, or fills. The report therefore failed and set `retired=true`.

Primary terminal counts were:

- 5,865 arm expiries
- 2,393 pressure-stop distances above the frozen one-unit maximum
- 878 pressure sample timeouts
- 706 one-active-lifecycle skips
- 612 BUY/SELL story invalidations
- 390 directional-pressure failures
- 87 directional-displacement failures

The 2,393 geometry rejections are 21.88% of detected arms. The frozen report's `geometry_rejection_rate` field is zero because its valid-trigger denominator is zero; the absolute counter and derived per-arm rate are preserved here for clarity. This does not change the decision because numerous independent gates failed.

Safety, lifecycle, restart, telemetry, lookahead, and mutation failures were all zero.

## Enforced result

The held-out window must not be opened for V8, prospective registration is forbidden, and neither 0.01 nor 1.0 order-capable promotion is allowed. The old M1 engine is also blocked from order-capable startup. Any future attempt must be a newly named, independently preregistered candidate; V8 cannot be tuned on this failed discovery window.
