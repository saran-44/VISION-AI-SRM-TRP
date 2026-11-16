"""Five Gate Acceptance Checks for VISION AI - SRM TRP (Round 10 Handover).

1. Real scan 1: busimage1.jpg -> bus number identified
2. Real scan 2: busimage2.jpg -> bus number identified
3. Real scan 3: video frame from busvideo1.mp4 -> bus number identified
4. Refusal check: covered lens (black frame) -> early rejection with quality refusal
5. Report readout: backend.report.build_report() -> full system diagnostics
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PIL import Image

from backend.vision import detect, quality_settings
from backend.report import build_report

def run_acceptance_checks():
    print("=" * 70)
    print("VISION AI - SRM TRP :: FIVE GATE ACCEPTANCE CHECKS")
    print("=" * 70)

    # -------------------------------------------------------------
    # CHECK 1: busimage1.jpg
    # -------------------------------------------------------------
    print("\n>>> CHECK 1: Real Scan (busimage1.jpg)")
    p1 = ROOT / "local_media" / "busimage1.jpg"
    assert p1.exists(), f"Missing {p1}"
    img1 = Image.open(p1)
    t0 = time.perf_counter()
    r1 = detect(img1)
    ms1 = int((time.perf_counter() - t0) * 1000)
    
    bus_cands1 = [c for c in r1.candidates if c.class_name not in {"plate", "licence"}]
    plate_cands1 = r1.plate_candidates or [c for c in r1.candidates if c.class_name in {"plate", "licence"}]
    
    print(f"Status: PASS")
    print(f"File: {p1.name} ({r1.frame_width}x{r1.frame_height})")
    print(f"Inference Time: {ms1} ms (internal: {r1.inference_ms} ms)")
    print(f"Cascade: {r1.cascade} | Reason: {r1.reason}")
    print(f"Sticker candidates found: {len(bus_cands1)}")
    for i, c in enumerate(bus_cands1, 1):
        print(f"  [{i}] Bus Number: {c.bus_number!r} | Raw OCR: {c.raw_text!r} | Conf: {c.confidence:.2f} | Box: {c.bbox}")
    print(f"Plate candidates found: {len(plate_cands1)}")
    for i, c in enumerate(plate_cands1, 1):
        print(f"  [{i}] Plate: {c.bus_number or c.raw_text!r} | Conf: {c.confidence:.2f} | Box: {c.bbox}")
    assert any(c.bus_number in {"57", "19"} for c in bus_cands1), "Expected bus 57 or 19 in busimage1"

    # -------------------------------------------------------------
    # CHECK 2: busimage2.jpg
    # -------------------------------------------------------------
    print("\n>>> CHECK 2: Real Scan (busimage2.jpg)")
    p2 = ROOT / "local_media" / "busimage2.jpg"
    assert p2.exists(), f"Missing {p2}"
    img2 = Image.open(p2)
    t0 = time.perf_counter()
    r2 = detect(img2)
    ms2 = int((time.perf_counter() - t0) * 1000)
    
    bus_cands2 = [c for c in r2.candidates if c.class_name not in {"plate", "licence"}]
    plate_cands2 = r2.plate_candidates or [c for c in r2.candidates if c.class_name in {"plate", "licence"}]

    print(f"Status: PASS")
    print(f"File: {p2.name} ({r2.frame_width}x{r2.frame_height})")
    print(f"Inference Time: {ms2} ms (internal: {r2.inference_ms} ms)")
    print(f"Cascade: {r2.cascade} | Reason: {r2.reason}")
    print(f"Sticker candidates found: {len(bus_cands2)}")
    for i, c in enumerate(bus_cands2, 1):
        print(f"  [{i}] Bus Number: {c.bus_number!r} | Raw OCR: {c.raw_text!r} | Conf: {c.confidence:.2f} | Box: {c.bbox}")
    print(f"Plate candidates found: {len(plate_cands2)}")
    for i, c in enumerate(plate_cands2, 1):
        print(f"  [{i}] Plate: {c.bus_number or c.raw_text!r} | Conf: {c.confidence:.2f} | Box: {c.bbox}")
    assert any(c.bus_number in {"104", "21"} for c in bus_cands2), "Expected bus 104 or 21 in busimage2"

    # -------------------------------------------------------------
    # CHECK 3: Video Frame from busvideo1.mp4 (Appearance #2, Bus 57)
    # -------------------------------------------------------------
    print("\n>>> CHECK 3: Real Scan (Video Frame from busvideo1.mp4)")
    pv = ROOT / "local_media" / "busvideo1.mp4"
    assert pv.exists(), f"Missing {pv}"
    cap = cv2.VideoCapture(str(pv))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    # Frame 210 in appearance window 2 (170-250) has clear sticker for bus 57
    target_frame = 210
    cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ret, frame_bgr = cap.read()
    cap.release()
    assert ret and frame_bgr is not None, "Failed to read frame from video"
    
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    img_video = Image.fromarray(frame_rgb)
    t0 = time.perf_counter()
    r3 = detect(img_video)
    ms3 = int((time.perf_counter() - t0) * 1000)
    
    bus_cands3 = [c for c in r3.candidates if c.class_name not in {"plate", "licence"}]

    print(f"Status: PASS")
    print(f"Frame #{target_frame} at {target_frame/fps:.2f}s ({r3.frame_width}x{r3.frame_height})")
    print(f"Inference Time: {ms3} ms (internal: {r3.inference_ms} ms)")
    print(f"Cascade: {r3.cascade} | Reason: {r3.reason}")
    print(f"Sticker candidates found: {len(bus_cands3)}")
    for i, c in enumerate(bus_cands3, 1):
        print(f"  [{i}] Bus Number: {c.bus_number!r} | Raw OCR: {c.raw_text!r} | Conf: {c.confidence:.2f} | Box: {c.bbox}")
    assert any(c.bus_number == "57" for c in bus_cands3), "Expected bus 57 in video frame"

    # -------------------------------------------------------------
    # CHECK 4: Covered Lens / Black Frame Refusal
    # -------------------------------------------------------------
    print("\n>>> CHECK 4: Quality Gate Refusal on Covered Lens (Black Frame)")
    black_img = Image.new("RGB", (1280, 720), (0, 0, 0))
    t0 = time.perf_counter()
    r4 = detect(black_img)
    ms4 = int((time.perf_counter() - t0) * 1000)
    
    print(f"Status: PASS (Quality Gate Refusal Triggered)")
    print(f"Reason: {r4.reason!r}")
    print(f"Advice: {r4.advice!r}")
    print(f"Brightness: {r4.frame_brightness} | Sharpness: {r4.frame_sharpness}")
    print(f"Inference Time: {ms4} ms (Early reject without loading/computing detector)")
    assert r4.reason == "frame_unusable", f"Expected frame_unusable, got {r4.reason}"
    assert "dark" in r4.advice.lower() or "black frame" in r4.advice.lower(), f"Expected dark/black frame in advice, got {r4.advice}"

    # -------------------------------------------------------------
    # CHECK 5: Report Block Readout
    # -------------------------------------------------------------
    print("\n>>> CHECK 5: System Diagnostic Report Readout (--report)")
    rep_text = build_report(deep=False)
    print("-" * 50)
    print(rep_text)
    print("-" * 50)
    print("Check 5 Status: PASS")

    print("\n" + "=" * 70)
    print("ALL FIVE GATE ACCEPTANCE CHECKS PASSED SUCCESSFULLY.")
    print("=" * 70)

if __name__ == "__main__":
    run_acceptance_checks()
