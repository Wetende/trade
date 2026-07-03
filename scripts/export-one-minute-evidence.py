"""Export sanitized One Minute Scalper evidence fixtures."""

from __future__ import annotations

import argparse
from pathlib import Path

from tradingagents.agents.price_action.evidence_export import export_session


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in args.session:
        session = export_session(source)
        target = output_dir / f"{session.session_id}.json"
        target.write_text(
            session.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
