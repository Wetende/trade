# Time Filter Mode Design

## Goal

Let demo validation continue through Sunday/Asian low-liquidity windows without deleting the production safety rule.

## Modes

- `block`: default production behavior. A failed time/session rule immediately returns HOLD.
- `observe`: continue scanning and record candidate setups, but keep failed time rules in the checklist so no brokerable setup is approved.
- `allow`: demo validation behavior. Failed time/session rules are treated as passed so the bot can test setup detection and execution.

## Configuration

Set `TRADINGAGENTS_TIME_FILTER_MODE` in the current process.

Use `allow` only for short demo validation runs. Use `observe` when studying market behavior during low-liquidity windows. Keep `block` for normal production safety.

## Telemetry

Telemetry records `market_context.time_filter_mode` so run summaries can explain whether time rules were blocked, observed, or bypassed.
