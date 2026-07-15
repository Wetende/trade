"""Read-only MT5 evidence collection for post-close scalper research."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from tradingagents.brokers.mode_gate import account_safety_from_connection
from tradingagents.brokers.mt5 import MT5BrokerError


def parse_evidence_timestamp(value: str) -> datetime:
    """Parse one timezone-aware timestamp and normalize it to UTC."""
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise MT5BrokerError(f"invalid evidence timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise MT5BrokerError("evidence timestamps must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _timestamp(row: dict[str, Any], field: str) -> datetime:
    return parse_evidence_timestamp(str(row[field]))


def collect_post_close_fixture(
    broker: Any,
    *,
    connection: dict[str, Any],
    start_utc: datetime,
    end_utc: datetime,
    context_candles: int = 60,
) -> dict[str, Any]:
    """Collect one immutable-shape fixture without invoking a mutation API."""
    if start_utc.tzinfo is None or end_utc.tzinfo is None:
        raise MT5BrokerError("evidence timestamps must be timezone-aware")
    start = start_utc.astimezone(timezone.utc)
    end = end_utc.astimezone(timezone.utc)
    if end <= start:
        raise MT5BrokerError("evidence end must be after start")
    if isinstance(context_candles, bool) or context_candles < 2:
        raise MT5BrokerError("context_candles must be at least 2")
    if bool(getattr(broker.config, "allow_real_orders", False)):
        raise MT5BrokerError("read-only evidence collection requires real orders disabled")

    account_safety = account_safety_from_connection(
        connection,
        require_demo=bool(getattr(broker.config, "require_demo_account", True)),
    )
    if not account_safety["passed"]:
        raise MT5BrokerError(str(account_safety["reason"]))

    # Seven calendar days reliably supplies 60 prior trading bars across a
    # weekend while the serialized fixture retains only the final N bars.
    query_start = start - timedelta(days=7)
    raw_candles = broker.fetch_closed_rates_range("1m", query_start, end)
    before = sorted(
        (row for row in raw_candles if _timestamp(row, "timestamp") < start),
        key=lambda row: _timestamp(row, "timestamp"),
    )
    within = sorted(
        (
            row
            for row in raw_candles
            if start <= _timestamp(row, "timestamp") < end
        ),
        key=lambda row: _timestamp(row, "timestamp"),
    )
    if len(before) < context_candles:
        raise MT5BrokerError(
            f"MT5 returned only {len(before)} context candles; {context_candles} required"
        )
    if not within:
        raise MT5BrokerError("MT5 returned no M1 candles inside the evidence window")
    candles = before[-context_candles:] + within

    raw_ticks = broker.fetch_ticks_range(start, end)
    ticks = sorted(
        (
            row
            for row in raw_ticks
            if start <= _timestamp(row, "time") < end
        ),
        key=lambda row: _timestamp(row, "time"),
    )
    if not ticks:
        raise MT5BrokerError("MT5 returned no ticks inside the evidence window")

    orders = broker.open_orders(broker.config.symbol)
    positions = broker.open_positions(broker.config.symbol)
    return {
        "schema_version": 1,
        "symbol": broker.config.symbol,
        "timeframe": "1m",
        "evidence_start": start.isoformat(),
        "evidence_end": end.isoformat(),
        "context_candle_count": context_candles,
        "broker_mutation_enabled": False,
        "collection": {
            "read_only": True,
            "collected_at_utc": datetime.now(timezone.utc).isoformat(),
            "account_trade_mode": account_safety["trade_mode"],
            "open_order_count": len(orders),
            "open_position_count": len(positions),
            "range_semantics": "START_INCLUSIVE_END_EXCLUSIVE",
        },
        "candles": candles,
        "ticks": ticks,
    }


__all__ = ["collect_post_close_fixture", "parse_evidence_timestamp"]
