from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
)
from tradingagents.agents.price_action.opening_tick_replay import (
    MarketTick,
    PreparedTickSeries,
    ReplayConfig,
    simulate_opportunity_from_sorted_ticks,
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
    assert result.completed_at == (START + timedelta(seconds=20)).isoformat()
    assert result.filled_at is None
    assert result.profit is None


def test_closed_trade_completion_time_is_close_time():
    result = simulate_opportunity(
        _buy_opportunity(),
        [_tick(0, 100.05, 100.25), _tick(3, 101.50, 101.70)],
        ReplayConfig(),
    )

    assert result.status == "CLOSED"
    assert result.completed_at == result.closed_at


def test_missing_decision_tick_is_insufficient_evidence():
    result = simulate_opportunity(_buy_opportunity(), [], ReplayConfig())

    assert result.status == "INSUFFICIENT_TICK_EVIDENCE"
    assert result.reason == "NO_DECISION_TICK"


def test_invalid_zero_ask_tick_is_ignored_before_decision_quote():
    ticks = [
        _tick(0, 4025.40, 0.0),
        _tick(1, 100.05, 100.25),
        _tick(3, 101.50, 101.70),
    ]

    result = simulate_opportunity(_buy_opportunity(), ticks, ReplayConfig())

    assert result.status == "CLOSED"
    assert result.filled_at == ticks[1].time
    assert result.spread_at_decision == 0.2


def test_all_invalid_ticks_are_insufficient_quote_evidence():
    ticks = [_tick(0, 4025.40, 0.0), _tick(1, 4025.50, 0.0)]

    result = simulate_opportunity(_buy_opportunity(), ticks, ReplayConfig())

    assert result.status == "INSUFFICIENT_TICK_EVIDENCE"
    assert result.reason == "NO_VALID_DECISION_TICK"


def test_sorted_tick_replay_starts_at_supplied_index():
    ticks = [
        _tick(-10, 4025.40, 0.0),
        _tick(0, 100.05, 100.25),
        _tick(3, 101.50, 101.70),
    ]

    result = simulate_opportunity_from_sorted_ticks(
        _buy_opportunity(),
        ticks,
        ReplayConfig(),
        start_index=1,
    )

    assert result.status == "CLOSED"
    assert result.filled_at == ticks[1].time


def test_prepared_tick_series_matches_scalar_replay_with_invalid_rows():
    ticks = [
        _tick(0, 4025.40, 0.0),
        _tick(1, 100.05, 100.25),
        _tick(3, 101.50, 101.70),
    ]

    scalar = simulate_opportunity(_buy_opportunity(), ticks, ReplayConfig())
    prepared = PreparedTickSeries.from_ticks(ticks).simulate(
        _buy_opportunity(),
        ReplayConfig(),
    )

    assert prepared == scalar


def test_ambiguous_stop_and_target_same_tick_is_excluded():
    ticks = [
        _tick(0, 100.05, 100.25),
        MarketTick(time=(START + timedelta(seconds=1)).isoformat(), bid=98.0, ask=102.0),
    ]

    result = simulate_opportunity(_buy_opportunity(), ticks, ReplayConfig())

    assert result.status == "INSUFFICIENT_TICK_EVIDENCE"
    assert result.reason == "AMBIGUOUS_STOP_AND_TARGET"


def test_window_replay_marks_stale_when_slot_frees_after_expiry():
    opportunity = _buy_opportunity().model_copy(update={"entry_kind": "reaction"})
    series = PreparedTickSeries.from_ticks((_tick(21, 100.30, 100.50),))

    result = series.simulate_window(
        opportunity,
        ReplayConfig(),
        available_at=START + timedelta(seconds=20),
        expires_at=START + timedelta(seconds=20),
    )

    assert result.status == "EXPIRED"
    assert result.reason == "QUEUE_EXPIRED_BEFORE_AVAILABLE"
    assert result.placed_at == (START + timedelta(seconds=20)).isoformat()
    assert result.completed_at == (START + timedelta(seconds=20)).isoformat()
    assert result.filled_at is None


def test_window_replay_uses_remaining_absolute_expiry():
    opportunity = _buy_opportunity().model_copy(update={"entry_kind": "reaction"})
    series = PreparedTickSeries.from_ticks(
        (
            _tick(10, 100.00, 100.10),
            _tick(25, 100.30, 100.50),
        )
    )

    result = series.simulate_window(
        opportunity,
        ReplayConfig(),
        available_at=START + timedelta(seconds=10),
        expires_at=START + timedelta(seconds=20),
    )

    assert result.status == "EXPIRED"
    assert result.reason == "ENTRY_NOT_TOUCHED_BEFORE_EXPIRY"
    assert result.placed_at == (START + timedelta(seconds=10)).isoformat()
    assert result.completed_at == (START + timedelta(seconds=20)).isoformat()
    assert result.filled_at is None


def test_window_replay_places_after_active_slot_frees_and_closes():
    opportunity = _buy_opportunity()
    series = PreparedTickSeries.from_ticks(
        (
            _tick(12, 100.05, 100.25),
            _tick(13, 100.12, 100.32),
            _tick(14, 101.00, 101.20),
        )
    )

    result = series.simulate_window(
        opportunity,
        ReplayConfig(risk_reward=1.0),
        available_at=START + timedelta(seconds=12),
        expires_at=START + timedelta(seconds=45),
    )

    assert result.status == "CLOSED"
    assert result.placed_at == (START + timedelta(seconds=12)).isoformat()
    assert result.filled_at == (START + timedelta(seconds=12)).isoformat()
    assert result.exit_reason == "TARGET"
    assert result.profit == 0.4


def test_realistic_replay_waits_for_candle_close_and_placement_delay():
    ticks = [
        _tick(0, 100.05, 100.25),
        _tick(65, 100.00, 100.10),
        _tick(66, 100.05, 100.25),
        _tick(70, 100.70, 100.90),
    ]

    result = simulate_opportunity(
        _buy_opportunity(),
        ticks,
        ReplayConfig(
            risk_reward=1.0,
            candle_close_delay_seconds=60,
            placement_delay_seconds=5,
            absolute_pending_expiry=True,
            skip_if_entry_crossed_at_placement=True,
        ),
    )

    assert result.status == "CLOSED"
    assert result.placed_at == (START + timedelta(seconds=65)).isoformat()
    assert result.filled_at == (START + timedelta(seconds=66)).isoformat()
    assert result.filled_at != ticks[0].time
    assert result.exit_reason == "TARGET"


def test_realistic_replay_skips_entry_already_crossed_at_placement():
    ticks = [
        _tick(65, 100.25, 100.45),
        _tick(70, 100.70, 100.90),
    ]

    result = simulate_opportunity(
        _buy_opportunity(),
        ticks,
        ReplayConfig(
            candle_close_delay_seconds=60,
            placement_delay_seconds=5,
            absolute_pending_expiry=True,
            skip_if_entry_crossed_at_placement=True,
        ),
    )

    assert result.status == "SKIPPED"
    assert result.reason == "ENTRY_ALREADY_CROSSED_AT_PLACEMENT"
    assert result.filled_at is None


def test_replay_uses_spread_floor_for_stop_and_target():
    result = simulate_opportunity(
        _buy_opportunity(),
        [_tick(0, 100.00, 100.20), _tick(3, 101.01, 101.21)],
        ReplayConfig(risk_reward=1.0, minimum_stop_spread_multiple=4.0),
    )

    assert result.status == "CLOSED"
    assert result.stop_loss == 99.4
    assert result.take_profit == 101.0
