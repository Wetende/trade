from typing import Annotated, Optional

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """State passed through the price-action playbook graph."""

    company_of_interest: Annotated[str, "Instrument ticker to analyze"]
    as_of: Annotated[str, "Analysis timestamp in market timezone"]
    timeframe: Annotated[str, "Trading timeframe, e.g. 15m"]
    confirmation_timeframe: Annotated[str, "Higher timeframe confirmation, e.g. 30m"]
    market_timezone: Annotated[str, "Market timezone, e.g. America/New_York"]
    sender: Annotated[Optional[str], "Agent that sent the latest message"]

    price_action_report: Annotated[str, "Report from the Price Action Analyst"]
    trade_plan: Annotated[str, "Structured markdown trade plan from the Trader"]
    order_proposal: Annotated[str, "Local proposed order or no-trade artifact"]
    order_proposal_path: Annotated[Optional[str], "JSON file path for the local order proposal"]
