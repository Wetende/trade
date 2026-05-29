"""Shared BUY/SELL/HOLD parsing helpers."""

from __future__ import annotations

import re


_ACTION_LABEL_RE = re.compile(
    r"^\s*(?:[-*]\s*)?(?:\*\*)?(?:Action|Recommendation|Decision)(?:\*\*)?\s*:\s*"
    r"(BUY|SELL|HOLD)\b",
    re.IGNORECASE | re.MULTILINE,
)


def normalize_trade_action(value: str, default: str = "HOLD") -> str:
    action = (value or default).strip().upper()
    if action in {"BUY", "SELL", "HOLD"}:
        return action
    return "HOLD"


def parse_trade_action(text: str, default: str = "HOLD") -> str:
    if not text:
        return normalize_trade_action(default)

    match = _ACTION_LABEL_RE.search(text)
    if match:
        return match.group(1).upper()

    return normalize_trade_action(default)
