"""Data vendor routing for price-action OHLC data."""

from .y_finance import get_YFin_data_online, get_YFin_intraday_data


TOOLS_CATEGORIES = {
    "core_stock_apis": {
        "description": "OHLCV price data",
        "tools": ["get_stock_data", "get_intraday_price_data"],
    },
}

VENDOR_METHODS = {
    "get_stock_data": {
        "yfinance": get_YFin_data_online,
    },
    "get_intraday_price_data": {
        "yfinance": get_YFin_intraday_data,
    },
}


def get_category_for_method(method: str) -> str:
    for category, info in TOOLS_CATEGORIES.items():
        if method in info["tools"]:
            return category
    raise ValueError(f"Method '{method}' not found in any category")


def get_vendor(category: str, method: str = None) -> str:
    from .config import get_config

    config = get_config()
    if method:
        tool_vendors = config.get("tool_vendors", {})
        if method in tool_vendors:
            return tool_vendors[method]
    return config.get("data_vendors", {}).get(category, "yfinance")


def route_to_vendor(method: str, *args, **kwargs):
    category = get_category_for_method(method)
    vendor = get_vendor(category, method)
    if method not in VENDOR_METHODS:
        raise ValueError(f"Method '{method}' not supported")
    if vendor not in VENDOR_METHODS[method]:
        raise ValueError(f"Vendor '{vendor}' is not supported for '{method}'")
    return VENDOR_METHODS[method][vendor](*args, **kwargs)
