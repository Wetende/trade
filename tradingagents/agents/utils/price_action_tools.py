"""Price-action playbook detection tools.

The LLM should explain the trade plan, not infer chart structure from raw
candles. This module owns the deterministic parts of the playbook: session
filters, support/resistance zones, M30/M15 correlation, wick rejection,
breakout/retest validation, and basic risk/reward math.
"""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import datetime, time, timedelta
from typing import Annotated, Any, Dict, List
from zoneinfo import ZoneInfo

from langchain_core.tools import tool

from tradingagents.agents.price_action.engine import (
    analyze_playbook as analyze_top_down_playbook,
)
from tradingagents.dataflows.interface import route_to_vendor
from tradingagents.dataflows.price_action import fetch_price_action_timeframes


PASS = "passed"
FAIL = "failed"
UNKNOWN = "unknown"


def _float(value: Any) -> float:
    if value is None or value == "":
        return math.nan
    return float(value)


def _round_price(value: float) -> float:
    return round(float(value), 4)


def _normalize_candle(row: Dict[str, Any]) -> Dict[str, Any] | None:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    timestamp = (
        lowered.get("timestamp")
        or lowered.get("datetime")
        or lowered.get("date")
        or lowered.get("")
    )
    try:
        candle = {
            "timestamp": str(timestamp) if timestamp is not None else "",
            "open": _float(lowered.get("open")),
            "high": _float(lowered.get("high")),
            "low": _float(lowered.get("low")),
            "close": _float(lowered.get("close")),
            "volume": _float(lowered.get("volume", 0)),
        }
    except (TypeError, ValueError):
        return None

    if any(math.isnan(candle[key]) for key in ("open", "high", "low", "close")):
        return None
    return candle


def parse_ohlcv_text(raw_data: str) -> List[Dict[str, Any]]:
    """Parse the repo's CSV-like OHLCV text format into normalized candles."""
    if not isinstance(raw_data, str) or not raw_data.strip():
        return []
    if raw_data.lstrip().startswith("No data found"):
        return []

    data_lines = [
        line
        for line in raw_data.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not data_lines:
        return []

    reader = csv.DictReader(io.StringIO("\n".join(data_lines)))
    candles = []
    for row in reader:
        candle = _normalize_candle(row)
        if candle is not None:
            candles.append(candle)
    return candles


def _candles(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, str):
        return parse_ohlcv_text(data)
    if data is None:
        return []
    candles = []
    for row in data:
        candle = _normalize_candle(row)
        if candle is not None:
            candles.append(candle)
    return candles


def _range(candle: Dict[str, Any]) -> float:
    return max(float(candle["high"]) - float(candle["low"]), 0.0)


def _body_high(candle: Dict[str, Any]) -> float:
    return max(float(candle["open"]), float(candle["close"]))


def _body_low(candle: Dict[str, Any]) -> float:
    return min(float(candle["open"]), float(candle["close"]))


def _upper_wick(candle: Dict[str, Any]) -> float:
    return max(float(candle["high"]) - _body_high(candle), 0.0)


def _lower_wick(candle: Dict[str, Any]) -> float:
    return max(_body_low(candle) - float(candle["low"]), 0.0)


def _is_bullish(candle: Dict[str, Any]) -> bool:
    return float(candle["close"]) > float(candle["open"])


def _is_bearish(candle: Dict[str, Any]) -> bool:
    return float(candle["close"]) < float(candle["open"])


def _wick_ratio(candle: Dict[str, Any], side: str) -> float:
    candle_range = _range(candle)
    if candle_range <= 0:
        return 0.0
    wick = _lower_wick(candle) if side == "lower" else _upper_wick(candle)
    return wick / candle_range


def _atr(candles: List[Dict[str, Any]], period: int = 14) -> float:
    if not candles:
        return 0.0

    ranges = []
    previous_close = None
    for candle in candles:
        high = float(candle["high"])
        low = float(candle["low"])
        if previous_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - previous_close),
                abs(low - previous_close),
            )
        ranges.append(true_range)
        previous_close = float(candle["close"])

    recent = ranges[-period:]
    return sum(recent) / len(recent) if recent else 0.0


def _timeframe_weight(timeframe: str) -> int:
    tf = str(timeframe).lower()
    if tf in {"1d", "d", "daily"}:
        return 5
    if tf in {"4h", "240m"}:
        return 4
    if tf in {"1h", "60m"}:
        return 3
    if tf in {"30m", "m30"}:
        return 2
    return 1


def _default_zone_tolerance(candles: List[Dict[str, Any]], timeframe: str) -> float:
    atr = _atr(candles)
    tf = str(timeframe).lower()
    if tf in {"1d", "d", "daily"}:
        multiplier = 0.30
    elif tf in {"4h", "240m"}:
        multiplier = 0.25
    elif tf in {"1h", "60m"}:
        multiplier = 0.20
    else:
        multiplier = 0.15
    return max(0.5, atr * multiplier)


def _swing_points(
    candles: List[Dict[str, Any]],
    point_type: str,
    lookback: int = 1,
) -> List[Dict[str, Any]]:
    points = []
    if len(candles) < (lookback * 2) + 1:
        return points

    for index in range(lookback, len(candles) - lookback):
        candle = candles[index]
        left = candles[index - lookback : index]
        right = candles[index + 1 : index + 1 + lookback]
        if point_type == "resistance":
            price = float(candle["high"])
            if price > max(float(c["high"]) for c in left) and price >= max(
                float(c["high"]) for c in right
            ):
                points.append({"price": price, "timestamp": candle["timestamp"]})
        else:
            price = float(candle["low"])
            if price < min(float(c["low"]) for c in left) and price <= min(
                float(c["low"]) for c in right
            ):
                points.append({"price": price, "timestamp": candle["timestamp"]})
    return points


def _cluster_points(
    points: List[Dict[str, Any]],
    zone_type: str,
    timeframe: str,
    tolerance: float,
    min_touches: int,
) -> List[Dict[str, Any]]:
    if not points:
        return []

    clusters: List[List[Dict[str, Any]]] = []
    for point in sorted(points, key=lambda item: item["price"]):
        placed = False
        for cluster in clusters:
            midpoint = sum(p["price"] for p in cluster) / len(cluster)
            if abs(point["price"] - midpoint) <= tolerance:
                cluster.append(point)
                placed = True
                break
        if not placed:
            clusters.append([point])

    zones = []
    for cluster in clusters:
        if len(cluster) < min_touches:
            continue
        prices = [point["price"] for point in cluster]
        low = min(prices) - tolerance
        high = max(prices) + tolerance
        touches = len(cluster)
        zones.append(
            {
                "type": zone_type,
                "timeframe": timeframe,
                "low": _round_price(low),
                "high": _round_price(high),
                "midpoint": _round_price((low + high) / 2),
                "touches": touches,
                "score": _timeframe_weight(timeframe) + (touches * 2),
                "source": "swing_cluster",
                "reactions": [
                    {"timestamp": point["timestamp"], "price": _round_price(point["price"])}
                    for point in cluster
                ],
            }
        )
    return zones


def calculate_support_resistance(
    data: Any = None,
    timeframe: str = "30m",
    tolerance: float | None = None,
    min_touches: int = 2,
) -> List[Dict[str, Any]]:
    """Detect support/resistance zones from repeated swing reactions."""
    candles = _candles(data)
    if not candles:
        return []

    zone_tolerance = tolerance
    if zone_tolerance is None:
        zone_tolerance = _default_zone_tolerance(candles, timeframe)

    zones = []
    zones.extend(
        _cluster_points(
            _swing_points(candles, "support"),
            "support",
            timeframe,
            zone_tolerance,
            min_touches,
        )
    )
    zones.extend(
        _cluster_points(
            _swing_points(candles, "resistance"),
            "resistance",
            timeframe,
            zone_tolerance,
            min_touches,
        )
    )
    return sorted(zones, key=lambda zone: zone["score"], reverse=True)


def _touches_zone(candle: Dict[str, Any], zone: Dict[str, Any]) -> bool:
    return float(candle["low"]) <= float(zone["high"]) and float(candle["high"]) >= float(
        zone["low"]
    )


def _stop_buffer(candle: Dict[str, Any]) -> float:
    return max(0.1, _range(candle) * 0.05)


def _risk_setup(
    name: str,
    direction: str,
    zone: Dict[str, Any],
    candle: Dict[str, Any],
    entry_price: float,
    retest_depth: float | None = None,
) -> Dict[str, Any]:
    buffer = _stop_buffer(candle)
    if direction == "BUY":
        stop_loss = float(candle["low"]) - buffer
    else:
        stop_loss = float(candle["high"]) + buffer

    setup = {
        "name": name,
        "direction": direction,
        "zone": zone,
        "entry_price": _round_price(entry_price),
        "stop_loss": _round_price(stop_loss),
        "confirmation_candle": candle,
    }
    if retest_depth is not None:
        setup["retest_depth"] = round(retest_depth, 4)
    return setup


def detect_breakouts(data: Any = None, zones: List[Dict[str, Any]] | None = None) -> List[Dict[str, Any]]:
    """Detect a closed candle breakout beyond support or resistance."""
    candles = _candles(data)
    if not candles or not zones:
        return []

    candle = candles[-1]
    close = float(candle["close"])
    setups = []
    for zone in zones:
        if zone["type"] == "resistance" and close > float(zone["high"]):
            setups.append(
                {
                    "name": "Breakout",
                    "direction": "BUY",
                    "zone": zone,
                    "breakout_close": _round_price(close),
                }
            )
        elif zone["type"] == "support" and close < float(zone["low"]):
            setups.append(
                {
                    "name": "Breakout",
                    "direction": "SELL",
                    "zone": zone,
                    "breakout_close": _round_price(close),
                }
            )
    return sorted(setups, key=lambda setup: setup["zone"]["score"], reverse=True)


def detect_sr_bounce(
    data: Any = None,
    zones: List[Dict[str, Any]] | None = None,
    min_wick_ratio: float = 0.30,
) -> List[Dict[str, Any]]:
    """Detect buy/sell rejection from a support or resistance zone."""
    candles = _candles(data)
    if not candles or not zones:
        return []

    candle = candles[-1]
    setups = []
    for zone in zones:
        if not _touches_zone(candle, zone):
            continue
        if (
            zone["type"] == "support"
            and _wick_ratio(candle, "lower") >= min_wick_ratio
            and float(candle["close"]) > float(zone["midpoint"])
            and (_is_bullish(candle) or float(candle["close"]) > float(zone["high"]))
        ):
            setups.append(
                _risk_setup(
                    "Support/Resistance Bounce",
                    "BUY",
                    zone,
                    candle,
                    float(zone["high"]),
                )
            )
        elif (
            zone["type"] == "resistance"
            and _wick_ratio(candle, "upper") >= min_wick_ratio
            and float(candle["close"]) < float(zone["midpoint"])
            and (_is_bearish(candle) or float(candle["close"]) < float(zone["low"]))
        ):
            setups.append(
                _risk_setup(
                    "Support/Resistance Bounce",
                    "SELL",
                    zone,
                    candle,
                    float(zone["low"]),
                )
            )
    return sorted(setups, key=lambda setup: setup["zone"]["score"], reverse=True)


def detect_break_and_retest(
    data: Any = None,
    zones: List[Dict[str, Any]] | None = None,
    direction: str | None = None,
    min_retest_depth: float = 0.50,
    min_wick_ratio: float = 0.10,
) -> List[Dict[str, Any]]:
    """Detect a valid retest after a broken zone.

    A half-zone retest is acceptable; a full-zone retest is ideal. A candle
    closing back inside the old zone invalidates the setup.
    """
    candles = _candles(data)
    if not candles or not zones:
        return []

    candle = candles[-1]
    setups = []
    allowed = {direction} if direction else {"BUY", "SELL"}
    for zone in zones:
        width = max(float(zone["high"]) - float(zone["low"]), 0.0001)
        if "BUY" in allowed and zone["type"] == "resistance":
            depth = (float(zone["high"]) - float(candle["low"])) / width
            if (
                depth + 1e-9 >= min_retest_depth
                and _wick_ratio(candle, "lower") >= min_wick_ratio
                and float(candle["close"]) > float(zone["high"])
            ):
                setups.append(
                    _risk_setup(
                        "Break and Retest",
                        "BUY",
                        zone,
                        candle,
                        float(zone["high"]),
                        min(depth, 1.0),
                    )
                )
        if "SELL" in allowed and zone["type"] == "support":
            depth = (float(candle["high"]) - float(zone["low"])) / width
            if (
                depth + 1e-9 >= min_retest_depth
                and _wick_ratio(candle, "upper") >= min_wick_ratio
                and float(candle["close"]) < float(zone["low"])
            ):
                setups.append(
                    _risk_setup(
                        "Break and Retest",
                        "SELL",
                        zone,
                        candle,
                        float(zone["low"]),
                        min(depth, 1.0),
                    )
                )
    return sorted(setups, key=lambda setup: setup["zone"]["score"], reverse=True)


def _parse_as_of(as_of: str, market_timezone: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(as_of).replace(" ", "T"))
    except ValueError:
        return None
    try:
        tz = ZoneInfo(market_timezone)
    except Exception:
        tz = ZoneInfo("America/New_York")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def _in_window(current: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= current < end
    return current >= start or current < end


def _minutes_before(dt: datetime, open_time: time) -> int:
    session_open = dt.replace(
        hour=open_time.hour,
        minute=open_time.minute,
        second=0,
        microsecond=0,
    )
    if session_open < dt:
        session_open += timedelta(days=1)
    return int((session_open - dt).total_seconds() // 60)


def evaluate_time_filters(as_of: str, market_timezone: str = "America/New_York") -> Dict[str, str]:
    """Evaluate session gates that can be checked without broker metadata."""
    dt = _parse_as_of(as_of, market_timezone)
    if dt is None:
        return {
            "volume_time": UNKNOWN,
            "not_last_15_of_4h": UNKNOWN,
            "not_15_min_before_open": UNKNOWN,
            "not_sunday_asian_session": UNKNOWN,
        }

    current = dt.time()
    opens = [time(19, 0), time(3, 0), time(8, 0)]
    in_pre_open = any(0 <= _minutes_before(dt, open_time) <= 15 for open_time in opens)
    in_last_15_of_4h = ((dt.hour + 1) % 4 == 0) and dt.minute >= 45
    is_sunday_asian = dt.weekday() == 6 and dt.hour >= 17
    is_monday_early_asian = dt.weekday() == 0 and dt.hour < 3

    in_asian = _in_window(current, time(19, 0), time(23, 59, 59))
    in_london = _in_window(current, time(3, 0), time(11, 0))
    in_new_york = _in_window(current, time(8, 0), time(12, 0))
    in_session = in_asian or in_london or in_new_york

    hard_block = in_pre_open or in_last_15_of_4h or is_sunday_asian or is_monday_early_asian
    return {
        "volume_time": PASS if in_session and not hard_block else FAIL,
        "not_last_15_of_4h": FAIL if in_last_15_of_4h else PASS,
        "not_15_min_before_open": FAIL if in_pre_open else PASS,
        "not_sunday_asian_session": FAIL if is_sunday_asian else PASS,
    }


def _average_recent_range(candles: List[Dict[str, Any]], limit: int = 10) -> float:
    recent = candles[-limit:]
    if not recent:
        return 0.0
    return sum(_range(candle) for candle in recent) / len(recent)


def _is_overextended(candles: List[Dict[str, Any]]) -> bool:
    if not candles:
        return True
    if len(candles) == 1:
        return False
    average_range = _average_recent_range(candles[:-1], 10)
    if average_range <= 0:
        return False
    return _range(candles[-1]) > (average_range * 1.5)


def _has_top_and_bottom_wick(candle: Dict[str, Any]) -> bool:
    return _upper_wick(candle) > 0 and _lower_wick(candle) > 0


def _add_risk_reward(setup: Dict[str, Any], target_rr: float = 3.0) -> Dict[str, Any]:
    direction = setup["direction"]
    entry = float(setup["entry_price"])
    stop = float(setup["stop_loss"])
    risk = abs(entry - stop)
    if risk <= 0:
        setup["risk_reward"] = 0.0
        return setup

    if direction == "BUY":
        take_profit = entry + (risk * target_rr)
    else:
        take_profit = entry - (risk * target_rr)
    reward = abs(take_profit - entry)

    setup["take_profit"] = _round_price(take_profit)
    setup["risk_distance"] = _round_price(risk)
    setup["reward_distance"] = _round_price(reward)
    setup["risk_reward"] = round(reward / risk, 2)
    return setup


def _no_setup_with_context(
    symbol: str,
    as_of: str,
    timeframe: str,
    confirmation_timeframe: str,
    checklist: Dict[str, str],
    zones: List[Dict[str, Any]],
    market_context: Dict[str, Any],
    data_status: Dict[str, Any] | None = None,
    message: str | None = None,
) -> Dict[str, Any]:
    payload = build_no_setup_payload(
        symbol,
        as_of,
        timeframe,
        confirmation_timeframe,
        data_status=data_status,
    )
    payload["checklist"].update(checklist)
    payload["zones"] = zones
    payload["market_context"] = market_context
    if message:
        payload["message"] = message
    return payload


def analyze_playbook(
    symbol: str,
    as_of: str,
    trading_data: Any,
    confirmation_data: Any,
    timeframe: str = "15m",
    confirmation_timeframe: str = "30m",
    market_timezone: str = "America/New_York",
    higher_timeframe_data: Dict[str, Any] | None = None,
    data_status: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Analyze closed M15/M30 candles and return a playbook decision payload."""
    trading_candles = _candles(trading_data)
    confirmation_candles = _candles(confirmation_data)
    time_checks = evaluate_time_filters(as_of, market_timezone)
    checklist = {
        "volume_time": time_checks["volume_time"],
        "playbook_setup": FAIL,
        "timeframe_correlation": UNKNOWN,
        "clean_range_to_fill": UNKNOWN,
        "candle_closed": PASS if trading_candles and confirmation_candles else FAIL,
        "not_overextended": UNKNOWN,
        "not_last_15_of_4h": time_checks["not_last_15_of_4h"],
        "not_15_min_before_open": time_checks["not_15_min_before_open"],
        "not_sunday_asian_session": time_checks["not_sunday_asian_session"],
        "confirmation_candle_wicks": UNKNOWN,
        "trading_candle_stop_wick": UNKNOWN,
        "not_activated_last_5_min": PASS,
    }

    higher_timeframe_data = higher_timeframe_data or {}
    all_zones = []
    for tf, data in higher_timeframe_data.items():
        all_zones.extend(calculate_support_resistance(data, timeframe=tf))
    m30_zones = calculate_support_resistance(
        confirmation_candles,
        timeframe=confirmation_timeframe,
    )
    all_zones.extend(m30_zones)
    all_zones = sorted(all_zones, key=lambda zone: zone["score"], reverse=True)

    market_context = {
        "confirmation_timeframe": confirmation_timeframe,
        "trading_timeframe": timeframe,
        "m30_bias": "UNCLEAR",
        "m30_context": "UNCLEAR",
    }

    if not trading_candles or not confirmation_candles:
        return _no_setup_with_context(
            symbol,
            as_of,
            timeframe,
            confirmation_timeframe,
            checklist,
            all_zones,
            market_context,
            data_status,
            "Insufficient closed OHLCV data. Default to HOLD.",
        )

    hard_time_failures = {
        "volume_time",
        "not_last_15_of_4h",
        "not_15_min_before_open",
        "not_sunday_asian_session",
    }
    if any(checklist[key] == FAIL for key in hard_time_failures):
        return _no_setup_with_context(
            symbol,
            as_of,
            timeframe,
            confirmation_timeframe,
            checklist,
            all_zones,
            market_context,
            data_status,
            "Time filter failed. Default to HOLD.",
        )

    if not m30_zones:
        return _no_setup_with_context(
            symbol,
            as_of,
            timeframe,
            confirmation_timeframe,
            checklist,
            all_zones,
            market_context,
            data_status,
            "No repeated M30 support/resistance zone was detected. Default to HOLD.",
        )

    m30_breakouts = detect_breakouts(confirmation_candles, m30_zones)
    if m30_breakouts:
        m30_direction = m30_breakouts[0]["direction"]
        market_context["m30_bias"] = "BULLISH" if m30_direction == "BUY" else "BEARISH"
        market_context["m30_context"] = "BREAKOUT"
        market_context["m30_breakout"] = m30_breakouts[0]
    else:
        m30_direction = None

    entry_setups: List[Dict[str, Any]] = []
    if m30_direction:
        entry_setups.extend(
            detect_break_and_retest(trading_candles, m30_zones, direction=m30_direction)
        )
    if not entry_setups:
        entry_setups.extend(detect_sr_bounce(trading_candles, all_zones or m30_zones))

    if not entry_setups:
        checklist["not_overextended"] = FAIL if _is_overextended(trading_candles) else PASS
        return _no_setup_with_context(
            symbol,
            as_of,
            timeframe,
            confirmation_timeframe,
            checklist,
            all_zones,
            market_context,
            data_status,
            "No valid M15 playbook setup was detected. Default to HOLD.",
        )

    setup = entry_setups[0]
    _add_risk_reward(setup)
    direction = setup["direction"]
    checklist["playbook_setup"] = PASS
    checklist["timeframe_correlation"] = PASS if m30_direction in {None, direction} else FAIL
    checklist["clean_range_to_fill"] = PASS if setup.get("risk_reward", 0) >= 1.5 else FAIL
    checklist["not_overextended"] = FAIL if _is_overextended(trading_candles) else PASS
    checklist["confirmation_candle_wicks"] = (
        PASS if _has_top_and_bottom_wick(trading_candles[-1]) else FAIL
    )
    if direction == "BUY":
        checklist["trading_candle_stop_wick"] = (
            PASS if _lower_wick(trading_candles[-1]) > 0 else FAIL
        )
    else:
        checklist["trading_candle_stop_wick"] = (
            PASS if _upper_wick(trading_candles[-1]) > 0 else FAIL
        )

    required = [
        "volume_time",
        "playbook_setup",
        "timeframe_correlation",
        "clean_range_to_fill",
        "candle_closed",
        "not_overextended",
        "not_last_15_of_4h",
        "not_15_min_before_open",
        "not_sunday_asian_session",
        "confirmation_candle_wicks",
        "trading_candle_stop_wick",
        "not_activated_last_5_min",
    ]
    if any(checklist[key] != PASS for key in required):
        return _no_setup_with_context(
            symbol,
            as_of,
            timeframe,
            confirmation_timeframe,
            checklist,
            all_zones,
            market_context,
            data_status,
            "A required A+ checklist rule failed. Default to HOLD.",
        )

    payload = {
        "symbol": symbol.upper(),
        "as_of": as_of,
        "timeframe": timeframe,
        "confirmation_timeframe": confirmation_timeframe,
        "status": "SETUP_FOUND",
        "recommendation": direction,
        "setups": [setup],
        "checklist": checklist,
        "zones": all_zones,
        "market_context": market_context,
        "message": "A deterministic A+ price-action setup passed the current checklist.",
    }
    if data_status is not None:
        payload["data_status"] = data_status
    return payload


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
        "zones": [],
        "market_context": {
            "confirmation_timeframe": confirmation_timeframe,
            "trading_timeframe": timeframe,
            "m30_bias": "UNCLEAR",
            "m30_context": "UNCLEAR",
        },
        "message": "No complete A+ price-action setup is available. Default to HOLD.",
    }
    if data_status is not None:
        payload["data_status"] = data_status
    return payload


def _timeframe_status(candles: Any, interval: str) -> Dict[str, Any]:
    rows = len(candles) if candles is not None else 0
    return {"interval": interval, "available": rows > 0, "rows": rows}


def _top_down_data_status(
    timeframe_data: Dict[str, Any],
    timeframe: str,
    confirmation_timeframe: str,
) -> Dict[str, Any]:
    statuses = {
        tf: _timeframe_status(timeframe_data.get(tf, []), tf)
        for tf in ("1d", "4h", "1h", "30m", "15m")
    }
    return {
        "trading_timeframe": _timeframe_status(
            timeframe_data.get("15m", []),
            timeframe,
        ),
        "confirmation_timeframe": _timeframe_status(
            timeframe_data.get("30m", []),
            confirmation_timeframe,
        ),
        "timeframes": statuses,
    }


def _default_price_action_session_config() -> Dict[str, Any] | None:
    from tradingagents.default_config import DEFAULT_CONFIG

    return DEFAULT_CONFIG.get("price_action")


@tool
def get_playbook_setups(
    symbol: Annotated[str, "Ticker symbol to analyze"],
    as_of: Annotated[str, "Analysis timestamp in market timezone"],
    timeframe: Annotated[str, "Trading timeframe, defaults to 15m"] = "15m",
    confirmation_timeframe: Annotated[str, "Confirmation timeframe, defaults to 30m"] = "30m",
    market_timezone: Annotated[str, "Market timezone for session rules"] = "America/New_York",
) -> str:
    """Return detected playbook setups for the price-action trader."""
    try:
        timeframe_data = fetch_price_action_timeframes(symbol)
        data_status = _top_down_data_status(
            timeframe_data,
            timeframe,
            confirmation_timeframe,
        )
        if (
            data_status["trading_timeframe"]["available"]
            and data_status["confirmation_timeframe"]["available"]
        ):
            payload = analyze_top_down_playbook(
                symbol,
                as_of,
                timeframe_data,
                market_timezone=market_timezone,
                session_config=_default_price_action_session_config(),
            )
            payload["timeframe"] = timeframe
            payload["confirmation_timeframe"] = confirmation_timeframe
            payload["data_status"] = data_status
            return json.dumps(payload, indent=2, sort_keys=True)
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
