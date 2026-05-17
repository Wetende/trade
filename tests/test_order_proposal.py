import json

import pytest

from tradingagents.agents.execution.order_proposal import (
    build_order_proposal,
    create_order_proposal_executor,
)
from tradingagents.agents.schemas import OrderStatus, TradeAction


def _state(trade_plan: str, tmp_path):
    return {
        "company_of_interest": "SPY",
        "as_of": "2026-05-17 10:15",
        "timeframe": "15m",
        "confirmation_timeframe": "30m",
        "market_timezone": "America/New_York",
        "trade_plan": trade_plan,
        "price_action_report": "Report.",
        "messages": [],
    }


@pytest.mark.unit
def test_hold_trade_plan_creates_no_trade_proposal(tmp_path):
    proposal = build_order_proposal(
        _state("**Action**: HOLD\n\n**Reason**: No valid setup.", tmp_path)
    )
    assert proposal.status == OrderStatus.NO_TRADE
    assert proposal.side == TradeAction.HOLD
    assert proposal.entry_price is None


@pytest.mark.unit
def test_buy_trade_plan_creates_proposed_limit_order(tmp_path):
    plan = (
        "**Action**: BUY\n\n"
        "**Reason**: Break and retest confirmed.\n\n"
        "**Entry Price**: 100.5\n\n"
        "**Stop Loss**: 99.25\n\n"
        "**Take Profit**: 103.0"
    )
    proposal = build_order_proposal(_state(plan, tmp_path))
    assert proposal.status == OrderStatus.PROPOSED
    assert proposal.side == TradeAction.BUY
    assert proposal.order_type == "LIMIT"
    assert proposal.entry_price == 100.5
    assert proposal.stop_loss == 99.25
    assert proposal.take_profit == 103.0


@pytest.mark.unit
def test_plain_label_trade_plan_creates_proposed_limit_order(tmp_path):
    plan = (
        "Action: SELL\n\n"
        "Reason: Breakdown confirmed.\n\n"
        "Entry Price: 100\n\n"
        "Stop Loss: 101\n\n"
        "Take Profit: 98"
    )
    proposal = build_order_proposal(_state(plan, tmp_path))
    assert proposal.status == OrderStatus.PROPOSED
    assert proposal.side == TradeAction.SELL
    assert proposal.entry_price == 100
    assert proposal.stop_loss == 101
    assert proposal.take_profit == 98


@pytest.mark.unit
def test_missing_levels_creates_no_trade_proposal(tmp_path):
    plan = "Action: BUY\n\nReason: Breakout confirmed.\n\nEntry Price: 100"
    proposal = build_order_proposal(_state(plan, tmp_path))
    assert proposal.status == OrderStatus.NO_TRADE
    assert proposal.side == TradeAction.BUY
    assert proposal.reason == "No order proposed because the trade plan is missing entry, stop, or target."


@pytest.mark.unit
def test_negated_action_words_do_not_create_proposal(tmp_path):
    plan = "No BUY or SELL setup is present.\n\nReason: No valid setup."
    proposal = build_order_proposal(_state(plan, tmp_path))
    assert proposal.status == OrderStatus.NO_TRADE
    assert proposal.side == TradeAction.HOLD


@pytest.mark.unit
def test_executor_writes_json_artifact(tmp_path):
    plan = (
        "**Action**: SELL\n\n"
        "**Reason**: Breakdown confirmed.\n\n"
        "**Entry Price**: 100\n\n"
        "**Stop Loss**: 101\n\n"
        "**Take Profit**: 98"
    )
    node = create_order_proposal_executor({"results_dir": str(tmp_path)})
    result = node(_state(plan, tmp_path))
    assert "order_proposal_path" in result
    saved = json.loads(open(result["order_proposal_path"], encoding="utf-8").read())
    assert saved["status"] == "PROPOSED"
    assert saved["side"] == "SELL"
