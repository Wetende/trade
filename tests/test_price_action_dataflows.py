from tradingagents.dataflows.price_action import (
    fetch_price_action_snapshot,
    fetch_price_action_timeframes,
)


def test_fetches_all_required_timeframes_and_resamples_4h(monkeypatch):
    calls = []

    def fake_route(method, symbol, period, interval):
        calls.append((method, symbol, period, interval))
        return "\n".join(
            [
                "Datetime,Open,High,Low,Close,Volume",
                "2026-05-18 00:00:00,100,102,99,101,10",
                "2026-05-18 01:00:00,101,103,100,102,20",
                "2026-05-18 02:00:00,102,105,101,104,30",
                "2026-05-18 03:00:00,104,106,103,105,40",
            ]
        )

    monkeypatch.setattr(
        "tradingagents.dataflows.price_action.route_to_vendor",
        fake_route,
    )

    result = fetch_price_action_timeframes("XAUUSD")

    assert set(result) == {"1d", "4h", "1h", "30m", "15m"}
    assert calls == [
        ("get_intraday_price_data", "XAUUSD", "1y", "1d"),
        ("get_intraday_price_data", "XAUUSD", "60d", "1h"),
        ("get_intraday_price_data", "XAUUSD", "10d", "30m"),
        ("get_intraday_price_data", "XAUUSD", "10d", "15m"),
    ]
    assert result["4h"][0].open == 100
    assert result["4h"][0].close == 105


def test_keeps_all_timeframe_keys_when_one_vendor_response_has_no_data(monkeypatch):
    def fake_route(method, symbol, period, interval):
        if interval == "30m":
            return f"No data found for symbol '{symbol}'"
        return "\n".join(
            [
                "Datetime,Open,High,Low,Close,Volume",
                "2026-05-18 00:00:00,100,102,99,101,10",
                "2026-05-18 01:00:00,101,103,100,102,20",
                "2026-05-18 02:00:00,102,105,101,104,30",
                "2026-05-18 03:00:00,104,106,103,105,40",
            ]
        )

    monkeypatch.setattr(
        "tradingagents.dataflows.price_action.route_to_vendor",
        fake_route,
    )

    result = fetch_price_action_timeframes("XAUUSD")

    assert set(result) == {"1d", "4h", "1h", "30m", "15m"}
    assert all(isinstance(candles, list) for candles in result.values())
    assert result["30m"] == []
    assert result["1d"]
    assert result["1h"]
    assert result["4h"]
    assert result["15m"]


def test_fetch_price_action_snapshot_includes_data_status(monkeypatch):
    def fake_route(method, symbol, period, interval):
        return "\n".join(
            [
                "Datetime,Open,High,Low,Close,Volume",
                "2026-05-18 00:00:00,100,102,99,101,10",
                "2026-05-18 01:00:00,101,103,100,102,20",
                "2026-05-18 02:00:00,102,105,101,104,30",
                "2026-05-18 03:00:00,104,106,103,105,40",
            ]
        )

    monkeypatch.setattr(
        "tradingagents.dataflows.price_action.route_to_vendor",
        fake_route,
    )

    snapshot = fetch_price_action_snapshot(
        "XAUUSD",
        as_of="2026-05-18 03:15",
        market_timezone="America/New_York",
    )

    assert set(snapshot.candles) == {"1d", "4h", "1h", "30m", "15m"}
    assert snapshot.data_status["healthy"] is True
    assert snapshot.data_status["trading_timeframe"]["rows"] == 4
