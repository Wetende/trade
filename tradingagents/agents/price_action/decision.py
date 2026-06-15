"""Engine-first price-action decision service."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingagents.agents.price_action.engine import analyze_playbook
from tradingagents.agents.utils.price_action_tools import (
    build_no_setup_payload,
    write_engine_payload,
)
from tradingagents.dataflows.data_health import data_is_healthy
from tradingagents.dataflows.price_action import (
    PriceActionSnapshot,
    fetch_price_action_snapshot,
)


def _timeframe_rows(data_status: dict[str, Any]) -> dict[str, int]:
    return {
        timeframe: int(status.get("rows", 0))
        for timeframe, status in data_status.get("timeframes", {}).items()
    }


def _failed_checklist_items(payload: dict[str, Any]) -> list[str]:
    return [
        str(key)
        for key, value in (payload.get("checklist") or {}).items()
        if value == "failed"
    ]


def _m30_label(payload: dict[str, Any]) -> str:
    telemetry = payload.get("telemetry") or {}
    m30 = telemetry.get("m30_context") or {}
    bias = str(m30.get("bias") or payload.get("market_context", {}).get("m30_bias") or "UNCLEAR")
    context = str(
        m30.get("context")
        or payload.get("market_context", {}).get("m30_context")
        or "UNCLEAR"
    )
    return f"{bias} {context}".strip()


def _context_heading(payload: dict[str, Any]) -> str:
    timeframe = str(payload.get("confirmation_timeframe") or "30m").strip()
    if timeframe.lower() == "30m":
        return "M30 Context"
    return "1m History"


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _parse_utc_datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _market_health(
    market_metadata: dict[str, Any],
    config: dict[str, Any],
    *,
    now_utc: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate live MT5 tick/symbol metadata before setup analysis."""
    if not market_metadata:
        return {"passed": True, "reasons": [], "metadata_available": False}
    if market_metadata.get("error"):
        return {
            "passed": False,
            "reasons": ["market_metadata_error"],
            "error": str(market_metadata["error"]),
            "metadata_available": True,
        }

    symbol = market_metadata.get("symbol") or {}
    tick = market_metadata.get("tick") or {}
    bid = _as_float(tick.get("bid", symbol.get("bid")))
    ask = _as_float(tick.get("ask", symbol.get("ask")))
    spread_price = _as_float(symbol.get("spread_price"))
    if spread_price is None and bid is not None and ask is not None:
        spread_price = ask - bid

    reasons: list[str] = []
    if bid is None or ask is None or spread_price is None or spread_price < 0:
        reasons.append("live_tick_missing_or_invalid")

    max_spread = _as_float(config.get("max_entry_spread_price"))
    if (
        max_spread is not None
        and max_spread > 0
        and spread_price is not None
        and spread_price > max_spread
    ):
        reasons.append("spread_too_wide")

    tick_age_seconds = None
    max_tick_age = _as_float(config.get("max_tick_age_seconds"))
    tick_time = _parse_utc_datetime(tick.get("time_utc"))
    if max_tick_age is not None and max_tick_age > 0:
        if tick_time is None:
            reasons.append("tick_time_missing")
        else:
            current = now_utc or datetime.now(timezone.utc)
            tick_age_seconds = max(
                (current.astimezone(timezone.utc) - tick_time).total_seconds(),
                0.0,
            )
            if tick_age_seconds > max_tick_age:
                reasons.append("tick_stale")

    return {
        "passed": not reasons,
        "reasons": reasons,
        "metadata_available": True,
        "bid": bid,
        "ask": ask,
        "spread_price": spread_price,
        "max_entry_spread_price": max_spread,
        "tick_age_seconds": tick_age_seconds,
        "max_tick_age_seconds": max_tick_age,
    }


def render_engine_decision_report(payload: dict[str, Any]) -> str:
    """Render deterministic decision text from engine payload fields."""
    telemetry = payload.get("telemetry") or {}
    risk = payload.get("risk") or {}
    setups = payload.get("setups") or []
    recommendation = str(payload.get("recommendation") or "HOLD").upper()
    action = recommendation if payload.get("status") == "SETUP_FOUND" else "HOLD"
    failed = _failed_checklist_items(payload)

    lines = [
        f"# Engine Decision Report: {payload.get('symbol', '')}",
        "",
        f"**As of:** {payload.get('as_of', '')}",
        f"**Status:** {payload.get('status', '')}",
        f"**Final Action: {action}**",
        f"**{_context_heading(payload)}:** {_m30_label(payload)}",
        f"**Candidate Setups:** {telemetry.get('candidate_setup_count', len(setups))}",
        "",
        "## Decision Reason",
        str(
            telemetry.get("primary_hold_reason")
            or payload.get("message")
            or "No engine reason supplied."
        ),
    ]

    if failed:
        lines.extend(["", "## Failed Checklist", ", ".join(failed)])

    if risk:
        risk_parts = []
        if risk.get("reason"):
            risk_parts.append(str(risk["reason"]))
        if risk.get("risk_reward") is not None:
            try:
                risk_parts.append(f"R:R {float(risk['risk_reward']):.2f}")
            except (TypeError, ValueError):
                risk_parts.append(f"R:R {risk['risk_reward']}")
        if risk_parts:
            lines.extend(["", "## Risk", " | ".join(risk_parts)])

    data_status = payload.get("data_status") or {}
    if data_status:
        blocking = data_status.get("blocking_timeframes") or []
        health = "healthy" if data_status.get("healthy") else "unhealthy"
        lines.extend(
            [
                "",
                "## Data Health",
                f"Status: {health}",
                "Blocking timeframes: " + (", ".join(blocking) if blocking else "none"),
            ]
        )

    if setups:
        setup = setups[0]
        lines.extend(
            [
                "",
                "## Primary Setup",
                f"Name: {setup.get('name', '')}",
                f"Side: {setup.get('direction', '')}",
                f"Entry: {setup.get('entry_price', '')}",
                f"Stop Loss: {setup.get('stop_loss', '')}",
                f"Take Profit: {setup.get('take_profit', '')}",
            ]
        )

    return "\n".join(lines)


def _data_health_payload(
    symbol: str,
    as_of: str,
    timeframe: str,
    confirmation_timeframe: str,
    data_status: dict[str, Any],
) -> dict[str, Any]:
    payload = build_no_setup_payload(
        symbol,
        as_of,
        timeframe,
        confirmation_timeframe,
        data_status=data_status,
    )
    payload["message"] = "Data health failed. Default to HOLD."
    payload["telemetry"] = {
        "decision_stage": "data_health",
        "primary_hold_reason": "Data health failed. Default to HOLD.",
        "timeframe_rows": _timeframe_rows(data_status),
        "candidate_setup_count": 0,
        "m30_context": {"bias": "UNCLEAR", "context": "UNCLEAR"},
    }
    return payload


def _market_health_payload(
    symbol: str,
    as_of: str,
    timeframe: str,
    confirmation_timeframe: str,
    data_status: dict[str, Any],
    market_health: dict[str, Any],
    market_metadata: dict[str, Any],
) -> dict[str, Any]:
    reasons = market_health.get("reasons") or ["market_health_failed"]
    payload = build_no_setup_payload(
        symbol,
        as_of,
        timeframe,
        confirmation_timeframe,
        data_status=data_status,
    )
    payload["message"] = "Market health failed: " + ", ".join(map(str, reasons))
    payload["market_health"] = market_health
    payload["market_metadata"] = market_metadata
    payload["telemetry"] = {
        "decision_stage": "market_health",
        "primary_hold_reason": payload["message"],
        "timeframe_rows": _timeframe_rows(data_status),
        "candidate_setup_count": 0,
        "m30_context": {"bias": "UNCLEAR", "context": "UNCLEAR"},
        "market_health": market_health,
    }
    return payload


def run_engine_decision(
    symbol: str,
    *,
    broker_symbol: str | None,
    as_of: str,
    results_dir: str | Path,
    timeframe: str = "15m",
    confirmation_timeframe: str = "30m",
    market_timezone: str = "America/New_York",
    session_config: dict[str, Any] | None = None,
    snapshot: PriceActionSnapshot | None = None,
) -> dict[str, Any]:
    """Run the deterministic price-action engine and return proposal-ready state."""
    profile_config = session_config or {}
    if snapshot is None:
        snapshot = fetch_price_action_snapshot(
            symbol,
            as_of=as_of,
            market_timezone=market_timezone,
        )
    data_status = snapshot.data_status
    market_metadata = getattr(snapshot, "market_metadata", {}) or {}
    market_health = _market_health(market_metadata, profile_config)

    if not data_is_healthy(data_status):
        payload = _data_health_payload(
            symbol,
            as_of,
            timeframe,
            confirmation_timeframe,
            data_status,
        )
        payload["market_metadata"] = market_metadata
        payload["market_health"] = market_health
    elif not market_health["passed"]:
        payload = _market_health_payload(
            symbol,
            as_of,
            timeframe,
            confirmation_timeframe,
            data_status,
            market_health,
            market_metadata,
        )
    else:
        payload = analyze_playbook(
            symbol,
            as_of,
            snapshot.candles,
            market_timezone=market_timezone,
            session_config=session_config,
        )
        payload.setdefault("timeframe", timeframe)
        payload.setdefault("confirmation_timeframe", confirmation_timeframe)
        payload["data_status"] = data_status
        payload["market_metadata"] = market_metadata
        payload["market_health"] = market_health
        payload.setdefault("telemetry", {})["market_health"] = market_health

    if profile_config.get("entry_profile"):
        payload["entry_profile"] = str(profile_config["entry_profile"])
    if profile_config.get("activation_window_minutes") is not None:
        payload["activation_window_minutes"] = int(
            profile_config["activation_window_minutes"]
        )

    telemetry_path = write_engine_payload(payload, results_dir)
    payload["telemetry_path"] = str(telemetry_path)
    report = render_engine_decision_report(payload)
    action = payload.get("recommendation", "HOLD")
    resolved_timeframe = str(payload.get("timeframe") or timeframe)
    resolved_confirmation_timeframe = str(
        payload.get("confirmation_timeframe") or confirmation_timeframe
    )

    return {
        "company_of_interest": symbol,
        "broker_symbol": broker_symbol or symbol,
        "as_of": as_of,
        "timeframe": resolved_timeframe,
        "confirmation_timeframe": resolved_confirmation_timeframe,
        "market_timezone": market_timezone,
        "price_action_report": report,
        "trade_plan": f"Action: {action}\n\nReason: {payload.get('message', '')}",
        "order_proposal": "",
        "order_proposal_path": None,
        "engine_payload": payload,
        "engine_telemetry": payload.get("telemetry", {}),
        "data_status": data_status,
        "telemetry_path": str(telemetry_path),
        "messages": [],
        "sender": "Engine Decision",
    }
