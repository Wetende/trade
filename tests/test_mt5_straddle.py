import json

from tradingagents.agents.straddle_breakout import (
    StraddleBreakoutConfig,
    build_straddle_breakout_pair,
)
from tradingagents.brokers import mt5_straddle
from tradingagents.brokers.mt5 import MT5ConnectionConfig
from tradingagents.brokers.mt5_straddle import MT5StraddleExecutor


class FakeBroker:
    def __init__(self):
        self.symbol_info = {
            "name": "XAUUSD.vx",
            "digits": 2,
            "point": 0.01,
            "trade_tick_size": 0.01,
            "bid": 4499.80,
            "ask": 4500.10,
        }
        self.rates = [
            {
                "timestamp": "2026-06-04T12:00:00+00:00",
                "open": 4499.0,
                "high": 4500.0,
                "low": 4496.5,
                "close": 4498.0,
                "volume": 100,
            },
            {
                "timestamp": "2026-06-04T12:01:00+00:00",
                "open": 4498.0,
                "high": 4501.0,
                "low": 4497.0,
                "close": 4500.0,
                "volume": 100,
            },
            {
                "timestamp": "2026-06-04T12:02:00+00:00",
                "open": 4500.0,
                "high": 4502.0,
                "low": 4498.0,
                "close": 4501.0,
                "volume": 100,
            },
        ]
        self.placed_requests = []
        self.cancelled = []
        self.place_results = [
            {"ok": True, "order": 101, "retcode": 10009, "comment": "buy ok"},
            {"ok": True, "order": 202, "retcode": 10009, "comment": "sell ok"},
        ]
        self.fetch_calls = []
        self.pending_orders = []
        self.positions = []
        self.modified_stops = []
        self.closed_positions = []
        self.history_deals_result = []
        self.history_deals_calls = []
        self.account = {"login": 123, "trade_mode_label": "DEMO"}

    def connect(self):
        return {
            "connected": True,
            "symbol": self.symbol_info,
            "account": self.account,
        }

    def fetch_rates(self, timeframe, count):
        self.fetch_calls.append((timeframe, count))
        return list(self.rates[-count:])

    def open_orders(self, symbol):
        return list(self.pending_orders)

    def open_positions(self, symbol):
        return list(self.positions)

    def place_pending_order(self, request):
        self.placed_requests.append(request)
        return dict(self.place_results.pop(0))

    def cancel_order(self, ticket):
        self.cancelled.append(ticket)
        return {"ok": True, "order": ticket, "retcode": 10009}

    def modify_position_stops(self, position_ticket, stop_loss, take_profit):
        self.modified_stops.append((position_ticket, stop_loss, take_profit))
        return {
            "ok": True,
            "position": position_ticket,
            "retcode": 10009,
            "request": {
                "position": position_ticket,
                "sl": stop_loss,
                "tp": take_profit,
            },
        }

    def close_position(self, position, *, comment="TradingAgents close"):
        self.closed_positions.append((dict(position), comment))
        return {
            "ok": True,
            "position": position["ticket"],
            "retcode": 10009,
            "request": {"position": position["ticket"], "comment": comment},
        }

    def history_deals(self, symbol, start_utc, end_utc):
        self.history_deals_calls.append((symbol, start_utc, end_utc))
        return list(self.history_deals_result)


def _config():
    return MT5ConnectionConfig(
        login=123,
        password="secret",
        server="Example",
        symbol="XAUUSD.vx",
        volume=0.7,
        max_entry_distance_points=20.0,
        min_stop_distance_price=0.0,
        min_stop_spread_multiple=0.0,
    )


def _pair():
    broker = FakeBroker()
    return build_straddle_breakout_pair(
        broker.rates,
        broker.symbol_info,
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        now_utc="2026-06-04T12:03:00+00:00",
    )


def test_straddle_executor_validates_pair_in_dry_run_without_placing_orders(tmp_path):
    broker = FakeBroker()
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)
    pair = _pair()

    result = executor.execute_pair(pair, live=False)

    assert result["status"] == "DRY_RUN_PAIR_READY"
    assert len(result["requests"]) == 2
    assert result["requests"][0]["type"] == "BUY_STOP"
    assert result["requests"][0]["comment"] == "BuyStop Straddle"
    assert result["requests"][1]["type"] == "SELL_STOP"
    assert result["requests"][1]["comment"] == "SellStop Straddle"
    assert broker.placed_requests == []
    state = executor.state.load()
    assert state["active_pair"]["dry_run"] is True
    assert state["active_pair"]["buy_ticket"] is None
    assert state["active_pair"]["sell_ticket"] is None


def test_straddle_executor_builds_pair_from_closed_candles_only(tmp_path):
    broker = FakeBroker()
    broker.rates.append(
        {
            "timestamp": "2026-06-04T12:03:00+00:00",
            "open": 4501.0,
            "high": 4508.5,
            "low": 4500.0,
            "close": 4507.0,
            "volume": 100,
        }
    )
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    pair = executor.build_pair(
        StraddleBreakoutConfig(
            symbol="XAUUSD.vx",
            lookback_candles=3,
            max_box_points=8.0,
        )
    )

    assert broker.fetch_calls == [("1m", 4)]
    assert pair.status == "PROPOSED"
    assert pair.box["high"] == 4502.0
    assert pair.box["low"] == 4496.5


def test_straddle_evaluates_entry_candidate_without_mutating_state(tmp_path):
    broker = FakeBroker()
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.evaluate_entry_candidate(
        StraddleBreakoutConfig(
            symbol="XAUUSD.vx",
            lookback_candles=3,
            max_box_points=8.0,
        ),
        now_utc="2026-06-04T12:03:00+00:00",
    )

    assert result["status"] == "PROPOSED"
    assert result["pair"].status == "PROPOSED"
    assert len(result["requests"]) == 2
    assert broker.placed_requests == []
    assert executor.state.load()["active_pair"] is None


def test_straddle_executor_places_two_live_orders_and_records_tickets(tmp_path):
    broker = FakeBroker()
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.execute_pair(_pair(), live=True)

    assert result["status"] == "PAIR_PLACED"
    assert [request["type"] for request in broker.placed_requests] == [
        "BUY_STOP",
        "SELL_STOP",
    ]
    state = executor.state.load()["active_pair"]
    assert state["dry_run"] is False
    assert state["buy_ticket"] == 101
    assert state["sell_ticket"] == 202


def test_straddle_result_and_journal_include_account_safety(tmp_path):
    broker = FakeBroker()
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.execute_pair(_pair(), live=True)

    assert result["account_safety"] == {
        "require_demo": True,
        "trade_mode": "DEMO",
        "passed": True,
        "reason": None,
    }
    journal_path = tmp_path / "XAUUSD.vx" / "execution_journal" / "mt5_events.jsonl"
    events = [
        json.loads(line)
        for line in journal_path.read_text(encoding="utf-8").splitlines()
    ]
    connected = events[0]
    assert connected["event_type"] == "STRADDLE_CONNECTED"
    assert connected["payload"]["account_safety"]["trade_mode"] == "DEMO"


def test_straddle_live_order_skips_when_account_safety_fails(tmp_path):
    broker = FakeBroker()
    broker.account = {"login": 123, "trade_mode_label": "REAL"}
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.execute_pair(_pair(), live=True)

    assert result["status"] == "STRADDLE_SKIPPED_ACCOUNT_SAFETY"
    assert result["account_safety"]["passed"] is False
    assert broker.placed_requests == []


def test_straddle_executor_cancels_first_order_when_second_live_order_fails(tmp_path):
    broker = FakeBroker()
    broker.place_results = [
        {"ok": True, "order": 101, "retcode": 10009, "comment": "buy ok"},
        {"ok": False, "order": None, "retcode": 10030, "comment": "sell rejected"},
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.execute_pair(_pair(), live=True)

    assert result["status"] == "PAIR_REJECTED_ROLLBACK"
    assert broker.cancelled == [101]
    assert executor.state.load()["active_pair"] is None


def test_straddle_watch_once_clears_triggered_live_pair_before_building_new_pair(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 333,
            "symbol": "XAUUSD.vx",
            "side": "BUY",
            "entry_price": 4502.0,
            "stop_loss": 4496.0,
            "take_profit": 4511.0,
            "current_price": 4504.0,
        }
    ]
    broker.pending_orders = [{"ticket": 202, "symbol": "XAUUSD.vx"}]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)
    executor.state.save(
        {
            "symbol": "XAUUSD.vx",
            "active_pair": {
                "dry_run": False,
                "buy_ticket": 101,
                "sell_ticket": 202,
                "placed_at_utc": "2026-06-04T12:00:00+00:00",
                "cancel_after_utc": "2026-06-04T12:03:00+00:00",
                "pair": _pair().model_dump(mode="json"),
                "requests": [],
            },
        }
    )

    result = executor.watch_once(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        now_utc="2026-06-04T12:02:00+00:00",
    )

    assert result["status"] == "PAIR_RESOLVED"
    assert broker.cancelled == [202]
    assert executor.state.load()["active_pair"] is None
    assert broker.placed_requests == []


def test_straddle_position_manager_moves_buy_stop_to_break_even(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 333,
            "symbol": "XAUUSD.vx",
            "side": "BUY",
            "entry_price": 4500.0,
            "stop_loss": 4494.0,
            "take_profit": 4509.0,
            "current_price": 4503.2,
        }
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.manage_open_positions(
        mt5_straddle.StraddleExitManagementConfig(
            break_even_trigger_points=3.0,
            break_even_lock_points=0.3,
            trailing_trigger_points=5.0,
            trailing_distance_points=2.0,
            early_loss_exit_points=4.0,
            scalp_profit_points=0.0,
        )
    )

    assert result["status"] == "POSITION_STOP_MOVED"
    assert result["actions"][0]["reason"] == "BREAK_EVEN"
    assert broker.modified_stops == [(333, 4500.3, 4509.0)]
    assert broker.closed_positions == []


def test_straddle_position_manager_trails_sell_stop_after_profit_expands(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 444,
            "symbol": "XAUUSD.vx",
            "side": "SELL",
            "entry_price": 4500.0,
            "stop_loss": 4506.0,
            "take_profit": 4491.0,
            "current_price": 4494.5,
        }
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.manage_open_positions(
        mt5_straddle.StraddleExitManagementConfig(
            break_even_trigger_points=3.0,
            break_even_lock_points=0.3,
            trailing_trigger_points=5.0,
            trailing_distance_points=2.0,
            early_loss_exit_points=4.0,
            scalp_profit_points=0.0,
        )
    )

    assert result["status"] == "POSITION_STOP_MOVED"
    assert result["actions"][0]["reason"] == "TRAILING_STOP"
    assert broker.modified_stops == [(444, 4496.5, 4491.0)]
    assert broker.closed_positions == []


def test_straddle_position_manager_closes_early_adverse_position(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 555,
            "symbol": "XAUUSD.vx",
            "side": "BUY",
            "entry_price": 4500.0,
            "stop_loss": 4494.0,
            "take_profit": 4509.0,
            "current_price": 4495.8,
        }
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.manage_open_positions(
        mt5_straddle.StraddleExitManagementConfig(early_loss_exit_points=4.0)
    )

    assert result["status"] == "POSITION_CLOSED_EARLY"
    assert result["actions"][0]["reason"] == "EARLY_LOSS_EXIT"
    assert broker.closed_positions[0][0]["ticket"] == 555
    assert broker.modified_stops == []


def test_straddle_position_manager_closes_scalp_profit_before_break_even(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 666,
            "symbol": "XAUUSD.vx",
            "side": "BUY",
            "entry_price": 4500.0,
            "stop_loss": 4494.0,
            "take_profit": 4509.0,
            "current_price": 4501.6,
        }
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.manage_open_positions(
        mt5_straddle.StraddleExitManagementConfig(
            scalp_profit_points=1.5,
            break_even_trigger_points=1.0,
            break_even_lock_points=0.2,
        )
    )

    assert result["status"] == "POSITION_CLOSED_SCALP"
    assert result["actions"][0]["reason"] == "SCALP_PROFIT_EXIT"
    assert broker.closed_positions[0][0]["ticket"] == 666
    assert broker.modified_stops == []


def test_straddle_watch_once_manages_open_position_before_building_pair(tmp_path):
    broker = FakeBroker()
    broker.positions = [
        {
            "ticket": 333,
            "symbol": "XAUUSD.vx",
            "side": "BUY",
            "entry_price": 4500.0,
            "stop_loss": 4494.0,
            "take_profit": 4509.0,
            "current_price": 4503.2,
        }
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.watch_once(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        exit_management=mt5_straddle.StraddleExitManagementConfig(
            break_even_trigger_points=3.0,
            break_even_lock_points=0.3,
            scalp_profit_points=0.0,
        ),
    )

    assert result["status"] == "POSITION_STOP_MOVED"
    assert broker.modified_stops == [(333, 4500.3, 4509.0)]
    assert broker.fetch_calls == []
    assert broker.placed_requests == []


def _closed_trade(position_id, profit, *, ticket=None, exit_ticket=None):
    entry_ticket = ticket or position_id
    close_ticket = exit_ticket or (entry_ticket + 1)
    return [
        {
            "ticket": entry_ticket,
            "order": entry_ticket,
            "position_id": position_id,
            "symbol": "XAUUSD.vx",
            "entry": 0,
            "magic": 150015,
            "type": 0,
            "volume": 1.0,
            "price": 4500.0,
            "profit": 0.0,
            "commission": 0.0,
            "swap": 0.0,
            "fee": 0.0,
            "time_utc": "2026-06-05T12:00:00+00:00",
            "comment": "BuyStop Straddle",
        },
        {
            "ticket": close_ticket,
            "order": close_ticket,
            "position_id": position_id,
            "symbol": "XAUUSD.vx",
            "entry": 1,
            "magic": 150015,
            "type": 1,
            "volume": 1.0,
            "price": 4498.0,
            "profit": profit,
            "commission": 0.0,
            "swap": 0.0,
            "fee": 0.0,
            "time_utc": "2026-06-05T12:01:00+00:00",
            "comment": "Straddle early loss exit" if profit < 0 else "Straddle scalp profit exit",
        },
    ]


def test_straddle_watch_once_cools_down_after_two_closed_losses(tmp_path):
    broker = FakeBroker()
    broker.history_deals_result = [
        *_closed_trade(701, -156.0, ticket=1001),
        *_closed_trade(702, -200.0, ticket=2001),
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    result = executor.watch_once(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        now_utc="2026-06-05T12:10:00+00:00",
        entry_regime=mt5_straddle.StraddleEntryRegimeConfig(
            loss_streak_limit=2,
            loss_cooldown_minutes=10,
        ),
    )

    assert result["status"] == "STRADDLE_ENTRY_COOLDOWN"
    assert result["reason"] == "loss streak 2 reached limit 2"
    assert result["cooldown_until_utc"] == "2026-06-05T12:20:00+00:00"
    assert broker.history_deals_calls
    assert broker.fetch_calls == []
    assert broker.placed_requests == []


def test_straddle_watch_once_requires_momentum_after_loss_cooldown(tmp_path):
    broker = FakeBroker()
    broker.history_deals_result = [
        *_closed_trade(701, -156.0, ticket=1001),
        *_closed_trade(702, -200.0, ticket=2001),
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)
    regime = mt5_straddle.StraddleEntryRegimeConfig(
        loss_streak_limit=2,
        loss_cooldown_minutes=10,
        post_cooldown_momentum_body_points=0.8,
        post_cooldown_momentum_breakout_points=0.2,
    )

    first = executor.watch_once(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        now_utc="2026-06-05T12:10:00+00:00",
        entry_regime=regime,
    )
    second = executor.watch_once(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        now_utc="2026-06-05T12:21:00+00:00",
        entry_regime=regime,
    )

    assert first["status"] == "STRADDLE_ENTRY_COOLDOWN"
    assert second["status"] == "STRADDLE_ENTRY_WAIT_MOMENTUM"
    assert second["reason"] == "post-cooldown momentum confirmation not met"
    assert broker.fetch_calls == [("1m", 4)]
    assert broker.placed_requests == []


def test_straddle_watch_once_places_pair_after_cooldown_when_momentum_confirms(
    tmp_path,
):
    broker = FakeBroker()
    broker.rates = [
        {
            "timestamp": "2026-06-04T12:00:00+00:00",
            "open": 4499.0,
            "high": 4500.0,
            "low": 4498.0,
            "close": 4499.0,
            "volume": 100,
        },
        {
            "timestamp": "2026-06-04T12:01:00+00:00",
            "open": 4499.0,
            "high": 4501.0,
            "low": 4498.8,
            "close": 4500.0,
            "volume": 100,
        },
        {
            "timestamp": "2026-06-04T12:02:00+00:00",
            "open": 4500.0,
            "high": 4502.0,
            "low": 4499.7,
            "close": 4501.5,
            "volume": 100,
        },
    ]
    broker.history_deals_result = [
        *_closed_trade(701, -156.0, ticket=1001),
        *_closed_trade(702, -200.0, ticket=2001),
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)
    regime = mt5_straddle.StraddleEntryRegimeConfig(
        loss_streak_limit=2,
        loss_cooldown_minutes=10,
        post_cooldown_momentum_body_points=0.8,
        post_cooldown_momentum_breakout_points=0.2,
    )

    executor.watch_once(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        now_utc="2026-06-05T12:10:00+00:00",
        entry_regime=regime,
    )
    result = executor.watch_once(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        now_utc="2026-06-05T12:21:00+00:00",
        entry_regime=regime,
    )

    assert result["status"] == "PAIR_PLACED"
    assert [request["type"] for request in broker.placed_requests] == [
        "BUY_STOP",
        "SELL_STOP",
    ]


def test_straddle_watch_once_cools_down_after_repeated_wide_boxes(tmp_path):
    broker = FakeBroker()
    broker.rates = [
        {
            "timestamp": "2026-06-04T12:00:00+00:00",
            "open": 4500.0,
            "high": 4505.0,
            "low": 4498.0,
            "close": 4502.0,
            "volume": 100,
        },
        {
            "timestamp": "2026-06-04T12:01:00+00:00",
            "open": 4502.0,
            "high": 4506.0,
            "low": 4499.0,
            "close": 4501.0,
            "volume": 100,
        },
        {
            "timestamp": "2026-06-04T12:02:00+00:00",
            "open": 4501.0,
            "high": 4507.0,
            "low": 4497.0,
            "close": 4500.0,
            "volume": 100,
        },
    ]
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)
    regime = mt5_straddle.StraddleEntryRegimeConfig(
        wide_box_streak_limit=2,
        wide_box_cooldown_minutes=5,
    )
    config = StraddleBreakoutConfig(symbol="XAUUSD.vx", max_box_points=3.0)

    first = executor.watch_once(
        config,
        live=True,
        now_utc="2026-06-05T12:10:00+00:00",
        entry_regime=regime,
    )
    broker.rates[2] = {
        "timestamp": "2026-06-04T12:03:00+00:00",
        "open": 4500.0,
        "high": 4508.0,
        "low": 4496.0,
        "close": 4501.0,
        "volume": 100,
    }
    second = executor.watch_once(
        config,
        live=True,
        now_utc="2026-06-05T12:11:00+00:00",
        entry_regime=regime,
    )

    assert first["status"] == "STRADDLE_NO_TRADE"
    assert second["status"] == "STRADDLE_ENTRY_COOLDOWN"
    assert second["reason"] == "wide box streak 2 reached limit 2"
    assert second["cooldown_until_utc"] == "2026-06-05T12:16:00+00:00"
    assert broker.placed_requests == []


def test_straddle_watch_forever_keeps_polling_until_max_cycles(tmp_path, monkeypatch):
    broker = FakeBroker()
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)
    calls = []
    results = iter(
        [
            {"status": "STRADDLE_NO_TRADE"},
            {"status": "PAIR_PLACED"},
        ]
    )

    monkeypatch.setattr(
        executor,
        "watch_once",
        lambda straddle_config,
        live=False,
        now_utc=None,
        exit_management=None,
        entry_regime=None: calls.append(
            (
                straddle_config.symbol,
                live,
                exit_management is not None,
                entry_regime is not None,
            )
        )
        or next(results),
    )
    sleeps = []
    monkeypatch.setattr(
        "tradingagents.brokers.mt5_straddle.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    result = executor.watch_forever(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        poll_seconds=5,
        max_cycles=2,
    )

    assert result["status"] == "STOPPED_MAX_CYCLES"
    assert result["last_result"]["status"] == "PAIR_PLACED"
    assert calls == [
        ("XAUUSD.vx", True, True, True),
        ("XAUUSD.vx", True, True, True),
    ]
    assert sleeps == [5]


def test_straddle_watch_forever_writes_heartbeat_each_cycle(tmp_path, monkeypatch):
    broker = FakeBroker()
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)

    monkeypatch.setattr(
        executor,
        "watch_once",
        lambda straddle_config,
        live=False,
        now_utc=None,
        exit_management=None,
        entry_regime=None: {
            "status": "PAIR_PLACED"
        },
    )

    result = executor.watch_forever(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        poll_seconds=0,
        max_cycles=1,
    )

    heartbeat_path = result["last_result"]["heartbeat_path"]
    heartbeat = json.loads(open(heartbeat_path, encoding="utf-8").read())
    assert heartbeat["status"] == "PAIR_PLACED"
    assert heartbeat["cycle"] == 1
    assert heartbeat["live"] is True
    assert heartbeat["symbol"] == "XAUUSD.vx"


def test_straddle_heartbeat_contains_trading_mode_and_method(tmp_path, monkeypatch):
    broker = FakeBroker()
    executor = MT5StraddleExecutor(
        _config(),
        tmp_path,
        broker=broker,
        trading_mode="STRADDLE_ONLY",
    )

    monkeypatch.setattr(
        executor,
        "watch_once",
        lambda straddle_config,
        live=False,
        now_utc=None,
        exit_management=None,
        entry_regime=None: {
            "status": "PAIR_PLACED",
        },
    )

    result = executor.watch_forever(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        poll_seconds=0,
        max_cycles=1,
    )

    heartbeat = result["last_result"]
    assert heartbeat["trading_mode"] == "STRADDLE_ONLY"
    assert heartbeat["selected_method"] == "STRADDLE"
    assert heartbeat["selected_profile"] is None
    assert heartbeat["mode_decision"] == "STRADDLE_PAIR_PLACED"


def test_straddle_watch_forever_records_error_and_keeps_polling(tmp_path, monkeypatch):
    broker = FakeBroker()
    executor = MT5StraddleExecutor(_config(), tmp_path, broker=broker)
    results = iter([RuntimeError("mt5 unavailable"), {"status": "STRADDLE_NO_TRADE"}])
    sleeps = []

    def watch_once(
        straddle_config,
        live=False,
        now_utc=None,
        exit_management=None,
        entry_regime=None,
    ):
        item = next(results)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(executor, "watch_once", watch_once)
    monkeypatch.setattr(
        "tradingagents.brokers.mt5_straddle.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    result = executor.watch_forever(
        StraddleBreakoutConfig(symbol="XAUUSD.vx"),
        live=True,
        poll_seconds=5,
        max_cycles=2,
    )

    assert result["status"] == "STOPPED_MAX_CYCLES"
    assert result["last_result"]["status"] == "STRADDLE_NO_TRADE"
    assert sleeps == [5]
