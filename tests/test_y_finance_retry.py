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


def test_yfinance_configures_cache_location(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setenv("TRADINGAGENTS_YFINANCE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        y_finance.yf,
        "set_tz_cache_location",
        lambda path: calls.append(("tz", path)),
    )
    monkeypatch.setattr(
        y_finance.yf.cache,
        "set_cache_location",
        lambda path: calls.append(("cache", path)),
    )

    cache_dir = y_finance.configure_yfinance_runtime()

    assert cache_dir == tmp_path
    assert tmp_path.exists()
    assert ("tz", str(tmp_path)) in calls
    assert ("cache", str(tmp_path)) in calls


def test_yfinance_cache_dir_uses_project_cache_env_when_specific_env_absent(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("TRADINGAGENTS_YFINANCE_CACHE_DIR", raising=False)
    monkeypatch.setenv("TRADINGAGENTS_CACHE_DIR", str(tmp_path))

    cache_dir = y_finance._default_yfinance_cache_dir()

    assert cache_dir == tmp_path / "yfinance"


def test_yfinance_cache_dir_uses_home_default_when_env_absent(monkeypatch, tmp_path):
    monkeypatch.delenv("TRADINGAGENTS_YFINANCE_CACHE_DIR", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_CACHE_DIR", raising=False)
    monkeypatch.setattr(y_finance.Path, "home", staticmethod(lambda: tmp_path))

    cache_dir = y_finance._default_yfinance_cache_dir()

    assert cache_dir == tmp_path / ".tradingagents" / "cache" / "yfinance"


def test_yfinance_configure_skips_missing_cache_setter(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setenv("TRADINGAGENTS_YFINANCE_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(
        y_finance.yf,
        "set_tz_cache_location",
        lambda path: calls.append(("tz", path)),
    )
    monkeypatch.setattr(y_finance.yf, "cache", object())

    cache_dir = y_finance.configure_yfinance_runtime()

    assert cache_dir == tmp_path
    assert calls == [("tz", str(tmp_path))]


def test_yfinance_fetch_clears_dead_local_proxy(monkeypatch, tmp_path):
    captured = {}
    fake = FakeTicker([_frame()])

    monkeypatch.setenv("TRADINGAGENTS_YFINANCE_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("https_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("all_proxy", "http://127.0.0.1:9")
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: fake)
    monkeypatch.setattr(y_finance.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(y_finance.yf, "set_tz_cache_location", lambda path: None)
    monkeypatch.setattr(y_finance.yf.cache, "set_cache_location", lambda path: None)

    def history_with_capture(**kwargs):
        captured["HTTP_PROXY"] = y_finance.os.environ.get("HTTP_PROXY")
        captured["HTTPS_PROXY"] = y_finance.os.environ.get("HTTPS_PROXY")
        captured["ALL_PROXY"] = y_finance.os.environ.get("ALL_PROXY")
        captured["http_proxy"] = y_finance.os.environ.get("http_proxy")
        captured["https_proxy"] = y_finance.os.environ.get("https_proxy")
        captured["all_proxy"] = y_finance.os.environ.get("all_proxy")
        return _frame()

    fake.history = history_with_capture

    text = y_finance.get_YFin_intraday_data("GC=F", period="10d", interval="15m")

    assert "No data found" not in text
    assert captured == {
        "HTTP_PROXY": None,
        "HTTPS_PROXY": None,
        "ALL_PROXY": None,
        "http_proxy": None,
        "https_proxy": None,
        "all_proxy": None,
    }


def test_yfinance_fetch_preserves_legitimate_proxy_values(monkeypatch, tmp_path):
    captured = {}
    fake = FakeTicker([_frame()])

    monkeypatch.setenv("TRADINGAGENTS_YFINANCE_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("http_proxy", raising=False)
    monkeypatch.delenv("https_proxy", raising=False)
    monkeypatch.delenv("all_proxy", raising=False)
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://127.0.0.1:9")
    monkeypatch.setattr(y_finance.yf, "Ticker", lambda symbol: fake)
    monkeypatch.setattr(y_finance.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(y_finance.yf, "set_tz_cache_location", lambda path: None)
    monkeypatch.setattr(y_finance.yf.cache, "set_cache_location", lambda path: None)

    def history_with_capture(**kwargs):
        captured["HTTP_PROXY"] = y_finance.os.environ.get("HTTP_PROXY")
        captured["HTTPS_PROXY"] = y_finance.os.environ.get("HTTPS_PROXY")
        captured["ALL_PROXY"] = y_finance.os.environ.get("ALL_PROXY")
        captured["http_proxy"] = y_finance.os.environ.get("http_proxy")
        captured["https_proxy"] = y_finance.os.environ.get("https_proxy")
        captured["all_proxy"] = y_finance.os.environ.get("all_proxy")
        return _frame()

    fake.history = history_with_capture

    text = y_finance.get_YFin_intraday_data("GC=F", period="10d", interval="15m")

    assert "No data found" not in text
    assert captured == {
        "HTTP_PROXY": None,
        "HTTPS_PROXY": "http://127.0.0.1:8080",
        "ALL_PROXY": "socks5://127.0.0.1:9",
        "http_proxy": None,
        "https_proxy": "http://127.0.0.1:8080",
        "all_proxy": "socks5://127.0.0.1:9",
    }


def test_yfinance_market_timezone_does_not_apply_global_override_to_generic_symbol(
    monkeypatch,
):
    monkeypatch.setenv("TRADINGAGENTS_MARKET_TIMEZONE", "America/New_York")

    assert y_finance._market_timezone_for_symbol("7203.T") is None


def test_yfinance_formats_futures_timezone_aware_index_in_new_york_timezone():
    index = pd.DatetimeIndex(["2026-05-29 16:45:00+00:00"])
    data = pd.DataFrame(
        {
            "Open": [1.0],
            "High": [2.0],
            "Low": [0.5],
            "Close": [1.5],
            "Volume": [100],
        },
        index=index,
    )

    text = y_finance._format_history(
        "GC=F",
        data,
        "period=10d, interval=15m",
        market_timezone="America/New_York",
    )

    assert "2026-05-29 12:45:00" in text
    assert "2026-05-29 16:45:00" not in text


def test_yfinance_format_preserves_local_time_without_market_timezone():
    index = pd.DatetimeIndex(["2026-05-29 16:45:00+09:00"])
    data = pd.DataFrame(
        {
            "Open": [1.0],
            "High": [2.0],
            "Low": [0.5],
            "Close": [1.5],
            "Volume": [100],
        },
        index=index,
    )

    text = y_finance._format_history(
        "7203.T",
        data,
        "period=10d, interval=15m",
        market_timezone=None,
    )

    assert "2026-05-29 16:45:00" in text
    assert "2026-05-29 03:45:00" not in text


def test_yfinance_format_does_not_mutate_original_dataframe_index():
    index = pd.DatetimeIndex(["2026-05-29 16:45:00+00:00"])
    data = pd.DataFrame(
        {
            "Open": [1.12345],
            "High": [2.12345],
            "Low": [0.51234],
            "Close": [1.51234],
            "Volume": [100],
        },
        index=index,
    )
    original_index = data.index.copy()

    y_finance._format_history(
        "GC=F",
        data,
        "period=10d, interval=15m",
        market_timezone="America/New_York",
    )

    pd.testing.assert_index_equal(data.index, original_index)
