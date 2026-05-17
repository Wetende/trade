import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from langgraph.prebuilt import ToolNode

from tradingagents.agents.utils.agent_utils import get_playbook_setups
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.llm_clients import create_llm_client
from tradingagents.dataflows.config import set_config
from tradingagents.dataflows.utils import safe_ticker_component

from .checkpointer import checkpoint_step, clear_checkpoint, get_checkpointer, thread_id
from .conditional_logic import ConditionalLogic
from .propagation import Propagator
from .setup import GraphSetup
from .signal_processing import SignalProcessor

logger = logging.getLogger(__name__)


class TradingAgentsGraph:
    """Orchestrates the price-action playbook trading assistant."""

    def __init__(
        self,
        selected_analysts=None,
        debug=False,
        config: Dict[str, Any] = None,
        callbacks: Optional[List] = None,
    ):
        self.debug = debug
        self.config = config or DEFAULT_CONFIG
        self.callbacks = callbacks or []

        set_config(self.config)
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        llm_kwargs = self._get_provider_kwargs()
        if self.callbacks:
            llm_kwargs["callbacks"] = self.callbacks

        deep_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["deep_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )
        quick_client = create_llm_client(
            provider=self.config["llm_provider"],
            model=self.config["quick_think_llm"],
            base_url=self.config.get("backend_url"),
            **llm_kwargs,
        )

        self.deep_thinking_llm = deep_client.get_llm()
        self.quick_thinking_llm = quick_client.get_llm()
        self.tool_nodes = self._create_tool_nodes()
        self.conditional_logic = ConditionalLogic()
        self.graph_setup = GraphSetup(
            self.quick_thinking_llm,
            self.deep_thinking_llm,
            self.tool_nodes,
            self.conditional_logic,
            self.config,
        )
        self.propagator = Propagator(
            max_recur_limit=self.config.get("max_recur_limit", 20),
        )
        self.signal_processor = SignalProcessor()
        self.curr_state = None
        self.ticker = None
        self.log_states_dict = {}
        self.workflow = self.graph_setup.setup_graph()
        self.graph = self.workflow.compile()
        self._checkpointer_ctx = None

    def _get_provider_kwargs(self) -> Dict[str, Any]:
        kwargs = {}
        provider = self.config.get("llm_provider", "").lower()
        if provider == "google" and self.config.get("google_thinking_level"):
            kwargs["thinking_level"] = self.config["google_thinking_level"]
        elif provider == "openai" and self.config.get("openai_reasoning_effort"):
            kwargs["reasoning_effort"] = self.config["openai_reasoning_effort"]
        elif provider == "anthropic" and self.config.get("anthropic_effort"):
            kwargs["effort"] = self.config["anthropic_effort"]
        return kwargs

    def _create_tool_nodes(self) -> Dict[str, ToolNode]:
        return {
            "price_action": ToolNode([get_playbook_setups]),
        }

    def propagate(self, company_name, as_of):
        """Run the price-action graph for an instrument and timestamp."""
        self.ticker = company_name

        if self.config.get("checkpoint_enabled"):
            self._checkpointer_ctx = get_checkpointer(
                self.config["data_cache_dir"], company_name
            )
            saver = self._checkpointer_ctx.__enter__()
            self.graph = self.workflow.compile(checkpointer=saver)

            step = checkpoint_step(
                self.config["data_cache_dir"], company_name, str(as_of)
            )
            if step is not None:
                logger.info("Resuming from step %d for %s at %s", step, company_name, as_of)
            else:
                logger.info("Starting fresh for %s at %s", company_name, as_of)

        try:
            return self._run_graph(company_name, as_of)
        finally:
            if self._checkpointer_ctx is not None:
                self._checkpointer_ctx.__exit__(None, None, None)
                self._checkpointer_ctx = None
                self.graph = self.workflow.compile()

    def _run_graph(self, company_name, as_of):
        init_agent_state = self.propagator.create_initial_state(
            company_name,
            as_of,
            timeframe=self.config.get("timeframe", "15m"),
            confirmation_timeframe=self.config.get("confirmation_timeframe", "30m"),
            market_timezone=self.config.get("market_timezone", "America/New_York"),
        )
        args = self.propagator.get_graph_args()

        if self.config.get("checkpoint_enabled"):
            tid = thread_id(company_name, str(as_of))
            args.setdefault("config", {}).setdefault("configurable", {})["thread_id"] = tid

        if self.debug:
            trace = []
            for chunk in self.graph.stream(init_agent_state, **args):
                if chunk.get("messages"):
                    chunk["messages"][-1].pretty_print()
                trace.append(chunk)
            final_state = {}
            for chunk in trace:
                final_state.update(chunk)
        else:
            final_state = self.graph.invoke(init_agent_state, **args)

        self.curr_state = final_state
        self._log_state(as_of, final_state)

        if self.config.get("checkpoint_enabled"):
            clear_checkpoint(self.config["data_cache_dir"], company_name, str(as_of))

        return final_state, self.process_signal(final_state.get("trade_plan", ""))

    def _log_state(self, as_of, final_state):
        self.log_states_dict[str(as_of)] = {
            "company_of_interest": final_state["company_of_interest"],
            "as_of": final_state["as_of"],
            "timeframe": final_state["timeframe"],
            "confirmation_timeframe": final_state["confirmation_timeframe"],
            "market_timezone": final_state["market_timezone"],
            "price_action_report": final_state.get("price_action_report", ""),
            "trade_plan": final_state.get("trade_plan", ""),
            "order_proposal": final_state.get("order_proposal", ""),
            "order_proposal_path": final_state.get("order_proposal_path"),
        }

        safe_ticker = safe_ticker_component(self.ticker)
        safe_as_of = re.sub(r"[^0-9A-Za-z_-]+", "_", str(as_of)).strip("_")
        directory = Path(self.config["results_dir"]) / safe_ticker / "PriceActionStrategy_logs"
        directory.mkdir(parents=True, exist_ok=True)

        log_path = directory / f"full_state_{safe_as_of}.json"
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.log_states_dict[str(as_of)], f, indent=4)

    def process_signal(self, full_signal):
        return self.signal_processor.process_signal(full_signal)
