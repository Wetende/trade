"""Trader: converts the price-action report into a trade plan."""

from __future__ import annotations

import functools

from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TradePlan, render_trade_plan
from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext,
)


def create_trader(llm):
    structured_llm = bind_structured(llm, TradePlan, "Trader")

    def trader_node(state, name):
        symbol = state["company_of_interest"]
        instrument_context = build_instrument_context(symbol)
        report = state["price_action_report"]
        timeframe = state["timeframe"]
        confirmation_timeframe = state["confirmation_timeframe"]

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a price-action trader. Trade only the playbook: "
                    "The Breakout, Buys/Sells off Support/Resistance, and The Break and Retest. "
                    "If the analyst report does not confirm a valid setup, output HOLD. "
                    "Do not use fundamentals, news, sentiment, MACD, RSI, or other indicators."
                    + get_language_instruction()
                ),
            },
            {
                "role": "user",
                "content": (
                    f"{instrument_context}\n"
                    f"Trading timeframe: {timeframe}\n"
                    f"Confirmation timeframe: {confirmation_timeframe}\n\n"
                    f"Price Action Analyst report:\n{report}\n\n"
                    "Return a BUY, SELL, or HOLD trade plan. For BUY/SELL include a limit "
                    "entry, stop loss, take profit, setup name, confidence, checklist status, "
                    "and concise reason. For HOLD, leave prices null and explain which rule failed."
                ),
            },
        ]

        trade_plan = invoke_structured_or_freetext(
            structured_llm,
            llm,
            messages,
            render_trade_plan,
            "Trader",
        )

        return {
            "messages": [AIMessage(content=trade_plan)],
            "trade_plan": trade_plan,
            "sender": name,
        }

    return functools.partial(trader_node, name="Trader")
