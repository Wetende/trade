# Windows AI Agent Handoff

This note is for an AI agent or operator continuing this repository on the
Windows machine that runs MetaTrader 5 Desktop.

## Current State

TradingAgents now has a generic MT5 execution surface:

- Use `tradingagents mt5-execute`, `tradingagents mt5-monitor`, and
  `tradingagents mt5-run`.
- Account mode is explicit: `demo`, `real`, or `contest`.
- Analysis/data symbols and broker execution symbols are separate.
- The runner writes summary reporting for each cycle.
- The price-action engine writes raw telemetry for each analysis.
- Market data freshness is checked before a setup is trusted.
- The old MT5 demo-named commands, aliases, files, and docs have been removed.

The MT5 path is ready to verify on Windows. It is not automatically allowed to
send real-money orders. Start with `TRADINGAGENTS_MT5_EXECUTION_MODE=dry_run`.

## Do Not Skip These Guards

Before attempting any broker action, confirm `.env` has:

```bash
TRADINGAGENTS_MT5_ACCOUNT_MODE=demo
TRADINGAGENTS_MT5_EXECUTION_MODE=dry_run
TRADINGAGENTS_MT5_EXPECTED_LOGIN=<same login shown in MT5>
TRADINGAGENTS_MT5_EXPECTED_SERVER=<same server shown in MT5>
```

For a real account, broker execution additionally requires:

```bash
TRADINGAGENTS_MT5_ACCOUNT_MODE=real
TRADINGAGENTS_MT5_EXECUTION_MODE=broker
TRADINGAGENTS_MT5_ALLOW_REAL_ORDERS=I_UNDERSTAND_REAL_MONEY_IS_AT_RISK
```

Do not add that acknowledgement unless the human operator explicitly asks for
real-money broker execution.

## Windows Setup Checklist

1. Open PowerShell in the repo root.
2. Pull the latest code:

   ```powershell
   git checkout main
   git pull origin main
   ```

3. Install dependencies:

   ```powershell
   uv sync --group dev
   uv pip install MetaTrader5
   ```

4. Copy and edit environment settings:

   ```powershell
   Copy-Item .env.example .env
   notepad .env
   ```

5. Configure an LLM backend for non-interactive analysis:

   ```bash
   TRADINGAGENTS_LLM_PROVIDER=openai
   OPENAI_API_KEY=<key>
   TRADINGAGENTS_DEEP_THINK_LLM=gpt-5.4
   TRADINGAGENTS_QUICK_THINK_LLM=gpt-5.4-mini
   ```

   OpenRouter is supported as an OpenAI-compatible provider:

   ```bash
   TRADINGAGENTS_LLM_PROVIDER=openrouter
   OPENROUTER_API_KEY=<key>
   TRADINGAGENTS_DEEP_THINK_LLM=<openrouter-model-id>
   TRADINGAGENTS_QUICK_THINK_LLM=<openrouter-model-id>
   ```

   Or use Ollama:

   ```bash
   TRADINGAGENTS_LLM_PROVIDER=ollama
   OLLAMA_BASE_URL=http://localhost:11434/v1
   TRADINGAGENTS_DEEP_THINK_LLM=<installed-model>
   TRADINGAGENTS_QUICK_THINK_LLM=<installed-model>
   ```

6. Configure symbols. For gold on brokers with suffixes:

   ```bash
   TRADINGAGENTS_ANALYSIS_SYMBOL=GC=F
   TRADINGAGENTS_BROKER_SYMBOL=XAUUSD.vx
   TRADINGAGENTS_MT5_SYMBOL=XAUUSD.vx
   ```

7. Open MT5 Desktop and log into the same account/server configured in `.env`.

## Verification Commands

Run local tests first:

```powershell
uv run --group dev pytest tests/test_mt5_broker.py tests/test_mt5_execution.py tests/test_cli_mt5_execution.py tests/test_mt5_runner.py tests/test_cli_config.py tests/test_import_smoke.py -q
```

Probe MT5 without placing orders:

```powershell
uv run tradingagents broker-probe
```

Run one unattended dry-run cycle:

```powershell
uv run tradingagents mt5-run --once
```

If the analysis produces a `NO_TRADE` proposal, that is a valid safe outcome.
It means no broker order was attempted.

Review the audit outputs after the cycle:

```text
<results_dir>\<analysis-symbol>\engine_telemetry\engine_payload_<as-of>.json
<results_dir>\<analysis-symbol>\order_proposals\order_proposal_<as-of>.json
<results_dir>\mt5_runner\summary.json
<results_dir>\mt5_runner\cycles.jsonl
```

The summary should show total checks, HOLD/PROPOSED counts, broker-order counts,
rejection counts, categorized HOLD reasons, and latest data-health status.

## Manual Cycle

To inspect each stage separately:

```powershell
uv run tradingagents analyze --non-interactive
uv run tradingagents mt5-execute --proposal "<path-to-order-proposal.json>"
uv run tradingagents mt5-monitor --cancel-stale --manage-stops
```

## Long-Running Mode

Only after tests, `broker-probe`, and `mt5-run --once` pass:

```powershell
uv run tradingagents mt5-run --poll-seconds 30
```

For a bounded market-reopen or London/New York overlap test, keep `.env` safe
with `TRADINGAGENTS_MT5_EXECUTION_MODE=dry_run` and override only the current
PowerShell process:

```powershell
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
$env:ALL_PROXY=""
$env:GIT_HTTP_PROXY=""
$env:GIT_HTTPS_PROXY=""
$env:TRADINGAGENTS_MT5_ACCOUNT_MODE="demo"
$env:TRADINGAGENTS_MT5_EXECUTION_MODE="broker"
tradingagents mt5-run --poll-seconds 30 --duration-hours 4
```

Do not start a setup-validation run after the Friday gold close. For
observation, Sunday New York reopen is acceptable. For cleaner strategy
validation, prefer London/New York overlap.

After the run, review:

```text
<results_dir>\mt5_runner\summary.json
<results_dir>\mt5_runner\cycles.jsonl
<results_dir>\<analysis-symbol>\engine_telemetry\engine_payload_<as-of>.json
<results_dir>\<broker-symbol>\execution_journal\mt5_events.jsonl
```

For Task Scheduler, use:

- Program: path to `uv`
- Arguments: `run tradingagents mt5-run --poll-seconds 30`
- Start in: the repo root

## Troubleshooting

- `MetaTrader5 Python bridge is not installed`: run `uv pip install MetaTrader5`
  on Windows.
- `MT5 account mode` error: set `TRADINGAGENTS_MT5_ACCOUNT_MODE` to match MT5.
- `unexpected MT5 account login/server`: update `.env` or log into the intended
  MT5 account.
- `symbol must match configured MT5 symbol`: set `TRADINGAGENTS_MT5_SYMBOL` to
  the exact broker symbol shown in Market Watch.
- No proposal path after analysis: configure an LLM provider key or Ollama model.
- `Data health failed. Default to HOLD.`: inspect the raw engine telemetry and
  confirm whether YFinance returned stale or missing GC=F candles.
- Frequent `GC=F: possibly delisted; no price data found` warnings: rerun during
  an active market window and compare `data_status` before changing strategy
  rules.

## Readiness Signal

The Windows setup is ready for unattended dry-run execution when these pass:

```text
pytest focused MT5 suite: pass
broker-probe: pass
mt5-run --once: exits with JSON status, with no MT5 guard errors
summary.json: records the cycle and data-health state
```

Broker order sending is a separate human decision controlled by
`TRADINGAGENTS_MT5_EXECUTION_MODE=broker`.
