def test_price_action_dataflow_imports_without_agent_cycle():
    from tradingagents.dataflows.price_action import fetch_price_action_timeframes

    assert callable(fetch_price_action_timeframes)


def test_agent_package_public_imports_are_available():
    from tradingagents.agents import (
        AgentState,
        create_market_analyst,
        create_msg_delete,
        create_order_proposal_executor,
        create_price_action_analyst,
        create_trader,
    )

    assert AgentState is not None
    assert callable(create_market_analyst)
    assert callable(create_msg_delete)
    assert callable(create_order_proposal_executor)
    assert callable(create_price_action_analyst)
    assert callable(create_trader)
