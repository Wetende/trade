import datetime
import json
import locale
import math
import os
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from cli.utils import (
    ask_anthropic_effort,
    ask_gemini_thinking_config,
    ask_glm_region,
    ask_minimax_region,
    ask_openai_reasoning_effort,
    ask_output_language,
    ask_qwen_region,
    confirm_ollama_endpoint,
    ensure_api_key,
    get_as_of_timestamp,
    get_ticker,
    last_closed_candle,
    select_deep_thinking_agent,
    select_llm_provider,
    select_shallow_thinking_agent,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph

console = Console()

app = typer.Typer(
    name="TradingAgents",
    help="Price Action Playbook trading assistant",
    add_completion=True,
)


def _load_runtime_env() -> None:
    """Load local .env and refresh config values used by the CLI."""
    load_dotenv(dotenv_path=Path.cwd() / ".env", override=False)
    env_overrides = {
        "TRADINGAGENTS_ANALYSIS_SYMBOL": "analysis_symbol",
        "TRADINGAGENTS_BROKER_SYMBOL": "broker_symbol",
        "TRADINGAGENTS_LLM_PROVIDER": "llm_provider",
        "TRADINGAGENTS_DEEP_THINK_LLM": "deep_think_llm",
        "TRADINGAGENTS_QUICK_THINK_LLM": "quick_think_llm",
        "TRADINGAGENTS_LLM_BACKEND_URL": "backend_url",
        "TRADINGAGENTS_OUTPUT_LANGUAGE": "output_language",
        "TRADINGAGENTS_CHECKPOINT_ENABLED": "checkpoint_enabled",
        "TRADINGAGENTS_TIMEFRAME": "timeframe",
        "TRADINGAGENTS_CONFIRMATION_TIMEFRAME": "confirmation_timeframe",
        "TRADINGAGENTS_MARKET_TIMEZONE": "market_timezone",
        "TRADINGAGENTS_RUNNER_POLL_SECONDS": "runner_poll_seconds",
        "TRADINGAGENTS_RUNNER_MAINTENANCE_POLL_SECONDS": "runner_maintenance_poll_seconds",
        "TRADINGAGENTS_RUNNER_MAX_CYCLES": "runner_max_cycles",
        "TRADINGAGENTS_RUNNER_MAX_RUNTIME_SECONDS": "runner_max_runtime_seconds",
        "TRADINGAGENTS_RUNNER_MAX_SESSION_LOSS": "runner_max_session_loss",
        "TRADINGAGENTS_RUNNER_POST_CLOSE_COOLDOWN_SECONDS": "runner_post_close_cooldown_seconds",
        "TRADINGAGENTS_RUNNER_LOSS_COOLDOWN_SECONDS": "runner_loss_cooldown_seconds",
        "TRADINGAGENTS_RUNNER_LOSS_STREAK_COOLDOWN_COUNT": "runner_loss_streak_cooldown_count",
        "TRADINGAGENTS_RUNNER_LOSS_STREAK_COOLDOWN_SECONDS": "runner_loss_streak_cooldown_seconds",
        "TRADINGAGENTS_RUNNER_BLOCKED_STRATEGY_RULES": "runner_blocked_strategy_rules",
        "TRADINGAGENTS_TRADING_MODE": "trading_mode",
        "TRADINGAGENTS_REQUIRE_DEMO_ACCOUNT": "require_demo_account",
        "TRADINGAGENTS_TIME_FILTER_MODE": "time_filter_mode",
        "TRADINGAGENTS_DECISION_MODE": "decision_mode",
        "TRADINGAGENTS_ENTRY_PROFILE_MODE": "entry_profile_mode",
        "TRADINGAGENTS_MIN_SETUP_GRADE": "minimum_setup_grade",
        "TRADINGAGENTS_B_PLUS_MIN_RR": "b_plus_min_rr",
        "TRADINGAGENTS_FAST_ENTRIES_ENABLED": "fast_entries_enabled",
        "TRADINGAGENTS_FAST_TIMEFRAME": "fast_timeframe",
        "TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME": "fast_confirmation_timeframe",
        "TRADINGAGENTS_FAST_HISTORY_WINDOW_CANDLES": "fast_history_window_candles",
        "TRADINGAGENTS_FAST_REACTION_PENDING_SECONDS": "fast_reaction_pending_seconds",
        "TRADINGAGENTS_FAST_IMPULSE_PENDING_SECONDS": "fast_impulse_pending_seconds",
        "TRADINGAGENTS_FAST_MIN_CANDIDATE_SCORE": "fast_min_candidate_score",
        "TRADINGAGENTS_FAST_MIN_STOP_SPREAD_MULTIPLE": "fast_min_stop_spread_multiple",
        "TRADINGAGENTS_FAST_VOLUME_BOOST_ENABLED": "fast_volume_boost_enabled",
        "TRADINGAGENTS_NORMAL_ACTIVATION_WINDOW_MINUTES": "normal_activation_window_minutes",
        "TRADINGAGENTS_FAST_ACTIVATION_WINDOW_MINUTES": "fast_activation_window_minutes",
        "TRADINGAGENTS_FAST_COUNTER_BIAS_MIN_GRADE": "fast_counter_bias_minimum_grade",
        "TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE": "minimum_stop_distance_price",
        "TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE": "minimum_stop_spread_multiple",
        "TRADINGAGENTS_MAX_ENTRY_SPREAD_PRICE": "max_entry_spread_price",
        "TRADINGAGENTS_MAX_TICK_AGE_SECONDS": "max_tick_age_seconds",
        "TRADINGAGENTS_MARKET_ROLLOVER_BLOCK_ENABLED": "market_rollover_block_enabled",
        "TRADINGAGENTS_MARKET_ROLLOVER_CLOSE_TIME": "market_rollover_close_time",
        "TRADINGAGENTS_MARKET_ROLLOVER_REOPEN_TIME": "market_rollover_reopen_time",
        "TRADINGAGENTS_MARKET_ROLLOVER_PRE_CLOSE_MINUTES": "market_rollover_pre_close_minutes",
        "TRADINGAGENTS_MARKET_ROLLOVER_POST_REOPEN_MINUTES": "market_rollover_post_reopen_minutes",
        "TRADINGAGENTS_EXIT_SCALP_PROFIT_POINTS": "exit_scalp_profit_points",
        "TRADINGAGENTS_EXIT_EARLY_LOSS_POINTS": "exit_early_loss_points",
        "TRADINGAGENTS_EXIT_BREAK_EVEN_TRIGGER_POINTS": "exit_break_even_trigger_points",
        "TRADINGAGENTS_EXIT_BREAK_EVEN_LOCK_POINTS": "exit_break_even_lock_points",
        "TRADINGAGENTS_EXIT_TRAILING_TRIGGER_POINTS": "exit_trailing_trigger_points",
        "TRADINGAGENTS_EXIT_TRAILING_DISTANCE_POINTS": "exit_trailing_distance_points",
        "TRADINGAGENTS_EXIT_MIN_STOP_UPDATE_POINTS": "exit_min_stop_update_points",
        "TRADINGAGENTS_EXIT_PARTIAL_FIRST_TRIGGER_POINTS": "exit_partial_first_trigger_points",
        "TRADINGAGENTS_EXIT_PARTIAL_FIRST_TARGET_VOLUME": "exit_partial_first_target_volume",
        "TRADINGAGENTS_EXIT_PARTIAL_SECOND_TRIGGER_POINTS": "exit_partial_second_trigger_points",
        "TRADINGAGENTS_EXIT_PARTIAL_SECOND_TARGET_VOLUME": "exit_partial_second_target_volume",
    }
    for env_var, key in env_overrides.items():
        raw = os.environ.get(env_var)
        if raw in (None, ""):
            continue
        reference = DEFAULT_CONFIG.get(key)
        if isinstance(reference, bool):
            DEFAULT_CONFIG[key] = raw.strip().lower() in ("true", "1", "yes", "on")
        elif isinstance(reference, int) and not isinstance(reference, bool):
            DEFAULT_CONFIG[key] = int(raw)
        elif isinstance(reference, float):
            DEFAULT_CONFIG[key] = float(raw)
        elif isinstance(reference, tuple):
            DEFAULT_CONFIG[key] = tuple(
                item.strip() for item in raw.split(",") if item.strip()
            )
        else:
            DEFAULT_CONFIG[key] = raw

    results_dir = os.environ.get("TRADINGAGENTS_RESULTS_DIR")
    if results_dir not in (None, ""):
        DEFAULT_CONFIG["results_dir"] = results_dir
    data_cache_dir = os.environ.get("TRADINGAGENTS_CACHE_DIR")
    if data_cache_dir not in (None, ""):
        DEFAULT_CONFIG["data_cache_dir"] = data_cache_dir
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
    DEFAULT_CONFIG["price_action"]["fast_history_window_candles"] = DEFAULT_CONFIG[
        "fast_history_window_candles"
    ]
    DEFAULT_CONFIG["price_action"]["fast_reaction_pending_seconds"] = DEFAULT_CONFIG[
        "fast_reaction_pending_seconds"
    ]
    DEFAULT_CONFIG["price_action"]["fast_impulse_pending_seconds"] = DEFAULT_CONFIG[
        "fast_impulse_pending_seconds"
    ]
    DEFAULT_CONFIG["price_action"]["fast_min_candidate_score"] = DEFAULT_CONFIG[
        "fast_min_candidate_score"
    ]
    DEFAULT_CONFIG["price_action"]["fast_min_stop_spread_multiple"] = DEFAULT_CONFIG[
        "fast_min_stop_spread_multiple"
    ]
    DEFAULT_CONFIG["price_action"]["fast_volume_boost_enabled"] = DEFAULT_CONFIG[
        "fast_volume_boost_enabled"
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
    DEFAULT_CONFIG["price_action"]["max_entry_spread_price"] = DEFAULT_CONFIG[
        "max_entry_spread_price"
    ]
    DEFAULT_CONFIG["price_action"]["max_tick_age_seconds"] = DEFAULT_CONFIG[
        "max_tick_age_seconds"
    ]
    DEFAULT_CONFIG["price_action"]["market_rollover_block_enabled"] = DEFAULT_CONFIG[
        "market_rollover_block_enabled"
    ]
    DEFAULT_CONFIG["price_action"]["market_rollover_close_time"] = DEFAULT_CONFIG[
        "market_rollover_close_time"
    ]
    DEFAULT_CONFIG["price_action"]["market_rollover_reopen_time"] = DEFAULT_CONFIG[
        "market_rollover_reopen_time"
    ]
    DEFAULT_CONFIG["price_action"]["market_rollover_pre_close_minutes"] = DEFAULT_CONFIG[
        "market_rollover_pre_close_minutes"
    ]
    DEFAULT_CONFIG["price_action"]["market_rollover_post_reopen_minutes"] = DEFAULT_CONFIG[
        "market_rollover_post_reopen_minutes"
    ]


def _trading_disabled_result(command: str) -> dict:
    return {
        "status": "TRADING_DISABLED",
        "trading_mode": "OFF",
        "selected_method": "HOLD",
        "selected_profile": None,
        "mode_decision": "TRADING_DISABLED",
        "mode_rejection_reason": f"{command} disabled by trading mode OFF",
        "health_gate": {"passed": False, "reasons": ["trading_mode_off"]},
    }


def _console_encoding(console_obj: Console) -> str:
    file_encoding = getattr(getattr(console_obj, "file", None), "encoding", None)
    return file_encoding or locale.getpreferredencoding(False) or "utf-8"


def _coerce_console_text(text: str, console_obj: Console) -> str:
    encoding = _console_encoding(console_obj)
    try:
        text.encode(encoding)
    except UnicodeEncodeError:
        return text.encode(encoding, errors="replace").decode(encoding)
    return text


def _panel_box(console_obj: Console):
    encoding = _console_encoding(console_obj).lower()
    if encoding.startswith("utf"):
        return None
    return box.ASCII


def _render_panel_body(text: str, console_obj: Console):
    safe_text = _coerce_console_text(text, console_obj)
    if _panel_box(console_obj) is box.ASCII:
        return safe_text
    return Markdown(safe_text)


def get_user_selections():
    _load_runtime_env()
    console.print(Panel("[bold green]Price Action Playbook[/bold green]", title="TradingAgents"))

    ticker = DEFAULT_CONFIG.get("analysis_symbol") or get_ticker()
    output_language = ask_output_language()
    timeframe = DEFAULT_CONFIG["timeframe"]
    confirmation_timeframe = DEFAULT_CONFIG["confirmation_timeframe"]
    market_timezone = DEFAULT_CONFIG["market_timezone"]
    as_of = get_as_of_timestamp(timeframe, market_timezone)

    llm_provider, backend_url = select_llm_provider()
    if llm_provider == "qwen":
        llm_provider, backend_url = ask_qwen_region()
    elif llm_provider == "minimax":
        llm_provider, backend_url = ask_minimax_region()
    elif llm_provider == "glm":
        llm_provider, backend_url = ask_glm_region()
    elif llm_provider == "ollama":
        confirm_ollama_endpoint(backend_url)

    ensure_api_key(llm_provider)

    quick_model = select_shallow_thinking_agent(llm_provider)
    deep_model = select_deep_thinking_agent(llm_provider)

    thinking_level = None
    reasoning_effort = None
    anthropic_effort = None
    provider_lower = llm_provider.lower()
    if provider_lower == "google":
        thinking_level = ask_gemini_thinking_config()
    elif provider_lower == "openai":
        reasoning_effort = ask_openai_reasoning_effort()
    elif provider_lower == "anthropic":
        anthropic_effort = ask_anthropic_effort()

    return {
        "ticker": ticker,
        "broker_symbol": DEFAULT_CONFIG.get("broker_symbol") or ticker,
        "as_of": as_of,
        "timeframe": timeframe,
        "confirmation_timeframe": confirmation_timeframe,
        "market_timezone": market_timezone,
        "llm_provider": llm_provider.lower(),
        "backend_url": backend_url,
        "quick_model": quick_model,
        "deep_model": deep_model,
        "google_thinking_level": thinking_level,
        "openai_reasoning_effort": reasoning_effort,
        "anthropic_effort": anthropic_effort,
        "output_language": output_language,
    }


def build_env_selections(as_of: str | None = None) -> dict:
    _load_runtime_env()
    timeframe = DEFAULT_CONFIG["timeframe"]
    confirmation_timeframe = DEFAULT_CONFIG["confirmation_timeframe"]
    market_timezone = DEFAULT_CONFIG["market_timezone"]
    ticker = (
        os.environ.get("TRADINGAGENTS_ANALYSIS_SYMBOL")
        or DEFAULT_CONFIG.get("analysis_symbol")
        or "GC=F"
    )

    return {
        "ticker": ticker,
        "broker_symbol": (
            os.environ.get("TRADINGAGENTS_BROKER_SYMBOL")
            or DEFAULT_CONFIG.get("broker_symbol")
            or ticker
        ),
        "as_of": as_of or last_closed_candle(timeframe, market_timezone),
        "timeframe": timeframe,
        "confirmation_timeframe": confirmation_timeframe,
        "market_timezone": market_timezone,
        "llm_provider": (
            os.environ.get("TRADINGAGENTS_LLM_PROVIDER")
            or DEFAULT_CONFIG["llm_provider"]
        ).lower(),
        "backend_url": (
            os.environ.get("TRADINGAGENTS_LLM_BACKEND_URL")
            or DEFAULT_CONFIG.get("backend_url")
        ),
        "quick_model": (
            os.environ.get("TRADINGAGENTS_QUICK_THINK_LLM")
            or DEFAULT_CONFIG["quick_think_llm"]
        ),
        "deep_model": (
            os.environ.get("TRADINGAGENTS_DEEP_THINK_LLM")
            or DEFAULT_CONFIG["deep_think_llm"]
        ),
        "google_thinking_level": DEFAULT_CONFIG.get("google_thinking_level"),
        "openai_reasoning_effort": DEFAULT_CONFIG.get("openai_reasoning_effort"),
        "anthropic_effort": DEFAULT_CONFIG.get("anthropic_effort"),
        "output_language": (
            os.environ.get("TRADINGAGENTS_OUTPUT_LANGUAGE")
            or DEFAULT_CONFIG.get("output_language", "English")
        ),
    }


def build_config(selections: dict, checkpoint: bool) -> dict:
    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = selections["llm_provider"]
    config["backend_url"] = selections["backend_url"]
    config["quick_think_llm"] = selections["quick_model"]
    config["deep_think_llm"] = selections["deep_model"]
    config["timeframe"] = selections["timeframe"]
    config["confirmation_timeframe"] = selections["confirmation_timeframe"]
    config["market_timezone"] = selections["market_timezone"]
    config["google_thinking_level"] = selections.get("google_thinking_level")
    config["openai_reasoning_effort"] = selections.get("openai_reasoning_effort")
    config["anthropic_effort"] = selections.get("anthropic_effort")
    config["output_language"] = selections.get("output_language", "English")
    config["analysis_symbol"] = selections["ticker"]
    config["broker_symbol"] = selections.get("broker_symbol") or selections["ticker"]
    config["checkpoint_enabled"] = checkpoint
    return config


def save_report_to_disk(final_state: dict, ticker: str, as_of: str, save_path: Path):
    save_path.mkdir(parents=True, exist_ok=True)
    sections = [
        f"# Price Action Playbook Report: {ticker}",
        f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"As of: {as_of}",
        "",
        "## Price Action Analyst",
        final_state.get("price_action_report", ""),
        "",
        "## Trader",
        final_state.get("trade_plan", ""),
        "",
        "## Order Proposal",
        final_state.get("order_proposal", ""),
    ]
    report_file = save_path / "complete_report.md"
    report_file.write_text("\n\n".join(sections), encoding="utf-8")
    return report_file


def run_analysis(checkpoint: bool = False, selections: dict | None = None):
    if selections is None:
        selections = get_user_selections()
    config = build_config(selections, checkpoint)

    graph = TradingAgentsGraph(config=config, debug=False)
    final_state, decision = graph.propagate(selections["ticker"], selections["as_of"])
    panel_box = _panel_box(console)

    console.print()
    console.print(
        Panel(
            _coerce_console_text(f"Decision: {decision}", console),
            title="Result",
            border_style="green",
            box=panel_box,
        )
    )
    console.print(
        Panel(
            _render_panel_body(final_state.get("price_action_report", ""), console),
            title="Price Action Analyst",
            box=panel_box,
        )
    )
    console.print(
        Panel(
            _render_panel_body(final_state.get("trade_plan", ""), console),
            title="Trader",
            box=panel_box,
        )
    )
    console.print(
        Panel(
            _render_panel_body(final_state.get("order_proposal", ""), console),
            title="Order Proposal",
            box=panel_box,
        )
    )

    default_path = (
        Path(config["results_dir"])
        / selections["ticker"]
        / selections["as_of"].replace(" ", "_").replace(":", "")
        / "reports"
    )
    report_file = save_report_to_disk(final_state, selections["ticker"], selections["as_of"], default_path)
    console.print(f"\n[green]Report saved to:[/green] {report_file}")
    if final_state.get("order_proposal_path"):
        console.print(f"[green]Order proposal saved to:[/green] {final_state['order_proposal_path']}")
    return final_state, decision


@app.command()
def analyze(
    checkpoint: bool = typer.Option(
        False,
        "--checkpoint",
        help="Enable checkpoint/resume for the graph run.",
    ),
    clear_checkpoints: bool = typer.Option(
        False,
        "--clear-checkpoints",
        help="Delete all saved checkpoints before running.",
    ),
    non_interactive: bool = typer.Option(
        False,
        "--non-interactive",
        help="Use environment configuration without prompts.",
    ),
    symbol: str | None = typer.Option(
        None,
        "--symbol",
        help="Analysis/data symbol, e.g. GC=F.",
    ),
    broker_symbol: str | None = typer.Option(
        None,
        "--broker-symbol",
        help="Broker execution symbol, e.g. XAUUSD.",
    ),
    as_of: str | None = typer.Option(
        None,
        "--as-of",
        help="As-of timestamp in market timezone, YYYY-MM-DD HH:MM.",
    ),
):
    _load_runtime_env()
    if clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints

        n = clear_all_checkpoints(DEFAULT_CONFIG["data_cache_dir"])
        console.print(f"[yellow]Cleared {n} checkpoint(s).[/yellow]")
    selections = None
    if non_interactive:
        selections = build_env_selections(as_of=as_of)
        original_ticker = selections["ticker"]
        if symbol:
            selections["ticker"] = symbol
            if selections.get("broker_symbol") == original_ticker and broker_symbol is None:
                selections["broker_symbol"] = symbol
        if broker_symbol:
            selections["broker_symbol"] = broker_symbol
    run_analysis(checkpoint=checkpoint, selections=selections)


@app.command()
def backtest(
    symbol: str = typer.Option("XAUUSD", "--symbol", help="Symbol to simulate."),
):
    console.print(f"[yellow]Backtest simulation scaffold ready for {symbol}.[/yellow]")
    console.print(
        "[yellow]Use tradingagents.agents.price_action.backtest with historical "
        "candles or fixtures. No broker orders are placed.[/yellow]"
    )


@app.command("broker-probe")
def broker_probe(
    json_only: bool = typer.Option(
        False,
        "--json-only",
        help="Print only sanitized machine-readable JSON.",
    ),
):
    """Check MT5 account connectivity without placing orders."""
    _load_runtime_env()
    from tradingagents.brokers.mode_gate import account_safety_from_connection
    from tradingagents.brokers.mt5 import (
        MT5Broker,
        MT5BrokerError,
        MT5ConnectionConfig,
        safe_mt5_connection_status,
    )

    try:
        config = MT5ConnectionConfig.from_env()
        broker = MT5Broker(config)
        connection = broker.connect()
        snapshot = broker.current_symbol_snapshot()
        orders = broker.open_orders(config.symbol)
        positions = broker.open_positions(config.symbol)
        account_safety = account_safety_from_connection(
            connection,
            require_demo=config.require_demo_account,
        )
        result = safe_mt5_connection_status(
            connection,
            account_safety=account_safety,
            symbol_snapshot=snapshot,
            open_order_count=len(orders),
            open_position_count=len(positions),
        )
    except MT5BrokerError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        if "broker" in locals():
            broker.shutdown()

    if not json_only:
        console.print("[green]MT5 account connection verified.[/green]")
    console.print(json.dumps(result, indent=2, sort_keys=True))


def _execute_mt5_proposal(proposal_path: Path, config=None) -> dict:
    from tradingagents.brokers.mt5 import MT5BrokerError, MT5ConnectionConfig
    from tradingagents.brokers.mt5_execution import MT5Executor, load_order_proposal

    try:
        if config is None:
            config = MT5ConnectionConfig.from_env()
        proposal = load_order_proposal(proposal_path)
        executor = MT5Executor(config, DEFAULT_CONFIG["results_dir"])
        return executor.execute_proposal(proposal)
    except (MT5BrokerError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


def _monitor_mt5(cancel_stale: bool, manage_stops: bool, config=None) -> dict:
    from tradingagents.brokers.mt5 import MT5BrokerError, MT5ConnectionConfig
    from tradingagents.brokers.mt5_execution import (
        MT5Executor,
        MT5OneMinuteLifecycleConfig,
    )

    try:
        if config is None:
            config = MT5ConnectionConfig.from_env()
        executor = MT5Executor(
            config,
            DEFAULT_CONFIG["results_dir"],
            exit_management=_mt5_exit_management_config(),
            one_minute_lifecycle=MT5OneMinuteLifecycleConfig(
                reaction_pending_seconds=float(
                    DEFAULT_CONFIG["fast_reaction_pending_seconds"]
                ),
                impulse_pending_seconds=float(
                    DEFAULT_CONFIG["fast_impulse_pending_seconds"]
                ),
            ),
        )
        results = {}
        if cancel_stale:
            results["cancel_stale"] = executor.cancel_stale_pending_orders()
        if manage_stops:
            results["manage_stops"] = executor.manage_open_positions()
        if not results:
            results["state"] = executor.snapshot_state()
        return results
    except (MT5BrokerError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc


def _mt5_exit_management_config():
    from tradingagents.brokers.mt5_execution import MT5ExitManagementConfig

    return MT5ExitManagementConfig(
        scalp_profit_points=float(DEFAULT_CONFIG.get("exit_scalp_profit_points", 0.0)),
        early_loss_exit_points=float(DEFAULT_CONFIG.get("exit_early_loss_points", 0.0)),
        break_even_trigger_points=float(
            DEFAULT_CONFIG.get("exit_break_even_trigger_points", 2.0)
        ),
        break_even_lock_points=float(
            DEFAULT_CONFIG.get("exit_break_even_lock_points", 0.0)
        ),
        trailing_trigger_points=float(
            DEFAULT_CONFIG.get("exit_trailing_trigger_points", 0.0)
        ),
        trailing_distance_points=float(
            DEFAULT_CONFIG.get("exit_trailing_distance_points", 0.0)
        ),
        min_stop_update_points=float(
            DEFAULT_CONFIG.get("exit_min_stop_update_points", 0.0)
        ),
        partial_first_trigger_points=float(
            DEFAULT_CONFIG.get("exit_partial_first_trigger_points", 0.0)
        ),
        partial_first_target_volume=float(
            DEFAULT_CONFIG.get("exit_partial_first_target_volume", 0.0)
        ),
        partial_second_trigger_points=float(
            DEFAULT_CONFIG.get("exit_partial_second_trigger_points", 0.0)
        ),
        partial_second_target_volume=float(
            DEFAULT_CONFIG.get("exit_partial_second_target_volume", 0.0)
        ),
    )


def _mt5_default_straddle_config(mt5_config):
    from tradingagents.agents.straddle_breakout import StraddleBreakoutConfig

    return StraddleBreakoutConfig(
        symbol=mt5_config.symbol,
        broker_symbol=mt5_config.symbol,
        timeframe="1m",
        confirmation_timeframe="3m",
        lookback_candles=3,
        entry_buffer_points=0.50,
        stop_distance_points=2.0,
        target_distance_points=3.0,
        activation_window_minutes=3,
        max_spread_points=0.50,
        min_box_points=0.50,
        max_box_points=3.0,
    )


def _mt5_default_straddle_exit_management_config():
    from tradingagents.brokers.mt5_straddle import StraddleExitManagementConfig

    return StraddleExitManagementConfig(
        enabled=True,
        break_even_trigger_points=0.8,
        break_even_lock_points=0.20,
        trailing_trigger_points=0.0,
        trailing_distance_points=0.8,
        min_stop_update_points=0.30,
        early_loss_exit_points=1.5,
        scalp_profit_points=1.50,
    )


def _mt5_default_straddle_entry_regime_config():
    from tradingagents.brokers.mt5_straddle import StraddleEntryRegimeConfig

    return StraddleEntryRegimeConfig(
        enabled=True,
        loss_streak_limit=2,
        loss_cooldown_minutes=10.0,
        wide_box_streak_limit=3,
        wide_box_cooldown_minutes=5.0,
        post_cooldown_momentum_body_points=0.80,
        post_cooldown_momentum_breakout_points=0.20,
    )


def _mt5_runner_analysis_func():
    def analyze_once():
        selections = build_env_selections()
        final_state, _decision = run_analysis(
            checkpoint=bool(DEFAULT_CONFIG.get("checkpoint_enabled")),
            selections=selections,
        )
        from tradingagents.brokers.mt5_execution import load_order_proposal
        from tradingagents.dataflows.utils import safe_ticker_component
        import re

        proposal = load_order_proposal(final_state["order_proposal_path"])
        safe_symbol = safe_ticker_component(selections["ticker"])
        safe_as_of = re.sub(r"[^0-9A-Za-z_-]+", "_", selections["as_of"]).strip("_")
        telemetry_path = (
            Path(DEFAULT_CONFIG["results_dir"])
            / safe_symbol
            / "engine_telemetry"
            / f"engine_payload_{safe_as_of}.json"
        )
        engine_payload = {}
        if telemetry_path.exists():
            engine_payload = json.loads(telemetry_path.read_text(encoding="utf-8"))
        analysis = {
            "order_proposal_path": final_state.get("order_proposal_path"),
            "telemetry_path": str(telemetry_path) if telemetry_path.exists() else None,
            "telemetry": engine_payload.get("telemetry", {}),
            "data_status": engine_payload.get("data_status", {}),
            "price_action_report": final_state.get("price_action_report", ""),
            "trade_plan": final_state.get("trade_plan", ""),
        }
        return selections["as_of"], proposal, analysis

    return analyze_once


def _mt5_runner_engine_analysis_func(mt5_config=None):
    def analyze_once():
        selections = build_env_selections()
        from tradingagents.agents.execution.order_proposal import (
            create_order_proposal_executor,
        )
        from tradingagents.agents.price_action.decision import run_engine_decision
        from tradingagents.agents.price_action.profiles import fast_profile, normal_profile
        from tradingagents.brokers.mt5 import MT5Broker
        from tradingagents.brokers.mt5_execution import load_order_proposal
        from tradingagents.dataflows.data_health import build_data_status
        from tradingagents.dataflows.mt5_price_action import (
            fetch_mt5_price_action_snapshot,
            mt5_health_reference,
        )
        from tradingagents.dataflows.price_action import PriceActionSnapshot

        engine_symbol = selections["ticker"]
        broker_symbol = selections.get("broker_symbol")
        snapshot = None
        if mt5_config is not None:
            engine_symbol = mt5_config.symbol
            broker_symbol = mt5_config.symbol
            analysis_broker = MT5Broker(mt5_config)
            try:
                analysis_broker.connect()
                snapshot = fetch_mt5_price_action_snapshot(
                    analysis_broker,
                    as_of=selections["as_of"],
                    market_timezone=selections.get(
                        "market_timezone",
                        DEFAULT_CONFIG["market_timezone"],
                    ),
                )
            finally:
                analysis_broker.shutdown()

        market_timezone = selections.get(
            "market_timezone",
            DEFAULT_CONFIG["market_timezone"],
        )
        profile_mode = str(
            DEFAULT_CONFIG.get("entry_profile_mode", "auto")
        ).strip().lower()
        if profile_mode == "fast_only":
            profiles = [fast_profile(DEFAULT_CONFIG)]
        elif profile_mode == "normal_only":
            profiles = [normal_profile(DEFAULT_CONFIG)]
        elif profile_mode in {"auto", "normal_and_fast"}:
            profiles = [normal_profile(DEFAULT_CONFIG)]
            if DEFAULT_CONFIG.get("fast_entries_enabled"):
                profiles.append(fast_profile(DEFAULT_CONFIG))
        else:
            raise ValueError(
                "TRADINGAGENTS_ENTRY_PROFILE_MODE must be auto, normal_only, or fast_only"
            )

        proposal_executor = create_order_proposal_executor(DEFAULT_CONFIG)
        rows = []
        for profile in profiles:
            profile_as_of = (
                selections["as_of"]
                if profile.name == "normal"
                else last_closed_candle(profile.timeframe, market_timezone)
            )
            profile_config = {
                **DEFAULT_CONFIG.get("price_action", {}),
                "entry_profile": profile.name,
                "timeframe": profile.timeframe,
                "confirmation_timeframe": profile.confirmation_timeframe,
                "zone_timeframes": profile.zone_timeframes,
                "context_timeframes": profile.context_timeframes,
                "governing_timeframes": profile.governing_timeframes,
                "activation_window_minutes": profile.activation_window_minutes,
                "independent_direction": profile.independent_direction,
                "fast_counter_bias_minimum_grade": profile.counter_bias_minimum_grade,
            }
            profile_snapshot = snapshot
            if snapshot is not None:
                required_timeframes = tuple(
                    dict.fromkeys(
                        (
                            *profile.zone_timeframes,
                            *profile.context_timeframes,
                            *profile.governing_timeframes,
                            profile.timeframe,
                            profile.confirmation_timeframe,
                        )
                    )
                )
                health_as_of, reference_source = mt5_health_reference(
                    snapshot.market_metadata,
                    profile_as_of,
                )
                profile_data_status = build_data_status(
                    snapshot.candles,
                    health_as_of,
                    market_timezone,
                    required_timeframes=required_timeframes,
                    trading_timeframe=profile.timeframe,
                    confirmation_timeframe=profile.confirmation_timeframe,
                )
                profile_data_status["reference_timestamp"] = health_as_of
                profile_data_status["reference_source"] = reference_source
                profile_snapshot = PriceActionSnapshot(
                    candles=snapshot.candles,
                    market_metadata=snapshot.market_metadata,
                    data_status=profile_data_status,
                )
            state = run_engine_decision(
                symbol=engine_symbol,
                broker_symbol=broker_symbol,
                as_of=profile_as_of,
                results_dir=DEFAULT_CONFIG["results_dir"],
                timeframe=profile.timeframe,
                confirmation_timeframe=profile.confirmation_timeframe,
                market_timezone=market_timezone,
                session_config=profile_config,
                snapshot=profile_snapshot,
            )
            state["entry_profile"] = profile.name
            state["activation_window_minutes"] = profile.activation_window_minutes
            engine_payload = state.get("engine_payload") or {}
            engine_payload.setdefault("entry_profile", profile.name)
            engine_payload.setdefault(
                "activation_window_minutes",
                profile.activation_window_minutes,
            )
            engine_payload.setdefault("timeframe", profile.timeframe)
            engine_payload.setdefault(
                "confirmation_timeframe",
                profile.confirmation_timeframe,
            )
            state["engine_payload"] = engine_payload

            proposal_state = proposal_executor(state)
            proposal_path = proposal_state["order_proposal_path"]
            proposal = load_order_proposal(proposal_path)
            analysis = {
                "entry_profile": profile.name,
                "order_proposal_path": proposal_path,
                "telemetry_path": state.get("telemetry_path"),
                "telemetry": engine_payload.get("telemetry", {}),
                "data_status": engine_payload.get("data_status", {}),
                "price_action_report": state.get("price_action_report", ""),
                "trade_plan": state.get("trade_plan", ""),
                "engine_status": engine_payload.get("status"),
            }
            rows.append((profile.name, profile_as_of, proposal, analysis))

        if len(rows) == 1:
            _profile, as_of, proposal, analysis = rows[0]
            return as_of, proposal, analysis
        return rows

    return analyze_once


def _mt5_runner_current_as_of_func():
    def current_as_of():
        _load_runtime_env()
        timeframe = (
            DEFAULT_CONFIG.get("fast_timeframe", "1m")
            if DEFAULT_CONFIG.get("fast_entries_enabled")
            else DEFAULT_CONFIG["timeframe"]
        )
        return last_closed_candle(timeframe, DEFAULT_CONFIG["market_timezone"])

    return current_as_of


@app.command("mt5-execute")
def mt5_execute(
    proposal_path: Path = typer.Option(
        ...,
        "--proposal",
        exists=True,
        readable=True,
        help="Path to a generated order_proposal_*.json file.",
    ),
):
    """Place a guarded MT5 pending order from an order proposal."""
    _load_runtime_env()
    result = _execute_mt5_proposal(proposal_path)
    console.print(json.dumps(result, indent=2, sort_keys=True))


@app.command("mt5-monitor")
def mt5_monitor(
    cancel_stale: bool = typer.Option(
        False,
        "--cancel-stale",
        help="Cancel stale pending orders for the configured symbol.",
    ),
    manage_stops: bool = typer.Option(
        False,
        "--manage-stops",
        help="Run break-even stop management for open positions.",
    ),
):
    """Monitor MT5 orders and positions."""
    _load_runtime_env()
    results = _monitor_mt5(cancel_stale, manage_stops)
    console.print(json.dumps(results, indent=2, sort_keys=True))


@app.command("mt5-run")
def mt5_run(
    once: bool = typer.Option(
        False,
        "--once",
        help="Run one automation cycle and exit.",
    ),
    poll_seconds: int = typer.Option(
        DEFAULT_CONFIG.get("runner_poll_seconds", 30),
        "--poll-seconds",
        min=5,
        help="Seconds between runner cycles.",
    ),
    duration_hours: float = typer.Option(
        0.0,
        "--duration-hours",
        min=0.0,
        help="Stop the runner after this many wall-clock hours. Zero means no duration limit.",
    ),
    decision_mode: str = typer.Option(
        DEFAULT_CONFIG.get("decision_mode", "engine"),
        "--decision-mode",
        help="Decision path for runner execution: engine or graph.",
    ),
):
    """Run unattended MT5 automation.

    Seconds between runner cycles.
    """
    _load_runtime_env()
    from tradingagents.brokers.mode_gate import TradingMode, parse_trading_mode
    from tradingagents.brokers.mt5_autogate import MT5AutoGateConfig, MT5AutoGateRunner
    from tradingagents.brokers.mt5 import MT5BrokerError, MT5ConnectionConfig
    from tradingagents.brokers.mt5_execution import (
        MT5Executor,
        MT5OneMinuteLifecycleConfig,
    )
    from tradingagents.brokers.mt5_runner import MT5Runner, MT5RunnerConfig
    from tradingagents.brokers.mt5_straddle import MT5StraddleExecutor

    try:
        trading_mode = parse_trading_mode(DEFAULT_CONFIG.get("trading_mode", "OFF"))
        if trading_mode == TradingMode.OFF:
            console.print(
                json.dumps(
                    _trading_disabled_result("mt5-run"),
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        if trading_mode == TradingMode.STRADDLE_ONLY:
            raise ValueError("mt5-run requires ENTRY_ONLY or AUTO_GATED trading mode")
        normalized_decision_mode = decision_mode.strip().lower()
        if normalized_decision_mode not in {"engine", "graph"}:
            raise typer.BadParameter("decision-mode must be 'engine' or 'graph'")
        if normalized_decision_mode == "graph":
            raise ValueError(
                "graph decision mode is not allowed for MT5 execution"
            )
        config = MT5ConnectionConfig.from_env()
        executor = MT5Executor(
            config,
            DEFAULT_CONFIG["results_dir"],
            exit_management=_mt5_exit_management_config(),
            one_minute_lifecycle=MT5OneMinuteLifecycleConfig(
                reaction_pending_seconds=float(
                    DEFAULT_CONFIG["fast_reaction_pending_seconds"]
                ),
                impulse_pending_seconds=float(
                    DEFAULT_CONFIG["fast_impulse_pending_seconds"]
                ),
            ),
        )
        analysis_func = _mt5_runner_engine_analysis_func(config)
        runner_config_kwargs = {
            "results_dir": DEFAULT_CONFIG["results_dir"],
            "poll_seconds": poll_seconds,
            "max_cycles": (
                1
                if once
                else (
                    0
                    if duration_hours
                    else int(DEFAULT_CONFIG.get("runner_max_cycles", 0))
                )
            ),
            "max_runtime_seconds": (
                math.ceil(duration_hours * 3600)
                if duration_hours
                else int(DEFAULT_CONFIG.get("runner_max_runtime_seconds", 0))
            ),
            "max_session_loss": float(
                DEFAULT_CONFIG.get("runner_max_session_loss", 0.0)
            ),
            "blocked_strategy_rules": tuple(
                DEFAULT_CONFIG.get("runner_blocked_strategy_rules", ())
            ),
            "trading_mode": trading_mode.value,
        }
        if trading_mode != TradingMode.AUTO_GATED:
            runner_config_kwargs.update(
                {
                    "maintenance_poll_seconds": float(
                        DEFAULT_CONFIG.get(
                            "runner_maintenance_poll_seconds",
                            1.0,
                        )
                    ),
                    "post_close_cooldown_seconds": int(
                        DEFAULT_CONFIG.get(
                            "runner_post_close_cooldown_seconds",
                            0,
                        )
                    ),
                    "loss_cooldown_seconds": int(
                        DEFAULT_CONFIG.get("runner_loss_cooldown_seconds", 0)
                    ),
                    "loss_streak_cooldown_count": int(
                        DEFAULT_CONFIG.get(
                            "runner_loss_streak_cooldown_count",
                            0,
                        )
                    ),
                    "loss_streak_cooldown_seconds": int(
                        DEFAULT_CONFIG.get(
                            "runner_loss_streak_cooldown_seconds",
                            0,
                        )
                    ),
                }
            )
        if trading_mode == TradingMode.AUTO_GATED:
            straddle_executor = MT5StraddleExecutor(
                config,
                DEFAULT_CONFIG["results_dir"],
                trading_mode=trading_mode.value,
            )
            runner = MT5AutoGateRunner(
                MT5AutoGateConfig(**runner_config_kwargs),
                directional_executor=executor,
                straddle_executor=straddle_executor,
                directional_analysis_func=analysis_func,
                straddle_config=_mt5_default_straddle_config(config),
                current_as_of_func=_mt5_runner_current_as_of_func(),
                straddle_exit_management=_mt5_default_straddle_exit_management_config(),
                straddle_entry_regime=_mt5_default_straddle_entry_regime_config(),
            )
        else:
            runner = MT5Runner(
                MT5RunnerConfig(**runner_config_kwargs),
                executor=executor,
                analysis_func=analysis_func,
                current_as_of_func=_mt5_runner_current_as_of_func(),
            )
        result = runner.run_once() if once else runner.run_forever()
    except (MT5BrokerError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(json.dumps(result, indent=2, sort_keys=True))


@app.command("mt5-straddle-run")
def mt5_straddle_run(
    live: bool = typer.Option(
        False,
        "--live",
        help="Place the straddle pair. Without this flag the command only validates and records a dry run.",
    ),
    watch: bool = typer.Option(
        False,
        "--watch",
        help="Keep scanning continuously until stopped.",
    ),
    poll_seconds: int = typer.Option(
        5,
        "--poll-seconds",
        min=5,
        help="Seconds between watch cycles.",
    ),
    duration_hours: float = typer.Option(
        0.0,
        "--duration-hours",
        min=0.0,
        help="Stop the watch loop after this many wall-clock hours. Zero means no duration limit.",
    ),
    max_cycles: int = typer.Option(
        0,
        "--max-cycles",
        min=0,
        help="Stop the watch loop after this many cycles. Zero means no cycle limit.",
    ),
    timeframe: str = typer.Option(
        "1m",
        "--timeframe",
        help="MT5 candle timeframe used to build the straddle box.",
    ),
    confirmation_timeframe: str = typer.Option(
        "3m",
        "--confirmation-timeframe",
        help="Metadata timeframe recorded on the straddle proposals.",
    ),
    lookback_candles: int = typer.Option(
        3,
        "--lookback-candles",
        min=2,
        help="Number of recent candles used for the straddle box.",
    ),
    entry_buffer_points: float = typer.Option(
        0.50,
        "--entry-buffer-points",
        min=0.0,
        help="Price buffer added outside the box high/low.",
    ),
    stop_distance_points: float = typer.Option(
        2.0,
        "--stop-distance-points",
        min=0.01,
        help="Fixed stop distance from each pending entry.",
    ),
    target_distance_points: float = typer.Option(
        3.0,
        "--target-distance-points",
        min=0.01,
        help="Fixed target distance from each pending entry.",
    ),
    activation_window_minutes: int = typer.Option(
        3,
        "--activation-window-minutes",
        min=1,
        help="Minutes before the untriggered pair should expire.",
    ),
    max_spread_points: float = typer.Option(
        0.50,
        "--max-spread-points",
        min=0.0,
        help="Maximum live bid/ask spread allowed for pair creation.",
    ),
    min_box_points: float = typer.Option(
        0.50,
        "--min-box-points",
        min=0.0,
        help="Minimum candle-box height allowed for pair creation.",
    ),
    max_box_points: float = typer.Option(
        3.0,
        "--max-box-points",
        min=0.0,
        help="Maximum candle-box height allowed for pair creation.",
    ),
    entry_regime_filter: bool = typer.Option(
        True,
        "--entry-regime-filter/--no-entry-regime-filter",
        help="Pause new straddle entries after loss streaks or repeated wide boxes.",
    ),
    loss_streak_cooldown_trades: int = typer.Option(
        2,
        "--loss-streak-cooldown-trades",
        min=0,
        help="Consecutive closed losing straddle trades before pausing entries. Zero disables loss-streak cooldown.",
    ),
    loss_cooldown_minutes: float = typer.Option(
        10.0,
        "--loss-cooldown-minutes",
        min=0.0,
        help="Minutes to pause entries after the loss-streak limit is reached.",
    ),
    wide_box_cooldown_count: int = typer.Option(
        3,
        "--wide-box-cooldown-count",
        min=0,
        help="Distinct too-wide straddle boxes before pausing entries. Zero disables wide-box cooldown.",
    ),
    wide_box_cooldown_minutes: float = typer.Option(
        5.0,
        "--wide-box-cooldown-minutes",
        min=0.0,
        help="Minutes to pause entries after repeated too-wide boxes.",
    ),
    post_cooldown_momentum_body_points: float = typer.Option(
        0.80,
        "--post-cooldown-momentum-body-points",
        min=0.0,
        help="Minimum latest-candle body required before entries resume after cooldown.",
    ),
    post_cooldown_momentum_breakout_points: float = typer.Option(
        0.20,
        "--post-cooldown-momentum-breakout-points",
        min=0.0,
        help="Minimum latest-candle close beyond the prior high/low before entries resume after cooldown.",
    ),
    exit_management: bool = typer.Option(
        True,
        "--exit-management/--no-exit-management",
        help="Manage active straddle positions with early exits, break-even, and trailing stops.",
    ),
    break_even_trigger_points: float = typer.Option(
        0.8,
        "--break-even-trigger-points",
        min=0.0,
        help="Favorable price points before moving the stop to break-even. Zero disables break-even.",
    ),
    break_even_lock_points: float = typer.Option(
        0.20,
        "--break-even-lock-points",
        min=0.0,
        help="Price points locked beyond entry when break-even is triggered.",
    ),
    trailing_trigger_points: float = typer.Option(
        0.0,
        "--trailing-trigger-points",
        min=0.0,
        help="Favorable price points before trailing stop management starts. Zero disables trailing.",
    ),
    trailing_distance_points: float = typer.Option(
        0.8,
        "--trailing-distance-points",
        min=0.0,
        help="Distance behind current price used for the trailing stop.",
    ),
    min_stop_update_points: float = typer.Option(
        0.30,
        "--min-stop-update-points",
        min=0.0,
        help="Minimum stop improvement required before sending another stop update.",
    ),
    early_loss_exit_points: float = typer.Option(
        1.5,
        "--early-loss-exit-points",
        min=0.0,
        help="Adverse price points before closing the active position early. Zero disables early loss exit.",
    ),
    scalp_profit_points: float = typer.Option(
        1.50,
        "--scalp-profit-points",
        min=0.0,
        help="Favorable price points before closing the active position to bank a scalp. Zero disables scalp closes.",
    ),
):
    """Run isolated MT5 straddle breakout."""
    _load_runtime_env()
    from tradingagents.agents.straddle_breakout import StraddleBreakoutConfig
    from tradingagents.brokers.mode_gate import TradingMode, parse_trading_mode
    from tradingagents.brokers.mt5 import MT5BrokerError, MT5ConnectionConfig
    from tradingagents.brokers.mt5_straddle import (
        StraddleEntryRegimeConfig,
        MT5StraddleExecutor,
        StraddleExitManagementConfig,
    )

    try:
        trading_mode = parse_trading_mode(DEFAULT_CONFIG.get("trading_mode", "OFF"))
        if trading_mode == TradingMode.OFF:
            console.print(
                json.dumps(
                    _trading_disabled_result("mt5-straddle-run"),
                    indent=2,
                    sort_keys=True,
                )
            )
            return
        if trading_mode == TradingMode.ENTRY_ONLY:
            raise ValueError(
                "mt5-straddle-run requires STRADDLE_ONLY or AUTO_GATED trading mode"
            )
        config = MT5ConnectionConfig.from_env()
        straddle_config = StraddleBreakoutConfig(
            symbol=config.symbol,
            broker_symbol=config.symbol,
            timeframe=timeframe,
            confirmation_timeframe=confirmation_timeframe,
            lookback_candles=lookback_candles,
            entry_buffer_points=entry_buffer_points,
            stop_distance_points=stop_distance_points,
            target_distance_points=target_distance_points,
            activation_window_minutes=activation_window_minutes,
            max_spread_points=max_spread_points,
            min_box_points=min_box_points,
            max_box_points=max_box_points,
        )
        executor = MT5StraddleExecutor(
            config,
            DEFAULT_CONFIG["results_dir"],
            trading_mode=trading_mode.value,
        )
        exit_management_config = StraddleExitManagementConfig(
            enabled=exit_management,
            break_even_trigger_points=break_even_trigger_points,
            break_even_lock_points=break_even_lock_points,
            trailing_trigger_points=trailing_trigger_points,
            trailing_distance_points=trailing_distance_points,
            min_stop_update_points=min_stop_update_points,
            early_loss_exit_points=early_loss_exit_points,
            scalp_profit_points=scalp_profit_points,
        )
        entry_regime_config = StraddleEntryRegimeConfig(
            enabled=entry_regime_filter,
            loss_streak_limit=loss_streak_cooldown_trades,
            loss_cooldown_minutes=loss_cooldown_minutes,
            wide_box_streak_limit=wide_box_cooldown_count,
            wide_box_cooldown_minutes=wide_box_cooldown_minutes,
            post_cooldown_momentum_body_points=post_cooldown_momentum_body_points,
            post_cooldown_momentum_breakout_points=post_cooldown_momentum_breakout_points,
        )
        effective_live = bool(
            live
            or (
                watch
                and trading_mode
                in {TradingMode.STRADDLE_ONLY, TradingMode.AUTO_GATED}
            )
        )
        if watch:
            result = executor.watch_forever(
                straddle_config,
                live=effective_live,
                poll_seconds=poll_seconds,
                max_cycles=max_cycles,
                max_runtime_seconds=(
                    math.ceil(duration_hours * 3600)
                    if duration_hours
                    else 0
                ),
                exit_management=exit_management_config,
                entry_regime=entry_regime_config,
            )
        else:
            pair = executor.build_pair(straddle_config)
            result = executor.execute_pair(pair, live=live)
    except (MT5BrokerError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
