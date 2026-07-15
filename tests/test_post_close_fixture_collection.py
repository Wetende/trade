from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from tradingagents.agents.price_action.post_close_fixture_collection import (
    collect_post_close_fixture,
    parse_evidence_timestamp,
)
from tradingagents.brokers.mt5 import MT5BrokerError


class StubReadOnlyBroker:
    def __init__(self, *, allow_real_orders=False, trade_mode="DEMO"):
        self.config = SimpleNamespace(
            symbol="XAUUSD",
            allow_real_orders=allow_real_orders,
            require_demo_account=True,
        )
        self.connection = {
            "account": {"trade_mode_label": trade_mode},
        }
        self.calls = []
        start = datetime(2026, 6, 14, 22, 0, tzinfo=timezone.utc)
        self.candles = [
            {
                "timestamp": (start + timedelta(minutes=index)).isoformat(),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 1.0,
            }
            for index in range(181)
        ]
        self.ticks = [
            {
                "time": datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc).isoformat(),
                "bid": 1.0,
                "ask": 1.1,
            },
            {
                "time": datetime(2026, 6, 15, 1, 0, tzinfo=timezone.utc).isoformat(),
                "bid": 1.1,
                "ask": 1.2,
            },
        ]

    def fetch_closed_rates_range(self, timeframe, start, end):
        self.calls.append(("rates", timeframe, start, end))
        return self.candles

    def fetch_ticks_range(self, start, end):
        self.calls.append(("ticks", start, end))
        return self.ticks

    def open_orders(self, symbol):
        self.calls.append(("orders", symbol))
        return []

    def open_positions(self, symbol):
        self.calls.append(("positions", symbol))
        return []


def test_collect_post_close_fixture_retains_exact_context_and_exclusive_end():
    broker = StubReadOnlyBroker()
    start = datetime(2026, 6, 15, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 15, 1, 0, tzinfo=timezone.utc)

    result = collect_post_close_fixture(
        broker,
        connection=broker.connection,
        start_utc=start,
        end_utc=end,
        context_candles=60,
    )

    assert result["broker_mutation_enabled"] is False
    assert result["collection"]["read_only"] is True
    assert len(result["candles"]) == 120
    assert result["candles"][0]["timestamp"] == "2026-06-14T23:00:00+00:00"
    assert result["candles"][-1]["timestamp"] == "2026-06-15T00:59:00+00:00"
    assert [tick["time"] for tick in result["ticks"]] == [
        "2026-06-15T00:00:00+00:00"
    ]
    assert all(call[0] != "order_send" for call in broker.calls)


def test_collect_post_close_fixture_refuses_real_order_capable_config():
    broker = StubReadOnlyBroker(allow_real_orders=True)

    with pytest.raises(MT5BrokerError, match="real orders disabled"):
        collect_post_close_fixture(
            broker,
            connection=broker.connection,
            start_utc=datetime(2026, 6, 15, tzinfo=timezone.utc),
            end_utc=datetime(2026, 6, 16, tzinfo=timezone.utc),
        )


def test_collect_post_close_fixture_requires_demo_account():
    broker = StubReadOnlyBroker(trade_mode="REAL")

    with pytest.raises(MT5BrokerError, match="demo account required"):
        collect_post_close_fixture(
            broker,
            connection=broker.connection,
            start_utc=datetime(2026, 6, 15, tzinfo=timezone.utc),
            end_utc=datetime(2026, 6, 16, tzinfo=timezone.utc),
        )


def test_parse_evidence_timestamp_requires_timezone():
    with pytest.raises(MT5BrokerError, match="timezone-aware"):
        parse_evidence_timestamp("2026-06-15T00:00:00")
