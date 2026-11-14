#!/usr/bin/env python3
"""Describe what a frame actually contains, in text.

`scan_image.py` answers "did the model read a number?". When the answer is "no
box at all" the next question is always the same — *what was in the frame?* —
and on a laptop that is not the machine you are debugging from, the PNG is
unreachable. This prints the numbers plus a small luminance map, so the frame
can be read as text:

    python scripts/frame_report.py frames/gate/g01.jpg
    python scripts/frame_report.py frames/gate            # every image in it
    python scripts/frame_report.py frames/gate --limit 4

`sharpness` uses the same Laplacian variance that `scan_image.py` prints when it
saves a webcam frame, so the two numbers are directly comparable. Uses Pillow
only; numpy is used for the gradient numbers when it is installed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Dark to bright. Ten steps is enough to see a bus, a hand, or an empty room.
RAMP = " .:-=+*#%@"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def _laplacian(gray):
    """The 4-neighbour Laplacian as a 2-D float array, or None without numpy."""
    try:
        import numpy as np
    except ImportError:
        return None
    pixels = np.asarray(gray, dtype=np.float64)
    if pixels.ndim != 2 or min(pixels.shape) < 3:
        return None
    return (
        -4.0 * pixels[1:-1, 1:-1]
        + pixels[:-2, 1:-1]
        + pixels[2:, 1:-1]
        + pixels[1:-1, :-2]
        + pixels[1:-1, 2:]
    )


def sharpness(gray) -> float | None:
    """Laplacian variance — the number `scan_image.py` reports as sharpness."""
    lap = _laplacian(gray)
    if lap is None:
        return None
    return float(lap.var())


def edge_fraction(gray, threshold: float = 20.0) -> float | None:
    """Share of pixels carrying a real edge — detail, not just brightness."""
    lap = _laplacian(gray)
    if lap is None or lap.size == 0:
        return None
    return float((abs(lap) > threshold).mean())


def _map(gray, width: int) -> str:
    """A luminance map sized to terminal text: bright pixels become '@'."""
    rows = int(round(width * gray.height / max(1, gray.width) / 2.0))
    rows = max(6, min(24, rows))
    thumb = gray.resize((width, rows))
    pixels = list(thumb.tobytes())  # mode "L": one byte per pixel
    last = len(RAMP) - 1
    return "\n".join(
        "".join(RAMP[min(last, pixel * len(RAMP) // 256)] for pixel in pixels[start:start + width])
        for start in range(0, rows * width, width)
    )


def verdict(mean: float, spread: float, sharp: float | None, edges: float | None) -> str:
    """One sentence a person can act on."""
    if spread < 8.0:
        return "nearly uniform — the lens is covered, or the subject is not in shot at all"
    problems = []
    if mean < 45.0:
        problems.append("too dark (turn a light on: the sticker is a smudge at this brightness)")
    if sharp is not None and sharp < 60.0:
        problems.append("too soft (autofocus has not settled, or the subject is inside the lens' near limit)")
    elif sharp is not None and sharp < 150.0:
        problems.append("soft — fine for framing, weak for a sticker a few dozen pixels wide")
    if edges is not None and edges < 0.01:
        problems.append("almost no detail")
    return "; ".join(problems) if problems else "sharp enough for the detector"


def report(path: Path, width: int = 64) -> int:
    try:
        from PIL import Image, ImageStat
    except ImportError:
        print("Pillow is needed to read frames:", file=sys.stderr)
        print("  python -m pip install -r backend/requirements-vision.txt", file=sys.stderr)
        return 2

    if not path.exists():
        print(f"{path}: no such file", file=sys.stderr)
        return 2
    try:
        with Image.open(path) as opened:
            opened.load()
            image = opened.copy()
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same answer
        print(f"{path}: not a readable image ({exc})", file=sys.stderr)
        return 2

    gray = image.convert("L")
    stat = ImageStat.Stat(gray)
    mean, spread = float(stat.mean[0]), float(stat.stddev[0])
    histogram = gray.histogram()
    total = max(1, gray.width * gray.height)
    dark = sum(histogram[:32]) / total
    blown = sum(histogram[240:]) / total
    sharp = sharpness(gray)
    edges = edge_fraction(gray)

    print(f"{path}  ({image.width}×{image.height}, {path.stat().st_size // 1024} KB)")
    print(f"  brightness : mean {mean:.1f}, spread {spread:.1f}  (dark {dark:.0%}, blown {blown:.0%})")
    if sharp is None:
        print("  sharpness  : unknown (install numpy for the gradient numbers)")
    else:
        print(f"  sharpness  : {sharp:.0f}  (Laplacian variance — the same number scan_image.py prints)")
    if edges is not None:
        print(f"  detail     : {edges:.1%} of pixels carry an edge")
    print(f"  verdict    : {verdict(mean, spread, sharp, edges)}")
    print("  luminance map (bright '@', dark '.'):")
    for line in _map(gray, width).splitlines():
        print(f"  |{line}|")
    print()
    return 0


def _expand(target: Path, limit: int) -> list[Path]:
    """Files to report. A folder is listed newest first: the frame you want is
    the one the scan just failed on, not the oldest in failed-frames/."""
    if not target.exists():
        print(
            f"{target}: no such file or folder.\n"
            "  The failed-frames folder is created by the first scan that reads no "
            "number, so run a scan on the portal first.",
            file=sys.stderr,
        )
        return []
    if target.is_dir():
        files = sorted(
            (item for item in target.iterdir() if item.suffix.lower() in IMAGE_SUFFIXES),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        if not files:
            print(f"{target}: no frames in here yet (a scan that reads no number writes one)")
            return []
        return files[:limit] if limit else files
    return [target]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print what is in a frame: brightness, sharpness, and an ASCII luminance map",
        epilog="Examples:\n"
               "  python scripts/frame_report.py frames/gate/g01.jpg\n"
               "  python scripts/frame_report.py frames/gate --limit 3\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="+", help="image files, or folders of them")
    parser.add_argument("--limit", type=int, default=0, help="with a folder: report at most N images")
    parser.add_argument("--width", type=int, default=64, help="map width in characters (default 64)")
    args = parser.parse_args(argv)

    failures = 0
    reported = 0
    for target in (Path(item).expanduser() for item in args.paths):
        for path in _expand(target, args.limit):
            reported += 1
            failures += 1 if report(path, width=args.width) else 0
    if not reported:
        return 2
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
