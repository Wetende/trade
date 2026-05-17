"""Price-action playbook detection tools.

This first refactor creates the stable tool contract. The mathematical
detectors intentionally return no setups for now; the next pass will replace
the placeholder bodies with tested OHLC pattern detection.
"""

from __future__ import annotations

import json
from typing import Annotated, Any, Dict, List

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


def calculate_support_resistance(*_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
    """Placeholder for swing-high/swing-low S/R level detection."""
    return []


def detect_breakouts(*_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
    """Placeholder for decisive close above resistance or below support."""
    return []


def detect_sr_bounce(*_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
    """Placeholder for rejection candles at support/resistance."""
    return []


def detect_break_and_retest(*_args: Any, **_kwargs: Any) -> List[Dict[str, Any]]:
    """Placeholder for broken level retests and impulse retests."""
    return []


def fetch_intraday_ohlcv(symbol: str, interval: str, period: str = "5d") -> str:
    """Fetch intraday OHLCV text through the configured data vendor."""
    return route_to_vendor("get_intraday_price_data", symbol, period, interval)


def summarize_ohlcv_text(raw_data: str) -> Dict[str, Any]:
    """Return lightweight availability metadata without doing setup math yet."""
    if not isinstance(raw_data, str) or not raw_data.strip():
        return {"available": False, "rows": 0}
    if raw_data.lstrip().startswith("No data found"):
        return {"available": False, "rows": 0}

    data_lines = [
        line
        for line in raw_data.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not data_lines:
        return {"available": False, "rows": 0}

    header = {column.strip().lower() for column in data_lines[0].split(",")}
    required_columns = {"open", "high", "low", "close", "volume"}
    has_ohlcv = required_columns.issubset(header)
    return {"available": has_ohlcv and len(data_lines) > 1, "rows": max(len(data_lines) - 1, 0)}


def build_no_setup_payload(
    symbol: str,
    as_of: str,
    timeframe: str = "15m",
    confirmation_timeframe: str = "30m",
    data_status: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    payload = {
        "symbol": symbol.upper(),
        "as_of": as_of,
        "timeframe": timeframe,
        "confirmation_timeframe": confirmation_timeframe,
        "status": "NO_SETUP",
        "recommendation": "HOLD",
        "setups": [],
        "checklist": {
            "volume_time": "unknown",
            "playbook_setup": "failed",
            "timeframe_correlation": "unknown",
            "clean_range_to_fill": "unknown",
            "candle_closed": "unknown",
            "not_overextended": "unknown",
            "not_last_15_of_4h": "unknown",
            "not_15_min_before_open": "unknown",
            "not_sunday_asian_session": "unknown",
            "confirmation_candle_wicks": "unknown",
            "trading_candle_stop_wick": "unknown",
            "not_activated_last_5_min": "unknown",
        },
        "message": (
            "No mathematical detector has been implemented yet, so no A+ "
            "price-action setup is available. Default to HOLD."
        ),
    }
    if data_status is not None:
        payload["data_status"] = data_status
    return payload


@tool
def get_playbook_setups(
    symbol: Annotated[str, "Ticker symbol to analyze"],
    as_of: Annotated[str, "Analysis timestamp in market timezone"],
    timeframe: Annotated[str, "Trading timeframe, defaults to 15m"] = "15m",
    confirmation_timeframe: Annotated[str, "Confirmation timeframe, defaults to 30m"] = "30m",
) -> str:
    """Return detected playbook setups for the price-action trader."""
    try:
        trading_data = fetch_intraday_ohlcv(symbol, timeframe)
        confirmation_data = fetch_intraday_ohlcv(symbol, confirmation_timeframe)
        data_status = {
            "trading_timeframe": {
                "interval": timeframe,
                **summarize_ohlcv_text(trading_data),
            },
            "confirmation_timeframe": {
                "interval": confirmation_timeframe,
                **summarize_ohlcv_text(confirmation_data),
            },
        }
    except Exception as exc:
        data_status = {
            "trading_timeframe": {"interval": timeframe, "available": False, "rows": 0},
            "confirmation_timeframe": {
                "interval": confirmation_timeframe,
                "available": False,
                "rows": 0,
            },
            "error": str(exc),
        }

    payload = build_no_setup_payload(
        symbol,
        as_of,
        timeframe,
        confirmation_timeframe,
        data_status=data_status,
    )
    return json.dumps(payload, indent=2, sort_keys=True)
