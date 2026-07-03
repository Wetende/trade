# Price Action Playbook Trading Assistant

This repo is being refactored into a focused 15-minute price-action trading assistant.
The old multi-agent research-firm workflow has been removed from the active path.

The current isolated MT5 forward-test model is the deterministic One Minute
Scalper. It uses closed M1 candles and engine decisions only; no LLM chooses
BUY, SELL, HOLD, size, or exits. Start with:

- [One Minute Scalper handoff](docs/one-minute-scalper-handoff-2026-07-01.md)
- [New-machine migration guide](docs/one-minute-scalper-machine-migration.md)
- [Current forensic review](docs/analysis/2026-07-02-one-minute-scalper-forensic-review.md)
- [Post-change impulse loss review](docs/analysis/2026-07-02-one-minute-scalper-impulse-loss-review.md)
- [Windows setup script](scripts/setup-windows.ps1)
- [Safe DEMO runner script](scripts/start-one-minute-demo.ps1)
- [Read-only opening-state shadow watcher](scripts/start-opening-state-shadow-watch.ps1)

The active pipeline is:

```text
Price Action Analyst -> Trader -> Order Proposal
```

The current implementation includes deterministic playbook detection, risk
checks, proposal generation, and guarded MT5 execution. The system still
defaults to `HOLD` unless a complete A+ checklist passes.

## Playbook

The assistant is built around three setups:

- The Breakout
- Buys/Sells off Support/Resistance
- The Break and Retest, including impulse variations

The default trading timeframe is `15m`, with `30m` confirmation and
`America/New_York` market-time interpretation.

## Configuration

Copy `.env.example` to `.env` and set the API key for your chosen LLM provider.

Useful price-action settings:

```bash
TRADINGAGENTS_TIMEFRAME=15m
TRADINGAGENTS_CONFIRMATION_TIMEFRAME=30m
TRADINGAGENTS_MARKET_TIMEZONE=America/New_York
```

## Run

```bash
pip install .
tradingagents
```

The CLI asks for a ticker, an as-of timestamp, provider/model choices, then writes:

- a markdown report under the configured results directory
- a local JSON order proposal under `order_proposals/`

No live broker orders are placed.

## MT5 Broker Execution

The MT5 execution layer runs through MetaTrader 5 Desktop on Windows. Configure
one broker connection with MT5 credentials, symbol, volume, expected login, and
expected server. TradingAgents reads the account type from MT5 at runtime, and
broker order sending requires a real-money acknowledgement when MT5 reports a
real account.

Follow the Windows and VPS runbook here:

- [MT5 Broker Execution on Windows and VPS](docs/mt5-windows-vps.md)
- [MT5 Broker Execution on Windows](docs/mt5-windows.md)
- [Windows AI Agent Handoff](docs/windows-agent-handoff.md)

## Development

Run tests with:

```bash
uv run --group dev pytest
```
