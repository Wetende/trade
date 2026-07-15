# One Minute V5.1 Conformance Correction

Recorded before rerunning the frozen discovery folds.

## Scope

The first V5.1 discovery replay exposed no runtime exception, but a subsequent
causal-lifecycle audit found two implementation mismatches with the already
frozen design:

1. V5.1 used the shared breakout observer, which could trigger on the older
   retest-resume path after a quote entered the box. The frozen V5.1 design
   permits only two causally ordered quotes holding beyond the boundary for at
   least one second.
2. A triggered hold setup was still checked against the compression signal's
   120-second armed-state timer at placement. The frozen V5.1 design permits
   an already triggered lifecycle to continue until its 180-second absolute
   state cap.

The first correction disables only the retest-resume shortcut for the V5.1
entry policy and applies the frozen 180-second cap after a valid hold trigger.
A separate telemetry correction names an unfilled hold stop
`PENDING_HOLD_STOP_EXPIRED` while retaining it in the generic pending-expiry
metric.

No signal threshold, discovery range, direction, session, stop-distance
limit, target, cost, risk rule, management rule, gate, or held-out boundary is
changed. The same saved read-only discovery fixtures must be replayed. The
old nonconformant output must not be used as evidence.

## Pre-rerun hashes

- Manifest SHA-256:
  `C70A257A35021949540BE72EE7DD78C875C95981561A7BFE36B6AD2B6CB33340`.
- State implementation SHA-256:
  `36300DD0DE9EB2FD528FE018DB8CBD9C233258A468E29FC44DD916E5055154A3`.
- Replay implementation SHA-256:
  `458FD20A9FBEF71535FDAC8137A48CC62949E0756D88DDB67CD8404DF560CA5D`.
- Evaluation implementation SHA-256:
  `32AE78607F31A74B9FCE2E2617804DD5B4538E5434C3D68FA0E088D426DFB296`.

Focused conformance and regression verification before rerun: 58 passed.

## Post-rerun record

- Conformant report SHA-256:
  `C878EAA2EB1D9424641DBE606FBABA6EFBF4D3BF54BE571DDEF141AB77F852A8`.
- Superseded nonconformant report SHA-256:
  `B19A345C156CD3BF9B321B63491989D660B70B633D302489A071F217634DA3B9`.
- Decision: `FAIL_DISCOVERY_STOP`.

The conformant replay produced 17 fills, four wins, 13 losses, `-5.237728R`,
profit factor `0.320704`, and expectancy `-0.308102R`. It removed one
nonconforming SELL win from the superseded output. The held-out range remained
unfetched and uninspected.

## Direction-safe tick-grid addendum

A final pre-push safety audit found that the hold builder checked raw geometry
and then rounded entry, stop, and target to the nearest tick. For an off-grid
structural threshold, nearest-tick rounding could put a BUY stop below the
threshold or a SELL stop above it. It could also make final snapped risk differ
from the risk checked against the frozen `1.50` maximum.

Before another rerun, V5.1 was changed to snap entries outward, protective
stops outward, and targets conservatively on the broker tick grid, then check
the final snapped risk and structural drift. This objectively implements the
already frozen requirements that the future stop is never inside the
structural threshold and that maximum stop distance is `1.50`. No parameter or
gate changed. The `C878...` result is intermediate and is superseded by the
next same-fixture replay.

Pre-final-rerun hashes:

- State implementation SHA-256:
  `36300DD0DE9EB2FD528FE018DB8CBD9C233258A468E29FC44DD916E5055154A3`.
- Replay implementation SHA-256:
  `30ECFE6603A81D74A6622EE6147CC9C81B0C6FB4C2493ED161A5D88BA61DE566`.
- Evaluation implementation SHA-256:
  `32AE78607F31A74B9FCE2E2617804DD5B4538E5434C3D68FA0E088D426DFB296`.

Focused conformance and regression verification before the final rerun: 60
passed.

## Final rerun record

- Final conformant report SHA-256:
  `A22C4EEF33E227C3C5DEEC638656466B297B6F019FAE5FC23A9C590EEC13DBBC`.
- Intermediate pre-tick-grid report SHA-256:
  `C878EAA2EB1D9424641DBE606FBABA6EFBF4D3BF54BE571DDEF141AB77F852A8`.
- Decision: `FAIL_DISCOVERY_STOP`.

The final replay produced 17 fills, four wins, 13 losses, `-5.229206R`,
profit factor `0.319705`, and expectancy `-0.307600R`. The held-out range
remained unfetched and uninspected.
