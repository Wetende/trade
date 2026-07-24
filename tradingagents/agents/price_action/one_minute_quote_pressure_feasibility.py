"""Read-only feasibility audit for the M1 quote-pressure playbook."""

from __future__ import annotations

import json
import hashlib
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from typing import Any

from tradingagents.agents.price_action.post_close_fixture_collection import (
    assess_fixture_data_quality,
    parse_evidence_timestamp,
)


PROBE_NAME = "ONE_MINUTE_QUOTE_PRESSURE_FEASIBILITY_24H_V1"


@dataclass(frozen=True)
class FeasibilityConfig:
    pressure_change_count: int = 20
    pressure_window_seconds: float = 3.0
    minimum_directional_pressure: float = 0.60
    minimum_displacement_r: float = 0.10
    maximum_adverse_r: float = 0.15
    maximum_spread_multiple: float = 1.10
    maximum_stop_distance: float = 1.0
    minimum_windows: int = 1000
    minimum_sample_complete_rate: float = 0.15
    minimum_strict_feasible_rate: float = 0.05
    minimum_strict_events: int = 30
    minimum_session_coverage: float = 0.75
    session_hours: int = 3

    def __post_init__(self) -> None:
        if self.pressure_change_count < 1 or self.pressure_window_seconds <= 0:
            raise ValueError("invalid quote-pressure sample bounds")
        if self.minimum_windows < 1 or self.minimum_strict_events < 1:
            raise ValueError("invalid feasibility sample minimum")
        for name in (
            "minimum_directional_pressure",
            "minimum_displacement_r",
            "maximum_adverse_r",
            "maximum_spread_multiple",
            "minimum_sample_complete_rate",
            "minimum_strict_feasible_rate",
            "minimum_session_coverage",
        ):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and non-negative")
        if not 0 <= self.minimum_directional_pressure <= 1:
            raise ValueError("minimum_directional_pressure must be within [0, 1]")
        if not 0 <= self.minimum_session_coverage <= 1:
            raise ValueError("minimum_session_coverage must be within [0, 1]")
        if 24 % self.session_hours:
            raise ValueError("session_hours must divide 24")


def analyze_feasibility_fixture(
    fixture: dict[str, Any],
    *,
    config: FeasibilityConfig | None = None,
    evidence_role: str = "DEVELOPMENT_ONLY",
) -> dict[str, Any]:
    policy = config or FeasibilityConfig()
    start = parse_evidence_timestamp(fixture["evidence_start"])
    end = parse_evidence_timestamp(fixture["evidence_end"])
    candles = sorted(
        fixture.get("candles") or [],
        key=lambda row: parse_evidence_timestamp(row["timestamp"]),
    )
    ticks = sorted(
        fixture.get("ticks") or [],
        key=lambda row: parse_evidence_timestamp(row["time"]),
    )
    quality = assess_fixture_data_quality(
        candles,
        ticks,
        start_utc=start,
        end_utc=end,
    )

    parsed_ticks = [
        (
            parse_evidence_timestamp(row["time"]),
            float(row["bid"]),
            float(row["ask"]),
        )
        for row in ticks
    ]
    windows = []
    left = 0
    for candle in candles:
        close_time = parse_evidence_timestamp(candle["timestamp"]) + timedelta(minutes=1)
        deadline = close_time + timedelta(seconds=policy.pressure_window_seconds)
        if close_time < start or deadline > end:
            continue
        while left < len(parsed_ticks) and parsed_ticks[left][0] < close_time:
            left += 1
        cursor = left
        mids: list[float] = []
        spreads: list[float] = []
        while cursor < len(parsed_ticks) and parsed_ticks[cursor][0] <= deadline:
            _, bid, ask = parsed_ticks[cursor]
            mid = round((bid + ask) / 2.0, 10)
            if not mids or mid != mids[-1]:
                mids.append(mid)
                spreads.append(ask - bid)
                if len(mids) >= policy.pressure_change_count + 1:
                    break
            cursor += 1
        change_count = max(0, len(mids) - 1)
        complete = change_count >= policy.pressure_change_count
        strict = False
        direction = None
        pressure = 0.0
        displacement = 0.0
        adverse = 0.0
        spread_median = float(median(spreads)) if spreads else 0.0
        if complete:
            mids = mids[: policy.pressure_change_count + 1]
            spreads = spreads[: policy.pressure_change_count + 1]
            changes = [current - previous for previous, current in zip(mids, mids[1:])]
            spread_median = float(median(spreads))
            required_displacement = max(
                spread_median,
                policy.minimum_displacement_r * policy.maximum_stop_distance,
            )
            candidates = []
            for label, sign in (("BUY", 1.0), ("SELL", -1.0)):
                score = sum(change * sign > 0 for change in changes) / len(changes)
                move = (mids[-1] - mids[0]) * sign
                path_adverse = (
                    mids[0] - min(mids) if label == "BUY" else max(mids) - mids[0]
                )
                spread_ok = spread_median <= policy.maximum_spread_multiple * spreads[0]
                accepted = (
                    score >= policy.minimum_directional_pressure
                    and move >= required_displacement
                    and path_adverse <= policy.maximum_adverse_r * policy.maximum_stop_distance
                    and spread_ok
                )
                candidates.append((accepted, score, move, path_adverse, label))
            accepted = [value for value in candidates if value[0]]
            selected = max(accepted or candidates, key=lambda value: (value[0], value[1], value[2]))
            strict, pressure, displacement, adverse, direction = selected
        windows.append(
            {
                "closed_at_utc": close_time.isoformat(),
                "session_id": _session_id(close_time, policy.session_hours),
                "change_count": change_count,
                "sample_complete": complete,
                "strict_feasible": bool(strict),
                "direction": direction,
                "directional_pressure": round(pressure, 10),
                "directional_displacement": round(displacement, 10),
                "adverse_movement": round(adverse, 10),
                "median_spread": round(spread_median, 10),
            }
        )

    total = len(windows)
    complete_count = sum(row["sample_complete"] for row in windows)
    strict_count = sum(row["strict_feasible"] for row in windows)
    sessions = sorted({row["session_id"] for row in windows})
    strict_sessions = sorted(
        {row["session_id"] for row in windows if row["strict_feasible"]}
    )
    sample_rate = complete_count / total if total else 0.0
    strict_rate = strict_count / total if total else 0.0
    session_coverage = len(strict_sessions) / len(sessions) if sessions else 0.0
    change_counts = sorted(row["change_count"] for row in windows)
    metrics = {
        "eligible_windows": total,
        "sample_complete_windows": complete_count,
        "sample_complete_rate": round(sample_rate, 10),
        "strict_feasible_windows": strict_count,
        "strict_feasible_rate": round(strict_rate, 10),
        "sessions": len(sessions),
        "strict_feasible_sessions": len(strict_sessions),
        "strict_session_coverage": round(session_coverage, 10),
        "median_change_count": _percentile(change_counts, 0.50),
        "p90_change_count": _percentile(change_counts, 0.90),
        "buy_strict_windows": sum(
            row["strict_feasible"] and row["direction"] == "BUY" for row in windows
        ),
        "sell_strict_windows": sum(
            row["strict_feasible"] and row["direction"] == "SELL" for row in windows
        ),
    }
    reasons = []
    if not quality["passed"]:
        reasons.append("DATA_QUALITY_FAILED")
    if total < policy.minimum_windows:
        reasons.append("ELIGIBLE_WINDOWS_BELOW_MINIMUM")
    if sample_rate < policy.minimum_sample_complete_rate:
        reasons.append("SAMPLE_COMPLETE_RATE_BELOW_MINIMUM")
    if strict_count < policy.minimum_strict_events:
        reasons.append("STRICT_EVENTS_BELOW_MINIMUM")
    if strict_rate < policy.minimum_strict_feasible_rate:
        reasons.append("STRICT_FEASIBLE_RATE_BELOW_MINIMUM")
    if session_coverage < policy.minimum_session_coverage:
        reasons.append("STRICT_SESSION_COVERAGE_BELOW_MINIMUM")
    return {
        "schema_version": 1,
        "probe": PROBE_NAME,
        "status": "PASS" if not reasons else "FAIL",
        "decision": "FEED_FEASIBLE" if not reasons else "FEED_INFEASIBLE",
        "evidence_role": evidence_role,
        "broker_mutation_enabled": False,
        "order_capability": False,
        "evidence_start": start.isoformat(),
        "evidence_end": end.isoformat(),
        "config": asdict(policy),
        "data_quality": quality,
        "metrics": metrics,
        "reasons": reasons,
        "windows": windows,
    }


def analyze_feasibility_path(
    fixture_path: str | Path,
    *,
    config: FeasibilityConfig | None = None,
    evidence_role: str = "DEVELOPMENT_ONLY",
) -> dict[str, Any]:
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    return analyze_feasibility_fixture(
        fixture,
        config=config,
        evidence_role=evidence_role,
    )


def validate_feasibility_manifest(path: str | Path) -> dict[str, Any]:
    manifest_file = Path(path).resolve()
    payload = json.loads(manifest_file.read_text(encoding="utf-8"))
    if payload.get("probe") != PROBE_NAME or payload.get("status") != "FROZEN":
        raise ValueError("unexpected or unfrozen feasibility manifest")
    if payload.get("broker_mutation_enabled") is not False:
        raise ValueError("feasibility manifest enables broker mutation")
    config = FeasibilityConfig(**dict(payload.get("config") or {}))
    if asdict(config) != asdict(FeasibilityConfig()):
        raise ValueError("feasibility manifest differs from frozen KPI design")
    window = payload.get("evidence_window") or []
    if len(window) != 2 or parse_evidence_timestamp(window[1]) <= parse_evidence_timestamp(window[0]):
        raise ValueError("feasibility manifest evidence window is invalid")
    root = manifest_file.parents[2]
    hashes = payload.get("artifact_hashes") or {}
    if not hashes:
        raise ValueError("feasibility manifest artifact hashes are missing")
    for relative, expected in hashes.items():
        artifact = (root / relative).resolve()
        if root not in artifact.parents or not artifact.is_file():
            raise ValueError(f"feasibility artifact missing: {relative}")
        if _sha256_file(artifact) != expected:
            raise ValueError(f"feasibility artifact hash mismatch: {relative}")
    return payload


def _session_id(value: datetime, hours: int) -> str:
    bucket = value.hour - value.hour % hours
    return value.replace(hour=bucket, minute=0, second=0, microsecond=0).isoformat()


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, max(0, math.ceil(quantile * len(values)) - 1))
    return int(values[index])


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "FeasibilityConfig",
    "PROBE_NAME",
    "analyze_feasibility_fixture",
    "analyze_feasibility_path",
    "validate_feasibility_manifest",
]
