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
        "TRADINGAGENTS_RUNNER_MAX_CYCLES": "runner_max_cycles",
        "TRADINGAGENTS_RUNNER_MAX_RUNTIME_SECONDS": "runner_max_runtime_seconds",
        "TRADINGAGENTS_TIME_FILTER_MODE": "time_filter_mode",
        "TRADINGAGENTS_DECISION_MODE": "decision_mode",
        "TRADINGAGENTS_MIN_SETUP_GRADE": "minimum_setup_grade",
        "TRADINGAGENTS_B_PLUS_MIN_RR": "b_plus_min_rr",
        "TRADINGAGENTS_FAST_ENTRIES_ENABLED": "fast_entries_enabled",
        "TRADINGAGENTS_FAST_TIMEFRAME": "fast_timeframe",
        "TRADINGAGENTS_FAST_CONFIRMATION_TIMEFRAME": "fast_confirmation_timeframe",
        "TRADINGAGENTS_NORMAL_ACTIVATION_WINDOW_MINUTES": "normal_activation_window_minutes",
        "TRADINGAGENTS_FAST_ACTIVATION_WINDOW_MINUTES": "fast_activation_window_minutes",
        "TRADINGAGENTS_FAST_COUNTER_BIAS_MIN_GRADE": "fast_counter_bias_minimum_grade",
        "TRADINGAGENTS_MIN_STOP_DISTANCE_PRICE": "minimum_stop_distance_price",
        "TRADINGAGENTS_MIN_STOP_SPREAD_MULTIPLE": "minimum_stop_spread_multiple",
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
        else:
            DEFAULT_CONFIG[key] = raw

    DEFAULT_CONFIG["results_dir"] = os.getenv(
        "TRADINGAGENTS_RESULTS_DIR",
        DEFAULT_CONFIG["results_dir"],
    )
    DEFAULT_CONFIG["data_cache_dir"] = os.getenv(
        "TRADINGAGENTS_CACHE_DIR",
        DEFAULT_CONFIG["data_cache_dir"],
    )
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
def broker_probe():
    """Check MT5 account connectivity without placing orders."""
    _load_runtime_env()
    from tradingagents.brokers.mt5 import MT5Broker, MT5BrokerError, MT5ConnectionConfig

    try:
        config = MT5ConnectionConfig.from_env()
        broker = MT5Broker(config)
        result = broker.connect()
    except MT5BrokerError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    finally:
        if "broker" in locals():
            broker.shutdown()

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
    from tradingagents.brokers.mt5_execution import MT5Executor

    try:
        if config is None:
            config = MT5ConnectionConfig.from_env()
        executor = MT5Executor(config, DEFAULT_CONFIG["results_dir"])
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
        )
        from tradingagents.dataflows.price_action import PriceActionSnapshot

        engine_symbol = selections["ticker"]
        broker_symbol = selections.get("broker_symbol")
        snapshot = None
        if mt5_config is not None:
            engine_symbol = mt5_config.symbol
            broker_symbol = mt5_config.symbol
            analysis_broker = MT5Broker(mt5_config)
            analysis_broker.connect()
            snapshot = fetch_mt5_price_action_snapshot(
                analysis_broker,
                as_of=selections["as_of"],
                market_timezone=selections.get(
                    "market_timezone",
                    DEFAULT_CONFIG["market_timezone"],
                ),
            )

        market_timezone = selections.get(
            "market_timezone",
            DEFAULT_CONFIG["market_timezone"],
        )
        profiles = [normal_profile(DEFAULT_CONFIG)]
        if DEFAULT_CONFIG.get("fast_entries_enabled"):
            profiles.append(fast_profile(DEFAULT_CONFIG))

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
                            profile.timeframe,
                            profile.confirmation_timeframe,
                        )
                    )
                )
                profile_snapshot = PriceActionSnapshot(
                    candles=snapshot.candles,
                    data_status=build_data_status(
                        snapshot.candles,
                        profile_as_of,
                        market_timezone,
                        required_timeframes=required_timeframes,
                        trading_timeframe=profile.timeframe,
                        confirmation_timeframe=profile.confirmation_timeframe,
                    ),
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
    from tradingagents.brokers.mt5 import MT5BrokerError, MT5ConnectionConfig
    from tradingagents.brokers.mt5_execution import MT5Executor
    from tradingagents.brokers.mt5_runner import MT5Runner, MT5RunnerConfig

    try:
        normalized_decision_mode = decision_mode.strip().lower()
        if normalized_decision_mode not in {"engine", "graph"}:
            raise typer.BadParameter("decision-mode must be 'engine' or 'graph'")
        config = MT5ConnectionConfig.from_env()
        executor = MT5Executor(config, DEFAULT_CONFIG["results_dir"])
        analysis_func = (
            _mt5_runner_engine_analysis_func(config)
            if normalized_decision_mode == "engine"
            else _mt5_runner_analysis_func()
        )
        runner = MT5Runner(
            MT5RunnerConfig(
                results_dir=DEFAULT_CONFIG["results_dir"],
                poll_seconds=poll_seconds,
                max_cycles=(
                    1
                    if once
                    else (
                        0
                        if duration_hours
                        else int(DEFAULT_CONFIG.get("runner_max_cycles", 0))
                    )
                ),
                max_runtime_seconds=(
                    math.ceil(duration_hours * 3600)
                    if duration_hours
                    else int(DEFAULT_CONFIG.get("runner_max_runtime_seconds", 0))
                ),
            ),
            executor=executor,
            analysis_func=analysis_func,
            current_as_of_func=_mt5_runner_current_as_of_func(),
        )
        result = runner.run_once() if once else runner.run_forever()
    except (MT5BrokerError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    app()
