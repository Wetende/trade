import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tradingagents.agents.price_action.one_minute_entry_model import (
    FAILED_LOW_BREAK_BUY,
    HIGH_BREAK_BUY,
    LOW_RESPECT_BUY,
)
from tradingagents.agents.price_action.one_minute_post_close_state import PostCloseArm
from tradingagents.agents.price_action.one_minute_quote_pressure_v8 import CANDIDATE_NAME
from tradingagents.agents.price_action.one_minute_quote_pressure_v8_promotion import (
    V8PromotionValidation,
)
from tradingagents.brokers.mt5_one_minute_v8_runner import (
    MT5OneMinuteV8Runner,
    MT5OneMinuteV8RunnerConfig,
)


START = datetime(2026, 7, 20, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = START

    def set(self, seconds):
        self.value = START + timedelta(seconds=seconds)

    def __call__(self):
        return self.value


class FakeBroker:
    def __init__(self, clock, trade_mode="DEMO"):
        self.clock = clock
        self.trade_mode = trade_mode
        self.bid = 99.98
        self.ask = 100.02
        self.orders = []
        self.positions = []
        self.cancel_results = []
        self.close_results = []
        self.close_failures_remaining = 0
        self.candles = [
            {
                "timestamp": (START - timedelta(minutes=60 - index)).isoformat(),
                "open": 100.0,
                "high": 100.1,
                "low": 99.9,
                "close": 100.0,
                "tick_volume": 100,
            }
            for index in range(60)
        ]

    def connect(self):
        return {
            "connected": True,
            "account": {"trade_mode_label": self.trade_mode},
            "symbol": {
                "name": "XAUUSD",
                "point": 0.01,
                "trade_tick_size": 0.01,
                "supports_stop_orders": True,
                "supports_order_time_specified": True,
                "pending_filling_mode": "ORDER_FILLING_RETURN",
                "trade_stops_distance_price": 0.0,
                "trade_freeze_distance_price": 0.0,
            },
        }

    def current_symbol_snapshot(self):
        return {
            "symbol": {
                **self.connect()["symbol"],
                "bid": self.bid,
                "ask": self.ask,
                "spread_price": self.ask - self.bid,
            },
            "tick": {"time_utc": self.clock().isoformat()},
            "terminal": {"trade_allowed": True, "tradeapi_disabled": False},
        }

    def open_orders(self, symbol):
        return list(self.orders)

    def open_positions(self, symbol):
        return list(self.positions)

    def fetch_closed_rates(self, timeframe, count):
        return list(self.candles[-count:])

    def estimate_stop_loss_account_currency(self, side, volume, entry, stop):
        return abs(float(entry) - float(stop)) * 100.0 * float(volume)

    def cancel_order(self, ticket):
        self.orders = [order for order in self.orders if int(order["ticket"]) != int(ticket)]
        result = {"ok": True, "ticket": ticket}
        self.cancel_results.append(result)
        return result

    def close_position(self, position, *, comment):
        if self.close_failures_remaining:
            self.close_failures_remaining -= 1
            result = {"ok": False, "comment": "retry"}
        else:
            self.positions = [
                item for item in self.positions if item["ticket"] != position["ticket"]
            ]
            result = {"ok": True, "comment": comment}
        self.close_results.append(result)
        return result


class FakeExecutor:
    def __init__(self, broker):
        self.broker = broker
        self.config = SimpleNamespace(symbol="XAUUSD")
        self.proposals = []
        self.manage_calls = 0
        self.history = {
            "status": "RECONCILED",
            "net_profit": 0.0,
            "closed_trade_count": 0,
            "closed_trades": [],
        }

    def execute_proposal(self, proposal):
        self.proposals.append(proposal)
        ticket = 1000 + len(self.proposals)
        self.broker.orders.append(
            {
                "ticket": ticket,
                "symbol": "XAUUSD",
                "side": proposal.side.value,
                "price_open": proposal.entry_price,
                "sl": proposal.stop_loss,
                "volume": proposal.volume,
            }
        )
        return {"status": "PLACED", "order": ticket, "account_safety": {"passed": True}}

    def reconcile_trade_history(self, *, since_utc, now_utc):
        return dict(self.history)

    def manage_open_positions(self):
        self.manage_calls += 1
        return {"status": "DISABLED"}


def _validation():
    return V8PromotionValidation(
        candidate=CANDIDATE_NAME,
        manifest_path="manifest.json",
        manifest_sha256="a" * 64,
        promotion_path="promotion.json",
        promotion_sha256="b" * 64,
        approved_volume_cap=1.0,
        promotion_kind="VOLUME_1_DEMO",
        evidence_stages=("DISCOVERY", "HELD_OUT", "PROSPECTIVE", "DEMO_0_01"),
    )


def _v9_validation():
    return replace(
        _validation(),
        candidate="ONE_MINUTE_CAUSAL_MICROBURST_V9_1",
    )


def _write_v9_manifest(path):
    path.write_text(
        json.dumps(
            {
                "candidate": "ONE_MINUTE_CAUSAL_MICROBURST_V9_1",
                "strategy": {
                    "history_candles": 60,
                    "pressure_change_count": 8,
                    "pressure_window_seconds": 2.0,
                    "minimum_nonzero_moves": 4,
                    "minimum_directional_pressure": 0.625,
                    "minimum_displacement_r": 0.08,
                    "maximum_adverse_r": 0.15,
                    "maximum_spread_multiple": 1.15,
                    "placement_delay_seconds": 2.0,
                    "pending_expiry_seconds": 20,
                    "minimum_stop_distance": 0.35,
                    "minimum_stop_spread_multiple": 1.2,
                    "maximum_stop_distance": 1.0,
                    "risk_reward": 1.5,
                    "tick_size": 0.01,
                },
                "modeled_round_trip_cost_r": 0.05,
                "two_loss_pause_minutes": 15,
            }
        ),
        encoding="utf-8",
    )


def _v10_validation():
    return replace(_validation(), candidate="ONE_MINUTE_CAUSAL_RECLAIM_V10")


def _write_v10_manifest(path):
    path.write_text(
        json.dumps(
            {
                "candidate": "ONE_MINUTE_CAUSAL_RECLAIM_V10",
                "strategy": {
                    "history_candles": 60,
                    "pressure_change_count": 20,
                    "pressure_window_seconds": 3.0,
                    "minimum_nonzero_moves": 10,
                    "minimum_directional_pressure": 0.60,
                    "minimum_displacement_r": 0.10,
                    "maximum_adverse_r": 0.15,
                    "maximum_spread_multiple": 1.10,
                    "placement_delay_seconds": 5.0,
                    "pending_expiry_seconds": 20,
                    "minimum_stop_distance": 0.35,
                    "minimum_stop_spread_multiple": 1.2,
                    "maximum_stop_distance": 1.0,
                    "risk_reward": 1.5,
                    "tick_size": 0.01,
                },
                "modeled_round_trip_cost_r": 0.05,
                "two_loss_pause_minutes": 15,
            }
        ),
        encoding="utf-8",
    )


def _runner(tmp_path, broker, executor, clock, **updates):
    config = MT5OneMinuteV8RunnerConfig(
        results_dir=tmp_path,
        candidate_manifest=tmp_path / "manifest.json",
        promotion_record=tmp_path / "promotion.json",
        repo_root=tmp_path,
        volume=1.0,
        max_runtime_seconds=updates.pop("max_runtime_seconds", 100),
        shutdown_grace_seconds=updates.pop("shutdown_grace_seconds", 120),
        flat_verification_count=updates.pop("flat_verification_count", 3),
        **updates,
    )
    return MT5OneMinuteV8Runner(
        config,
        executor=executor,
        promotion_validation=_validation(),
        now_func=clock,
        sleep_func=lambda _seconds: None,
    )


def _arm():
    return PostCloseArm(
        candidate=CANDIDATE_NAME,
        arm_id="v8-live-arm",
        family=LOW_RESPECT_BUY,
        direction="BUY",
        level_side="low",
        level=100.0,
        touch_count=2,
        tolerance=0.2,
        break_margin=0.05,
        zone_low=99.8,
        zone_high=100.2,
        confirmation_type="rejection",
        confirmation_time=(START - timedelta(minutes=1)).isoformat(),
        confirmation_closed_at=START.isoformat(),
        trigger_eligible_at=(START + timedelta(seconds=5)).isoformat(),
        expires_at=(START + timedelta(seconds=60)).isoformat(),
        invalidation=99.7,
        confirmation_open=100.0,
        confirmation_high=100.25,
        confirmation_low=99.75,
        confirmation_close=100.0,
    )


def test_runner_config_locks_volume_steps_and_two_r_ceiling(tmp_path):
    base = {
        "results_dir": tmp_path,
        "candidate_manifest": tmp_path / "manifest.json",
        "promotion_record": tmp_path / "promotion.json",
        "repo_root": tmp_path,
    }
    with pytest.raises(ValueError, match="exactly 0.01 or 1.0"):
        MT5OneMinuteV8RunnerConfig(**base, volume=0.5)
    with pytest.raises(ValueError, match="frozen 2R"):
        MT5OneMinuteV8RunnerConfig(**base, volume=0.01, max_session_r=2.01)


def test_runner_refuses_real_account_and_nonzero_initial_exposure(tmp_path):
    clock = Clock()
    real = FakeBroker(clock, trade_mode="REAL")
    with pytest.raises(ValueError, match="demo account required"):
        _runner(tmp_path / "real", real, FakeExecutor(real), clock).initialize()

    demo = FakeBroker(clock)
    demo.orders.append({"ticket": 1})
    with pytest.raises(ValueError, match="zero initial exposure"):
        _runner(tmp_path / "exposed", demo, FakeExecutor(demo), clock).initialize()


def test_live_fake_broker_path_places_fixed_volume_v8_stop(monkeypatch, tmp_path):
    clock = Clock()
    broker = FakeBroker(clock)
    executor = FakeExecutor(broker)
    runner = _runner(tmp_path, broker, executor, clock)
    monkeypatch.setattr(
        "tradingagents.brokers.mt5_one_minute_v8_runner.detect_v8_arms",
        lambda candles, config: (_arm(),),
    )

    runner.initialize()
    runner.run_once()  # arm
    clock.set(5)
    broker.bid, broker.ask = 99.98, 100.02
    runner.run_once()  # zone test
    clock.set(6)
    broker.bid, broker.ask = 100.26, 100.30
    runner.run_once()  # structural trigger
    for index in range(1, 21):
        clock.set(6 + index * 0.1)
        mid = 100.28 + index * 0.01
        broker.bid, broker.ask = mid - 0.02, mid + 0.02
        runner.run_once()
    clock.set(13)
    broker.bid, broker.ask = 100.46, 100.50

    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert len(executor.proposals) == 1
    proposal = executor.proposals[0]
    assert proposal.setup_name == CANDIDATE_NAME
    assert proposal.order_type == "BUY_STOP"
    assert proposal.volume == 1.0
    assert proposal.volume_multiplier is None
    assert proposal.volume_decision == "FIXED_NO_BOOST"
    assert datetime.fromisoformat(proposal.valid_until) - clock() == timedelta(seconds=20)
    assert result["risk"]["accepted"] is True
    executor.history = {
        "status": "RECONCILED",
        "net_profit": 10.0,
        "closed_trade_count": 1,
        "filled_trades": [
            {
                "position_id": 2001,
                "entry_order": 1001,
                "entry_price": proposal.entry_price + 0.01,
                "opened_at_utc": (clock() + timedelta(seconds=1)).isoformat(),
            }
        ],
        "closed_trades": [
            {
                "position_id": 2001,
                "entry_order": 1001,
                "entry_price": proposal.entry_price + 0.01,
                "opened_at_utc": (clock() + timedelta(seconds=1)).isoformat(),
                "closed_at_utc": (clock() + timedelta(seconds=10)).isoformat(),
                "profit": 10.0,
                "outcome": "WIN",
                "exit_comment": "TA target",
                "exit_deal_ticket": 3001,
            }
        ],
    }

    runner._reconcile_history(clock() + timedelta(seconds=10))

    assert runner.runtime["entry_drift_failures"] == 0
    assert runner.runtime["submissions"]["1001"]["entry_drift_compliant"] is True
    assert runner.runtime["evidence_rows"][0]["profit_r"] == pytest.approx(0.1)


def test_promoted_runner_uses_frozen_v9_detector_and_strategy(monkeypatch, tmp_path):
    clock = Clock()
    broker = FakeBroker(clock)
    executor = FakeExecutor(broker)
    manifest = tmp_path / "manifest.json"
    _write_v9_manifest(manifest)
    config = MT5OneMinuteV8RunnerConfig(
        results_dir=tmp_path,
        candidate_manifest=manifest,
        promotion_record=tmp_path / "promotion.json",
        repo_root=tmp_path,
        volume=0.01,
        max_runtime_seconds=100,
    )
    runner = MT5OneMinuteV8Runner(
        config,
        executor=executor,
        promotion_validation=_v9_validation(),
        now_func=clock,
        sleep_func=lambda _seconds: None,
    )
    arm = replace(
        _arm(),
        candidate="ONE_MINUTE_CAUSAL_MICROBURST_V9_1",
        family=HIGH_BREAK_BUY,
        trigger_eligible_at=(START + timedelta(seconds=1)).isoformat(),
        invalidation=99.9,
    )
    monkeypatch.setattr(
        "tradingagents.agents.price_action.one_minute_causal_microburst_v9.detect_causal_microburst_arms",
        lambda candles, candidate_name: (arm,),
    )

    runner.initialize()
    runner.run_once()
    clock.set(1)
    broker.bid, broker.ask = 100.21, 100.25
    runner.run_once()
    clock.set(2)
    broker.bid, broker.ask = 100.22, 100.26
    runner.run_once()
    for index in range(1, 9):
        clock.set(2 + index * 0.1)
        mid = 100.24 + index * 0.01
        broker.bid, broker.ask = mid - 0.02, mid + 0.02
        runner.run_once()
    clock.set(4.8)
    broker.bid, broker.ask = 100.30, 100.34
    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert runner.runtime["candidate"] == "ONE_MINUTE_CAUSAL_MICROBURST_V9_1"
    assert executor.proposals[0].setup_name == "ONE_MINUTE_CAUSAL_MICROBURST_V9_1"
    assert executor.proposals[0].volume == 0.01


def test_promoted_runner_uses_frozen_v10_reclaim_and_strict_pressure(
    monkeypatch, tmp_path
):
    clock = Clock()
    broker = FakeBroker(clock)
    executor = FakeExecutor(broker)
    manifest = tmp_path / "manifest.json"
    _write_v10_manifest(manifest)
    config = MT5OneMinuteV8RunnerConfig(
        results_dir=tmp_path,
        candidate_manifest=manifest,
        promotion_record=tmp_path / "promotion.json",
        repo_root=tmp_path,
        volume=0.01,
        max_runtime_seconds=100,
    )
    runner = MT5OneMinuteV8Runner(
        config,
        executor=executor,
        promotion_validation=_v10_validation(),
        now_func=clock,
        sleep_func=lambda _seconds: None,
    )
    arm = replace(
        _arm(),
        candidate="ONE_MINUTE_CAUSAL_RECLAIM_V10",
        family=FAILED_LOW_BREAK_BUY,
        trigger_eligible_at=(START + timedelta(seconds=1)).isoformat(),
        invalidation=99.7,
    )
    monkeypatch.setattr(
        "tradingagents.agents.price_action.one_minute_causal_reclaim_v10.detect_causal_reclaim_arms",
        lambda candles, candidate_name: (arm,),
    )

    runner.initialize()
    runner.run_once()
    clock.set(1)
    broker.bid, broker.ask = 99.98, 100.02
    runner.run_once()
    clock.set(1.1)
    broker.bid, broker.ask = 100.21, 100.25
    runner.run_once()
    for index in range(1, 21):
        clock.set(1.1 + index * 0.1)
        mid = 100.23 + index * 0.01
        broker.bid, broker.ask = mid - 0.02, mid + 0.02
        runner.run_once()
    clock.set(8.1)
    broker.bid, broker.ask = 100.37, 100.41
    result = runner.run_once()

    assert result["status"] == "ORDER_PLACED"
    assert runner.runtime["candidate"] == "ONE_MINUTE_CAUSAL_RECLAIM_V10"
    assert executor.proposals[0].strategy_type == "causal_reclaim"
    assert executor.proposals[0].volume == 0.01


def test_restart_preserves_original_runtime_and_drain_deadlines(tmp_path):
    clock = Clock()
    broker = FakeBroker(clock)
    executor = FakeExecutor(broker)
    first = _runner(tmp_path, broker, executor, clock, max_runtime_seconds=100)
    runtime = first.initialize()
    original_deadline = runtime["runtime_deadline_utc"]
    clock.set(50)

    recovered = _runner(tmp_path, broker, executor, clock, max_runtime_seconds=100)

    assert recovered.initialize()["runtime_deadline_utc"] == original_deadline
    clock.set(100)
    recovered.run_once()
    drain_deadline = recovered.runtime["drain_deadline_utc"]
    clock.set(150)
    recovered_again = _runner(tmp_path, broker, executor, clock, max_runtime_seconds=100)
    assert recovered_again.initialize()["drain_deadline_utc"] == drain_deadline


def test_deadline_cancels_pending_and_requires_three_fresh_flat_snapshots(tmp_path):
    clock = Clock()
    broker = FakeBroker(clock)
    executor = FakeExecutor(broker)
    runner = _runner(tmp_path, broker, executor, clock, max_runtime_seconds=1)
    runner.initialize()
    broker.orders.append({"ticket": 7, "symbol": "XAUUSD"})
    clock.set(1)

    first = runner.run_once()
    second = runner.run_once()
    third = runner.run_once()

    assert broker.cancel_results == [{"ok": True, "ticket": 7}]
    assert first["status"] == "DRAINING"
    assert second["status"] == "DRAINING"
    assert third["status"] == "DRAINED_FLAT"
    assert third["flat_verification_count"] == 3


def test_deadline_manages_during_grace_then_retries_close_until_flat(tmp_path):
    clock = Clock()
    broker = FakeBroker(clock)
    executor = FakeExecutor(broker)
    runner = _runner(
        tmp_path,
        broker,
        executor,
        clock,
        max_runtime_seconds=1,
        shutdown_grace_seconds=2,
        flat_verification_count=2,
    )
    runner.initialize()
    broker.positions.append(
        {
            "ticket": 9,
            "symbol": "XAUUSD",
            "side": "BUY",
            "price_open": 100.0,
            "sl": 99.5,
            "volume": 1.0,
        }
    )
    broker.close_failures_remaining = 1
    clock.set(1)
    grace = runner.run_once()
    assert grace["status"] == "DRAINING"
    assert executor.manage_calls == 1
    assert not broker.close_results

    clock.set(3)
    failed_close = runner.run_once()
    assert failed_close["positions"]
    assert broker.close_results[-1]["ok"] is False
    retry = runner.run_once()
    assert broker.close_results[-1]["ok"] is True
    complete = runner.run_once()

    assert retry["status"] == "DRAINING"
    assert complete["status"] == "DRAINED_FLAT"
    assert complete["positions"] == []


def test_run_forever_survives_transient_drain_snapshot_failure(tmp_path):
    clock = Clock()
    broker = FakeBroker(clock)
    executor = FakeExecutor(broker)
    runner = _runner(
        tmp_path,
        broker,
        executor,
        clock,
        max_runtime_seconds=1,
        flat_verification_count=2,
    )
    runner.initialize()
    clock.set(1)
    original_connect = broker.connect
    failures = 1

    def flaky_connect():
        nonlocal failures
        if failures:
            failures -= 1
            raise RuntimeError("transient MT5 connection failure")
        return original_connect()

    broker.connect = flaky_connect

    result = runner.run_forever()

    assert result["status"] == "DRAINED_FLAT"
    assert runner.runtime["phase"] == "COMPLETE"
    assert runner.runtime["safety_failures"] == 1


def test_two_loss_pause_is_persisted_for_fifteen_minutes_and_requires_new_structure(tmp_path):
    clock = Clock()
    broker = FakeBroker(clock)
    executor = FakeExecutor(broker)
    executor.history = {
        "status": "RECONCILED",
        "net_profit": -150.0,
        "closed_trade_count": 2,
        "closed_trades": [
            {
                "exit_deal_ticket": 1,
                "profit": -50.0,
                "closed_at_utc": (START + timedelta(seconds=10)).isoformat(),
            },
            {
                "exit_deal_ticket": 2,
                "profit": -100.0,
                "closed_at_utc": (START + timedelta(seconds=20)).isoformat(),
            },
        ],
    }
    runner = _runner(tmp_path, broker, executor, clock)
    runner.initialize()
    clock.set(20)

    runner._reconcile_history(clock())

    assert runner.runtime["consecutive_losses"] == 2
    assert runner.runtime["cooldown_until_utc"] == (
        START + timedelta(seconds=920)
    ).isoformat()
    recovered = _runner(tmp_path, broker, executor, clock)
    assert recovered.initialize()["cooldown_until_utc"] == runner.runtime["cooldown_until_utc"]
