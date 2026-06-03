from tradingagents.agents.price_action.models import Candle
from tradingagents.dataflows.mt5_price_action import fetch_mt5_price_action_snapshot


class FakeBroker:
    def __init__(self):
        self.calls = []

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


def test_fetch_mt5_price_action_snapshot_uses_existing_shape():
    broker = FakeBroker()

    snapshot = fetch_mt5_price_action_snapshot(
        broker,
        as_of="2026-06-02T19:16:00-04:00",
        market_timezone="America/New_York",
    )

    assert broker.calls == [
        ("1d", 260),
        ("1h", 1200),
        ("30m", 500),
        ("15m", 1000),
    ]
    assert set(snapshot.candles) == {"1d", "4h", "1h", "30m", "15m"}
    assert isinstance(snapshot.candles["15m"][0], Candle)
    assert snapshot.data_status["timeframes"]["15m"]["rows"] == 2
