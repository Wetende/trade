import datetime
from pathlib import Path

import typer
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


def get_user_selections():
    console.print(Panel("[bold green]Price Action Playbook[/bold green]", title="TradingAgents"))

    ticker = get_ticker()
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


def run_analysis(checkpoint: bool = False):
    selections = get_user_selections()
    config = build_config(selections, checkpoint)

    graph = TradingAgentsGraph(config=config, debug=False)
    final_state, decision = graph.propagate(selections["ticker"], selections["as_of"])

    console.print()
    console.print(Panel(f"[bold]Decision:[/bold] {decision}", title="Result", border_style="green"))
    console.print(Panel(Markdown(final_state.get("price_action_report", "")), title="Price Action Analyst"))
    console.print(Panel(Markdown(final_state.get("trade_plan", "")), title="Trader"))
    console.print(Panel(Markdown(final_state.get("order_proposal", "")), title="Order Proposal"))

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
):
    if clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints

        n = clear_all_checkpoints(DEFAULT_CONFIG["data_cache_dir"])
        console.print(f"[yellow]Cleared {n} checkpoint(s).[/yellow]")
    run_analysis(checkpoint=checkpoint)


if __name__ == "__main__":
    app()
