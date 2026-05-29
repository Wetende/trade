from typing import Any, Dict, List, Optional


class Propagator:
    """Initialize and invoke the compact price-action graph."""

    def __init__(self, max_recur_limit=20):
        self.max_recur_limit = max_recur_limit

    def create_initial_state(
        self,
        company_name: str,
        as_of: str,
        *,
        timeframe: str = "15m",
        confirmation_timeframe: str = "30m",
        market_timezone: str = "America/New_York",
        broker_symbol: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "messages": [("human", company_name)],
            "company_of_interest": company_name,
            "broker_symbol": broker_symbol or company_name,
            "as_of": str(as_of),
            "timeframe": timeframe,
            "confirmation_timeframe": confirmation_timeframe,
            "market_timezone": market_timezone,
            "sender": None,
            "price_action_report": "",
            "trade_plan": "",
            "order_proposal": "",
            "order_proposal_path": None,
        }

    def get_graph_args(self, callbacks: Optional[List] = None) -> Dict[str, Any]:
        config = {"recursion_limit": self.max_recur_limit}
        if callbacks:
            config["callbacks"] = callbacks
        return {
            "stream_mode": "values",
            "config": config,
        }
