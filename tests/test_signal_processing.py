"""Tests for BUY/SELL/HOLD extraction from trade plans."""

import pytest

from tradingagents.graph.signal_processing import SignalProcessor, parse_trade_action


@pytest.mark.unit
class TestParseTradeAction:
    def test_explicit_label_buy(self):
        assert parse_trade_action("**Action**: BUY\nReasoning here.") == "BUY"

    def test_explicit_label_sell(self):
        assert parse_trade_action("**Action**: SELL\nBreakdown confirmed.") == "SELL"

    def test_explicit_label_hold(self):
        assert parse_trade_action("**Action**: HOLD\nNo valid setup.") == "HOLD"

    def test_plain_action_label_buy(self):
        assert parse_trade_action("Action: BUY\nReasoning here.") == "BUY"

    def test_plain_recommendation_label_sell(self):
        assert parse_trade_action("Recommendation: SELL\nBreakdown confirmed.") == "SELL"

    def test_plain_decision_label_hold(self):
        assert parse_trade_action("Decision: HOLD\nNo setup.") == "HOLD"

    def test_negated_action_words_default_to_hold(self):
        assert parse_trade_action("No BUY or SELL setup is present.") == "HOLD"

    def test_unlabeled_prose_defaults_to_hold(self):
        assert parse_trade_action("The correct response is sell until a retest forms.") == "HOLD"

    def test_no_action_returns_hold(self):
        assert parse_trade_action("No clear directional setup.") == "HOLD"


@pytest.mark.unit
class TestSignalProcessor:
    def test_returns_action_from_trade_plan(self):
        sp = SignalProcessor()
        assert sp.process_signal("**Action**: BUY\n\n**Setup**: The Breakout") == "BUY"

    def test_makes_no_llm_calls(self):
        from unittest.mock import MagicMock

        llm = MagicMock()
        sp = SignalProcessor(llm)
        sp.process_signal("**Action**: HOLD")
        llm.invoke.assert_not_called()
        llm.with_structured_output.assert_not_called()
