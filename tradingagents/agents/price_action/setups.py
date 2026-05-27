"""Playbook setup detection on closed candles."""

from __future__ import annotations

from collections.abc import Iterable

from tradingagents.agents.price_action.candles import (
    body_high,
    body_low,
    candle_range,
    is_bearish,
    is_bullish,
    lower_wick,
    normalize_candles,
    upper_wick,
    wick_ratio,
)
from tradingagents.agents.price_action.models import Candle, Setup, Zone


def _round_price(value: float) -> float:
    return round(float(value), 4)


def _stop_buffer(candle: Candle) -> float:
    return max(0.1, candle_range(candle) * 0.05)


def _setup(
    name: str,
    direction: str,
    zone: Zone,
    candle: Candle,
    entry_price: float,
    retest_depth: float | None = None,
) -> Setup:
    buffer = _stop_buffer(candle)
    stop_loss = candle.low - buffer if direction == "BUY" else candle.high + buffer
    return Setup(
        name=name,
        direction=direction,
        zone=zone,
        entry_price=_round_price(entry_price),
        stop_loss=_round_price(stop_loss),
        confirmation_candle=candle,
        retest_depth=None if retest_depth is None else round(retest_depth, 4),
    )


def is_strong_directional_close(candle: Candle, direction: str) -> bool:
    """Return whether a candle closes strongly in the intended direction."""
    direction = str(direction).strip().upper()
    total_range = candle_range(candle)
    if total_range <= 0:
        return False

    body = abs(candle.close - candle.open)
    body_ratio = body / total_range
    if direction == "BUY":
        closes_away = candle.close >= candle.low + (total_range * 0.65)
        return is_bullish(candle) and body_ratio >= 0.50 and closes_away
    if direction == "SELL":
        closes_away = candle.close <= candle.high - (total_range * 0.65)
        return is_bearish(candle) and body_ratio >= 0.50 and closes_away
    return False


def _touches_zone(candle: Candle, zone: Zone) -> bool:
    return candle.low <= zone.high and candle.high >= zone.low


def detect_breakouts(
    data: Iterable[Candle] | str | None,
    zones: Iterable[Zone],
) -> list[Setup]:
    """Detect a closed candle breakout beyond support or resistance."""
    candles = normalize_candles(data)
    if not candles:
        return []
    candle = candles[-1]
    setups: list[Setup] = []
    for zone in zones:
        if zone.type == "resistance" and candle.close > zone.high:
            setups.append(_setup("Breakout", "BUY", zone, candle, zone.high))
        elif zone.type == "support" and candle.close < zone.low:
            setups.append(_setup("Breakout", "SELL", zone, candle, zone.low))
    return sorted(setups, key=lambda setup: setup.zone.score, reverse=True)


def detect_sr_bounce(
    data: Iterable[Candle] | str | None,
    zones: Iterable[Zone],
    min_wick_ratio: float = 0.25,
) -> list[Setup]:
    """Detect support/resistance rejection with a stop-loss wick."""
    candles = normalize_candles(data)
    if not candles:
        return []
    candle = candles[-1]
    setups: list[Setup] = []
    for zone in zones:
        if not _touches_zone(candle, zone):
            continue

        if zone.type == "support":
            has_stop_wick = lower_wick(candle) > 0 and wick_ratio(candle, "lower") >= min_wick_ratio
            rejects_zone = candle.close > zone.midpoint and body_low(candle) >= zone.low
            if has_stop_wick and rejects_zone and (is_bullish(candle) or is_strong_directional_close(candle, "BUY")):
                setups.append(
                    _setup(
                        "Support/Resistance Bounce",
                        "BUY",
                        zone,
                        candle,
                        zone.high,
                    )
                )
        elif zone.type == "resistance":
            has_stop_wick = upper_wick(candle) > 0 and wick_ratio(candle, "upper") >= min_wick_ratio
            rejects_zone = candle.close < zone.midpoint and body_high(candle) <= zone.high
            if has_stop_wick and rejects_zone and (is_bearish(candle) or is_strong_directional_close(candle, "SELL")):
                setups.append(
                    _setup(
                        "Support/Resistance Bounce",
                        "SELL",
                        zone,
                        candle,
                        zone.low,
                    )
                )
    return sorted(setups, key=lambda setup: setup.zone.score, reverse=True)


def detect_break_and_retest(
    data: Iterable[Candle] | str | None,
    zones: Iterable[Zone],
    direction: str | None = None,
    min_retest_depth: float = 0.50,
    min_wick_ratio: float = 0.10,
) -> list[Setup]:
    """Detect a valid half-or-full retest of a broken zone."""
    candles = normalize_candles(data)
    if not candles:
        return []
    candle = candles[-1]
    allowed = {str(direction).strip().upper()} if direction else {"BUY", "SELL"}
    setups: list[Setup] = []
    for zone in zones:
        width = max(zone.high - zone.low, 0.0001)
        if "BUY" in allowed and zone.type == "resistance":
            depth = (zone.high - candle.low) / width
            if (
                depth + 1e-9 >= min_retest_depth
                and lower_wick(candle) > 0
                and wick_ratio(candle, "lower") >= min_wick_ratio
                and candle.close > zone.high
            ):
                setups.append(
                    _setup(
                        "Break and Retest",
                        "BUY",
                        zone,
                        candle,
                        zone.high,
                        min(depth, 1.0),
                    )
                )
        if "SELL" in allowed and zone.type == "support":
            depth = (candle.high - zone.low) / width
            if (
                depth + 1e-9 >= min_retest_depth
                and upper_wick(candle) > 0
                and wick_ratio(candle, "upper") >= min_wick_ratio
                and candle.close < zone.low
            ):
                setups.append(
                    _setup(
                        "Break and Retest",
                        "SELL",
                        zone,
                        candle,
                        zone.low,
                        min(depth, 1.0),
                    )
                )
    return sorted(setups, key=lambda setup: setup.zone.score, reverse=True)
