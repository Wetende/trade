"""Deterministic MT5 trading mode and gate metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class TradingMode(str, Enum):
    OFF = "OFF"
    ENTRY_ONLY = "ENTRY_ONLY"
    STRADDLE_ONLY = "STRADDLE_ONLY"
    AUTO_GATED = "AUTO_GATED"


def parse_trading_mode(value: Any) -> TradingMode:
    raw = "OFF" if value in (None, "") else str(value).strip().upper()
    try:
        return TradingMode(raw)
    except ValueError as exc:
        allowed = ", ".join(mode.value for mode in TradingMode)
        raise ValueError(
            "TRADINGAGENTS_TRADING_MODE must be one of: " + allowed
        ) from exc


def mode_value(value: Any) -> str:
    return parse_trading_mode(value).value


def health_gate(
    passed: bool = True,
    reasons: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    return {"passed": bool(passed), "reasons": list(reasons or [])}


@dataclass(frozen=True)
class AccountSafety:
    require_demo: bool
    trade_mode: str | None
    passed: bool
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "require_demo": self.require_demo,
            "trade_mode": self.trade_mode,
            "passed": self.passed,
            "reason": self.reason,
        }
