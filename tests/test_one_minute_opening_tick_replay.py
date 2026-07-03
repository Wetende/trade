from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
)
from tradingagents.agents.price_action.opening_tick_replay import (
    MarketTick,
    ReplayConfig,
    simulate_opportunity,
)


START = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def _tick(seconds, bid, ask):
    return MarketTick(
        time=(START + timedelta(seconds=seconds)).isoformat(),
        bid=bid,
        ask=ask,
    )


def _buy_opportunity():
    return OpeningOpportunity(
        template=OpeningTemplate.BREAK_HOLD,
        direction="BUY",
        signal_time=START.isoformat(),
        level_side="high",
        level=100.0,
        touch_count=3,
        tolerance=0.2,
        used_candle_indexes=(10, 11),
        entry_kind="continuation",
    )


def test_continuation_order_fills_until_target_with_mfe_and_mae():
    ticks = [
        _tick(0, 100.05, 100.25),
        _tick(2, 100.35, 100.55),
        _tick(5, 100.80, 101.00),
        _tick(7, 101.50, 101.70),
    ]

    result = simulate_opportunity(_buy_opportunity(), ticks, ReplayConfig())

    assert result.status == "CLOSED"
    assert result.exit_reason == "TARGET"
    assert result.filled_at == ticks[0].time
    assert result.profit > 0
    assert result.mfe > 0
    assert result.mae <= 0


def test_reaction_order_expires_after_20_seconds_without_fill():
    opportunity = _buy_opportunity().model_copy(update={"entry_kind": "reaction"})
    ticks = [_tick(0, 99.70, 99.90), _tick(21, 99.75, 99.95)]

    result = simulate_opportunity(opportunity, ticks, ReplayConfig())

    assert result.status == "EXPIRED"
    assert result.filled_at is None
    assert result.profit is None


def test_missing_decision_tick_is_insufficient_evidence():
    result = simulate_opportunity(_buy_opportunity(), [], ReplayConfig())

    assert result.status == "INSUFFICIENT_TICK_EVIDENCE"
    assert result.reason == "NO_DECISION_TICK"


def test_ambiguous_stop_and_target_same_tick_is_excluded():
    ticks = [
        _tick(0, 100.05, 100.25),
        MarketTick(time=(START + timedelta(seconds=1)).isoformat(), bid=98.0, ask=102.0),
    ]

    result = simulate_opportunity(_buy_opportunity(), ticks, ReplayConfig())

    assert result.status == "INSUFFICIENT_TICK_EVIDENCE"
    assert result.reason == "AMBIGUOUS_STOP_AND_TARGET"
