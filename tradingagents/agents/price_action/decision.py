"""Engine-first price-action decision service."""

from __future__ import annotations

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
        f"**M30 Context:** {_m30_label(payload)}",
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

    if not data_is_healthy(data_status):
        payload = _data_health_payload(
            symbol,
            as_of,
            timeframe,
            confirmation_timeframe,
            data_status,
        )
    else:
        payload = analyze_playbook(
            symbol,
            as_of,
            snapshot.candles,
            market_timezone=market_timezone,
            session_config=session_config,
        )
        payload["timeframe"] = timeframe
        payload["confirmation_timeframe"] = confirmation_timeframe
        payload["data_status"] = data_status

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

    return {
        "company_of_interest": symbol,
        "broker_symbol": broker_symbol or symbol,
        "as_of": as_of,
        "timeframe": timeframe,
        "confirmation_timeframe": confirmation_timeframe,
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
