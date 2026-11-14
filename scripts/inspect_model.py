#!/usr/bin/env python3
"""Inspect a trained YOLO checkpoint before you swap it into the portal.

Run this on the file you just downloaded from a training run:

    python scripts/inspect_model.py                     # best.pt in the repo
    python scripts/inspect_model.py ~/Downloads/best.pt

It prints the class names the checkpoint actually carries, so you can see
whether the app will label detections correctly, plus the licence note that
comes with Ultralytics weights.

Requires ultralytics (backend/requirements-vision.txt). Nothing here talks to
the network: the weights are read from disk only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str]) -> int:
    configured = os.getenv("VISION_MODEL_PATH", "").strip()
    candidate = argv[1] if len(argv) > 1 else (configured or str(ROOT / "best.pt"))
    path = Path(candidate).expanduser()

    if not path.exists():
        print(f"No checkpoint at {path}", file=sys.stderr)
        print("Pass a path:  python scripts/inspect_model.py ~/Downloads/best.pt", file=sys.stderr)
        return 2

    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError:
        print("ultralytics is not installed.", file=sys.stderr)
        print("  python -m pip install ultralytics==8.4.20", file=sys.stderr)
        return 2

    print(f"checkpoint : {path}")
    print(f"size       : {path.stat().st_size / 1e6:.1f} MB")

    model = YOLO(str(path))
    names = getattr(model, "names", {}) or {}
    task = getattr(model, "task", "unknown")

    print(f"task       : {task}")
    print(f"classes    : {len(names)}")
    for index in sorted(names):
        print(f"  {index}: {names[index]}")

    if (path.parent / "args.yaml").exists():
        print(f"train args : {path.parent / 'args.yaml'}")
        for line in (path.parent / "args.yaml").read_text().splitlines():
            if line.startswith(("imgsz:", "epochs:", "data:", "model:", "batch:")):
                print(f"  {line}")

    print()
    print("How the portal uses this file")
    print("  * every detected box is cropped and OCR'd - the class name is only a label")
    print("  * VISION_CONFIDENCE   (default 0.35) filters weak boxes")
    print("  * VISION_IMAGE_SIZE   (default 640)  letterbox size at inference")
    print("  * VISION_MODEL_PATH   points at another checkpoint without touching git")
    print()
    print("Licence: Ultralytics weights are AGPL-3.0. Keep the repository AGPL-3.0")
    print("         and see docs/TRAINING.md before publishing a hosted build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
