from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

from tradingagents.agents.utils.agent_utils import (
    build_instrument_context,
    get_language_instruction,
    get_playbook_setups,
)


def create_price_action_analyst(llm):
    """Create the Price Action Analyst node."""

    def price_action_analyst_node(state):
        symbol = state["company_of_interest"]
        as_of = state["as_of"]
        timeframe = state["timeframe"]
        confirmation_timeframe = state["confirmation_timeframe"]
        instrument_context = build_instrument_context(symbol)
        tools = [get_playbook_setups]

        system_message = f"""You are the Price Action Analyst for a strict A+ setup playbook.

Your sole job is to call `get_playbook_setups` and write a report from that tool output only.
Do not use MACD, RSI, moving averages, Bollinger Bands, fundamentals, news, or sentiment.

Playbook setups:
- The Breakout: a decisive candle close beyond support or resistance.
- Buys/Sells off Support/Resistance: rejection from a known horizontal level.
- The Break and Retest: price breaks a level, returns to it, then rejects it.
- Impulse and impulse break-and-retest variations are part of the same playbook.

A+ checklist to discuss:
- Is it volume time?
- Is it a playbook setup?
- Is there 15m/30m timeframe correlation?
- Is there a clean range to fill?
- Has the candle closed?
- Is it not overextended and not already at target?
- Is it not the last 15 minutes of a 4h candle?
- Is it not 15 minutes before the market opens?
- Is it not a Sunday Asian session?
- Does the confirmation candle have both top and bottom wick?
- Does the trading candle have the stop-loss wick?
- Is the order not activated in the last 5 minutes of the 15m candle?

Report format:
1. Setup verdict: name the setup or say No Valid Setup.
2. Direction: BUY, SELL, or HOLD.
3. Checklist: pass/fail/unknown for each available rule.
4. Levels: support, resistance, entry model, stop area, target/range if available.
5. Trading note: one concise paragraph for the Trader.

If the tool returns NO_SETUP, the report must clearly recommend HOLD.
Use `{timeframe}` as the trading timeframe and `{confirmation_timeframe}` as confirmation.
{get_language_instruction()}"""

        prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are a focused price-action analyst. "
                    "You have access to these tools: {tool_names}.\n"
                    "{system_message}\n"
                    "As of timestamp: {as_of}. {instrument_context}",
                ),
                MessagesPlaceholder(variable_name="messages"),
            ]
        )

        prompt = prompt.partial(system_message=system_message)
        prompt = prompt.partial(tool_names=", ".join([tool.name for tool in tools]))
        prompt = prompt.partial(as_of=as_of)
        prompt = prompt.partial(instrument_context=instrument_context)

        chain = prompt | llm.bind_tools(tools)
        result = chain.invoke(state["messages"])
        report = "" if getattr(result, "tool_calls", None) else result.content

        return {
            "messages": [result],
            "price_action_report": report,
            "sender": "Price Action Analyst",
        }

    return price_action_analyst_node


# Backwards-compatible import name while the repo is being slimmed down.
def create_market_analyst(llm):
    return create_price_action_analyst(llm)
