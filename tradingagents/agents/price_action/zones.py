"""Support/resistance zone detection and range classification."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from tradingagents.agents.price_action.candles import atr, normalize_candles
from tradingagents.agents.price_action.models import Candle, Zone


def _round_price(value: float) -> float:
    return round(float(value), 4)


def timeframe_weight(timeframe: str) -> int:
    """Return a relative score weight for a timeframe label."""
    normalized = str(timeframe).strip().lower()
    if normalized in {"1d", "d", "daily"}:
        return 50
    if normalized in {"4h", "240m"}:
        return 40
    if normalized in {"1h", "60m", "h1"}:
        return 30
    if normalized in {"30m", "m30"}:
        return 20
    if normalized in {"15m", "m15"}:
        return 10
    return 5


def default_zone_tolerance(
    candles: Iterable[Candle] | str | None,
    timeframe: str = "30m",
) -> float:
    """Derive a zone thickness from recent true range."""
    normalized = normalize_candles(candles)
    recent_atr = atr(normalized)
    tf = str(timeframe).strip().lower()
    if tf in {"1d", "d", "daily"}:
        multiplier = 0.30
    elif tf in {"4h", "240m"}:
        multiplier = 0.25
    elif tf in {"1h", "60m", "h1"}:
        multiplier = 0.20
    else:
        multiplier = 0.15
    return max(0.0001, recent_atr * multiplier)


def _swing_points(
    candles: list[Candle],
    zone_type: str,
    lookback: int = 1,
) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    if len(candles) < (lookback * 2) + 1:
        return points

    for index in range(lookback, len(candles) - lookback):
        candle = candles[index]
        left = candles[index - lookback : index]
        right = candles[index + 1 : index + 1 + lookback]
        if zone_type == "resistance":
            price = float(candle.high)
            if price > max(float(item.high) for item in left) and price >= max(
                float(item.high) for item in right
            ):
                points.append({"price": price, "timestamp": candle.timestamp})
        else:
            price = float(candle.low)
            if price < min(float(item.low) for item in left) and price <= min(
                float(item.low) for item in right
            ):
                points.append({"price": price, "timestamp": candle.timestamp})
    return points


def _cluster_points(
    points: list[dict[str, Any]],
    zone_type: str,
    timeframe: str,
    tolerance: float,
    min_touches: int,
) -> list[Zone]:
    if not points:
        return []

    clusters: list[list[dict[str, Any]]] = []
    for point in sorted(points, key=lambda item: item["price"]):
        point_price = float(point["price"])
        for cluster in clusters:
            anchor = float(cluster[0]["price"])
            cluster_prices = [float(item["price"]) for item in cluster]
            next_low = min([*cluster_prices, point_price])
            next_high = max([*cluster_prices, point_price])
            if (
                abs(point_price - anchor) <= tolerance
                and next_high - next_low <= tolerance
            ):
                cluster.append(point)
                break
        else:
            clusters.append([point])

    zones: list[Zone] = []
    for cluster in clusters:
        if len(cluster) < min_touches:
            continue

        prices = [float(point["price"]) for point in cluster]
        low = min(prices) - tolerance
        high = max(prices) + tolerance
        midpoint = (low + high) / 2
        touches = len(cluster)
        reactions = [
            {
                "timestamp": point["timestamp"],
                "price": _round_price(float(point["price"])),
            }
            for point in cluster
        ]
        zones.append(
            Zone(
                type=zone_type,
                timeframe=timeframe,
                low=_round_price(low),
                high=_round_price(high),
                midpoint=_round_price(midpoint),
                touches=touches,
                score=float(timeframe_weight(timeframe) + (touches * 2)),
                source="swing_cluster",
                reactions=reactions,
            )
        )
    return zones


def calculate_support_resistance(
    data: Iterable[Candle] | str | None = None,
    timeframe: str = "30m",
    tolerance: float | None = None,
    min_touches: int = 2,
) -> list[Zone]:
    """Detect support/resistance zones from repeated swing highs and lows."""
    candles = normalize_candles(data)
    if not candles:
        return []

    zone_tolerance = (
        default_zone_tolerance(candles, timeframe) if tolerance is None else float(tolerance)
    )
    zones = [
        *_cluster_points(
            _swing_points(candles, "support"),
            "support",
            timeframe,
            zone_tolerance,
            min_touches,
        ),
        *_cluster_points(
            _swing_points(candles, "resistance"),
            "resistance",
            timeframe,
            zone_tolerance,
            min_touches,
        ),
    ]
    return sorted(zones, key=lambda zone: zone.score, reverse=True)


def zone_to_dict(zone: Zone | dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-friendly zone representation."""
    if isinstance(zone, dict):
        return dict(zone)
    return {
        "type": zone.type,
        "timeframe": zone.timeframe,
        "low": zone.low,
        "high": zone.high,
        "midpoint": zone.midpoint,
        "touches": zone.touches,
        "score": zone.score,
        "source": zone.source,
        "reactions": list(zone.reactions),
    }


def _best_zone(zones: list[Zone], zone_type: str) -> Zone | None:
    candidates = [zone for zone in zones if zone.type == zone_type and zone.touches >= 2]
    if not candidates:
        return None
    return sorted(candidates, key=lambda zone: zone.score, reverse=True)[0]


def classify_range(
    data: Iterable[Candle] | str | None,
    zones: Iterable[Zone],
    min_inside_ratio: float = 0.67,
) -> dict[str, Any]:
    """Classify whether candles are boxed between equal-high/equal-low zones."""
    candles = normalize_candles(data)
    normalized_zones = list(zones)
    support = _best_zone(normalized_zones, "support")
    resistance = _best_zone(normalized_zones, "resistance")

    result: dict[str, Any] = {
        "market_type": "UNCLEAR",
        "support_zone": zone_to_dict(support) if support else None,
        "resistance_zone": zone_to_dict(resistance) if resistance else None,
        "inside_close_ratio": 0.0,
        "contained_candle_ratio": 0.0,
        "breakout_count": 0,
    }
    if not candles or support is None or resistance is None:
        return result
    if support.midpoint >= resistance.midpoint:
        return result

    lower_bound = support.low
    upper_bound = resistance.high
    inside_count = sum(
        1 for candle in candles if lower_bound <= float(candle.close) <= upper_bound
    )
    contained_count = sum(
        1
        for candle in candles
        if float(candle.low) >= lower_bound and float(candle.high) <= upper_bound
    )
    breakout_count = len(candles) - contained_count
    inside_ratio = inside_count / len(candles)
    contained_ratio = contained_count / len(candles)
    result["inside_close_ratio"] = round(inside_ratio, 4)
    result["contained_candle_ratio"] = round(contained_ratio, 4)
    result["breakout_count"] = breakout_count

    if (
        inside_ratio >= min_inside_ratio
        and contained_ratio >= min_inside_ratio
        and breakout_count == 0
    ):
        result["market_type"] = "RANGE"
        result["range_low"] = support.low
        result["range_high"] = resistance.high
        result["range_midpoint"] = _round_price((support.midpoint + resistance.midpoint) / 2)
    return result


def nearest_target_zone(
    zones: Iterable[Zone],
    direction: str,
    entry_price: float,
) -> dict[str, Any] | None:
    """Find the nearest opposite zone in the direction of a trade."""
    normalized_direction = str(direction).strip().upper()
    entry = float(entry_price)
    if normalized_direction == "BUY":
        candidates = [
            zone for zone in zones if zone.type == "resistance" and zone.midpoint > entry
        ]
        ordered = sorted(candidates, key=lambda zone: zone.midpoint - entry)
    elif normalized_direction == "SELL":
        candidates = [
            zone for zone in zones if zone.type == "support" and zone.midpoint < entry
        ]
        ordered = sorted(candidates, key=lambda zone: entry - zone.midpoint)
    else:
        return None

    if not ordered:
        return None
    return zone_to_dict(ordered[0])
