#!/usr/bin/env python3
"""Verify the CPU-only gate-PC vision environment."""
from __future__ import annotations

import importlib
from importlib import metadata


def main() -> int:
    distributions = {
        dist.metadata["Name"].lower()
        for dist in metadata.distributions()
        if dist.metadata.get("Name")
    }
    opencv = sorted(name for name in distributions if name in {"opencv-python", "opencv-python-headless", "opencv-contrib-python", "opencv-contrib-python-headless"})
    if len(opencv) != 1 or opencv[0] != "opencv-python-headless":
        raise SystemExit(f"expected exactly one headless OpenCV distribution, found {opencv}")

    modules = {}
    for name in ("cv2", "torch", "ultralytics", "rapidocr_onnxruntime"):
        modules[name] = importlib.import_module(name)
    torch = modules["torch"]
    if torch.version.cuda is not None:
        raise SystemExit(f"CUDA torch wheel detected: torch.version.cuda={torch.version.cuda!r}")

    print("environment OK")
    print(f"opencv distribution: {opencv[0]}")
    print(f"torch: {torch.__version__}")
    print(f"torch.version.cuda: {torch.version.cuda}")
    print(f"cv2: {modules['cv2'].__version__}")
    print(f"ultralytics: {modules['ultralytics'].__version__}")
    print(f"rapidocr_onnxruntime: {metadata.version('rapidocr-onnxruntime')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
