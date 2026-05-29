from tradingagents.agents.price_action.backtest import replay_backtest, summarize_backtest
from tradingagents.agents.price_action.candles import parse_ohlcv_text


def test_summarize_backtest_reports_core_metrics():
    trades = [
        {
            "result_r": -1.0,
            "setup": "Break and Retest",
            "session": "london",
            "zone_timeframe": "4h",
        },
        {
            "result_r": 3.0,
            "setup": "Break and Retest",
            "session": "new_york",
            "zone_timeframe": "1h",
        },
        {
            "result_r": 4.0,
            "setup": "Support/Resistance Bounce",
            "session": "new_york",
            "zone_timeframe": "1d",
        },
    ]

    summary = summarize_backtest(trades)

    assert summary["trade_count"] == 3
    assert summary["win_rate"] == 66.67
    assert summary["average_win_r"] == 3.5
    assert summary["average_loss_r"] == -1.0
    assert summary["net_r"] == 6.0


def test_summarize_backtest_handles_no_trades():
    summary = summarize_backtest([])

    assert summary["trade_count"] == 0
    assert summary["win_rate"] == 0.0
    assert summary["average_win_r"] == 0.0
    assert summary["average_loss_r"] == 0.0
    assert summary["net_r"] == 0


def test_replay_backtest_simulates_limit_entry_to_take_profit():
    def fake_analyzer(*args, **kwargs):
        return {
            "status": "SETUP_FOUND",
            "recommendation": "BUY",
            "setups": [
                {
                    "name": "Break and Retest",
                    "direction": "BUY",
                    "entry_price": 100.0,
                    "stop_loss": 99.0,
                    "take_profit": 103.0,
                    "risk_reward": 3.0,
                    "zone": {"timeframe": "4h"},
                }
            ],
            "market_context": {},
        }

    future = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:30:00,101,101.2,99.8,100.5,1000\n"
        "2026-05-18 08:45:00,100.5,103.2,100.1,103,1000"
    )

    result = replay_backtest(
        "XAUUSD",
        [
            {
                "as_of": "2026-05-18 08:30",
                "timeframe_data": {},
                "future_15m": future,
                "session": "new_york",
            }
        ],
        analyzer=fake_analyzer,
    )

    assert result["signals"] == 1
    assert result["summary"]["trade_count"] == 1
    assert result["summary"]["net_r"] == 3.0
    assert result["trades"][0]["result_r"] == 3.0
    assert result["trades"][0]["status"] == "TAKE_PROFIT"


def test_replay_backtest_cancels_untriggered_limit_order():
    def fake_analyzer(*args, **kwargs):
        return {
            "status": "SETUP_FOUND",
            "recommendation": "SELL",
            "setups": [
                {
                    "name": "Support/Resistance Bounce",
                    "direction": "SELL",
                    "entry_price": 100.0,
                    "stop_loss": 101.0,
                    "take_profit": 97.0,
                    "risk_reward": 3.0,
                    "zone": {"timeframe": "1h"},
                }
            ],
            "market_context": {},
        }

    future = parse_ohlcv_text(
        "Datetime,Open,High,Low,Close,Volume\n"
        "2026-05-18 08:30:00,99,99.5,98.5,99.2,1000"
    )

    result = replay_backtest(
        "XAUUSD",
        [{"as_of": "2026-05-18 08:30", "timeframe_data": {}, "future_15m": future}],
        analyzer=fake_analyzer,
    )

    assert result["signals"] == 1
    assert result["cancelled_orders"] == 1
    assert result["summary"]["trade_count"] == 0
