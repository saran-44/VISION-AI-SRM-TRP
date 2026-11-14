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


def _grab_webcam(
    index: int,
    frames: int,
    save: str | None,
    width: int = 1280,
    height: int = 720,
) -> Path | None:
    """Grab the sharpest of a few webcam frames and write it to disk.

    The capture size is requested explicitly: OpenCV's default is 640×480, and
    upscaling that to the 960 px letterbox only adds blur. A webcam that cannot
    deliver the requested size is reported, not silently accepted.
    """
    try:
        import cv2  # type: ignore
    except ImportError:
        print("OpenCV is needed to read the webcam:", file=sys.stderr)
        print("  python -m pip install opencv-python-headless==4.10.0.84", file=sys.stderr)
        return None

    capture = cv2.VideoCapture(index)
    if not capture.isOpened():
        print(f"Could not open camera {index}.", file=sys.stderr)
        print("Close Teams/Zoom/Camera first - Windows only lets one app hold the webcam.", file=sys.stderr)
        return None

    # Ask for the resolution before the first read; most drivers honour it.
    capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    negotiated = (
        int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0),
        int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0),
    )

    best = None
    best_score = -1.0
    try:
        # The first frames after opening are usually dark while exposure settles.
        for _ in range(max(1, frames)):
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            score = float(cv2.Laplacian(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var())
            if score > best_score:
                best, best_score = frame, score
    finally:
        capture.release()

    if best is None:
        print("The camera opened but returned no frame.", file=sys.stderr)
        return None

    if save:
        target = Path(save).expanduser()
    else:
        from datetime import datetime
        target = Path.cwd() / f"frame-{datetime.now():%Y%m%d-%H%M%S}.jpg"
    if not cv2.imwrite(str(target), best):
        print(f"Could not write {target}", file=sys.stderr)
        return None
    print(f"saved       : {target}  (sharpness {best_score:.0f})")
    print("             keep this file - it is what the detector saw")
    actual = (best.shape[1], best.shape[0])
    if actual[0] < 900:
        print(
            f"camera      : delivered {actual[0]}×{actual[1]} although {width}×{height} was requested.",
            file=sys.stderr,
        )
        print(
            "             A 640×480 frame upscaled to 960 px only adds blur; try "
            f"--width 1920 --height 1080, or a phone photo instead.",
            file=sys.stderr,
        )
    else:
        print(f"camera      : {actual[0]}×{actual[1]}")
    print()
    return target


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _scan_folder(folder: Path, overrides, as_json: bool) -> int:
    """Scan every image in a folder — the fastest way to tune the thresholds.

    One line per frame, then a summary. Ten real gate frames answer "is the
    recall good enough?" in a way one lucky frame never can.
    """
    from backend.vision import VisionUnavailable, best_identification, decode_image, detect

    if not folder.is_dir():
        print(f"Not a folder: {folder}", file=sys.stderr)
        return 2
    files = sorted(path for path in folder.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    if not files:
        print(f"No images in {folder} ({', '.join(sorted(IMAGE_SUFFIXES))})", file=sys.stderr)
        return 2

    rows = []
    reasons: dict[str, int] = {}
    cascades: dict[str, int] = {}
    for path in files:
        try:
            result = detect(decode_image(path.read_bytes()), stages=overrides)
        except VisionUnavailable as exc:
            print(f"Detector unavailable: {exc}", file=sys.stderr)
            print("Install the extras: python -m pip install -r backend/requirements-vision.txt", file=sys.stderr)
            return 2
        candidate = best_identification(result)
        vehicle = result.vehicle or {}
        rows.append({
            "file": path.name,
            "reason": result.reason,
            "cascade": result.cascade,
            "bus_number": candidate.bus_number if candidate and candidate.bus_number else None,
            "confidence": round(candidate.confidence, 4) if candidate else None,
            "vehicle": vehicle.get("label"),
        })
        reasons[result.reason] = reasons.get(result.reason, 0) + 1
        cascades[result.cascade] = cascades.get(result.cascade, 0) + 1

    if as_json:
        print(json.dumps(rows, indent=2))
        return 0

    print(f"{folder}  ({len(rows)} image{'s' if len(rows) != 1 else ''})")
    for row in rows:
        number = row["bus_number"] or "-"
        confidence = f"{row['confidence']:.2f}" if row["confidence"] is not None else "-"
        print(
            f"  {row['file']:<28} {row['reason']:<15} {row['cascade']:<13} "
            f"{number:<16} {confidence:<5} {row['vehicle'] or '-'}"
        )
    read = sum(1 for row in rows if row["bus_number"])
    print()
    print(f"summary: {read}/{len(rows)} frames produced a number")
    print("  reasons: " + ", ".join(f"{key}={value}" for key, value in sorted(reasons.items())))
    print("  read by: " + ", ".join(f"{key}={value}" for key, value in sorted(cascades.items())))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan one image (or a live webcam frame) with the bus-sticker detector",
        epilog="Examples:\n"
               "  python scripts/scan_image.py frame.jpg\n"
               "  python scripts/scan_image.py --camera 0            # this laptop's webcam\n"
               "  python scripts/scan_image.py --camera 0 --conf 0.15 --imgsz 1280\n"
               "  python scripts/scan_image.py --dir frames/        # one line per frame",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("image", nargs="?", help="path to a JPEG/PNG frame")
    parser.add_argument("--camera", type=int, default=None,
                        help="grab a frame from a local webcam instead (OpenCV index, usually 0)")
    parser.add_argument("--frames", type=int, default=5, help="frames to sample from the webcam (best is kept)")
    parser.add_argument("--width", type=int, default=1280, help="requested capture width (default 1280)")
    parser.add_argument("--height", type=int, default=720, help="requested capture height (default 720)")
    parser.add_argument("--save", default=None, help="where to write the webcam frame (default frame-<time>.jpg)")
    parser.add_argument("--conf", type=float, default=None, help="override VISION_CONFIDENCE")
    parser.add_argument("--imgsz", type=int, default=None, help="override VISION_IMAGE_SIZE")
    parser.add_argument(
        "--stages",
        default=None,
        help=(
            "which cascade stages to run, e.g. \"sticker=0,vehicle=1\" or \"plate\". "
            "Names: sticker, plate, vehicle. Omitted stages keep the VISION_STAGE_* default."
        ),
    )
    parser.add_argument(
        "--dir",
        default=None,
        help="scan every image in this folder and print one line per frame (tuning mode)",
    )
    parser.add_argument("--json", action="store_true", help="print the raw response instead of a summary")
    args = parser.parse_args(argv)

    if not args.image and args.camera is None and not args.dir:
        parser.print_help()
        print("\nGive a file, or use --camera 0 to grab one from the webcam.", file=sys.stderr)
        return 2

    if args.conf is not None:
        os.environ["VISION_CONFIDENCE"] = str(args.conf)
    if args.imgsz is not None:
        os.environ["VISION_IMAGE_SIZE"] = str(args.imgsz)

    from backend.vision import (
        STAGE_LABELS,
        VisionUnavailable,
        best_identification,
        decode_image,
        detect,
        stage_overrides_from_payload,
    )

    overrides = stage_overrides_from_payload({"stages": args.stages}) if args.stages else None

    if args.dir:
        return _scan_folder(Path(args.dir).expanduser(), overrides, args.json)

    if args.camera is not None:
        grabbed = _grab_webcam(args.camera, args.frames, args.save, args.width, args.height)
        if grabbed is None:
            return 2
        path = grabbed
    else:
        path = Path(args.image).expanduser()
        if not path.exists():
            print(f"No such file: {path}", file=sys.stderr)
            print("Use --camera 0 to grab a frame from this machine's webcam,", file=sys.stderr)
            print("or the \"Save frame\" button on the Test Lab camera tile.", file=sys.stderr)
            return 2

    try:
        image = decode_image(path.read_bytes())
        # "sticker=0,vehicle=1" and "plate" are both accepted; see --stages.
        result = detect(image, stages=overrides)
    except VisionUnavailable as exc:
        print(f"Detector unavailable: {exc}", file=sys.stderr)
        print("Install the extras: python -m pip install -r backend/requirements-vision.txt", file=sys.stderr)
        return 2

    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    candidate = best_identification(result)
    print(f"image       : {path} ({result.frame_width}×{result.frame_height})")
    print(f"model       : {result.model}  @ {result.image_size}px, threshold {result.threshold:.2f}")
    print(f"inference   : {result.inference_ms} ms")
    print(f"boxes       : {result.boxes_total} found, {result.boxes_above_threshold} above threshold, best {result.best_confidence:.2f}")
    print(f"class filter: only class {result.sticker_class} is OCR'd"
          + (f" ({result.boxes_other_class} box(es) of other classes were ignored)" if result.boxes_other_class else ""))
    for box in payload["candidates"]:
        print(f"  · {box['class_name']:<12} {box['confidence']:.2f}  bbox={box['bbox']}  text={box['raw_text']!r}")
    for stage in payload["stages"]:
        state = (
            f"skipped: {stage['skipped']}"
            if stage["skipped"]
            else f"ran in {stage['ms']} ms, {stage['found']} box(es), {stage['result']}"
        )
        print(f"stage       : {STAGE_LABELS.get(stage['name'], stage['name']):<13} {state}")
        if stage["skipped"] and stage["detail"]:
            print(f"              {stage['detail']}")
    vehicle = payload.get("vehicle")
    if vehicle:
        print(f"vehicle     : {vehicle['label']} ({vehicle['class_name']}, {vehicle['confidence']:.2f})")
    print()
    if candidate and candidate.bus_number:
        print(f"RESULT      : {candidate.bus_number}  ({candidate.confidence:.2f}, via {result.cascade})")
    else:
        print(f"RESULT      : no bus number — reason={result.reason}")
        print(f"ADVICE      : {result.advice}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
