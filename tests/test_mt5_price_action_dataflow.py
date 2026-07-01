from tradingagents.agents.price_action.models import Candle
from tradingagents.dataflows.mt5_price_action import fetch_mt5_price_action_snapshot


class FakeBroker:
    def __init__(self):
        self.calls = []
        self.closed_calls = []

    def fetch_rates(self, timeframe, count):
        self.calls.append((timeframe, count))
        return [
            {
                "timestamp": "2026-06-02T19:00:00+00:00",
                "open": 4500.0,
                "high": 4501.0,
                "low": 4499.0,
                "close": 4500.5,
                "volume": 100.0,
            },
            {
                "timestamp": "2026-06-02T19:15:00+00:00",
                "open": 4500.5,
                "high": 4502.0,
                "low": 4500.0,
                "close": 4501.5,
                "volume": 120.0,
            },
        ]

    def fetch_closed_rates(self, timeframe, count):
        self.closed_calls.append((timeframe, count))
        return [
            {
                "timestamp": "2026-06-02T19:00:00+00:00",
                "open": 4500.0,
                "high": 4501.0,
                "low": 4499.0,
                "close": 4500.5,
                "volume": 100.0,
                "spread": 3,
                "real_volume": 0,
            },
            {
                "timestamp": "2026-06-02T19:15:00+00:00",
                "open": 4500.5,
                "high": 4502.0,
                "low": 4500.0,
                "close": 4501.5,
                "volume": 120.0,
                "spread": 4,
                "real_volume": 0,
            },
        ]

    def current_symbol_snapshot(self):
        return {
            "symbol": {"name": "XAUUSD", "bid": 4501.0, "ask": 4501.2, "spread": 20},
            "tick": {"time": 1779614160, "bid": 4501.0, "ask": 4501.2},
        }


class FutureClockFakeBroker(FakeBroker):
    def __init__(self, *, tick_time_utc, latest_m1_timestamp):
        super().__init__()
        self.tick_time_utc = tick_time_utc
        self.latest_m1_timestamp = latest_m1_timestamp

    def fetch_closed_rates(self, timeframe, count):
        self.closed_calls.append((timeframe, count))
        return [
            {
                "timestamp": self.latest_m1_timestamp,
                "open": 4500.0,
                "high": 4501.0,
                "low": 4499.0,
                "close": 4500.5,
                "volume": 100.0,
                "spread": 3,
                "real_volume": 0,
            }
        ]

    def current_symbol_snapshot(self):
        return {
            "symbol": {"name": "XAUUSD", "bid": 4501.0, "ask": 4501.2, "spread": 20},
            "tick": {
                "time_utc": self.tick_time_utc,
                "bid": 4501.0,
                "ask": 4501.2,
            },
        }


def test_fetch_mt5_price_action_snapshot_uses_existing_shape():
    broker = FakeBroker()

    snapshot = fetch_mt5_price_action_snapshot(
        broker,
        as_of="2026-06-02T19:16:00-04:00",
        market_timezone="America/New_York",
    )

    assert broker.calls == []
    assert broker.closed_calls == [
        ("1d", 260),
        ("1h", 1200),
        ("30m", 500),
        ("15m", 1000),
        ("3m", 1200),
        ("1m", 1500),
    ]
    assert set(snapshot.candles) == {"1d", "4h", "1h", "30m", "15m", "3m", "1m"}
    assert isinstance(snapshot.candles["15m"][0], Candle)
    assert snapshot.data_status["timeframes"]["15m"]["rows"] == 2
    assert snapshot.data_status["timeframes"]["1m"]["available"] is True
    assert snapshot.data_status["timeframes"]["3m"]["available"] is True
    assert snapshot.market_metadata["symbol"]["name"] == "XAUUSD"
    assert snapshot.market_metadata["tick"]["bid"] == 4501.0


def test_mt5_snapshot_uses_tick_time_for_candle_freshness():
    broker = FutureClockFakeBroker(
        tick_time_utc="2026-07-01T21:55:00+00:00",
        latest_m1_timestamp="2026-07-01T21:54:00+00:00",
    )

    snapshot = fetch_mt5_price_action_snapshot(
        broker,
        as_of="2026-07-01T17:40:00-04:00",
        market_timezone="America/New_York",
    )

    assert snapshot.data_status["healthy"] is True
    assert snapshot.data_status["timeframes"]["1m"]["latest_age_minutes"] == 1
    assert snapshot.data_status["reference_source"] == "mt5_tick"
