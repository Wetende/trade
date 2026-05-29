from datetime import datetime
import time
from typing import Annotated

import yfinance as yf


def _history_with_retries(
    ticker,
    *,
    attempts: int = 3,
    delay_seconds: float = 0.5,
    **kwargs,
):
    last_data = None
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            data = ticker.history(**kwargs)
            last_data = data
            if not data.empty:
                return data, attempt, None
        except Exception as exc:
            last_error = exc
        if attempt < attempts:
            time.sleep(delay_seconds)
    if last_error is not None and last_data is None:
        raise last_error
    return last_data, attempts, last_error


def _format_history(symbol: str, data, source_note: str, attempts: int = 1) -> str:
    if data.empty:
        return f"No data found for symbol '{symbol}' ({source_note}, attempts={attempts})"

    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    numeric_columns = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]
    for col in numeric_columns:
        if col in data.columns:
            data[col] = data[col].round(4)

    header = f"# OHLCV data for {symbol.upper()} ({source_note})\n"
    header += f"# Total records: {len(data)}\n"
    header += f"# Data retrieved on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    header += f"# yfinance attempts: {attempts}\n"
    return header + data.to_csv()


def get_YFin_data_online(
    symbol: Annotated[str, "ticker symbol"],
    start_date: Annotated[str, "Start date in yyyy-mm-dd format"],
    end_date: Annotated[str, "End date in yyyy-mm-dd format"],
):
    datetime.strptime(start_date, "%Y-%m-%d")
    datetime.strptime(end_date, "%Y-%m-%d")
    ticker = yf.Ticker(symbol.upper())
    data, attempts, _error = _history_with_retries(
        ticker,
        start=start_date,
        end=end_date,
    )
    return _format_history(symbol, data, f"{start_date} to {end_date}", attempts=attempts)


def get_YFin_intraday_data(
    symbol: Annotated[str, "ticker symbol"],
    period: Annotated[str, "yfinance lookback period, e.g. 5d"] = "5d",
    interval: Annotated[str, "yfinance interval, e.g. 15m"] = "15m",
):
    ticker = yf.Ticker(symbol.upper())
    data, attempts, _error = _history_with_retries(
        ticker,
        period=period,
        interval=interval,
    )
    return _format_history(
        symbol,
        data,
        f"period={period}, interval={interval}",
        attempts=attempts,
    )
