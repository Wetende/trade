import json
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage

from tradingagents.agents.schemas import TradeAction, TradePlan
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


class _FakeClient:
    def __init__(self, llm):
        self._llm = llm

    def get_llm(self):
        return self._llm


class _FakeToolBoundLLM:
    def __init__(self):
        self.calls = 0

    def invoke(self, _messages):
        self.calls += 1
        if self.calls == 1:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_playbook_setups",
                        "args": {
                            "symbol": "SPY",
                            "as_of": "2026-05-17 10:15",
                            "timeframe": "15m",
                            "confirmation_timeframe": "30m",
                        },
                        "id": "call_playbook",
                    }
                ],
            )
        return AIMessage(content="Setup verdict: No Valid Setup\nDirection: HOLD")

    __call__ = invoke


class _FakeStructuredLLM:
    def invoke(self, _prompt):
        return TradePlan(
            action=TradeAction.HOLD,
            setup_name="No Valid Setup",
            confidence="None",
            checklist_status="Playbook setup failed",
            reason="The detector returned NO_SETUP, so there is no trade.",
        )


class _FakeLLM:
    def __init__(self):
        self.bound = _FakeToolBoundLLM()

    def bind_tools(self, _tools):
        return self.bound

    def with_structured_output(self, _schema):
        return _FakeStructuredLLM()

    def invoke(self, _prompt):
        return AIMessage(content="**Action**: HOLD\n\n**Reason**: fallback")


@pytest.mark.unit
def test_graph_contains_only_price_action_trader_and_order_nodes(tmp_path):
    config = DEFAULT_CONFIG.copy()
    config["results_dir"] = str(tmp_path)

    fake_llm = _FakeLLM()
    with patch(
        "tradingagents.graph.trading_graph.create_llm_client",
        return_value=_FakeClient(fake_llm),
    ):
        graph = TradingAgentsGraph(config=config)

    assert set(graph.workflow.nodes) == {
        "Price Action Analyst",
        "tools_price_action",
        "Trader",
        "Order Proposal",
    }


@pytest.mark.unit
def test_graph_run_returns_hold_and_writes_order_proposal(tmp_path):
    config = DEFAULT_CONFIG.copy()
    config["results_dir"] = str(tmp_path)
    config["checkpoint_enabled"] = False
    config["broker_symbol"] = "XAUUSD.vx"

    fake_llm = _FakeLLM()
    with patch(
        "tradingagents.graph.trading_graph.create_llm_client",
        return_value=_FakeClient(fake_llm),
    ):
        graph = TradingAgentsGraph(config=config)
        final_state, decision = graph.propagate("GC=F", "2026-05-17 10:15")

    assert decision == "HOLD"
    assert final_state["company_of_interest"] == "GC=F"
    assert final_state["broker_symbol"] == "XAUUSD.vx"
    assert final_state["price_action_report"]
    assert "**Action**: HOLD" in final_state["trade_plan"]
    assert "**Status**: NO_TRADE" in final_state["order_proposal"]
    saved = json.loads(open(final_state["order_proposal_path"], encoding="utf-8").read())
    assert saved["status"] == "NO_TRADE"
    assert saved["symbol"] == "GC=F"
    assert saved["broker_symbol"] == "XAUUSD.vx"
