import json
from pathlib import Path

import pytest

from tradingagents.agents.execution.order_proposal import (
    build_order_proposal,
    create_order_proposal_executor,
)
from tradingagents.agents.schemas import (
    OrderProposal,
    OrderStatus,
    TradeAction,
    render_order_proposal,
)


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
    assert proposal.activation_window_minutes is None
    assert proposal.cancel_if_not_triggered_after is None


@pytest.mark.unit
def test_no_trade_proposal_prefers_telemetry_reason_over_misleading_trade_plan(tmp_path):
    state = _state(
        "**Action**: HOLD\n\n"
        "**Reason**: No price-action data was provided, so no trade can be evaluated.",
        tmp_path,
    )
    state["engine_telemetry"] = {
        "decision_stage": "a_plus_checklist",
        "primary_hold_reason": "A required A+ checklist rule failed. Default to HOLD.",
        "candidate_setup_count": 1,
        "m30_context": {"bias": "BEARISH", "context": "BREAKOUT"},
    }
    state["engine_payload"] = {
        "checklist": {
            "playbook_setup": "passed",
            "timeframe_correlation": "passed",
            "clean_range_to_fill": "failed",
        },
        "risk": {
            "approved": False,
            "reason": "Clean range is below minimum risk-to-reward",
            "risk_reward": 0.62,
        },
        "market_context": {
            "higher_timeframe_permission": {
                "permission": "CONTEXT_ONLY",
                "planned_direction": "SELL",
            }
        },
    }

    proposal = build_order_proposal(state)

    assert proposal.status == OrderStatus.NO_TRADE
    assert "Clean range is below minimum risk-to-reward" in proposal.reason
    assert "R:R 0.62" in proposal.reason
    assert "M30 BEARISH BREAKOUT" in proposal.reason
    assert "no price-action data" not in proposal.reason.lower()


@pytest.mark.unit
def test_order_proposal_uses_engine_payload_for_proposed_trade_without_llm_levels(tmp_path):
    state = _state(
        "**Action**: HOLD\n\n"
        "**Reason**: LLM fallback text should not drive execution.",
        tmp_path,
    )
    state["engine_payload"] = {
        "status": "SETUP_FOUND",
        "recommendation": "SELL",
        "message": "A deterministic A+ price-action setup passed the checklist.",
        "setups": [
            {
                "name": "Break and Retest",
                "direction": "SELL",
                "entry_price": 4498.5,
                "stop_loss": 4503.2,
                "take_profit": 4488.0,
            }
        ],
        "risk": {
            "approved": True,
            "risk_reward": 2.23,
            "take_profit": 4488.0,
        },
        "telemetry": {
            "decision_stage": "setup_found",
            "primary_hold_reason": "A deterministic A+ price-action setup passed the checklist.",
            "candidate_setup_count": 1,
            "m30_context": {"bias": "BEARISH", "context": "BREAKOUT"},
        },
    }

    proposal = build_order_proposal(state)

    assert proposal.status == OrderStatus.PROPOSED
    assert proposal.side == TradeAction.SELL
    assert proposal.entry_price == 4498.5
    assert proposal.stop_loss == 4503.2
    assert proposal.take_profit == 4488.0
    assert "M30 BEARISH BREAKOUT" in proposal.reason
    assert "R:R 2.23" in proposal.reason
    assert "LLM fallback" not in proposal.reason


@pytest.mark.unit
def test_engine_proposal_records_strategy_metadata_and_auto_order_type(tmp_path):
    state = _state(
        "**Action**: HOLD\n\n"
        "**Reason**: LLM fallback text should not drive execution.",
        tmp_path,
    )
    state["engine_payload"] = {
        "status": "SETUP_FOUND",
        "recommendation": "SELL",
        "setups": [
            {
                "name": "Breakout",
                "setup_grade": "B_PLUS",
                "strategy_type": "BREAKOUT",
                "direction": "SELL",
                "entry_price": 4490.85,
                "stop_loss": 4491.29,
                "take_profit": 4489.52,
            }
        ],
        "risk": {
            "approved": True,
            "risk_reward": 3.02,
            "take_profit": 4489.52,
        },
        "telemetry": {
            "decision_stage": "setup_found",
            "primary_hold_reason": "A deterministic A+ price-action setup passed.",
        },
    }

    proposal = build_order_proposal(state)
    rendered = render_order_proposal(proposal)

    assert proposal.status == OrderStatus.PROPOSED
    assert proposal.order_type == "AUTO"
    assert proposal.setup_name == "Breakout"
    assert proposal.setup_grade == "B_PLUS"
    assert proposal.strategy_type == "BREAKOUT"
    assert "**Setup Name**: Breakout" in rendered
    assert "**Setup Grade**: B_PLUS" in rendered
    assert "**Strategy Type**: BREAKOUT" in rendered


@pytest.mark.unit
def test_engine_order_proposal_uses_fast_profile_activation_window(tmp_path):
    state = {
        "company_of_interest": "XAUUSD.vx",
        "broker_symbol": "XAUUSD.vx",
        "as_of": "2026-06-03 08:15",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "market_timezone": "America/New_York",
        "engine_payload": {
            "status": "SETUP_FOUND",
            "recommendation": "BUY",
            "entry_profile": "fast",
            "activation_window_minutes": 1,
            "message": "Fast A+ setup passed.",
            "setups": [
                {
                    "name": "Breakout",
                    "direction": "BUY",
                    "entry_price": 4460.87,
                    "stop_loss": 4458.37,
                    "take_profit": 4465.87,
                    "setup_grade": "A_PLUS",
                }
            ],
            "risk": {"take_profit": 4465.87},
        },
    }

    proposal_state = create_order_proposal_executor({"results_dir": tmp_path})(state)
    proposal_path = Path(proposal_state["order_proposal_path"])
    proposal = json.loads(proposal_path.read_text())

    assert proposal_path.name == "order_proposal_2026-06-03_08_15_fast.json"
    assert proposal["timeframe"] == "1m"
    assert proposal["confirmation_timeframe"] == "1m"
    assert proposal["activation_window_minutes"] == 1
    assert proposal["cancel_if_not_triggered_after"] == "2026-06-03 08:16 EDT"


@pytest.mark.unit
def test_fast_order_proposal_renders_history_window_not_confirmation_label():
    proposal = OrderProposal(
        symbol="XAUUSD.vx",
        side=TradeAction.BUY,
        order_type="AUTO",
        timeframe="1m",
        confirmation_timeframe="1m",
        valid_until="2026-06-03 08:15 EDT",
        status=OrderStatus.PROPOSED,
        reason="Fast setup passed.",
    )

    rendered = render_order_proposal(proposal)

    assert "**Scalper Memory**: 1m" in rendered
    assert "Confirmation Timeframe" not in rendered


@pytest.mark.unit
def test_engine_order_proposal_carries_fast_volume_multiplier(tmp_path):
    state = {
        "company_of_interest": "XAUUSD.vx",
        "broker_symbol": "XAUUSD.vx",
        "as_of": "2026-06-03 08:15",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "market_timezone": "America/New_York",
        "engine_payload": {
            "status": "SETUP_FOUND",
            "recommendation": "SELL",
            "entry_profile": "fast",
            "activation_window_minutes": 1,
            "message": "Fast microstructure setup passed.",
            "setups": [
                {
                    "name": "Confirmed Break",
                    "direction": "SELL",
                    "entry_price": 4075.17,
                    "stop_loss": 4076.82,
                    "take_profit": 4072.70,
                    "setup_grade": "A_PLUS",
                }
            ],
            "risk": {
                "take_profit": 4072.70,
                "volume_multiplier": 1.5,
                "position_lifecycle": "FAST_PARTIAL_SCALE",
            },
            "telemetry": {
                "decision_stage": "setup_found",
                "primary_hold_reason": "Fast microstructure setup passed.",
                "candidate_setup_count": 1,
                "m30_context": {"bias": "BEARISH", "context": "BREAKOUT"},
            },
        },
    }

    proposal_state = create_order_proposal_executor({"results_dir": tmp_path})(state)
    proposal = json.loads(Path(proposal_state["order_proposal_path"]).read_text())

    assert proposal["volume_multiplier"] == 1.5
    assert proposal["position_lifecycle"] == "FAST_PARTIAL_SCALE"
    assert "1m history" in proposal["reason"]
    assert "3m" not in proposal["reason"]
    assert "M30" not in proposal["reason"]


@pytest.mark.unit
def test_engine_order_proposal_carries_dynamic_fast_exit_settings(tmp_path):
    state = {
        "company_of_interest": "XAUUSD.vx",
        "broker_symbol": "XAUUSD.vx",
        "as_of": "2026-06-03 08:15",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "market_timezone": "America/New_York",
        "engine_payload": {
            "status": "SETUP_FOUND",
            "recommendation": "SELL",
            "entry_profile": "fast",
            "activation_window_minutes": 1,
            "message": "Fast microstructure setup passed.",
            "setups": [
                {
                    "name": "Confirmed Break",
                    "direction": "SELL",
                    "entry_price": 4075.17,
                    "stop_loss": 4076.82,
                    "take_profit": 4072.70,
                    "setup_grade": "A_PLUS",
                }
            ],
            "risk": {
                "take_profit": 4072.70,
                "volume_multiplier": 1.5,
                "position_lifecycle": "FAST_PARTIAL_SCALE",
                "break_even_trigger_points": 0.82,
                "break_even_lock_points": 0.16,
                "partial_first_trigger_points": 1.24,
                "partial_first_target_volume": 1.0,
                "partial_second_trigger_points": 2.06,
                "partial_second_target_volume": 0.4,
                "trailing_trigger_points": 2.06,
                "trailing_distance_points": 0.66,
            },
        },
    }

    proposal_state = create_order_proposal_executor({"results_dir": tmp_path})(state)
    proposal = json.loads(Path(proposal_state["order_proposal_path"]).read_text())

    assert proposal["break_even_trigger_points"] == 0.82
    assert proposal["break_even_lock_points"] == 0.16
    assert proposal["partial_first_trigger_points"] == 1.24
    assert proposal["partial_first_target_volume"] == 1.0
    assert proposal["partial_second_trigger_points"] == 2.06
    assert proposal["partial_second_target_volume"] == 0.4
    assert proposal["trailing_trigger_points"] == 2.06
    assert proposal["trailing_distance_points"] == 0.66


@pytest.mark.unit
def test_one_minute_scalper_proposal_carries_selected_candidate_journal_fields(tmp_path):
    state = {
        "company_of_interest": "XAUUSD.vx",
        "broker_symbol": "XAUUSD.vx",
        "as_of": "2026-06-03 08:15",
        "timeframe": "1m",
        "confirmation_timeframe": "1m",
        "market_timezone": "America/New_York",
        "engine_payload": {
            "status": "SETUP_FOUND",
            "recommendation": "SELL",
            "entry_profile": "fast",
            "activation_window_minutes": 1,
            "message": "One Minute Scalper selected a candidate.",
            "setups": [
                {
                    "name": "FAILED_HIGH_BREAK_SELL",
                    "direction": "SELL",
                    "entry_price": 4075.17,
                    "stop_loss": 4076.82,
                    "take_profit": 4072.70,
                    "setup_grade": "A_PLUS",
                }
            ],
            "risk": {
                "take_profit": 4072.70,
                "volume_multiplier": 1.5,
                "position_lifecycle": "FAST_PARTIAL_SCALE",
            },
            "telemetry": {
                "selected_candidate": {
                    "trigger": "FAILED_HIGH_BREAK_SELL",
                    "reaction_type": "fakeout",
                    "confirmation_type": "engulfing",
                    "touch_count": 3,
                    "score": 10,
                    "volume_decision": "BOOST_1_5",
                },
                "candidate_setup_count": 2,
            },
        },
    }

    proposal_state = create_order_proposal_executor({"results_dir": tmp_path})(state)
    proposal = json.loads(Path(proposal_state["order_proposal_path"]).read_text())

    assert proposal["trigger_name"] == "FAILED_HIGH_BREAK_SELL"
    assert proposal["reaction_type"] == "fakeout"
    assert proposal["confirmation_type"] == "engulfing"
    assert proposal["touch_count"] == 3
    assert proposal["candidate_score"] == 10
    assert proposal["volume_decision"] == "BOOST_1_5"
    assert "**Trigger Name**: FAILED_HIGH_BREAK_SELL" in proposal_state["order_proposal"]
    assert "**Volume Decision**: BOOST_1_5" in proposal_state["order_proposal"]


@pytest.mark.unit
def test_engine_no_setup_overrides_llm_buy_text(tmp_path):
    state = _state(
        "**Action**: BUY\n\n"
        "**Reason**: LLM says buy.\n\n"
        "**Entry Price**: 100\n\n"
        "**Stop Loss**: 99\n\n"
        "**Take Profit**: 103",
        tmp_path,
    )
    state["engine_payload"] = {
        "status": "NO_SETUP",
        "recommendation": "HOLD",
        "message": "No valid M15 setup. Default to HOLD.",
        "checklist": {"playbook_setup": "failed"},
        "telemetry": {
            "decision_stage": "no_m15_setup",
            "primary_hold_reason": "No valid M15 setup. Default to HOLD.",
            "candidate_setup_count": 0,
            "m30_context": {"bias": "BULLISH", "context": "BREAKOUT"},
        },
    }

    proposal = build_order_proposal(state)

    assert proposal.status == OrderStatus.NO_TRADE
    assert proposal.side == TradeAction.HOLD
    assert proposal.entry_price is None
    assert "LLM says buy" not in proposal.reason
    assert "No valid M15 setup" in proposal.reason


@pytest.mark.unit
def test_engine_setup_found_overrides_llm_hold_text(tmp_path):
    state = _state(
        "**Action**: HOLD\n\n"
        "**Reason**: LLM says hold.",
        tmp_path,
    )
    state["engine_payload"] = {
        "status": "SETUP_FOUND",
        "recommendation": "BUY",
        "message": "A deterministic A+ price-action setup passed the checklist.",
        "setups": [
            {
                "name": "Break and Retest",
                "direction": "BUY",
                "entry_price": 100.5,
                "stop_loss": 99.25,
                "take_profit": 103.0,
            }
        ],
        "risk": {
            "approved": True,
            "risk_reward": 2.0,
            "take_profit": 103.0,
        },
        "telemetry": {
            "decision_stage": "setup_found",
            "primary_hold_reason": "A deterministic A+ price-action setup passed the checklist.",
            "candidate_setup_count": 1,
            "m30_context": {"bias": "BULLISH", "context": "BREAKOUT"},
        },
    }

    proposal = build_order_proposal(state)

    assert proposal.status == OrderStatus.PROPOSED
    assert proposal.side == TradeAction.BUY
    assert proposal.entry_price == 100.5
    assert "LLM says hold" not in proposal.reason


@pytest.mark.unit
def test_engine_setup_missing_levels_creates_no_trade_even_if_llm_has_levels(tmp_path):
    state = _state(
        "**Action**: SELL\n\n"
        "**Reason**: LLM has levels.\n\n"
        "**Entry Price**: 100\n\n"
        "**Stop Loss**: 101\n\n"
        "**Take Profit**: 98",
        tmp_path,
    )
    state["engine_payload"] = {
        "status": "SETUP_FOUND",
        "recommendation": "SELL",
        "setups": [{"name": "Break and Retest", "direction": "SELL"}],
        "telemetry": {
            "decision_stage": "setup_found",
            "primary_hold_reason": "A deterministic A+ price-action setup passed the checklist.",
        },
    }

    proposal = build_order_proposal(state)

    assert proposal.status == OrderStatus.NO_TRADE
    assert proposal.side == TradeAction.SELL
    assert proposal.entry_price is None
    assert "missing entry, stop, or target" in proposal.reason
    assert "LLM has levels" not in proposal.reason


@pytest.mark.unit
def test_executor_loads_engine_payload_before_writing_order_proposal(tmp_path):
    state = _state(
        "**Action**: HOLD\n\n"
        "**Reason**: No price-action data was provided.",
        tmp_path,
    )
    safe_dir = tmp_path / "SPY" / "engine_telemetry"
    safe_dir.mkdir(parents=True)
    (safe_dir / "engine_payload_2026-05-17_10_15.json").write_text(
        json.dumps(
            {
                "status": "NO_SETUP",
                "recommendation": "HOLD",
                "message": "A required A+ checklist rule failed. Default to HOLD.",
                "checklist": {"clean_range_to_fill": "failed"},
                "risk": {
                    "approved": False,
                    "reason": "Clean range is below minimum risk-to-reward",
                    "risk_reward": 0.62,
                },
                "telemetry": {
                    "decision_stage": "a_plus_checklist",
                    "primary_hold_reason": "A required A+ checklist rule failed. Default to HOLD.",
                    "candidate_setup_count": 1,
                    "m30_context": {"bias": "BEARISH", "context": "BREAKOUT"},
                },
            }
        ),
        encoding="utf-8",
    )

    node = create_order_proposal_executor({"results_dir": str(tmp_path)})
    result = node(state)
    saved = json.loads(open(result["order_proposal_path"], encoding="utf-8").read())

    assert saved["status"] == "NO_TRADE"
    assert "Clean range is below minimum risk-to-reward" in saved["reason"]
    assert "no price-action data" not in saved["reason"].lower()


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
    assert proposal.activation_window_minutes == 10
    assert proposal.cancel_if_not_triggered_after == "2026-05-17 10:25 EDT"


@pytest.mark.unit
def test_order_proposal_preserves_analysis_and_broker_symbols(tmp_path):
    plan = (
        "**Action**: BUY\n\n"
        "**Reason**: Break and retest confirmed.\n\n"
        "**Entry Price**: 2450\n\n"
        "**Stop Loss**: 2440\n\n"
        "**Take Profit**: 2470"
    )
    state = _state(plan, tmp_path)
    state["company_of_interest"] = "GC=F"
    state["broker_symbol"] = "XAUUSD.vx"

    proposal = build_order_proposal(state)
    rendered = render_order_proposal(proposal)

    assert proposal.symbol == "GC=F"
    assert proposal.broker_symbol == "XAUUSD.vx"
    assert "**Symbol**: GC=F" in rendered
    assert "**Broker Symbol**: XAUUSD.vx" in rendered


@pytest.mark.unit
def test_order_proposal_defaults_broker_symbol_to_analysis_symbol():
    proposal = OrderProposal.model_validate(
        {
            "symbol": "GC=F",
            "side": "BUY",
            "order_type": "LIMIT",
            "entry_price": 2450,
            "stop_loss": 2440,
            "take_profit": 2470,
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "valid_until": "2026-05-17 10:30 EDT",
            "activation_window_minutes": 10,
            "cancel_if_not_triggered_after": "2026-05-17 10:25 EDT",
            "status": "PROPOSED",
            "reason": "A+ setup passed.",
        }
    )

    assert proposal.broker_symbol == "GC=F"


@pytest.mark.unit
def test_order_proposal_defaults_missing_metadata_for_old_json():
    proposal = OrderProposal.model_validate(
        {
            "symbol": "GC=F",
            "broker_symbol": "XAUUSD.vx",
            "side": "BUY",
            "order_type": "LIMIT",
            "entry_price": 2450,
            "stop_loss": 2440,
            "take_profit": 2470,
            "timeframe": "15m",
            "confirmation_timeframe": "30m",
            "valid_until": "2026-05-17 10:30 EDT",
            "activation_window_minutes": 10,
            "cancel_if_not_triggered_after": "2026-05-17 10:25 EDT",
            "status": "PROPOSED",
            "reason": "legacy artifact",
        }
    )

    assert proposal.setup_name is None
    assert proposal.setup_grade is None
    assert proposal.strategy_type is None


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
    assert saved["symbol"] == "SPY"
    assert saved["broker_symbol"] == "SPY"
    assert saved["activation_window_minutes"] == 10
    assert saved["cancel_if_not_triggered_after"] == "2026-05-17 10:25 EDT"
