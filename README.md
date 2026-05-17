# Price Action Playbook Trading Assistant

This repo is being refactored into a focused 15-minute price-action trading assistant.
The old multi-agent research-firm workflow has been removed from the active path.

The active pipeline is:

```text
Price Action Analyst -> Trader -> Order Proposal
```

The first implementation pass creates the new architecture and stable tool contracts.
The mathematical playbook detectors are currently stubs that return `NO_SETUP`, so the
system defaults to `HOLD` until detector logic is implemented.

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

## Development

Run tests with:

```bash
uv run --group dev pytest
```
