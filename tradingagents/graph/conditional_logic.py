from tradingagents.agents.utils.agent_states import AgentState


class ConditionalLogic:
    """Route the price-action analyst through its tool call cycle."""

    def should_continue_price_action(self, state: AgentState):
        messages = state["messages"]
        last_message = messages[-1]
        if getattr(last_message, "tool_calls", None):
            return "tools_price_action"
        return "Trader"
