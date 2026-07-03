import io
import os
import shutil
from pathlib import Path

import cli.main as cli_main
import pytest
from cli.main import build_config
from rich.console import Console
from typer.testing import CliRunner


runner = CliRunner()


def test_cli_pretty_exceptions_do_not_show_locals():
    assert cli_main.app.pretty_exceptions_show_locals is False


def test_get_user_selections_uses_config_broker_symbol(monkeypatch):
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "analysis_symbol", None)
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "broker_symbol", "XAUUSD.vx")
    monkeypatch.setattr(cli_main, "get_ticker", lambda: "GC=F")
    monkeypatch.setattr(cli_main, "ask_output_language", lambda: "English")
    monkeypatch.setattr(cli_main, "get_as_of_timestamp", lambda timeframe, market_timezone: "2026-05-27 10:15")
    monkeypatch.setattr(cli_main, "select_llm_provider", lambda: ("openai", "https://api.openai.com/v1"))
    monkeypatch.setattr(cli_main, "ensure_api_key", lambda llm_provider: None)
    monkeypatch.setattr(cli_main, "select_shallow_thinking_agent", lambda llm_provider: "gpt-5.4-mini")
    monkeypatch.setattr(cli_main, "select_deep_thinking_agent", lambda llm_provider: "gpt-5.4")
    monkeypatch.setattr(cli_main, "ask_openai_reasoning_effort", lambda: "medium")

    selections = cli_main.get_user_selections()

    assert selections["ticker"] == "GC=F"
    assert selections["broker_symbol"] == "XAUUSD.vx"


def test_get_user_selections_uses_configured_analysis_symbol_without_prompt(monkeypatch):
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "analysis_symbol", "GC=F")
    monkeypatch.setitem(cli_main.DEFAULT_CONFIG, "broker_symbol", "XAUUSD.vx")
    monkeypatch.setattr(
        cli_main,
        "get_ticker",
        lambda: pytest.fail("get_ticker should not be called when analysis_symbol is configured"),
    )
    monkeypatch.setattr(cli_main, "ask_output_language", lambda: "English")
    monkeypatch.setattr(cli_main, "get_as_of_timestamp", lambda timeframe, market_timezone: "2026-05-27 10:15")
    monkeypatch.setattr(cli_main, "select_llm_provider", lambda: ("openai", "https://api.openai.com/v1"))
    monkeypatch.setattr(cli_main, "ensure_api_key", lambda llm_provider: None)
    monkeypatch.setattr(cli_main, "select_shallow_thinking_agent", lambda llm_provider: "gpt-5.4-mini")
    monkeypatch.setattr(cli_main, "select_deep_thinking_agent", lambda llm_provider: "gpt-5.4")
    monkeypatch.setattr(cli_main, "ask_openai_reasoning_effort", lambda: "medium")

    selections = cli_main.get_user_selections()
    config = build_config(selections, checkpoint=False)

    assert selections["ticker"] == "GC=F"
    assert selections["broker_symbol"] == "XAUUSD.vx"
    assert config["analysis_symbol"] == "GC=F"
    assert config["broker_symbol"] == "XAUUSD.vx"


def test_build_config_carries_broker_symbol():
    selections = {
        "ticker": "GC=F",
        "broker_symbol": "XAUUSD.vx",
        "llm_provider": "openai",
        "backend_url": None,
        "quick_model": "gpt-5.4-mini",
        "deep_model": "gpt-5.4",
        "timeframe": "15m",
        "confirmation_timeframe": "30m",
        "market_timezone": "America/New_York",
        "output_language": "English",
    }

    config = build_config(selections, checkpoint=False)

    assert config["analysis_symbol"] == "GC=F"
    assert config["broker_symbol"] == "XAUUSD.vx"


def test_build_env_selections_uses_analysis_and_broker_symbols(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_SYMBOL", "GC=F")
    monkeypatch.setenv("TRADINGAGENTS_BROKER_SYMBOL", "XAUUSD.vx")
    monkeypatch.setenv("TRADINGAGENTS_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("TRADINGAGENTS_LLM_BACKEND_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("TRADINGAGENTS_QUICK_THINK_LLM", "llama3.2")
    monkeypatch.setenv("TRADINGAGENTS_DEEP_THINK_LLM", "qwen2.5")
    monkeypatch.setenv("TRADINGAGENTS_OUTPUT_LANGUAGE", "English")
    monkeypatch.setattr(cli_main, "last_closed_candle", lambda timeframe, market_timezone: "2026-05-27 10:15")
    monkeypatch.setattr(cli_main, "get_ticker", lambda: pytest.fail("non-interactive should not prompt for ticker"))
    monkeypatch.setattr(cli_main, "ensure_api_key", lambda provider: pytest.fail("non-interactive should not prompt for keys"))

    selections = cli_main.build_env_selections()

    assert selections["ticker"] == "GC=F"
    assert selections["broker_symbol"] == "XAUUSD.vx"
    assert selections["as_of"] == "2026-05-27 10:15"
    assert selections["llm_provider"] == "ollama"
    assert selections["backend_url"] == "http://localhost:11434/v1"
    assert selections["quick_model"] == "llama3.2"
    assert selections["deep_model"] == "qwen2.5"
    assert selections["output_language"] == "English"


def test_analyze_non_interactive_passes_env_selections(monkeypatch):
    captured = {}
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_SYMBOL", "GC=F")
    monkeypatch.setenv("TRADINGAGENTS_BROKER_SYMBOL", "XAUUSD.vx")
    monkeypatch.setattr(cli_main, "last_closed_candle", lambda timeframe, market_timezone: "2026-05-27 10:15")
    monkeypatch.setattr(cli_main, "run_analysis", lambda checkpoint=False, selections=None: captured.update(
        checkpoint=checkpoint,
        selections=selections,
    ))
    monkeypatch.setattr(cli_main, "get_user_selections", lambda: pytest.fail("non-interactive should not prompt"))

    result = runner.invoke(cli_main.app, ["analyze", "--non-interactive", "--as-of", "2026-05-27 10:30"])

    assert result.exit_code == 0
    assert captured["checkpoint"] is False
    assert captured["selections"]["ticker"] == "GC=F"
    assert captured["selections"]["broker_symbol"] == "XAUUSD.vx"
    assert captured["selections"]["as_of"] == "2026-05-27 10:30"


def test_analyze_non_interactive_cli_symbol_overrides_env(monkeypatch):
    captured = {}
    monkeypatch.setenv("TRADINGAGENTS_ANALYSIS_SYMBOL", "GC=F")
    monkeypatch.setenv("TRADINGAGENTS_BROKER_SYMBOL", "XAUUSD.vx")
    monkeypatch.setattr(cli_main, "last_closed_candle", lambda timeframe, market_timezone: "2026-05-27 10:15")
    monkeypatch.setattr(cli_main, "run_analysis", lambda checkpoint=False, selections=None: captured.update(
        checkpoint=checkpoint,
        selections=selections,
    ))

    result = runner.invoke(
        cli_main.app,
        [
            "analyze",
            "--non-interactive",
            "--symbol",
            "SI=F",
            "--broker-symbol",
            "XAGUSD.vx",
        ],
    )

    assert result.exit_code == 0
    assert captured["selections"]["ticker"] == "SI=F"
    assert captured["selections"]["broker_symbol"] == "XAGUSD.vx"


def test_load_runtime_env_reads_dotenv_from_cwd(monkeypatch):
    original_cwd = Path.cwd()
    workspace = (Path.cwd() / "test-artifacts" / "dotenv-cwd").resolve()
    if workspace.exists():
        if workspace.exists():
            shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    env_file = workspace / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TRADINGAGENTS_ANALYSIS_SYMBOL=SI=F",
                "TRADINGAGENTS_BROKER_SYMBOL=XAGUSD.vx",
                "TRADINGAGENTS_TIMEFRAME=30m",
                "TRADINGAGENTS_TIME_FILTER_MODE=allow",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(workspace)
    for key in (
        "TRADINGAGENTS_ANALYSIS_SYMBOL",
        "TRADINGAGENTS_BROKER_SYMBOL",
        "TRADINGAGENTS_TIMEFRAME",
        "TRADINGAGENTS_TIME_FILTER_MODE",
    ):
        monkeypatch.delenv(key, raising=False)

    original = {
        "analysis_symbol": cli_main.DEFAULT_CONFIG.get("analysis_symbol"),
        "broker_symbol": cli_main.DEFAULT_CONFIG.get("broker_symbol"),
        "timeframe": cli_main.DEFAULT_CONFIG.get("timeframe"),
        "time_filter_mode": cli_main.DEFAULT_CONFIG.get("time_filter_mode"),
        "price_action_time_filter_mode": cli_main.DEFAULT_CONFIG["price_action"].get("time_filter_mode"),
    }
    try:
        cli_main._load_runtime_env()
        assert os.environ["TRADINGAGENTS_ANALYSIS_SYMBOL"] == "SI=F"
        assert cli_main.DEFAULT_CONFIG["analysis_symbol"] == "SI=F"
        assert cli_main.DEFAULT_CONFIG["broker_symbol"] == "XAGUSD.vx"
        assert cli_main.DEFAULT_CONFIG["timeframe"] == "30m"
        assert cli_main.DEFAULT_CONFIG["time_filter_mode"] == "allow"
        assert cli_main.DEFAULT_CONFIG["price_action"]["time_filter_mode"] == "allow"
    finally:
        monkeypatch.chdir(original_cwd)
        cli_main.DEFAULT_CONFIG["analysis_symbol"] = original["analysis_symbol"]
        cli_main.DEFAULT_CONFIG["broker_symbol"] = original["broker_symbol"]
        cli_main.DEFAULT_CONFIG["timeframe"] = original["timeframe"]
        cli_main.DEFAULT_CONFIG["time_filter_mode"] = original["time_filter_mode"]
        cli_main.DEFAULT_CONFIG["price_action"]["time_filter_mode"] = original[
            "price_action_time_filter_mode"
        ]
        shutil.rmtree(workspace)


class Cp1252Buffer(io.StringIO):
    encoding = "cp1252"

    def write(self, text):
        text.encode(self.encoding)
        return super().write(text)


def test_run_analysis_renders_safely_for_cp1252_console(monkeypatch):
    class FakeGraph:
        def __init__(self, config, debug=False):
            self.config = config
            self.debug = debug

        def propagate(self, ticker, as_of):
            return (
                {
                    "price_action_report": "## Price-Action Report — GC=F\n\nUnicode report 😀 with box char ─",
                    "trade_plan": "## Trader Plan\n\nTrader note 😀",
                    "order_proposal": "## Order Proposal\n\nOrder note 😀",
                },
                "HOLD",
            )

    buffer = Cp1252Buffer()
    monkeypatch.setattr(
        cli_main,
        "console",
        Console(file=buffer, force_terminal=False, color_system=None, width=79),
    )
    monkeypatch.setattr(cli_main, "TradingAgentsGraph", FakeGraph)
    monkeypatch.setattr(cli_main, "save_report_to_disk", lambda *args, **kwargs: Path("report.md"))

    final_state, decision = cli_main.run_analysis(
        checkpoint=False,
        selections={
            "ticker": "GC=F",
            "broker_symbol": "XAUUSD.vx",
            "as_of": "2026-05-29 10:15",
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "market_timezone": "America/New_York",
            "llm_provider": "openrouter",
            "backend_url": None,
            "quick_model": "deepseek/deepseek-v4-flash",
            "deep_model": "deepseek/deepseek-v4-flash",
            "output_language": "English",
        },
    )

    rendered = buffer.getvalue()

    assert decision == "HOLD"
    assert final_state["price_action_report"].startswith("## Price-Action Report")
    assert "Decision:" in rendered
    assert "?" in rendered
