#!/usr/bin/env python3
"""Compare detector image sizes against a folder of real frames."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from backend.vision import best_identification, detect, decode_image, unload_model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--sizes", default="640,960,1280,1536")
    args = parser.parse_args()
    sizes = [int(value) for value in args.sizes.split(",") if value.strip()]
    images = sorted(
        path for path in args.dir.iterdir()
        if path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    )
    if not images:
        raise SystemExit(f"no supported images found in {args.dir}")

    print("image\tsize\tdetections\tbest_conf\tplate_read\tms")
    for size in sizes:
        os.environ["VISION_IMAGE_SIZE"] = str(size)
        os.environ["VISION_STICKER_IMGSZ"] = str(size)
        for path in images:
            result = detect(decode_image(path.read_bytes()))
            candidate = best_identification(result)
            print(
                f"{path.name}\t{size}\t{result.boxes_total}\t"
                f"{result.best_confidence:.3f}\t{candidate.bus_number if candidate else '-'}\t"
                f"{result.inference_ms}"
            )
        unload_model()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
