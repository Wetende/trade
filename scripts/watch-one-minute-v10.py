"""Read-only chronological evidence watcher for the frozen M1 V10 candidate."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


FOLDS = (
    ("2026-07-22T20:00:00+00:00", "2026-07-23T12:00:00+00:00"),
    ("2026-07-23T12:00:00+00:00", "2026-07-24T04:00:00+00:00"),
    ("2026-07-24T04:00:00+00:00", "2026-07-24T20:00:00+00:00"),
)
HELD_OUT = ("2026-07-26T22:00:00+00:00", "2026-07-28T00:00:00+00:00")


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


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


def _run(command: list[str], root: Path, log: Path) -> str:
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
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(command[1:4])}"
        )
    return completed.stdout


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=int, default=600)
    parser.add_argument("--max-cycles", type=int, default=2016)
    args = parser.parse_args()
    if args.poll_seconds < 60 or args.max_cycles < 1:
        raise SystemExit("invalid watcher bounds")
    root = args.root.resolve()
    python = root / ".venv" / "Scripts" / "python.exe"
    manifest = root / "docs" / "analysis" / "2026-07-22-one-minute-causal-reclaim-v10-manifest.json"
    runtime = root / "runtime" / "one-minute-v10-evidence"
    evidence = root / "results" / "one-minute-causal-reclaim-v10-evidence"
    reports = root / "reports"
    heartbeat = runtime / "heartbeat.json"
    stop_file = runtime / "watch.stop"
    log = runtime / "watch.log"
    runtime.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    fold_paths = tuple(
        evidence / f"discovery-fold-{index}-v10.json"
        for index in range(1, len(FOLDS) + 1)
    )
    discovery_report = reports / "2026-07-24-one-minute-causal-reclaim-v10-discovery.json"
    heldout_fixture = evidence / "held-out-v10.json"
    heldout_report = reports / "2026-07-28-one-minute-causal-reclaim-v10-held-out.json"
    registration = reports / "2026-07-28-one-minute-causal-reclaim-v10-prospective-registration.json"

    for cycle in range(1, args.max_cycles + 1):
        if stop_file.exists():
            break
        now = datetime.now(timezone.utc)
        status = "WAITING_DISCOVERY"
        reason = None
        probe = None
        try:
            _run(
                [str(python), str(root / "scripts" / "freeze-one-minute-v10.py"), "--output", str(manifest), "--verify"],
                root,
                log,
            )
            probe = json.loads(
                _run([str(python), "-m", "cli.main", "broker-probe", "--json-only"], root, log)
            )
            safe = (
                probe.get("connected") is True
                and (probe.get("account_safety") or {}).get("trade_mode") == "DEMO"
                and probe.get("open_order_count") == 0
                and probe.get("open_position_count") == 0
            )
            if not safe:
                raise RuntimeError("DEMO safety or flat-state proof failed")

            for index, ((start, end), output) in enumerate(zip(FOLDS, fold_paths), 1):
                if now >= _utc(end) and not output.exists():
                    _run(
                        [str(python), "-m", "cli.main", "one-minute-post-close-collect", "--start", start, "--end", end, "--output", str(output), "--context-candles", "60"],
                        root,
                        log,
                    )
                if not output.exists():
                    status = f"WAITING_DISCOVERY_FOLD_{index}"
                    break
            else:
                if not discovery_report.exists():
                    command = [str(python), "-m", "cli.main", "one-minute-v10-screen"]
                    for value in fold_paths:
                        command.extend(["--fixture", str(value)])
                    command.extend(["--manifest", str(manifest), "--stage", "DISCOVERY", "--as-of-utc", now.isoformat(), "--output", str(discovery_report)])
                    _run(command, root, log)
                discovery = json.loads(discovery_report.read_text(encoding="utf-8"))
                if discovery.get("status") != "PASS":
                    status = "RETIRED_DISCOVERY_FAIL"
                elif now < _utc(HELD_OUT[1]):
                    status = "WAITING_HELD_OUT_COMPLETION"
                else:
                    if not heldout_fixture.exists():
                        _run(
                            [str(python), "-m", "cli.main", "one-minute-post-close-collect", "--start", HELD_OUT[0], "--end", HELD_OUT[1], "--output", str(heldout_fixture), "--context-candles", "60"],
                            root,
                            log,
                        )
                    if not heldout_report.exists():
                        _run(
                            [str(python), "-m", "cli.main", "one-minute-v10-screen", "--fixture", str(heldout_fixture), "--manifest", str(manifest), "--stage", "HELD_OUT", "--discovery-report", str(discovery_report), "--as-of-utc", now.isoformat(), "--output", str(heldout_report)],
                            root,
                            log,
                        )
                    heldout = json.loads(heldout_report.read_text(encoding="utf-8"))
                    if heldout.get("status") != "PASS":
                        status = "RETIRED_HELD_OUT_FAIL"
                    else:
                        if not registration.exists():
                            _run(
                                [str(python), "-m", "cli.main", "one-minute-v10-register-prospective", "--manifest", str(manifest), "--held-out-report", str(heldout_report), "--output", str(registration)],
                                root,
                                log,
                            )
                        status = "PROSPECTIVE_REGISTERED"
        except Exception as exc:  # watcher must preserve a terminal diagnostic
            status = "FAILED"
            reason = f"{type(exc).__name__}: {exc}"

        _atomic_json(
            heartbeat,
            {
                "schema_version": 1,
                "heartbeat_utc": now.isoformat(),
                "cycle": cycle,
                "candidate": "ONE_MINUTE_CAUSAL_RECLAIM_V10",
                "status": status,
                "reason": reason,
                "broker_mutation_enabled": False,
                "probe": probe,
                "manifest": str(manifest),
                "discovery_report": str(discovery_report) if discovery_report.exists() else None,
                "held_out_report": str(heldout_report) if heldout_report.exists() else None,
                "prospective_registration": str(registration) if registration.exists() else None,
            },
        )
        if status.startswith("RETIRED_") or status in {"FAILED", "PROSPECTIVE_REGISTERED"}:
            return 0 if status != "FAILED" else 1
        time.sleep(args.poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

