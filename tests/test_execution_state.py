from datetime import datetime, timezone

from tradingagents.agents.schemas import OrderProposal, OrderStatus, TradeAction
from tradingagents.brokers.execution_state import ExecutionStateStore


def _proposal() -> OrderProposal:
    return OrderProposal(
        symbol="XAUUSD",
        side=TradeAction.BUY,
        order_type="LIMIT",
        entry_price=2450.0,
        stop_loss=2447.0,
        take_profit=2456.0,
        timeframe="15m",
        confirmation_timeframe="30m",
        valid_until="2026-05-27 10:15 EDT",
        activation_window_minutes=10,
        cancel_if_not_triggered_after="2026-05-27 10:10 EDT",
        status=OrderStatus.PROPOSED,
        reason="A+ setup passed.",
    )


def test_execution_state_records_active_pending_order(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")

    state = store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    assert state["active_order_ticket"] == 111222
    assert state["symbol"] == "XAUUSD"
    assert state["placed_at_utc"] == "2026-05-27T14:00:00+00:00"
    assert state["cancel_after_utc"] == "2026-05-27T14:10:00+00:00"
    assert state["proposal"]["symbol"] == "XAUUSD"


def test_execution_state_loads_default_when_missing(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")

    assert store.load() == {
        "symbol": "XAUUSD",
        "active_order_ticket": None,
        "active_position_ticket": None,
    }


def test_execution_state_store_has_one_state_filename():
    assert ExecutionStateStore.filename == "mt5_state.json"
    state_file_attrs = [
        name for name in vars(ExecutionStateStore) if name.endswith("filename")
    ]
    assert state_file_attrs == ["filename"]


def test_execution_state_clears_active_pending_order(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    state = store.clear_pending_order()

    assert state["active_order_ticket"] is None
    assert store.load()["active_order_ticket"] is None


def test_execution_state_marks_active_position_and_clears_trade(tmp_path):
    store = ExecutionStateStore(tmp_path, "XAUUSD")
    store.record_pending_order(
        111222,
        _proposal(),
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    active = store.mark_position_active(333444)

    assert active["active_order_ticket"] is None
    assert active["active_position_ticket"] == 333444
    assert active["proposal"]["symbol"] == "XAUUSD"

    cleared = store.clear_trade()

    assert cleared == {
        "symbol": "XAUUSD",
        "active_order_ticket": None,
        "active_position_ticket": None,
    }


def test_execution_state_uses_default_activation_window(tmp_path):
    proposal = _proposal()
    proposal.activation_window_minutes = None
    store = ExecutionStateStore(tmp_path, "XAUUSD")

    state = store.record_pending_order(
        111222,
        proposal,
        placed_at_utc=datetime(2026, 5, 27, 14, 0, tzinfo=timezone.utc),
    )

    assert state["cancel_after_utc"] == "2026-05-27T14:10:00+00:00"
