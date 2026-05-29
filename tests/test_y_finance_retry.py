import pandas as pd

from tradingagents.dataflows import y_finance


class FakeTicker:
    def __init__(self, frames):
        self.frames = list(frames)
        self.calls = 0

    def history(self, **kwargs):
        self.calls += 1
        return self.frames.pop(0)


def _frame():
    index = pd.DatetimeIndex(["2026-05-29 08:00:00"])
    return pd.DataFrame(
        {
            "Open": [1.0],
            "High": [2.0],
            "Low": [0.5],
            "Close": [1.5],
            "Volume": [100],
        },
        index=index,
    )


def test_yfinance_intraday_retries_empty_response(monkeypatch):
    fake = FakeTicker([pd.DataFrame(), _frame()])
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: fake)
    monkeypatch.setattr(y_finance.time, "sleep", lambda seconds: None)

    text = y_finance.get_YFin_intraday_data("GC=F", period="10d", interval="15m")

    assert fake.calls == 2
    assert "# yfinance attempts: 2" in text
    assert "No data found" not in text


def test_yfinance_intraday_returns_no_data_after_all_attempts(monkeypatch):
    fake = FakeTicker([pd.DataFrame(), pd.DataFrame(), pd.DataFrame()])
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: fake)
    monkeypatch.setattr(y_finance.time, "sleep", lambda seconds: None)

    text = y_finance.get_YFin_intraday_data("GC=F", period="10d", interval="15m")

    assert fake.calls == 3
    assert "No data found for symbol 'GC=F'" in text
    assert "attempts=3" in text
