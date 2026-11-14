#!/usr/bin/env python3
"""Download a vehicle-classification checkpoint for the third cascade stage.

The vehicle stage needs a COCO-style YOLO model. Ultralytics publishes one under
an AGPL-3.0 licence; this script fetches it *into `weights/`* (git-ignored) so the
repository itself stays free of binary weights:

    python scripts/fetch_vehicle_model.py
    python scripts/fetch_vehicle_model.py --model yolo11s.pt   # larger, slower

Then the stage reports `bus`, `car`, `bike` and `truck` on every scan. Without
the file the stage is skipped with `skipped: model_missing` — nothing breaks.

Nothing here uploads your data: the only network call is the one Ultralytics
makes to download the published weights.
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT / "weights"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="yolo11n.pt", help="Ultralytics checkpoint name (default yolo11n.pt)")
    parser.add_argument("--force", action="store_true", help="overwrite an existing weights/vehicle.pt")
    args = parser.parse_args()

    target = TARGET_DIR / "vehicle.pt"
    if target.exists() and not args.force:
        print(f"Already present: {target}")
        print("Use --force to replace it.")
        return 0

    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        print("ultralytics is not installed.", file=sys.stderr)
        print("  python -m pip install -r backend/requirements-vision.txt", file=sys.stderr)
        return 2

    print(f"Downloading {args.model} (the first run fetches it once, ~6 MB)…")
    try:
        model = YOLO(args.model)
    except Exception as exc:  # network error, wrong name, corrupt download
        print(f"Could not load {args.model}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    names = getattr(model, "names", {}) or {}
    wanted = {name for name in names.values() if name in {"bus", "car", "truck", "motorcycle", "bicycle"}}
    if not wanted:
        print("That checkpoint carries no vehicle classes; pick a COCO model.", file=sys.stderr)
        return 2

    source = Path(args.model)
    if not source.exists():
        # Ultralytics resolved the weights somewhere else; ask it where.
        source = Path(getattr(model, "ckpt_path", "") or args.model)
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    if source.exists() and source.resolve() != target.resolve():
        shutil.move(str(source), str(target))
    elif not target.exists():
        print(f"Could not find the downloaded file for {args.model}.", file=sys.stderr)
        return 2

    print(f"Saved {target} ({target.stat().st_size / 1_000_000:.1f} MB)")
    print("Vehicle classes:", ", ".join(sorted(wanted)))
    print()
    print("The stage now classifies on every scan. Check it with:")
    print("  python scripts/scan_image.py --camera 0 --stages vehicle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
