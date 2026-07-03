from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_tick_replay import MarketTick
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
    screen_opening_fixture,
)


START = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def _candle(day, index, open_, high, low, close):
    return Candle(
        timestamp=(START + timedelta(days=day, minutes=index)).isoformat(),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=100,
    )


def _tick(day, seconds, bid, ask):
    return MarketTick(
        time=(START + timedelta(days=day, minutes=5, seconds=seconds)).isoformat(),
        bid=bid,
        ask=ask,
    )


def _day(day, profitable=True):
    candles = [
        _candle(day, 0, 100, 101, 99.5, 100.5),
        _candle(day, 1, 100.4, 101.02, 100.0, 100.2),
        _candle(day, 2, 100.1, 100.6, 99.9, 100.1),
        _candle(day, 3, 100.5, 101.8, 100.4, 101.35),
        _candle(day, 4, 101.3, 101.7, 101.1, 101.45),
    ]
    ticks = (
        [_tick(day, 0, 101.40, 101.60), _tick(day, 2, 102.60, 102.80)]
        if profitable
        else [_tick(day, 0, 101.40, 101.60), _tick(day, 2, 100.70, 100.90)]
    )
    return candles, ticks


def test_opening_screen_is_deterministic_and_broker_free():
    candles = []
    ticks = []
    for day in range(3):
        day_candles, day_ticks = _day(day, profitable=True)
        candles.extend(day_candles)
        ticks.extend(day_ticks)
    fixture = OpeningResearchFixture(schema_version=1, candles=candles, ticks=ticks)

    first = screen_opening_fixture(fixture)
    second = screen_opening_fixture(fixture)

    assert first == second
    assert first["broker_mutation_enabled"] is False
    assert first["decision"] == "FREEZE_OPENING_TEMPLATE"
    assert first["qualifying_templates"] == ["BREAK_HOLD"]


def test_opening_screen_reports_no_edge_when_all_templates_fail_gate():
    candles = []
    ticks = []
    for day in range(3):
        day_candles, day_ticks = _day(day, profitable=False)
        candles.extend(day_candles)
        ticks.extend(day_ticks)
    fixture = OpeningResearchFixture(schema_version=1, candles=candles, ticks=ticks)

    report = screen_opening_fixture(fixture)

    assert report["decision"] == "NO_OPENING_STATE_EDGE"
    assert report["qualifying_templates"] == []
    assert "NON_POSITIVE_EXPECTANCY" in report["templates"]["BREAK_HOLD"]["gate"][
        "reasons"
    ]
