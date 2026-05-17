from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG

# DEFAULT_CONFIG already applies TRADINGAGENTS_* env-var overrides
# (llm_provider, deep_think_llm, quick_think_llm, backend_url, etc.),
# so users can switch models or endpoints purely via .env without
# editing this script. Override individual keys here only when you
# want a hard-coded value that should ignore the environment.
config = DEFAULT_CONFIG.copy()

ta = TradingAgentsGraph(debug=True, config=config)

# Run the price-action playbook on a specific 15m candle timestamp.
_, decision = ta.propagate("NVDA", "2026-05-17 10:15")
print(decision)
