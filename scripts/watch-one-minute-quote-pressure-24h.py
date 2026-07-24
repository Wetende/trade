"""Read-only watcher for the frozen 24-hour quote-pressure feasibility gate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


START = "2026-07-26T22:00:00+00:00"
END = "2026-07-27T22:00:00+00:00"


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(timezone.utc)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _run(command: list[str], root: Path, log: Path) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    with log.open("a", encoding="utf-8") as handle:
        handle.write(
            f"{datetime.now(timezone.utc).isoformat()} exit={completed.returncode} "
            f"command={' '.join(command[1:4])}\n"
        )
        if completed.stderr:
            handle.write(completed.stderr[-4000:] + "\n")
    return completed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=int, default=600)
    parser.add_argument("--max-cycles", type=int, default=1008)
    args = parser.parse_args()
    if args.poll_seconds < 60 or args.max_cycles < 1:
        raise SystemExit("invalid watcher bounds")
    root = args.root.resolve()
    python = root / ".venv" / "Scripts" / "python.exe"
    manifest = root / "docs" / "analysis" / "2026-07-24-one-minute-quote-pressure-24h-manifest.json"
    runtime = root / "runtime" / "one-minute-quote-pressure-24h"
    fixture = root / "results" / "one-minute-quote-pressure-24h" / "future-24h.json"
    report = root / "reports" / "2026-07-27-one-minute-quote-pressure-24h-feasibility.json"
    heartbeat = runtime / "heartbeat.json"
    stop_file = runtime / "watch.stop"
    log = runtime / "watch.log"
    runtime.mkdir(parents=True, exist_ok=True)
    fixture.parent.mkdir(parents=True, exist_ok=True)

    for cycle in range(1, args.max_cycles + 1):
        if stop_file.exists():
            return 0
        now = datetime.now(timezone.utc)
        status = "WAITING_WINDOW_START"
        reason = None
        probe = None
        try:
            verified = _run(
                [str(python), str(root / "scripts" / "freeze-one-minute-quote-pressure-24h.py"), "--output", str(manifest), "--verify"],
                root,
                log,
            )
            if verified.returncode:
                raise RuntimeError("frozen feasibility manifest verification failed")
            broker_result = _run(
                [str(python), "-m", "cli.main", "broker-probe", "--json-only"],
                root,
                log,
            )
            if broker_result.returncode == 0:
                probe = json.loads(broker_result.stdout)
                account_safety = probe.get("account_safety") or {}
                if probe.get("connected") is not True or account_safety.get("passed") is not True:
                    probe = None
                    status = "WAITING_BROKER_CONNECTIVITY"
                    reason = "broker probe is not connected and safety-approved"
                else:
                    trade_mode = account_safety.get("trade_mode")
                    if trade_mode != "DEMO":
                        raise RuntimeError("account is not DEMO")
                    if probe.get("open_order_count") or probe.get("open_position_count"):
                        raise RuntimeError("DEMO account is not flat")
            else:
                status = "WAITING_BROKER_CONNECTIVITY"

            if probe is not None:
                if now < _utc(START):
                    status = "WAITING_WINDOW_START"
                elif now < _utc(END):
                    status = "COLLECTING_FUTURE_24H"
                else:
                    if not fixture.exists():
                        collection = _run(
                            [str(python), "-m", "cli.main", "one-minute-post-close-collect", "--start", START, "--end", END, "--output", str(fixture), "--context-candles", "60", "--attempts", "5", "--retry-seconds", "60"],
                            root,
                            log,
                        )
                        if collection.returncode:
                            status = "RETRYING_VERIFIED_COLLECTION"
                            reason = f"collection_exit_{collection.returncode}"
                    if fixture.exists() and not report.exists():
                        screened = _run(
                            [str(python), "-m", "cli.main", "one-minute-quote-pressure-feasibility", "--fixture", str(fixture), "--output", str(report), "--evidence-role", "FUTURE_24H", "--manifest", str(manifest)],
                            root,
                            log,
                        )
                        if screened.returncode:
                            status = "RETRYING_FEASIBILITY_SCREEN"
                            reason = f"screen_exit_{screened.returncode}"
                    if report.exists():
                        result = json.loads(report.read_text(encoding="utf-8"))
                        status = (
                            "COMPLETE_FEED_FEASIBLE"
                            if result.get("status") == "PASS"
                            else "COMPLETE_FEED_INFEASIBLE"
                        )
        except Exception as exc:
            status = "SAFETY_BLOCKED"
            reason = f"{type(exc).__name__}: {exc}"

        _atomic_json(
            heartbeat,
            {
                "schema_version": 1,
                "heartbeat_utc": now.isoformat(),
                "cycle": cycle,
                "probe": "ONE_MINUTE_QUOTE_PRESSURE_FEASIBILITY_24H_V1",
                "status": status,
                "reason": reason,
                "broker_mutation_enabled": False,
                "order_capability": False,
                "evidence_start": START,
                "evidence_end": END,
                "broker": probe,
                "fixture": str(fixture) if fixture.exists() else None,
                "report": str(report) if report.exists() else None,
            },
        )
        if status.startswith("COMPLETE_") or status == "SAFETY_BLOCKED":
            return 0 if status.startswith("COMPLETE_") else 1
        time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
