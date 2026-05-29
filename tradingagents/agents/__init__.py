"""Lazy public exports for the agent package namespace."""

from importlib import import_module

_EXPORTS = {
    "AgentState": ("tradingagents.agents.utils.agent_states", "AgentState"),
    "create_market_analyst": (
        "tradingagents.agents.analysts.market_analyst",
        "create_market_analyst",
    ),
    "create_msg_delete": (
        "tradingagents.agents.utils.agent_utils",
        "create_msg_delete",
    ),
    "create_order_proposal_executor": (
        "tradingagents.agents.execution",
        "create_order_proposal_executor",
    ),
    "create_price_action_analyst": (
        "tradingagents.agents.analysts.market_analyst",
        "create_price_action_analyst",
    ),
    "create_trader": ("tradingagents.agents.trader.trader", "create_trader"),
}

__all__ = sorted(_EXPORTS)


def __getattr__(name):
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from exc

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
