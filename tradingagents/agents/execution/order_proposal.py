"""Local order proposal writer.

This node deliberately does not place live orders. It creates a local JSON
artifact that a human or future broker adapter can inspect.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from tradingagents.agents.schemas import (
    OrderProposal,
    OrderStatus,
    TradeAction,
    render_order_proposal,
)
from tradingagents.agents.utils.action_parsing import parse_trade_action
from tradingagents.dataflows.utils import safe_ticker_component


_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(?P<label>[A-Za-z][A-Za-z0-9 /_-]*?)(?:\*\*)?"
    r"\s*:\s*(?P<value>.+?)\s*$"
)


def _field(markdown: str, label: str) -> Optional[str]:
    label_lower = label.lower()
    for line in markdown.splitlines():
        match = _LABEL_RE.search(line.strip())
        if not match:
            continue
        if match.group("label").strip().lower() == label_lower:
            return match.group("value").strip()
    return None


def _float_field(markdown: str, label: str) -> Optional[float]:
    raw = _field(markdown, label)
    if raw is None:
        return None
    try:
        return float(raw.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _float_value(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_value(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_action(markdown: str) -> TradeAction:
    return TradeAction(parse_trade_action(markdown))


def _failed_checklist_items(checklist: dict) -> list[str]:
    return [str(key) for key, value in checklist.items() if value == "failed"]


def _format_rr(risk: dict) -> str | None:
    rr = risk.get("risk_reward")
    if rr is None:
        rr = risk.get("available_risk_reward")
    if rr is None:
        return None
    try:
        return f"R:R {float(rr):.2f}"
    except (TypeError, ValueError):
        return f"R:R {rr}"


def _telemetry_reason(state: dict) -> str | None:
    payload = state.get("engine_payload") or {}
    telemetry = state.get("engine_telemetry") or payload.get("telemetry") or {}
    if not telemetry:
        return None

    stage = str(telemetry.get("decision_stage") or "").strip()
    primary = str(telemetry.get("primary_hold_reason") or "").strip()
    checklist = payload.get("checklist") or {}
    risk = payload.get("risk") or {}
    m30 = telemetry.get("m30_context") or {}
    m30_label = " ".join(
        part
        for part in (
            str(m30.get("bias") or "").strip(),
            str(m30.get("context") or "").strip(),
        )
        if part
    )
    candidate_count = telemetry.get("candidate_setup_count")
    failed = _failed_checklist_items(checklist)

    parts = [
        "Setup found."
        if str(payload.get("status") or "").strip().upper() == "SETUP_FOUND"
        else "No trade."
    ]
    if m30_label:
        confirmation_timeframe = str(
            state.get("confirmation_timeframe")
            or payload.get("confirmation_timeframe")
            or telemetry.get("confirmation_timeframe")
            or "30m"
        ).strip()
        entry_profile = str(
            state.get("entry_profile") or payload.get("entry_profile") or ""
        ).strip().lower()
        context_label = "1m history" if entry_profile == "fast" else confirmation_timeframe
        if entry_profile != "fast" and confirmation_timeframe.lower() == "30m":
            context_label = "M30"
        parts.append(f"{context_label} {m30_label}.")
    if candidate_count is not None:
        parts.append(f"Candidate setups: {candidate_count}.")
    if primary:
        parts.append(primary)
    if failed:
        parts.append("Failed checklist: " + ", ".join(failed) + ".")
    if risk.get("reason"):
        risk_detail = str(risk["reason"])
        rr = _format_rr(risk)
        if rr:
            risk_detail = f"{risk_detail} ({rr})"
        parts.append(risk_detail + ".")
    elif _format_rr(risk):
        parts.append(_format_rr(risk) + ".")
    if stage:
        parts.append(f"Decision stage: {stage}.")
    return " ".join(parts)


def _strategy_type_from_setup(setup: dict) -> str | None:
    raw = setup.get("strategy_type") or setup.get("name")
    if raw in (None, ""):
        return None
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", str(raw).strip().upper()).strip("_")
    return normalized or None


def _timeframe_minutes(timeframe: str) -> int:
    match = re.fullmatch(r"(\d+)\s*m", timeframe.strip().lower())
    if not match:
        return 15
    return int(match.group(1))


def _valid_until(as_of: str, timeframe: str, market_timezone: str) -> str:
    minutes = _timeframe_minutes(timeframe)
    return _minutes_after(as_of, minutes, market_timezone)


def _minutes_after(as_of: str, minutes: int, market_timezone: str) -> str:
    try:
        tz = ZoneInfo(market_timezone)
        parsed = datetime.fromisoformat(as_of.replace(" ", "T"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        else:
            parsed = parsed.astimezone(tz)
        return (parsed + timedelta(minutes=minutes)).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return as_of


def _profile_suffix(state: dict) -> str:
    payload = state.get("engine_payload") or {}
    raw = state.get("entry_profile") or payload.get("entry_profile")
    normalized = re.sub(r"[^0-9A-Za-z_-]+", "_", str(raw or "")).strip("_").lower()
    if not normalized or normalized == "normal":
        return ""
    return f"_{normalized}"


def _proposal_from_engine_payload(state: dict) -> OrderProposal | None:
    payload = state.get("engine_payload") or {}
    if not payload:
        return None

    payload_status = str(payload.get("status") or "").strip().upper()
    recommendation = str(payload.get("recommendation") or "").strip().upper()
    timeframe = state.get("timeframe", payload.get("timeframe", "15m"))
    confirmation_timeframe = state.get(
        "confirmation_timeframe",
        payload.get("confirmation_timeframe", "30m"),
    )
    as_of = state.get("as_of", payload.get("as_of", ""))
    market_timezone = state.get("market_timezone", "America/New_York")

    side = TradeAction.HOLD
    status = OrderStatus.NO_TRADE
    entry = stop = target = None
    setup_name = None
    setup_grade = None
    strategy_type = None
    trigger_name = None
    reaction_type = None
    confirmation_type = None
    touch_count = None
    candidate_score = None
    volume_decision = None
    volume = None
    volume_multiplier = None
    position_lifecycle = None
    dynamic_exit_fields: dict[str, float | None] = {
        "break_even_trigger_points": None,
        "break_even_lock_points": None,
        "trailing_trigger_points": None,
        "trailing_distance_points": None,
        "partial_first_trigger_points": None,
        "partial_first_target_volume": None,
        "partial_second_trigger_points": None,
        "partial_second_target_volume": None,
    }
    reason = _telemetry_reason(state) or str(payload.get("message") or "No engine reason supplied.")

    if payload_status == "SETUP_FOUND" and recommendation in {"BUY", "SELL"}:
        side = TradeAction(recommendation)
        setup = (payload.get("setups") or [{}])[0]
        setup_name = str(setup.get("name") or "").strip() or None
        setup_grade = str(setup.get("setup_grade") or "").strip() or None
        strategy_type = _strategy_type_from_setup(setup)
        risk = payload.get("risk") or {}
        telemetry = payload.get("telemetry") or {}
        selected_candidate = telemetry.get("selected_candidate") or {}
        if isinstance(selected_candidate, dict):
            trigger_name = (
                str(selected_candidate.get("trigger") or setup_name or "").strip()
                or None
            )
            reaction_type = (
                str(selected_candidate.get("reaction_type") or "").strip() or None
            )
            confirmation_type = (
                str(selected_candidate.get("confirmation_type") or "").strip()
                or None
            )
            touch_count = _int_value(selected_candidate.get("touch_count"))
            candidate_score = _float_value(selected_candidate.get("score"))
            volume_decision = (
                str(selected_candidate.get("volume_decision") or "").strip()
                or None
            )
        entry = _float_value(setup.get("entry_price"))
        stop = _float_value(setup.get("stop_loss"))
        target = _float_value(setup.get("take_profit") or risk.get("take_profit"))
        volume = _float_value(risk.get("volume"))
        volume_multiplier = _float_value(risk.get("volume_multiplier"))
        raw_lifecycle = risk.get("position_lifecycle")
        position_lifecycle = (
            str(raw_lifecycle).strip() if raw_lifecycle not in (None, "") else None
        )
        dynamic_exit_fields = {
            key: _float_value(risk.get(key)) for key in dynamic_exit_fields
        }
        if entry is not None and stop is not None and target is not None:
            status = OrderStatus.PROPOSED
        else:
            reason = "No order proposed because the engine setup is missing entry, stop, or target."

    activation_window_minutes = None
    if status == OrderStatus.PROPOSED:
        activation_window_minutes = int(
            payload.get("activation_window_minutes")
            or state.get("activation_window_minutes")
            or 10
        )
    return OrderProposal(
        symbol=state["company_of_interest"],
        broker_symbol=state.get("broker_symbol") or state["company_of_interest"],
        side=side,
        order_type="AUTO" if status == OrderStatus.PROPOSED else "LIMIT",
        setup_name=setup_name,
        setup_grade=setup_grade,
        strategy_type=strategy_type,
        trigger_name=trigger_name,
        reaction_type=reaction_type,
        confirmation_type=confirmation_type,
        touch_count=touch_count,
        candidate_score=candidate_score,
        volume_decision=volume_decision,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        volume=volume,
        volume_multiplier=volume_multiplier,
        position_lifecycle=position_lifecycle,
        **dynamic_exit_fields,
        timeframe=timeframe,
        confirmation_timeframe=confirmation_timeframe,
        valid_until=_valid_until(as_of, timeframe, market_timezone),
        activation_window_minutes=activation_window_minutes,
        cancel_if_not_triggered_after=(
            _minutes_after(as_of, activation_window_minutes, market_timezone)
            if activation_window_minutes is not None
            else None
        ),
        status=status,
        reason=reason,
    )


def build_order_proposal(state: dict, config: dict | None = None) -> OrderProposal:
    engine_proposal = _proposal_from_engine_payload(state)
    if engine_proposal is not None:
        return engine_proposal

    trade_plan = state.get("trade_plan", "")
    action = _parse_action(trade_plan)
    entry = _float_field(trade_plan, "Entry Price")
    stop = _float_field(trade_plan, "Stop Loss")
    target = _float_field(trade_plan, "Take Profit")
    reason = _field(trade_plan, "Reason") or "No trader reason supplied."

    has_required_levels = entry is not None and stop is not None and target is not None
    status = (
        OrderStatus.PROPOSED
        if action in {TradeAction.BUY, TradeAction.SELL} and has_required_levels
        else OrderStatus.NO_TRADE
    )

    if action in {TradeAction.BUY, TradeAction.SELL} and not has_required_levels:
        reason = "No order proposed because the trade plan is missing entry, stop, or target."
    elif status == OrderStatus.NO_TRADE:
        reason = _telemetry_reason(state) or reason

    as_of = state.get("as_of", "")
    market_timezone = state.get("market_timezone", "America/New_York")
    proposal_config = config or {}
    activation_window_minutes = (
        int(proposal_config.get("normal_activation_window_minutes", 10))
        if status == OrderStatus.PROPOSED
        else None
    )

    return OrderProposal(
        symbol=state["company_of_interest"],
        broker_symbol=state.get("broker_symbol") or state["company_of_interest"],
        side=action,
        order_type="LIMIT",
        setup_name=None,
        strategy_type=None,
        entry_price=entry,
        stop_loss=stop,
        take_profit=target,
        timeframe=state.get("timeframe", "15m"),
        confirmation_timeframe=state.get("confirmation_timeframe", "30m"),
        valid_until=_valid_until(
            as_of,
            state.get("timeframe", "15m"),
            market_timezone,
        ),
        activation_window_minutes=activation_window_minutes,
        cancel_if_not_triggered_after=(
            _minutes_after(as_of, activation_window_minutes, market_timezone)
            if activation_window_minutes is not None
            else None
        ),
        status=status,
        reason=reason,
    )


def create_order_proposal_executor(config: dict):
    def load_engine_payload(state: dict) -> dict:
        safe_symbol = safe_ticker_component(state["company_of_interest"])
        safe_as_of = re.sub(r"[^0-9A-Za-z_-]+", "_", state.get("as_of", "unknown")).strip("_")
        telemetry_dir = Path(config["results_dir"]) / safe_symbol / "engine_telemetry"
        suffix = _profile_suffix(state)
        candidates = []
        if suffix:
            candidates.append(telemetry_dir / f"engine_payload_{safe_as_of}{suffix}.json")
        candidates.append(telemetry_dir / f"engine_payload_{safe_as_of}.json")
        for telemetry_path in candidates:
            if telemetry_path.exists():
                return json.loads(telemetry_path.read_text(encoding="utf-8"))
        return {}

    def order_proposal_node(state):
        enriched_state = dict(state)
        if not enriched_state.get("engine_payload"):
            payload = load_engine_payload(enriched_state)
            if payload:
                enriched_state["engine_payload"] = payload
                enriched_state["engine_telemetry"] = payload.get("telemetry", {})
        proposal = build_order_proposal(enriched_state, config)
        rendered = render_order_proposal(proposal)

        safe_symbol = safe_ticker_component(state["company_of_interest"])
        safe_as_of = re.sub(r"[^0-9A-Za-z_-]+", "_", state.get("as_of", "unknown")).strip("_")
        proposal_dir = Path(config["results_dir"]) / safe_symbol / "order_proposals"
        proposal_dir.mkdir(parents=True, exist_ok=True)
        proposal_path = proposal_dir / f"order_proposal_{safe_as_of}{_profile_suffix(enriched_state)}.json"
        proposal_path.write_text(
            json.dumps(proposal.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )

        return {
            "order_proposal": rendered,
            "order_proposal_path": str(proposal_path),
            "sender": "Order Proposal",
        }

    return order_proposal_node
