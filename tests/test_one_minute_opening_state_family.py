from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
)
from tradingagents.agents.price_action.opening_state_family import (
    FAMILY_CANDIDATE_NAME,
    rank_family_opportunities,
    replay_family_fixture,
    screen_family_fixture,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
)
from tradingagents.agents.price_action.opening_tick_replay import MarketTick


START = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def _opportunity(template, direction="BUY", level=100.0, touch_count=2):
    return OpeningOpportunity(
        template=template,
        direction=direction,
        signal_time=START.isoformat(),
        level_side="high",
        level=level,
        touch_count=touch_count,
        tolerance=0.2,
        used_candle_indexes=(10, 11),
        entry_kind="continuation",
    )


def _tick(seconds, bid, ask):
    return MarketTick(
        time=(START + timedelta(seconds=seconds)).isoformat(),
        bid=bid,
        ask=ask,
    )


def test_family_ranking_prefers_touch_count_then_lifecycle_priority():
    ranked = rank_family_opportunities(
        (
            _opportunity(OpeningTemplate.REJECTION, touch_count=3),
            _opportunity(OpeningTemplate.BREAK_RETEST_HOLD, touch_count=2),
            _opportunity(OpeningTemplate.FAILED_BREAK, touch_count=3),
        )
    )

    assert [item.template for item in ranked] == [
        OpeningTemplate.FAILED_BREAK,
        OpeningTemplate.REJECTION,
        OpeningTemplate.BREAK_RETEST_HOLD,
    ]


def test_family_replay_enforces_one_active_trade():
    candles = [
        Candle(
            timestamp=(START + timedelta(minutes=i)).isoformat(),
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=100,
        )
        for i in range(5)
    ]
    fixture = OpeningResearchFixture(
        schema_version=1,
        candles=tuple(candles),
        ticks=(
            _tick(0, 100.05, 100.25),
            _tick(5, 100.06, 100.26),
            _tick(10, 101.50, 101.70),
        ),
    )
    rows = replay_family_fixture(
        fixture,
        opportunities=(
            _opportunity(OpeningTemplate.BREAK_HOLD),
            _opportunity(OpeningTemplate.BREAK_RETEST_HOLD),
        ),
    )

    assert rows[0].accepted is True
    assert rows[0].filled is True
    assert rows[1].accepted is False
    assert rows[1].reasons == ("ONE_ACTIVE_FAMILY_POSITION",)


def test_family_screen_freezes_manifest_when_gates_pass():
    fixture_path = "tests/fixtures/one_minute/opening_state/sample-openings.json"

    report = screen_family_fixture(fixture_path)

    assert report["candidate"] == FAMILY_CANDIDATE_NAME
    assert report["broker_mutation_enabled"] is False
    assert report["gate"]["passed"] is True
    assert report["frozen_manifest"]["candidate"] == FAMILY_CANDIDATE_NAME
