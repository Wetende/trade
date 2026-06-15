"""Price-action entry model dispatcher.

The public runner API stays as ``analyze_playbook`` while the actual strategy
implementations live in dedicated modules. This keeps the 1m candle-reader
model isolated from the 15m/30m playbook detectors.
"""

from __future__ import annotations

from typing import Any

from tradingagents.agents.price_action.normal_entry_model import analyze_normal_entry


def _is_one_minute_profile(session_config: dict[str, Any] | None) -> bool:
    config = session_config or {}
    profile = str(config.get("entry_profile", "normal")).strip().lower()
    timeframe = str(config.get("timeframe", "15m")).strip().lower()
    return profile == "fast" and timeframe in {"1m", "m1"}


def analyze_playbook(
    symbol: str,
    as_of: str,
    timeframe_data: dict[str, Any],
    market_timezone: str = "America/New_York",
    session_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route to the selected deterministic entry model."""
    if _is_one_minute_profile(session_config):
        from tradingagents.agents.price_action.one_minute_entry_model import (
            analyze_one_minute_entry,
        )

        return analyze_one_minute_entry(
            symbol,
            as_of,
            timeframe_data,
            market_timezone=market_timezone,
            session_config=session_config,
        )

    return analyze_normal_entry(
        symbol,
        as_of,
        timeframe_data,
        market_timezone=market_timezone,
        session_config=session_config,
    )
