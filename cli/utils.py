import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

import questionary
from dotenv import find_dotenv, set_key
from rich.console import Console

from tradingagents.dataflows.utils import safe_ticker_component
from tradingagents.llm_clients.api_key_env import get_api_key_env
from tradingagents.llm_clients.model_catalog import get_model_options

console = Console()

TICKER_INPUT_EXAMPLES = "Examples: SPY, QQQ, ES=F, BTC-USD, 0700.HK, ^GSPC"


def normalize_ticker_symbol(ticker: str) -> str:
    return ticker.strip().upper()


def validate_ticker_symbol(ticker: str):
    if not isinstance(ticker, str) or not ticker:
        return "Please enter a valid ticker symbol."
    if ticker != ticker.strip():
        return "Ticker symbols cannot include leading or trailing whitespace."

    normalized = normalize_ticker_symbol(ticker)
    try:
        safe_ticker_component(normalized)
    except ValueError as exc:
        return str(exc)
    return True


def get_ticker() -> str:
    ticker = questionary.text(
        f"Enter the exact ticker symbol to analyze ({TICKER_INPUT_EXAMPLES}):",
        validate=validate_ticker_symbol,
    ).ask()
    if not ticker:
        console.print("\n[red]No ticker symbol provided. Exiting...[/red]")
        raise SystemExit(1)
    normalized = normalize_ticker_symbol(ticker)
    safe_ticker_component(normalized)
    return normalized


def timeframe_to_minutes(timeframe: str) -> int:
    match = re.fullmatch(r"(\d+)\s*m", timeframe.strip().lower())
    if not match:
        raise ValueError("Only minute timeframes like 15m or 30m are supported.")
    return int(match.group(1))


def normalize_as_of_timestamp(value: str, market_timezone: str) -> str:
    raw = value.strip().replace("T", " ")
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M")
    except ValueError as exc:
        raise ValueError("Use YYYY-MM-DD HH:MM, e.g. 2026-05-17 10:15.") from exc
    tz = ZoneInfo(market_timezone)
    return parsed.replace(tzinfo=tz).strftime("%Y-%m-%d %H:%M")


def last_closed_candle(
    timeframe: str = "15m",
    market_timezone: str = "America/New_York",
    now: Optional[datetime] = None,
) -> str:
    minutes = timeframe_to_minutes(timeframe)
    tz = ZoneInfo(market_timezone)
    local_now = (now or datetime.now(tz)).astimezone(tz)
    bucket_minute = (local_now.minute // minutes) * minutes
    current_bucket = local_now.replace(minute=bucket_minute, second=0, microsecond=0)
    closed = current_bucket - timedelta(minutes=minutes)
    return closed.strftime("%Y-%m-%d %H:%M")


def get_as_of_timestamp(timeframe: str, market_timezone: str) -> str:
    default = last_closed_candle(timeframe, market_timezone)
    answer = questionary.text(
        f"As-of timestamp in {market_timezone} (YYYY-MM-DD HH:MM):",
        default=default,
        validate=lambda x: _validate_as_of(x, market_timezone),
    ).ask()
    if not answer:
        return default
    return normalize_as_of_timestamp(answer, market_timezone)


def _validate_as_of(value: str, market_timezone: str):
    try:
        normalize_as_of_timestamp(value, market_timezone)
        return True
    except ValueError as exc:
        return str(exc)


def _fetch_openrouter_models() -> List[Tuple[str, str]]:
    import requests

    try:
        resp = requests.get("https://openrouter.ai/api/v1/models", timeout=10)
        resp.raise_for_status()
        models = resp.json().get("data", [])
        return [(m.get("name") or m["id"], m["id"]) for m in models]
    except Exception as e:
        console.print(f"\n[yellow]Could not fetch OpenRouter models: {e}[/yellow]")
        return []


def select_openrouter_model() -> str:
    models = _fetch_openrouter_models()
    choices = [questionary.Choice(name, value=mid) for name, mid in models[:5]]
    choices.append(questionary.Choice("Custom model ID", value="custom"))
    choice = questionary.select("Select OpenRouter Model:", choices=choices).ask()
    if choice is None or choice == "custom":
        return _prompt_custom_model_id()
    return choice


def _prompt_custom_model_id() -> str:
    return questionary.text(
        "Enter model ID:",
        validate=lambda x: len(x.strip()) > 0 or "Please enter a model ID.",
    ).ask().strip()


def _select_model(provider: str, mode: str) -> str:
    provider_lower = provider.lower()
    if provider_lower == "openrouter":
        return select_openrouter_model()
    if provider_lower == "azure":
        return questionary.text(
            f"Enter Azure deployment name ({mode}-thinking):",
            validate=lambda x: len(x.strip()) > 0 or "Please enter a deployment name.",
        ).ask().strip()

    choice = questionary.select(
        f"Select your {mode}-thinking LLM:",
        choices=[
            questionary.Choice(display, value=value)
            for display, value in get_model_options(provider, mode)
        ],
    ).ask()
    if choice is None:
        console.print(f"\n[red]No {mode} model selected. Exiting...[/red]")
        raise SystemExit(1)
    if choice == "custom":
        return _prompt_custom_model_id()
    return choice


def select_shallow_thinking_agent(provider) -> str:
    return _select_model(provider, "quick")


def select_deep_thinking_agent(provider) -> str:
    return _select_model(provider, "deep")


def select_llm_provider() -> tuple[str, str | None]:
    ollama_url = os.environ.get("OLLAMA_BASE_URL") or "http://localhost:11434/v1"
    providers = [
        ("OpenAI", "openai", "https://api.openai.com/v1"),
        ("Google", "google", None),
        ("Anthropic", "anthropic", "https://api.anthropic.com/"),
        ("xAI", "xai", "https://api.x.ai/v1"),
        ("DeepSeek", "deepseek", "https://api.deepseek.com"),
        ("Qwen", "qwen", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        ("GLM", "glm", "https://open.bigmodel.cn/api/paas/v4/"),
        ("MiniMax", "minimax", "https://api.minimax.io/v1"),
        ("OpenRouter", "openrouter", "https://openrouter.ai/api/v1"),
        ("Azure OpenAI", "azure", None),
        ("Ollama", "ollama", ollama_url),
    ]
    choice = questionary.select(
        "Select your LLM provider:",
        choices=[
            questionary.Choice(display, value=(provider_key, url))
            for display, provider_key, url in providers
        ],
    ).ask()
    if choice is None:
        console.print("\n[red]No LLM provider selected. Exiting...[/red]")
        raise SystemExit(1)
    return choice


def ask_qwen_region() -> tuple[str, str]:
    return questionary.select(
        "Select Qwen region:",
        choices=[
            questionary.Choice(
                "International - dashscope-intl.aliyuncs.com",
                value=("qwen", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
            ),
            questionary.Choice(
                "China - dashscope.aliyuncs.com",
                value=("qwen-cn", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            ),
        ],
    ).ask()


def ask_glm_region() -> tuple[str, str]:
    return questionary.select(
        "Select GLM platform:",
        choices=[
            questionary.Choice("Z.AI international", value=("glm", "https://api.z.ai/api/paas/v4/")),
            questionary.Choice("BigModel China", value=("glm-cn", "https://open.bigmodel.cn/api/paas/v4/")),
        ],
    ).ask()


def ask_minimax_region() -> tuple[str, str]:
    return questionary.select(
        "Select MiniMax region:",
        choices=[
            questionary.Choice("Global - api.minimax.io", value=("minimax", "https://api.minimax.io/v1")),
            questionary.Choice("China - api.minimaxi.com", value=("minimax-cn", "https://api.minimaxi.com/v1")),
        ],
    ).ask()


def confirm_ollama_endpoint(url: str) -> None:
    from_env = os.environ.get("OLLAMA_BASE_URL")
    origin = " (from OLLAMA_BASE_URL)" if from_env and from_env == url else ""
    console.print(f"[green]Using Ollama at {url}{origin}[/green]")

    if not url.startswith(("http://", "https://")):
        console.print(
            f"[yellow]Note: {url!r} is missing a scheme. "
            "Ollama usually expects http://<host>:11434/v1.[/yellow]"
        )
    elif ":11434" not in url and "://localhost" not in url and "://127.0.0.1" not in url:
        console.print(
            f"[yellow]Note: {url!r} does not include port 11434. "
            "Make sure your remote Ollama server listens on the port shown above.[/yellow]"
        )


def ensure_api_key(provider: str) -> Optional[str]:
    env_var = get_api_key_env(provider)
    if env_var is None:
        return None

    existing = os.environ.get(env_var)
    if existing:
        return existing

    console.print(f"\n[yellow]{env_var} is not set in your environment.[/yellow]")
    key = questionary.password(f"Paste your {env_var} (will be saved to .env):").ask()
    if not key:
        console.print(f"[red]Skipped. API calls will fail until {env_var} is set.[/red]")
        return None

    env_path = find_dotenv(usecwd=True) or str(Path.cwd() / ".env")
    Path(env_path).touch(exist_ok=True)
    set_key(env_path, env_var, key)
    os.environ[env_var] = key
    console.print(f"[green]Saved {env_var} to {env_path}[/green]")
    return key


def ask_output_language() -> str:
    choice = questionary.select(
        "Select output language:",
        choices=[
            questionary.Choice("English (default)", "English"),
            questionary.Choice("Chinese", "Chinese"),
            questionary.Choice("Spanish", "Spanish"),
            questionary.Choice("French", "French"),
            questionary.Choice("Custom language", "custom"),
        ],
    ).ask()
    if choice == "custom":
        return questionary.text(
            "Enter language name:",
            validate=lambda x: len(x.strip()) > 0 or "Please enter a language name.",
        ).ask().strip()
    return choice or "English"


def ask_openai_reasoning_effort() -> str:
    return questionary.select(
        "Select OpenAI reasoning effort:",
        choices=[
            questionary.Choice("Medium", "medium"),
            questionary.Choice("High", "high"),
            questionary.Choice("Low", "low"),
        ],
    ).ask()


def ask_anthropic_effort() -> str | None:
    return questionary.select(
        "Select Anthropic effort:",
        choices=[
            questionary.Choice("High", "high"),
            questionary.Choice("Medium", "medium"),
            questionary.Choice("Low", "low"),
        ],
    ).ask()


def ask_gemini_thinking_config() -> str | None:
    return questionary.select(
        "Select Gemini thinking mode:",
        choices=[
            questionary.Choice("Enable thinking", "high"),
            questionary.Choice("Minimal thinking", "minimal"),
        ],
    ).ask()
