from typing import Any, Dict

from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from tradingagents.agents import (
    create_order_proposal_executor,
    create_price_action_analyst,
    create_trader,
)
from tradingagents.agents.utils.agent_states import AgentState

from .conditional_logic import ConditionalLogic


class GraphSetup:
    """Build the compact price-action playbook workflow."""

    def __init__(
        self,
        quick_thinking_llm: Any,
        deep_thinking_llm: Any,
        tool_nodes: Dict[str, ToolNode],
        conditional_logic: ConditionalLogic,
        config: dict,
    ):
        self.quick_thinking_llm = quick_thinking_llm
        self.deep_thinking_llm = deep_thinking_llm
        self.tool_nodes = tool_nodes
        self.conditional_logic = conditional_logic
        self.config = config

    def setup_graph(self):
        price_action_analyst = create_price_action_analyst(self.quick_thinking_llm)
        trader = create_trader(self.quick_thinking_llm)
        order_proposal = create_order_proposal_executor(self.config)

        workflow = StateGraph(AgentState)
        workflow.add_node("Price Action Analyst", price_action_analyst)
        workflow.add_node("tools_price_action", self.tool_nodes["price_action"])
        workflow.add_node("Trader", trader)
        workflow.add_node("Order Proposal", order_proposal)

        workflow.add_edge(START, "Price Action Analyst")
        workflow.add_conditional_edges(
            "Price Action Analyst",
            self.conditional_logic.should_continue_price_action,
            ["tools_price_action", "Trader"],
        )
        workflow.add_edge("tools_price_action", "Price Action Analyst")
        workflow.add_edge("Trader", "Order Proposal")
        workflow.add_edge("Order Proposal", END)

        return workflow
