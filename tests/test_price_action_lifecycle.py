from tradingagents.agents.price_action.lifecycle import (
    build_pending_order,
    cancel_stale_order,
    move_stop_to_break_even,
    should_exit_on_change_of_character,
    trail_stop_from_m15_structure,
    trigger_pending_order,
)


def test_pending_limit_order_expires_after_first_10_minutes_of_m15_candle():
    order = build_pending_order(
        symbol="XAUUSD",
        side="BUY",
        entry_price=2350.0,
        stop_loss=2348.0,
        take_profit=2356.0,
        candle_open="2026-05-18 08:30",
    )

    assert order.expires_at == "2026-05-18 08:40"


def test_order_triggers_if_price_hits_entry_before_expiry():
    order = build_pending_order(
        "XAUUSD",
        "BUY",
        2350.0,
        2348.0,
        2356.0,
        "2026-05-18 08:30",
    )

    result = trigger_pending_order(
        order,
        current_time="2026-05-18 08:35",
        high=2352,
        low=2349.8,
    )

    assert result.status == "TRIGGERED"


def test_order_cancels_if_not_triggered_after_expiry():
    order = build_pending_order(
        "XAUUSD",
        "BUY",
        2350.0,
        2348.0,
        2356.0,
        "2026-05-18 08:30",
    )

    result = cancel_stale_order(order, current_time="2026-05-18 08:41")

    assert result.status == "CANCELLED"


def test_order_cancels_at_exact_expiry_time():
    order = build_pending_order(
        "XAUUSD",
        "BUY",
        2350.0,
        2348.0,
        2356.0,
        "2026-05-18 08:30",
    )

    result = cancel_stale_order(order, current_time="2026-05-18 08:40")

    assert result.status == "CANCELLED"


def test_order_does_not_trigger_at_exact_expiry_time():
    order = build_pending_order(
        "XAUUSD",
        "BUY",
        2350.0,
        2348.0,
        2356.0,
        "2026-05-18 08:30",
    )

    result = trigger_pending_order(
        order,
        current_time="2026-05-18 08:40",
        high=2352,
        low=2349.8,
    )

    assert result.status == "CANCELLED"


def test_order_does_not_trigger_after_expiry_even_if_price_crosses_entry():
    order = build_pending_order(
        "XAUUSD",
        "SELL",
        2350.0,
        2352.0,
        2344.0,
        "2026-05-18 08:30",
    )

    result = trigger_pending_order(
        order,
        current_time="2026-05-18 08:41",
        high=2351,
        low=2349,
    )

    assert result.status == "CANCELLED"


def test_moves_stop_to_break_even_after_50_pips_profit():
    position = {
        "side": "BUY",
        "entry_price": 2350.0,
        "stop_loss": 2348.0,
        "current_price": 2355.0,
    }

    result = move_stop_to_break_even(position, threshold_pips=50)

    assert result["stop_loss"] == 2350.0
    assert result["management_action"] == "MOVE_TO_BREAK_EVEN"


def test_moves_sell_stop_to_break_even_after_50_pips_profit():
    position = {
        "side": "SELL",
        "entry_price": 2350.0,
        "stop_loss": 2352.0,
        "current_price": 2345.0,
    }

    result = move_stop_to_break_even(position, threshold_pips=50)

    assert result["stop_loss"] == 2350.0
    assert result["management_action"] == "MOVE_TO_BREAK_EVEN"


def test_break_even_does_not_worsen_already_protected_buy_stop():
    position = {
        "side": "BUY",
        "entry_price": 2350.0,
        "stop_loss": 2351.0,
        "current_price": 2355.0,
    }

    result = move_stop_to_break_even(position, threshold_pips=50)

    assert result["stop_loss"] == 2351.0
    assert result["management_action"] == "HOLD_STOP"


def test_break_even_does_not_worsen_already_protected_sell_stop():
    position = {
        "side": "SELL",
        "entry_price": 2350.0,
        "stop_loss": 2349.0,
        "current_price": 2345.0,
    }

    result = move_stop_to_break_even(position, threshold_pips=50)

    assert result["stop_loss"] == 2349.0
    assert result["management_action"] == "HOLD_STOP"


def test_break_even_holds_when_profit_threshold_is_not_reached():
    position = {
        "side": "BUY",
        "entry_price": 2350.0,
        "stop_loss": 2348.0,
        "current_price": 2354.99,
    }

    result = move_stop_to_break_even(position, threshold_pips=50)

    assert result["stop_loss"] == 2348.0
    assert result["management_action"] == "HOLD_STOP"


def test_trails_buy_stop_below_new_higher_low():
    position = {"side": "BUY", "entry_price": 2350.0, "stop_loss": 2350.0}
    m15_structure = [{"higher_low": 2352.0}, {"higher_low": 2354.0}]

    result = trail_stop_from_m15_structure(
        position,
        m15_structure,
        buffer_points=0.2,
    )

    assert result["stop_loss"] == 2353.8
    assert result["management_action"] == "TRAIL_STOP"


def test_trails_sell_stop_above_new_lower_high():
    position = {"side": "SELL", "entry_price": 2350.0, "stop_loss": 2350.0}
    m15_structure = [{"lower_high": 2348.0}, {"lower_high": 2346.0}]

    result = trail_stop_from_m15_structure(
        position,
        m15_structure,
        buffer_points=0.2,
    )

    assert result["stop_loss"] == 2346.2
    assert result["management_action"] == "TRAIL_STOP"


def test_trailing_does_not_move_buy_stop_backward():
    position = {"side": "BUY", "entry_price": 2350.0, "stop_loss": 2355.0}
    m15_structure = [{"higher_low": 2352.0}, {"higher_low": 2354.0}]

    result = trail_stop_from_m15_structure(
        position,
        m15_structure,
        buffer_points=0.2,
    )

    assert result["stop_loss"] == 2355.0
    assert result["management_action"] == "HOLD_STOP"


def test_trailing_does_not_move_sell_stop_backward():
    position = {"side": "SELL", "entry_price": 2350.0, "stop_loss": 2345.0}
    m15_structure = [{"lower_high": 2348.0}, {"lower_high": 2346.0}]

    result = trail_stop_from_m15_structure(
        position,
        m15_structure,
        buffer_points=0.2,
    )

    assert result["stop_loss"] == 2345.0
    assert result["management_action"] == "HOLD_STOP"


def test_sell_exits_when_price_breaks_previous_lower_high():
    position = {"side": "SELL", "entry_price": 2350.0, "stop_loss": 2348.0}
    m15_structure = [{"lower_high": 2347.5}, {"lower_high": 2346.0}]

    result = should_exit_on_change_of_character(
        position,
        m15_structure,
        current_price=2347.7,
    )

    assert result["management_action"] == "EXIT_CHANGE_OF_CHARACTER"


def test_buy_exits_when_price_breaks_previous_higher_low():
    position = {"side": "BUY", "entry_price": 2350.0, "stop_loss": 2352.0}
    m15_structure = [{"higher_low": 2351.0}, {"higher_low": 2353.0}]

    result = should_exit_on_change_of_character(
        position,
        m15_structure,
        current_price=2350.8,
    )

    assert result["management_action"] == "EXIT_CHANGE_OF_CHARACTER"
