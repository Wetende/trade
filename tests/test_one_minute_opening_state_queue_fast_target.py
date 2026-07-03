from datetime import datetime, timedelta, timezone

from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.evidence_metrics import HistoricalGateResult
from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
)
from tradingagents.agents.price_action import opening_state_queue_fast_target
from tradingagents.agents.price_action.opening_state_queue_fast_target import (
    QUEUE_FAST_TARGET_CANDIDATE_NAME,
    dedupe_signal_zone_opportunities,
    replay_queue_fast_target_fixture,
    screen_queue_fast_target_fixture,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
)
from tradingagents.agents.price_action.opening_tick_replay import MarketTick


START = datetime(2026, 7, 1, 12, tzinfo=timezone.utc)


def _opportunity(
    template,
    *,
    signal_offset=0,
    entry_kind="reaction",
    level=100.0,
):
    return OpeningOpportunity(
        template=template,
        direction="BUY",
        signal_time=(START + timedelta(seconds=signal_offset)).isoformat(),
        level_side="high",
        level=level,
        touch_count=2,
        tolerance=0.2,
        used_candle_indexes=(10, 11),
        entry_kind=entry_kind,
    )


def _tick(seconds, bid, ask):
    return MarketTick(
        time=(START + timedelta(seconds=seconds)).isoformat(),
        bid=bid,
        ask=ask,
    )


def _fixture(ticks):
    candles = tuple(
        Candle(
            timestamp=(START + timedelta(minutes=i)).isoformat(),
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=100,
        )
        for i in range(5)
    )
    return OpeningResearchFixture(schema_version=1, candles=candles, ticks=tuple(ticks))


def test_dedupe_signal_zone_keeps_distinct_levels_only():
    retained = dedupe_signal_zone_opportunities(
        (
            _opportunity(OpeningTemplate.REJECTION, level=100.0),
            _opportunity(OpeningTemplate.BREAK_HOLD, level=100.1),
            _opportunity(OpeningTemplate.FAILED_BREAK, level=101.0),
        )
    )

    assert [item.template for item in retained] == [
        OpeningTemplate.FAILED_BREAK,
        OpeningTemplate.BREAK_HOLD,
    ]


def test_queue_replay_accepts_fresh_second_after_first_expires():
    fixture = _fixture(
        (
            _tick(0, 99.90, 100.00),
            _tick(20, 99.90, 100.00),
            _tick(21, 100.12, 100.32),
            _tick(22, 100.80, 101.00),
        )
    )

    rows = replay_queue_fast_target_fixture(
        fixture,
        opportunities=(
            _opportunity(OpeningTemplate.REJECTION, entry_kind="reaction"),
            _opportunity(OpeningTemplate.BREAK_HOLD, entry_kind="continuation"),
        ),
    )

    assert rows[0].accepted is True
    assert rows[0].filled is False
    assert rows[1].accepted is True
    assert rows[1].filled is True


def test_queue_replay_skips_stale_second_after_active_trade():
    fixture = _fixture(
        (
            _tick(0, 100.12, 100.32),
            _tick(25, 100.80, 101.00),
        )
    )

    rows = replay_queue_fast_target_fixture(
        fixture,
        opportunities=(
            _opportunity(OpeningTemplate.REJECTION, entry_kind="reaction"),
            _opportunity(OpeningTemplate.FAILED_BREAK, entry_kind="reaction"),
        ),
    )

    assert rows[0].accepted is True
    assert rows[0].filled is True
    assert rows[1].accepted is False
    assert rows[1].reasons == ("QUEUE_EXPIRED_BEFORE_AVAILABLE",)


def test_queue_screen_reports_failure_without_manifest_when_gates_fail():
    report = screen_queue_fast_target_fixture(
        "tests/fixtures/one_minute/opening_state/sample-openings.json"
    )

    assert report["candidate"] == QUEUE_FAST_TARGET_CANDIDATE_NAME
    assert report["broker_mutation_enabled"] is False
    assert report["replay_config"]["risk_reward"] == 1.0
    assert report["gate"]["passed"] is False
    assert report["decision"] == "NO_OPENING_STATE_QUEUE_FAST_TARGET_EDGE"
    assert report["frozen_manifest"] is None


def test_queue_screen_freezes_manifest_when_gate_passes(monkeypatch):
    monkeypatch.setattr(
        opening_state_queue_fast_target,
        "evaluate_historical_gate",
        lambda _metrics, _baseline: HistoricalGateResult(passed=True, reasons=()),
    )

    report = screen_queue_fast_target_fixture(
        "tests/fixtures/one_minute/opening_state/sample-openings.json"
    )

    assert report["decision"] == "FREEZE_OPENING_STATE_QUEUE_FAST_TARGET"
    assert report["frozen_manifest"]["candidate"] == QUEUE_FAST_TARGET_CANDIDATE_NAME
    assert report["frozen_manifest"]["replay_config"]["risk_reward"] == 1.0
