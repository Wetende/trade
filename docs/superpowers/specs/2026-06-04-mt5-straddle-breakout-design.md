# MT5 Straddle Breakout Design

## Goal

Add an isolated MT5 straddle-breakout strategy that can run in dry-run mode first, while preparing a guarded broker-execution path for later live/demo activation.

## Design

The straddle strategy is a sidecar, not a change to the current price-action engine. It builds a short-term range from MT5-native candles, proposes one `BUY_STOP` above the range and one `SELL_STOP` below it, and uses fixed geometry based on the reverse-engineered bot: 6.0 points stop distance and 9.0 points target distance.

Dry-run mode validates both pending-order requests with the existing MT5 request builder, journals the proposed pair, and stores separate straddle state. Live mode will use the same validated pair path, but only when explicitly requested with `--live`; if the second order fails, the first order is cancelled immediately.

The current price-action runner also gets a small risk-control improvement: configurable strategy/side blocking rules, so weak combinations such as `SUPPORT_RESISTANCE_BOUNCE:SELL` can be disabled without changing the strategy engine.

## Initial Scope

- Build straddle pair proposal generation.
- Add dry-run paired-order validation and journaling.
- Add explicit live-ready paired placement path behind `--live`.
- Add isolated straddle state file.
- Add `mt5-straddle-run` CLI command.
- Add blocked strategy/side rules to `mt5-run`.
- Cover behavior with tests before implementation.
