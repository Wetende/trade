"""Risk approval and Gold pip/point helpers."""

from __future__ import annotations

from tradingagents.agents.price_action.models import Setup


def gold_points_to_pips(points: float) -> float:
    """Convert Gold price points to playbook pips.

    In this playbook, 2350.00 -> 2355.00 is 50 pips, so 1 Gold point is
    treated as 10 pips.
    """
    return round(float(points) * 10, 4)


def approve_risk(
    setup: Setup,
    target_zone: dict | None,
    minimum_rr: float = 1.5,
    preferred_rr: float = 3.0,
) -> dict:
    """Approve/reject a setup based on target distance and risk/reward."""
    if target_zone is None:
        return {"approved": False, "reason": "No target zone available"}

    entry = float(setup.entry_price)
    stop = float(setup.stop_loss)
    risk = abs(entry - stop)
    if risk <= 0:
        return {"approved": False, "reason": "Invalid stop-loss distance"}

    target_price = float(target_zone["midpoint"])
    reward = abs(target_price - entry)
    available_rr = round(reward / risk, 2)
    if available_rr < minimum_rr:
        return {
            "approved": False,
            "reason": "Clean range is below minimum risk-to-reward",
            "risk_reward": available_rr,
        }

    preferred_reward = min(reward, risk * preferred_rr)
    if setup.direction == "BUY":
        take_profit = entry + preferred_reward
    else:
        take_profit = entry - preferred_reward
    approved_reward = abs(take_profit - entry)

    return {
        "approved": True,
        "entry_price": round(entry, 4),
        "stop_loss": round(stop, 4),
        "take_profit": round(take_profit, 4),
        "risk_distance": round(risk, 4),
        "reward_distance": round(approved_reward, 4),
        "risk_reward": round(approved_reward / risk, 2),
        "available_risk_reward": available_rr,
    }


def move_to_break_even_allowed(
    entry: float,
    current: float,
    direction: str,
    threshold_pips: float,
) -> bool:
    """Return whether a fixed Gold pip move allows break-even protection."""
    normalized_direction = str(direction).strip().upper()
    if normalized_direction == "BUY":
        moved_points = float(current) - float(entry)
    elif normalized_direction == "SELL":
        moved_points = float(entry) - float(current)
    else:
        return False
    return gold_points_to_pips(moved_points) >= float(threshold_pips)
