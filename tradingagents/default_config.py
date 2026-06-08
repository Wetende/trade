import os

from tradingagents.agents.price_action.sessions import DEFAULT_SESSION_CONFIG

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_ANALYSIS_SYMBOL":      "analysis_symbol",
    "TRADINGAGENTS_BROKER_SYMBOL":        "broker_symbol",
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_TIMEFRAME":            "timeframe",
    "TRADINGAGENTS_CONFIRMATION_TIMEFRAME": "confirmation_timeframe",
    "TRADINGAGENTS_MARKET_TIMEZONE":      "market_timezone",
    "TRADINGAGENTS_RUNNER_POLL_SECONDS":  "runner_poll_seconds",
    "TRADINGAGENTS_RUNNER_MAX_CYCLES":    "runner_max_cycles",
    "TRADINGAGENTS_RUNNER_MAX_RUNTIME_SECONDS": "runner_max_runtime_seconds",
    "TRADINGAGENTS_RUNNER_MAX_SESSION_LOSS": "runner_max_session_loss",
    "TRADINGAGENTS_RUNNER_BLOCKED_STRATEGY_RULES": "runner_blocked_strategy_rules",
    "TRADINGAGENTS_TIME_FILTER_MODE":     "time_filter_mode",
    "TRADINGAGENTS_DECISION_MODE":        "decision_mode",
    "TRADINGAGENTS_MIN_SETUP_GRADE":      "minimum_setup_grade",
    "TRADINGAGENTS_B_PLUS_MIN_RR":        "b_plus_min_rr",
    "TRADINGAGENTS_FAST_ENTRIES_ENABLED": "fast_entries_enabled",
    "TRADINGAGENTS_FAST_TIMEFRAME": "fast_timeframe",
    "TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME": "fast_confirmation_timeframe",
    "TRADINGAGENTS_NORMAL_ACTIVATION_WINDOW_MINUTES": "normal_activation_window_minutes",
    "TRADINGAGENTS_FAST_ACTIVATION_WINDOW_MINUTES": "fast_activation_window_minutes",
    "TRADINGAGENTS_FAST_COUNTER_BIAS_MIN_GRADE": "fast_counter_bias_minimum_grade",
    "TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE": "minimum_stop_distance_price",
    "TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE": "minimum_stop_spread_multiple",
    "TRADINGAGENTS_EXIT_SCALP_PROFIT_POINTS": "exit_scalp_profit_points",
    "TRADINGAGENTS_EXIT_EARLY_LOSS_POINTS": "exit_early_loss_points",
    "TRADINGAGENTS_EXIT_BREAK_EVEN_TRIGGER_POINTS": "exit_break_even_trigger_points",
    "TRADINGAGENTS_EXIT_BREAK_EVEN_LOCK_POINTS": "exit_break_even_lock_points",
    "TRADINGAGENTS_EXIT_TRAILING_TRIGGER_POINTS": "exit_trailing_trigger_points",
    "TRADINGAGENTS_EXIT_TRAILING_DISTANCE_POINTS": "exit_trailing_distance_points",
    "TRADINGAGENTS_EXIT_MIN_STOP_UPDATE_POINTS": "exit_min_stop_update_points",
}


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    if isinstance(reference, tuple):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce(raw, config.get(key))
    return config


def _env_or_default(name: str, default: str) -> str:
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    return raw


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": _env_or_default(
        "TRADINGAGENTS_RESULTS_DIR",
        os.path.join(_TRADINGAGENTS_HOME, "logs"),
    ),
    "data_cache_dir": _env_or_default(
        "TRADINGAGENTS_CACHE_DIR",
        os.path.join(_TRADINGAGENTS_HOME, "cache"),
    ),
    # Symbol semantics: analysis_symbol is the market data/reporting symbol;
    # broker_symbol is the execution symbol used by broker integrations.
    "analysis_symbol": None,
    "broker_symbol": None,
    # LLM settings
    "llm_provider": "openai",
    "deep_think_llm": "gpt-5.4",
    "quick_think_llm": "gpt-5.4-mini",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Price Action Playbook settings
    "timeframe": "15m",
    "confirmation_timeframe": "30m",
    "market_timezone": "America/New_York",
    "runner_poll_seconds": 30,
    "runner_max_cycles": 0,
    "runner_max_runtime_seconds": 0,
    "runner_max_session_loss": 0.0,
    "runner_blocked_strategy_rules": (),
    "decision_mode": "engine",
    "time_filter_mode": DEFAULT_SESSION_CONFIG["time_filter_mode"],
    "minimum_setup_grade": DEFAULT_SESSION_CONFIG["minimum_setup_grade"],
    "b_plus_min_rr": DEFAULT_SESSION_CONFIG["b_plus_min_rr"],
    "fast_entries_enabled": False,
    "fast_timeframe": "1m",
    "fast_confirmation_timeframe": "3m",
    "normal_activation_window_minutes": 30,
    "fast_activation_window_minutes": 6,
    "fast_counter_bias_minimum_grade": "A_PLUS",
    "minimum_stop_distance_price": 2.5,
    "minimum_stop_spread_multiple": 4.0,
    "exit_scalp_profit_points": 1.5,
    "exit_early_loss_points": 1.5,
    "exit_break_even_trigger_points": 1.0,
    "exit_break_even_lock_points": 0.2,
    "exit_trailing_trigger_points": 3.0,
    "exit_trailing_distance_points": 1.2,
    "exit_min_stop_update_points": 0.3,
    "price_action": dict(DEFAULT_SESSION_CONFIG),
    "max_recur_limit": 20,
    # Data vendor configuration: keep only core OHLC fetching for now.
    "data_vendors": {
        "core_stock_apis": "yfinance",
    },
    "tool_vendors": {
    },
})

DEFAULT_CONFIG["price_action"]["time_filter_mode"] = DEFAULT_CONFIG["time_filter_mode"]
DEFAULT_CONFIG["price_action"]["minimum_setup_grade"] = DEFAULT_CONFIG["minimum_setup_grade"]
DEFAULT_CONFIG["price_action"]["b_plus_min_rr"] = DEFAULT_CONFIG["b_plus_min_rr"]
DEFAULT_CONFIG["price_action"]["fast_entries_enabled"] = DEFAULT_CONFIG[
    "fast_entries_enabled"
]
DEFAULT_CONFIG["price_action"]["fast_timeframe"] = DEFAULT_CONFIG["fast_timeframe"]
DEFAULT_CONFIG["price_action"]["fast_confirmation_timeframe"] = DEFAULT_CONFIG[
    "fast_confirmation_timeframe"
]
DEFAULT_CONFIG["price_action"]["normal_activation_window_minutes"] = DEFAULT_CONFIG[
    "normal_activation_window_minutes"
]
DEFAULT_CONFIG["price_action"]["fast_activation_window_minutes"] = DEFAULT_CONFIG[
    "fast_activation_window_minutes"
]
DEFAULT_CONFIG["price_action"]["fast_counter_bias_minimum_grade"] = DEFAULT_CONFIG[
    "fast_counter_bias_minimum_grade"
]
DEFAULT_CONFIG["price_action"]["minimum_stop_distance_price"] = DEFAULT_CONFIG[
    "minimum_stop_distance_price"
]
DEFAULT_CONFIG["price_action"]["minimum_stop_spread_multiple"] = DEFAULT_CONFIG[
    "minimum_stop_spread_multiple"
]
