"""Create or verify the frozen M1 quote-pressure 24-hour probe manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from tradingagents.agents.price_action.one_minute_quote_pressure_feasibility import (
    FeasibilityConfig,
    PROBE_NAME,
)


WINDOW = ("2026-07-26T22:00:00+00:00", "2026-07-27T22:00:00+00:00")
ARTIFACTS = (
    "cli/main.py",
    "docs/superpowers/specs/2026-07-24-one-minute-quote-pressure-24h-feasibility.md",
    "reports/2026-07-24-quote-pressure-feasibility-development-fold1.json",
    "reports/2026-07-24-quote-pressure-feasibility-development-fold2.json",
    "reports/2026-07-24-quote-pressure-feasibility-development-fold3.json",
    "scripts/freeze-one-minute-quote-pressure-24h.py",
    "scripts/start-one-minute-quote-pressure-24h.ps1",
    "scripts/watch-one-minute-quote-pressure-24h.py",
    "tradingagents/agents/price_action/one_minute_quote_pressure_feasibility.py",
    "tradingagents/agents/price_action/post_close_fixture_collection.py",
    "tradingagents/brokers/mode_gate.py",
    "tradingagents/brokers/mt5.py",
    "tests/test_one_minute_quote_pressure_feasibility.py",
    "tests/test_post_close_fixture_collection.py",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path, frozen_at_utc: str) -> dict:
    missing = [relative for relative in ARTIFACTS if not (root / relative).is_file()]
    if missing:
        raise ValueError("missing feasibility artifacts: " + ", ".join(missing))
    return {
        "schema_version": 1,
        "probe": PROBE_NAME,
        "status": "FROZEN",
        "frozen_at_utc": frozen_at_utc,
        "evidence_window": list(WINDOW),
        "evidence_role": "FUTURE_24H",
        "broker_mutation_enabled": False,
        "order_capability": False,
        "promotion_capability": False,
        "config": asdict(FeasibilityConfig()),
        "pass_action": "PERMIT_SEPARATELY_NAMED_V11_DEVELOPMENT_ONLY",
        "fail_action": "REQUIRE_EXPLICIT_PLAYBOOK_REVISION_OR_STOP",
        "data_quality": {
            "minimum_tick_minute_candle_coverage": 0.995,
            "unique_candle_timestamps": True,
            "retry_incomplete_recent_partition": True,
            "demo_read_only_flat_required": True,
        },
        "artifact_hashes": {
            relative: _sha256(root / relative) for relative in sorted(ARTIFACTS)
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frozen-at-utc")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output.resolve()
    if args.verify:
        current = json.loads(output.read_text(encoding="utf-8"))
        expected = build_manifest(root, str(current["frozen_at_utc"]))
        if current != expected:
            raise SystemExit("24-hour feasibility manifest verification failed")
        print(json.dumps({"status": "VERIFIED", "manifest": str(output)}, indent=2))
        return 0
    frozen_at = args.frozen_at_utc or datetime.now(timezone.utc).isoformat()
    if datetime.fromisoformat(frozen_at.replace("Z", "+00:00")) >= datetime.fromisoformat(WINDOW[0]):
        raise SystemExit("feasibility freeze must predate the future window")
    payload = build_manifest(root, frozen_at)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(json.dumps({"status": "FROZEN", "manifest": str(output)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
