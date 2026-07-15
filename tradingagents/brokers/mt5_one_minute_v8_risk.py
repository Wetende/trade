"""Account-currency risk budget for the promoted M1 V8 runner."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class V8RiskBudget:
    unit_risk_currency: float
    max_session_r: float = 2.0
    cost_buffer_r: float = 0.05

    def __post_init__(self) -> None:
        for name in ("unit_risk_currency", "max_session_r"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
            object.__setattr__(self, name, value)
        buffer = float(self.cost_buffer_r)
        if not math.isfinite(buffer) or buffer < 0:
            raise ValueError("cost_buffer_r must be finite and non-negative")
        object.__setattr__(self, "cost_buffer_r", buffer)

    @property
    def limit_currency(self) -> float:
        return self.unit_risk_currency * self.max_session_r

    @property
    def cost_buffer_currency(self) -> float:
        return self.unit_risk_currency * self.cost_buffer_r


@dataclass(frozen=True)
class V8RiskDecision:
    accepted: bool
    reason: str
    realized_loss_currency: float
    reserved_exposure_currency: float
    proposed_stop_risk_currency: float
    cost_buffer_currency: float
    required_currency: float
    budget_currency: float
    remaining_currency: float
    unpriced_exposure_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_v8_risk_budget(
    budget: V8RiskBudget,
    *,
    realized_net_currency: float,
    reserved_exposure_currency: float,
    proposed_stop_risk_currency: float,
    unpriced_exposure_count: int = 0,
) -> V8RiskDecision:
    """Block only when total reserved downside would exceed the 2R limit."""
    values = {
        "realized_net_currency": realized_net_currency,
        "reserved_exposure_currency": reserved_exposure_currency,
        "proposed_stop_risk_currency": proposed_stop_risk_currency,
    }
    normalized: dict[str, float] = {}
    for name, raw in values.items():
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be numeric") from exc
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        normalized[name] = value
    reserved = max(0.0, normalized["reserved_exposure_currency"])
    proposed = max(0.0, normalized["proposed_stop_risk_currency"])
    realized_loss = max(0.0, -normalized["realized_net_currency"])
    required = realized_loss + reserved + proposed + budget.cost_buffer_currency
    limit = budget.limit_currency
    unpriced = max(0, int(unpriced_exposure_count))
    accepted = unpriced == 0 and required <= limit + 1e-9
    reason = (
        "UNPRICED_EXPOSURE"
        if unpriced
        else "RISK_BUDGET_ACCEPTED" if accepted else "SESSION_RISK_BUDGET_EXCEEDED"
    )
    return V8RiskDecision(
        accepted=accepted,
        reason=reason,
        realized_loss_currency=round(realized_loss, 10),
        reserved_exposure_currency=round(reserved, 10),
        proposed_stop_risk_currency=round(proposed, 10),
        cost_buffer_currency=round(budget.cost_buffer_currency, 10),
        required_currency=round(required, 10),
        budget_currency=round(limit, 10),
        remaining_currency=round(limit - required, 10),
        unpriced_exposure_count=unpriced,
    )


def calculate_v8_unit_risk_currency(
    broker: Any,
    *,
    volume: float,
    bid: float,
    ask: float,
    maximum_stop_distance: float = 1.0,
) -> float:
    """Freeze one R as the larger BUY/SELL one-unit stop loss estimate."""
    distance = float(maximum_stop_distance)
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("maximum_stop_distance must be finite and positive")
    buy = broker.estimate_stop_loss_account_currency(
        "BUY", volume, ask, ask - distance
    )
    sell = broker.estimate_stop_loss_account_currency(
        "SELL", volume, bid, bid + distance
    )
    unit = max(float(buy), float(sell))
    if not math.isfinite(unit) or unit <= 0:
        raise ValueError("MT5 returned invalid one-unit stop risk")
    return unit


def calculate_reserved_exposure_currency(
    broker: Any,
    orders: Iterable[dict[str, Any]],
    positions: Iterable[dict[str, Any]],
) -> tuple[float, int]:
    """Price all current stops; missing stops fail closed as unpriced exposure."""
    total = 0.0
    unpriced = 0
    for item in (*tuple(orders), *tuple(positions)):
        side = str(item.get("side") or "").strip().upper()
        entry = _first_float(item, "price_open", "entry_price", "price")
        stop = _first_float(item, "sl", "stop_loss")
        volume = _first_float(item, "volume", "volume_current", "volume_initial")
        if side not in {"BUY", "SELL"} or entry is None or stop in (None, 0) or volume is None:
            unpriced += 1
            continue
        try:
            total += float(
                broker.estimate_stop_loss_account_currency(
                    side, volume, entry, float(stop)
                )
            )
        except Exception:
            unpriced += 1
    return round(total, 10), unpriced


def _first_float(source: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = source.get(key)
        if value in (None, ""):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


__all__ = [
    "V8RiskBudget",
    "V8RiskDecision",
    "calculate_reserved_exposure_currency",
    "calculate_v8_unit_risk_currency",
    "evaluate_v8_risk_budget",
]
