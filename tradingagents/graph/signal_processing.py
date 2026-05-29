"""Extract BUY/SELL/HOLD from the rendered trade plan."""

from __future__ import annotations

from typing import Any

from tradingagents.agents.utils.action_parsing import parse_trade_action


class SignalProcessor:
    """Read the directional trade action without making an LLM call."""

    def __init__(self, quick_thinking_llm: Any = None):
        self.quick_thinking_llm = quick_thinking_llm

    def process_signal(self, full_signal: str) -> str:
        return parse_trade_action(full_signal)
