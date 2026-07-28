from datetime import datetime, timedelta, timezone

import pytest

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_HIGH_BREAK_SELL,
    FAILED_LOW_BREAK_BUY,
    HIGH_BREAK_BUY,
    HIGH_RESPECT_SELL,
    LOW_BREAK_SELL,
    LOW_RESPECT_BUY,
    analyze_one_minute_entry,
)
from tradingagents.agents.price_action.one_minute_post_close_state import PostCloseArm
from tradingagents.agents.price_action.one_minute_scalper import (
    CANDIDATE_NAME,
    build_order_geometry,
    reconfirm_arm,
)


BUY_FAMILIES = (LOW_RESPECT_BUY, HIGH_BREAK_BUY, FAILED_LOW_BREAK_BUY)
SELL_FAMILIES = (HIGH_RESPECT_SELL, LOW_BREAK_SELL, FAILED_HIGH_BREAK_SELL)


def _arm(family: str) -> PostCloseArm:
    direction = "BUY" if family in BUY_FAMILIES else "SELL"
    level_side = "low" if family in {LOW_RESPECT_BUY, LOW_BREAK_SELL, FAILED_LOW_BREAK_BUY} else "high"
    if direction == "BUY":
        arm_open, arm_high, arm_low, arm_close = 99.7, 100.35, 99.55, 100.25
        invalidation = 99.80
    else:
        arm_open, arm_high, arm_low, arm_close = 100.3, 100.45, 99.65, 99.75
        invalidation = 100.20
    return PostCloseArm(
        candidate=CANDIDATE_NAME,
        arm_id=f"arm-{family}",
        family=family,
        direction=direction,
        level_side=level_side,
        level=100.0,
        touch_count=3,
        tolerance=0.1,
        break_margin=0.05,
        zone_low=99.9,
        zone_high=100.1,
        confirmation_type="strong_close",
        confirmation_time="2026-07-28T12:58:00+00:00",
        confirmation_closed_at="2026-07-28T12:59:00+00:00",
        trigger_eligible_at="2026-07-28T12:59:05+00:00",
        expires_at="2026-07-28T12:59:45+00:00",
        invalidation=invalidation,
        confirmation_open=arm_open,
        confirmation_high=arm_high,
        confirmation_low=arm_low,
        confirmation_close=arm_close,
    )


def _confirmation(family: str) -> Candle:
    if family == HIGH_BREAK_BUY:
        values = (100.08, 100.72, 100.04, 100.68)
    elif family in BUY_FAMILIES:
        values = (99.75, 100.52, 99.65, 100.47)
    elif family == LOW_BREAK_SELL:
        values = (99.92, 99.96, 99.28, 99.32)
    else:
        values = (100.25, 100.35, 99.48, 99.53)
    return Candle(
        timestamp="2026-07-28T12:59:00+00:00",
        open=values[0],
        high=values[1],
        low=values[2],
        close=values[3],
    )


@pytest.mark.parametrize("family", BUY_FAMILIES + SELL_FAMILIES)
def test_all_six_symmetric_families_require_and_pass_second_closed_candle(family):
    result = reconfirm_arm(_arm(family), _confirmation(family))

    assert result.accepted is True
    assert result.reason == "RECONFIRMATION_ACCEPTED"
    assert result.confirmation_type != "mixed"


def test_weak_or_noncausal_second_candle_is_rejected():
    arm = _arm(LOW_RESPECT_BUY)
    weak = Candle(
        timestamp="2026-07-28T12:59:00+00:00",
        open=99.95,
        high=100.12,
        low=99.90,
        close=100.01,
    )
    late = Candle(
        timestamp="2026-07-28T13:02:01+00:00",
        open=99.75,
        high=100.52,
        low=99.65,
        close=100.47,
    )

    assert reconfirm_arm(arm, weak).reason == "RECONFIRMATION_CANDLE_WEAK"
    assert reconfirm_arm(arm, late).reason == "RECONFIRMATION_TIME_INVALID"


def test_direction_safe_geometry_is_tick_snapped_and_bounded():
    buy = build_order_geometry(
        _arm(LOW_RESPECT_BUY),
        _confirmation(LOW_RESPECT_BUY),
        bid=100.25,
        ask=100.45,
        spread=0.20,
        minimum_stop_distance=0.35,
        tick_size=0.01,
    )
    sell = build_order_geometry(
        _arm(HIGH_RESPECT_SELL),
        _confirmation(HIGH_RESPECT_SELL),
        bid=99.60,
        ask=99.80,
        spread=0.20,
        minimum_stop_distance=0.35,
        tick_size=0.01,
    )

    assert buy.accepted is True
    assert buy.entry_price == 100.53
    assert buy.stop_loss == 99.64
    assert buy.risk_distance <= 1.0
    assert buy.take_profit > buy.entry_price
    assert sell.accepted is True
    assert sell.entry_price == 99.47
    assert sell.stop_loss == 100.36
    assert sell.risk_distance <= 1.0
    assert sell.take_profit < sell.entry_price


def test_crossed_moved_away_and_invalidated_quotes_fail_closed():
    arm = _arm(LOW_RESPECT_BUY)
    candle = _confirmation(LOW_RESPECT_BUY)

    crossed = build_order_geometry(
        arm,
        candle,
        bid=100.50,
        ask=100.53,
        spread=0.03,
        minimum_stop_distance=0.35,
    )
    moved = build_order_geometry(
        arm,
        candle,
        bid=99.50,
        ask=99.70,
        spread=0.20,
        minimum_stop_distance=0.35,
    )
    invalidated = build_order_geometry(
        arm,
        candle,
        bid=99.79,
        ask=99.99,
        spread=0.20,
        minimum_stop_distance=0.35,
    )

    assert crossed.reason == "BUY_STOP_ALREADY_CROSSED"
    assert moved.reason == "BUY_STORY_MOVED_AWAY"
    assert invalidated.reason == "BUY_STORY_INVALIDATED"


def _history() -> list[Candle]:
    start = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
    rows = []
    for index in range(60):
        base = 100.0 + (index % 4) * 0.02
        rows.append(
            Candle(
                timestamp=(start + timedelta(minutes=index)).isoformat(),
                open=base,
                high=base + 0.20,
                low=base - 0.20,
                close=base + 0.05,
            )
        )
    rows[-1] = _confirmation(LOW_RESPECT_BUY)
    return rows


def test_public_runtime_route_uses_new_model_and_produces_direct_pending_proposal(monkeypatch):
    arm = _arm(LOW_RESPECT_BUY)
    monkeypatch.setattr(
        "tradingagents.agents.price_action.one_minute_scalper.detect_post_close_arms",
        lambda *args, **kwargs: (arm,),
    )

    payload = analyze_one_minute_entry(
        "XAUUSD.vx",
        "2026-07-28 13:00 UTC",
        {"1m": _history()},
        session_config={
            "fast_signal_model": CANDIDATE_NAME,
            "current_bid_price": 100.25,
            "current_ask_price": 100.45,
            "current_spread_price": 0.20,
            "minimum_stop_distance_price": 0.35,
            "fast_min_stop_spread_multiple": 1.2,
            "fast_volume_boost_enabled": False,
        },
    )

    assert payload["status"] == "SETUP_FOUND"
    assert payload["recommendation"] == "BUY"
    assert payload["setups"][0]["name"] == CANDIDATE_NAME
    assert payload["setups"][0]["entry_price"] > 100.45
    assert payload["telemetry"]["selected_candidate"]["trigger"] == LOW_RESPECT_BUY
    assert payload["telemetry"]["selected_candidate"]["signal_quality"]["quote_pressure_used"] is False


def test_public_runtime_route_requires_sixty_fully_closed_candles():
    payload = analyze_one_minute_entry(
        "XAUUSD.vx",
        "2026-07-28 13:00 UTC",
        {"1m": _history()[:-1]},
        session_config={
            "fast_signal_model": CANDIDATE_NAME,
            "current_bid_price": 100.25,
            "current_ask_price": 100.45,
            "current_spread_price": 0.20,
        },
    )

    assert payload["status"] == "NO_SETUP"
    assert "60 fully closed" in payload["message"]
