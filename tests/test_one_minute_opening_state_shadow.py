from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace

from tradingagents.agents.price_action.evidence_metrics import VariantMetrics
from tradingagents.agents.price_action.models import Candle
from tradingagents.agents.price_action.opening_state import (
    OpeningOpportunity,
    OpeningTemplate,
)
from tradingagents.agents.price_action.opening_state_screening import (
    OpeningResearchFixture,
)
from tradingagents.agents.price_action.opening_tick_replay import MarketTick, ReplayConfig
from tradingagents.agents.price_action.opening_state_shadow import (
    FROZEN_BUY_CONTINUATION_CANDIDATE,
    FROZEN_TARGET_GRID_CANDIDATE,
    SHADOW_DEFAULT_CANDLE_COUNT,
    SHADOW_CONTEXT_CANDLE_COUNT,
    build_shadow_report,
    build_shadow_report_from_broker,
    buy_continuation_opportunities,
    cumulative_shadow_candle_count,
    evaluate_shadow_gate,
    load_frozen_manifest,
)


START = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
MANIFEST = {
    "candidate": FROZEN_TARGET_GRID_CANDIDATE,
    "final_target": 0.75,
    "target_grid_version": 1,
    "queue_policy_version": 1,
    "broker_mutation_enabled": False,
}
BUY_CONTINUATION_MANIFEST = {
    "candidate": FROZEN_BUY_CONTINUATION_CANDIDATE,
    "final_target": 0.9,
    "continuation_expiry_seconds": 120,
    "reaction_expiry_seconds": 20,
    "buy_continuation_policy_version": 1,
    "template_filter": ["BREAK_HOLD", "BREAK_RETEST_HOLD"],
    "direction_filter": "BUY",
    "entry_policy": "POST_CLOSE_FIXED_PENDING_ENTRY",
    "broker_mutation_enabled": False,
}


def _metrics(
    *,
    fills,
    wins,
    losses,
    net,
    gross_profit,
    gross_loss,
    pf,
    expectancy,
    max_loss_streak,
):
    return VariantMetrics(
        name="variant",
        fills=fills,
        wins=wins,
        losses=losses,
        net_profit=net,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=pf,
        no_gross_loss=losses == 0,
        expectancy=expectancy,
        fill_retention=1.0,
        max_loss_streak=max_loss_streak,
        max_session_drawdown=0.0,
        profitable_session_count=3,
    )


def _opportunity(signal_offset, *, level=100.0):
    return OpeningOpportunity(
        template=OpeningTemplate.BREAK_HOLD,
        direction="BUY",
        signal_time=(START + timedelta(seconds=signal_offset)).isoformat(),
        level_side="high",
        level=level,
        touch_count=2,
        tolerance=0.2,
        used_candle_indexes=(10, 11),
        entry_kind="continuation",
    )


def _typed_opportunity(
    signal_offset,
    *,
    template=OpeningTemplate.BREAK_HOLD,
    direction="BUY",
    level=100.0,
):
    return OpeningOpportunity(
        template=template,
        direction=direction,
        signal_time=(START + timedelta(seconds=signal_offset)).isoformat(),
        level_side="high" if direction == "BUY" else "low",
        level=level,
        touch_count=2,
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


def _fixture():
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
    return OpeningResearchFixture(
        schema_version=1,
        candles=candles,
        ticks=(
            _tick(0, 100.05, 100.25),
            _tick(1, 100.70, 100.90),
            _tick(70, 100.05, 100.25),
            _tick(71, 100.70, 100.90),
        ),
    )


def test_shadow_gate_collects_until_fill_and_session_minimums():
    gate = evaluate_shadow_gate(
        candidate=_metrics(
            fills=29,
            wins=20,
            losses=9,
            net=3.0,
            gross_profit=9.0,
            gross_loss=-6.0,
            pf=1.5,
            expectancy=0.1,
            max_loss_streak=2,
        ),
        baseline=_metrics(
            fills=40,
            wins=20,
            losses=20,
            net=0.0,
            gross_profit=10.0,
            gross_loss=-10.0,
            pf=1.0,
            expectancy=0.0,
            max_loss_streak=3,
        ),
        candidate_session_count=2,
    )

    assert gate["decision"] == "COLLECTING_PROSPECTIVE_SHADOW"
    assert gate["evaluable"] is False
    assert gate["reasons"] == [
        "FEWER_THAN_30_CANDIDATE_FILLS",
        "FEWER_THAN_3_CANDIDATE_SESSIONS",
    ]


def test_shadow_gate_passes_when_evaluable_and_profitable():
    gate = evaluate_shadow_gate(
        candidate=_metrics(
            fills=30,
            wins=20,
            losses=10,
            net=5.0,
            gross_profit=15.0,
            gross_loss=-10.0,
            pf=1.5,
            expectancy=0.1667,
            max_loss_streak=2,
        ),
        baseline=_metrics(
            fills=40,
            wins=20,
            losses=20,
            net=0.0,
            gross_profit=10.0,
            gross_loss=-10.0,
            pf=1.0,
            expectancy=0.0,
            max_loss_streak=3,
        ),
        candidate_session_count=3,
    )

    assert gate["decision"] == "PASS_PROSPECTIVE_SHADOW"
    assert gate["passed"] is True
    assert gate["reasons"] == []


def test_shadow_gate_fails_when_evaluable_but_unprofitable():
    gate = evaluate_shadow_gate(
        candidate=_metrics(
            fills=30,
            wins=10,
            losses=20,
            net=-5.0,
            gross_profit=5.0,
            gross_loss=-10.0,
            pf=0.5,
            expectancy=-0.1667,
            max_loss_streak=4,
        ),
        baseline=_metrics(
            fills=40,
            wins=20,
            losses=20,
            net=0.0,
            gross_profit=10.0,
            gross_loss=-10.0,
            pf=1.0,
            expectancy=0.0,
            max_loss_streak=3,
        ),
        candidate_session_count=3,
    )

    assert gate["decision"] == "FAIL_PROSPECTIVE_SHADOW"
    assert gate["passed"] is False
    assert "PROFIT_FACTOR_BELOW_1_10" in gate["reasons"]
    assert "NON_POSITIVE_EXPECTANCY" in gate["reasons"]
    assert "MAX_LOSS_STREAK_WORSE_THAN_BASELINE" in gate["reasons"]


def test_shadow_gate_requires_sixty_percent_win_rate():
    gate = evaluate_shadow_gate(
        candidate=_metrics(
            fills=30,
            wins=17,
            losses=13,
            net=5.0,
            gross_profit=18.0,
            gross_loss=-13.0,
            pf=1.3846,
            expectancy=0.1667,
            max_loss_streak=2,
        ),
        baseline=_metrics(
            fills=40,
            wins=20,
            losses=20,
            net=0.0,
            gross_profit=10.0,
            gross_loss=-10.0,
            pf=1.0,
            expectancy=0.0,
            max_loss_streak=3,
        ),
        candidate_session_count=3,
    )

    assert gate["decision"] == "FAIL_PROSPECTIVE_SHADOW"
    assert "WIN_RATE_BELOW_0_60" in gate["reasons"]


def test_shadow_report_filters_pre_start_and_uses_frozen_target():
    report = build_shadow_report(
        _fixture(),
        manifest=MANIFEST,
        prospective_start=(START + timedelta(seconds=30)).isoformat(),
        raw_opportunities=(
            _opportunity(0, level=100.0),
            _opportunity(70, level=100.0),
        ),
        candidate_opportunities=(
            _opportunity(0, level=100.0),
            _opportunity(70, level=100.0),
        ),
    )

    assert report["candidate"] == FROZEN_TARGET_GRID_CANDIDATE
    assert report["replay_config"]["risk_reward"] == 0.75
    assert report["raw_opportunities_after_start"] == 1
    assert report["candidate_opportunities_after_start"] == 1
    assert report["metrics"]["fills"] == 1
    assert report["broker_mutation_enabled"] is False


def test_shadow_report_accepts_realistic_replay_config():
    report = build_shadow_report(
        _fixture(),
        manifest=MANIFEST,
        prospective_start=(START + timedelta(seconds=30)).isoformat(),
        raw_opportunities=(_opportunity(70, level=100.0),),
        candidate_opportunities=(_opportunity(70, level=100.0),),
        replay_config=ReplayConfig(
            risk_reward=0.75,
            candle_close_delay_seconds=60,
            placement_delay_seconds=5,
            absolute_pending_expiry=True,
            skip_if_entry_crossed_at_placement=True,
        ),
    )

    assert report["replay_config"]["candle_close_delay_seconds"] == 60
    assert report["replay_config"]["placement_delay_seconds"] == 5
    assert report["replay_config"]["absolute_pending_expiry"] is True
    assert report["replay_config"]["skip_if_entry_crossed_at_placement"] is True


def test_load_frozen_manifest_accepts_buy_continuation_candidate(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(BUY_CONTINUATION_MANIFEST),
        encoding="utf-8",
    )

    manifest = load_frozen_manifest(manifest_path)

    assert manifest["candidate"] == FROZEN_BUY_CONTINUATION_CANDIDATE


def test_buy_continuation_shadow_uses_manifest_selector_and_expiry():
    report = build_shadow_report(
        _fixture(),
        manifest=BUY_CONTINUATION_MANIFEST,
        prospective_start=START.isoformat(),
        raw_opportunities=(
            _typed_opportunity(70, template=OpeningTemplate.BREAK_HOLD, direction="BUY"),
            _typed_opportunity(
                80,
                template=OpeningTemplate.BREAK_RETEST_HOLD,
                direction="BUY",
            ),
        ),
        candidate_opportunities=(
            _typed_opportunity(70, template=OpeningTemplate.BREAK_HOLD, direction="BUY"),
            _typed_opportunity(
                80,
                template=OpeningTemplate.BREAK_RETEST_HOLD,
                direction="BUY",
            ),
        ),
    )

    assert report["candidate"] == FROZEN_BUY_CONTINUATION_CANDIDATE
    assert report["replay_config"]["risk_reward"] == 0.9
    assert report["replay_config"]["continuation_expiry_seconds"] == 120
    assert report["manifest"]["template_filter"] == ["BREAK_HOLD", "BREAK_RETEST_HOLD"]
    assert report["manifest"]["direction_filter"] == "BUY"


def test_buy_continuation_opportunities_keep_buy_break_templates(monkeypatch):
    fixture = _fixture()
    opportunities = (
        _typed_opportunity(0, template=OpeningTemplate.BREAK_HOLD, direction="BUY"),
        _typed_opportunity(
            60,
            template=OpeningTemplate.BREAK_RETEST_HOLD,
            direction="BUY",
        ),
        _typed_opportunity(120, template=OpeningTemplate.BREAK_HOLD, direction="SELL"),
        _typed_opportunity(180, template=OpeningTemplate.REJECTION, direction="BUY"),
    )
    monkeypatch.setattr(
        "tradingagents.agents.price_action.opening_state_shadow.detected_candidate_opportunities",
        lambda _fixture: opportunities,
    )

    selected = buy_continuation_opportunities(fixture)

    assert [item.template for item in selected] == [
        OpeningTemplate.BREAK_HOLD,
        OpeningTemplate.BREAK_RETEST_HOLD,
    ]
    assert {item.direction for item in selected} == {"BUY"}


class _Broker:
    def __init__(self, *, orders=(), positions=(), tick_time=None):
        self.orders = list(orders)
        self.positions = list(positions)
        self.tick_time = tick_time
        self.connected = False
        self.fetched_ticks = False
        self.fetch_closed_rates_calls = []

    def connect(self):
        self.connected = True
        return {
            "connected": True,
            "account": {"trade_mode_label": "DEMO"},
            "symbol": {"name": "XAUUSD", "digits": 2, "point": 0.01},
        }

    def current_symbol_snapshot(self):
        tick = {"time_utc": self.tick_time} if self.tick_time else {}
        return {"symbol": {"name": "XAUUSD"}, "tick": tick, "terminal": {}}

    def open_orders(self, _symbol):
        return self.orders

    def open_positions(self, _symbol):
        return self.positions

    def fetch_closed_rates(self, _timeframe, _count):
        self.fetch_closed_rates_calls.append((_timeframe, _count))
        return []

    def fetch_ticks_range(self, _start, _end):
        self.fetched_ticks = True
        return []


def test_shadow_broker_refuses_real_order_configuration():
    broker = _Broker()

    report = build_shadow_report_from_broker(
        broker,
        config=SimpleNamespace(
            symbol="XAUUSD",
            allow_real_orders=True,
            require_demo_account=True,
        ),
        manifest=MANIFEST,
        prospective_start=START.isoformat(),
    )

    assert report["decision"] == "FAIL_PROSPECTIVE_SHADOW"
    assert "REAL_ORDER_CONFIGURATION_ENABLED" in report["gate"]["reasons"]
    assert broker.connected is False
    assert broker.fetched_ticks is False


def test_shadow_broker_refuses_open_orders_or_positions():
    broker = _Broker(orders=({"ticket": 1},))

    report = build_shadow_report_from_broker(
        broker,
        config=SimpleNamespace(
            symbol="XAUUSD",
            allow_real_orders=False,
            require_demo_account=True,
        ),
        manifest=MANIFEST,
        prospective_start=START.isoformat(),
    )

    assert report["decision"] == "FAIL_PROSPECTIVE_SHADOW"
    assert "OPEN_BROKER_STATE_PRESENT" in report["gate"]["reasons"]
    assert broker.fetched_ticks is False


def test_cumulative_shadow_candle_count_preserves_start_plus_context():
    evidence_end = START + timedelta(days=5)

    count = cumulative_shadow_candle_count(
        START.isoformat(),
        evidence_end,
        SHADOW_DEFAULT_CANDLE_COUNT,
    )

    assert count == 5 * 24 * 60 + SHADOW_CONTEXT_CANDLE_COUNT


def test_shadow_broker_expands_default_candle_count_for_elapsed_window():
    broker = _Broker(tick_time=(START + timedelta(days=5)).isoformat())

    build_shadow_report_from_broker(
        broker,
        config=SimpleNamespace(
            symbol="XAUUSD",
            allow_real_orders=False,
            require_demo_account=True,
        ),
        manifest=MANIFEST,
        prospective_start=START.isoformat(),
    )

    assert SHADOW_DEFAULT_CANDLE_COUNT >= 3 * 24 * 60
    assert broker.fetch_closed_rates_calls == [
        ("1m", 5 * 24 * 60 + SHADOW_CONTEXT_CANDLE_COUNT)
    ]
