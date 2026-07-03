from datetime import datetime, timedelta, timezone
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
from tradingagents.agents.price_action.opening_tick_replay import MarketTick
from tradingagents.agents.price_action.opening_state_shadow import (
    FROZEN_TARGET_GRID_CANDIDATE,
    SHADOW_DEFAULT_CANDLE_COUNT,
    build_shadow_report,
    build_shadow_report_from_broker,
    evaluate_shadow_gate,
)


START = datetime(2026, 7, 4, 12, tzinfo=timezone.utc)
MANIFEST = {
    "candidate": FROZEN_TARGET_GRID_CANDIDATE,
    "final_target": 0.75,
    "target_grid_version": 1,
    "queue_policy_version": 1,
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


class _Broker:
    def __init__(self, *, orders=(), positions=()):
        self.orders = list(orders)
        self.positions = list(positions)
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
        return {"symbol": {"name": "XAUUSD"}, "tick": {}, "terminal": {}}

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


def test_shadow_broker_default_candle_count_can_span_three_daily_sessions():
    broker = _Broker()

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
    assert broker.fetch_closed_rates_calls == [("1m", SHADOW_DEFAULT_CANDLE_COUNT)]
