#!/usr/bin/env python3
"""Run the detector on one saved photograph — no server, no browser.

This is the fastest way to answer "is the sticker being detected at all?".
Point a phone or the gate camera at the sticker, save the frame, then:

    python scripts/scan_image.py frame.jpg
    python scripts/scan_image.py frame.jpg --conf 0.15 --imgsz 1280

It prints what the model found, the best confidence, what the OCR read, and the
same reason/advice the API returns. Requires the vision extras and a model:

    python -m pip install -r backend/requirements-vision.txt
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan one image with the bus-sticker detector")
    parser.add_argument("image", help="path to a JPEG/PNG frame")
    parser.add_argument("--conf", type=float, default=None, help="override VISION_CONFIDENCE")
    parser.add_argument("--imgsz", type=int, default=None, help="override VISION_IMAGE_SIZE")
    parser.add_argument("--json", action="store_true", help="print the raw response instead of a summary")
    args = parser.parse_args(argv)

    if args.conf is not None:
        os.environ["VISION_CONFIDENCE"] = str(args.conf)
    if args.imgsz is not None:
        os.environ["VISION_IMAGE_SIZE"] = str(args.imgsz)

    from backend.vision import VisionUnavailable, best_candidate, decode_image, detect

    path = Path(args.image).expanduser()
    if not path.exists():
        print(f"No such file: {path}", file=sys.stderr)
        return 2

    try:
        image = decode_image(path.read_bytes())
        result = detect(image)
    except VisionUnavailable as exc:
        print(f"Detector unavailable: {exc}", file=sys.stderr)
        print("Install the extras: python -m pip install -r backend/requirements-vision.txt", file=sys.stderr)
        return 2

    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    candidate = best_candidate(result)
    print(f"image       : {path} ({result.frame_width}×{result.frame_height})")
    print(f"model       : {result.model}  @ {result.image_size}px, threshold {result.threshold:.2f}")
    print(f"inference   : {result.inference_ms} ms")
    print(f"boxes       : {result.boxes_total} found, {result.boxes_above_threshold} above threshold, best {result.best_confidence:.2f}")
    for box in payload["candidates"]:
        print(f"  · {box['class_name']:<12} {box['confidence']:.2f}  bbox={box['bbox']}  text={box['raw_text']!r}")
    print()
    if candidate and candidate.bus_number:
        print(f"RESULT      : {candidate.bus_number}  ({candidate.confidence:.2f})")
    else:
        print(f"RESULT      : no bus number — reason={result.reason}")
        print(f"ADVICE      : {result.advice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
