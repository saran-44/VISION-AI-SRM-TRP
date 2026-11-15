#!/usr/bin/env python3
"""Collect one copyable report of what this gate PC is doing.

    python scripts/gate_report.py                     # print it
    python scripts/gate_report.py --out report.txt    # save it, to attach
    python scripts/gate_report.py --deep              # also load the detector
    python scripts/gate_report.py --clear             # empty the error log

The report holds the version, the configuration (credentials masked), the
vision settings, what the camera answered, the preflight checks, the recorded
errors and the scans that produced no number. Paste it as one block.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect a VisionAI gate report")
    parser.add_argument("--out", default="", help="write the report here as well as printing it")
    parser.add_argument("--deep", action="store_true", help="run the slow preflight checks (~10 s)")
    parser.add_argument("--errors", type=int, default=20, help="how many recorded errors to include")
    parser.add_argument("--scans", type=int, default=15, help="how many failed scans to include")
    parser.add_argument("--env-file", default="", help="load this .env first (the gate config)")
    parser.add_argument("--clear", action="store_true", help="empty the error log after reporting")
    args = parser.parse_args(argv)

    if args.env_file:
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(args.env_file).expanduser(), override=True)
        except ImportError:
            print("python-dotenv is required for --env-file", file=sys.stderr)
            return 2

    from backend.report import build_report
    from backend import diagnostics

    text = build_report(deep=args.deep, errors=args.errors, scans=args.scans)
    print(text)

    if args.out:
        target = Path(args.out).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(f"\nwritten to {target.resolve()}", file=sys.stderr)

    if args.clear:
        removed = diagnostics.clear()
        print(f"cleared {removed} recorded block(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
