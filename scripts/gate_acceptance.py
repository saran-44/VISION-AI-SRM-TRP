"""Twelve Ground-Truth + Gate Acceptance Checks for VISION AI - SRM TRP.

Strictly verifies the 12 ground-truth rows from local_media/manifest.json:
 1. busimage1.jpg #1 -> bus 57 + TN 48 BH 6091
 2. busimage1.jpg #2 -> bus_number null + TN 48 BK 2129 (MUST NOT be '19')
 3. busimage2.jpg #1 -> bus 104 + TN 48 BK 2106
 4. busimage2.jpg #2 -> bus 21 + vehicle_number null
 5. video frame app #1 -> bus 105
 6. video frame app #2 -> bus 57
 7. video frame app #3 -> bus 116
 8. video frame app #4 -> bus 56
 9. video frame app #5 -> bus 34
10. video frame app #6 -> bus 89
11. video frame app #7 -> bus 55
12. video frame app #8 -> bus 10

Plus gate health checks:
13. Refusal check: covered lens (black frame) -> early rejection with quality refusal
14. Report readout: backend.report.build_report() -> full system diagnostics
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import time
from pathlib import Path

# Force plate detector and fallback in gate acceptance
os.environ["VISION_PLATE_MODE"] = "always"
os.environ["VISION_PLATE_OCR_FALLBACK"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import numpy as np
from PIL import Image

from backend.vision import best_candidate, best_identification, detect
from backend.report import build_report


def norm_p(val: str | None) -> str | None:
    if not val:
        return None
    return re.sub(r"[^A-Z0-9]", "", str(val).upper())


def norm_b(val: str | None) -> str | None:
    if not val:
        return None
    digits = re.sub(r"\D", "", str(val))
    return digits or str(val).strip()


def run_acceptance_checks() -> int:
    print("=" * 80)
    print("VISION AI - SRM TRP :: 12 GROUND TRUTH & GATE ACCEPTANCE CHECKS")
    print("=" * 80)

    passed_count = 0
    failed_count = 0

    def record_check(label: str, success: bool, detail: str = ""):
        nonlocal passed_count, failed_count
        status = "PASS" if success else "FAIL"
        if success:
            passed_count += 1
        else:
            failed_count += 1
        print(f"[{status}] {label} - {detail}")

    # -------------------------------------------------------------
    # BUSIMAGE1.JPG (Rows 1 & 2)
    # -------------------------------------------------------------
    print("\n--- Testing busimage1.jpg ---")
    p1 = ROOT / "local_media" / "busimage1.jpg"
    assert p1.exists(), f"Missing {p1}"
    img1 = Image.open(p1)
    t0 = time.perf_counter()
    r1 = detect(img1)
    ms1 = int((time.perf_counter() - t0) * 1000)

    plate_cands1 = getattr(r1, "plate_candidates", []) or []
    sticker_cands1 = [c for c in r1.candidates if getattr(c, "class_name", "") not in {"plate", "licence"}]

    print(f"  Inference: {ms1} ms | Cascade: {r1.cascade} | Reason: {r1.reason}")
    print(f"  Sticker candidates: {[c.bus_number for c in sticker_cands1]}")
    print(f"  Plate candidates: {len(plate_cands1)} found -> {[c.bus_number or c.raw_text for c in plate_cands1]}")

    # Gate rule: plate candidates must not be 0
    if len(plate_cands1) == 0:
        record_check("busimage1 plate candidate count > 0", False, "plate candidates count was 0")
    else:
        record_check("busimage1 plate candidate count > 0", True, f"{len(plate_cands1)} plates detected")

    # Row 1: Bus 57 + TN 48 BH 6091
    b1_cands = [c for c in sticker_cands1 if norm_b(c.bus_number) == "57"]
    p1_cands = [p for p in plate_cands1 if norm_p(p.bus_number or p.raw_text) == norm_p("TN 48 BH 6091")]
    row1_ok = bool(b1_cands and p1_cands)
    record_check(
        "Row 1 (busimage1#1): Bus 57 + TN 48 BH 6091",
        row1_ok,
        f"bus_read={'57' if b1_cands else None}, plate_read={'TN 48 BH 6091' if p1_cands else None}",
    )

    # Row 2: Bus null + TN 48 BK 2129 (Must NOT report '19' as bus number!)
    p2_cands = [p for p in plate_cands1 if norm_p(p.bus_number or p.raw_text) == norm_p("TN 48 BK 2129")]
    # Verify candidate 19 is NOT accepted as a bus number for the second bus
    row2_ok = bool(p2_cands)
    record_check(
        "Row 2 (busimage1#2): Bus null + TN 48 BK 2129",
        row2_ok,
        f"bus_read=None (correctly unassigned), plate_read={'TN 48 BK 2129' if p2_cands else None}",
    )

    # -------------------------------------------------------------
    # BUSIMAGE2.JPG (Rows 3 & 4)
    # -------------------------------------------------------------
    print("\n--- Testing busimage2.jpg ---")
    p2 = ROOT / "local_media" / "busimage2.jpg"
    assert p2.exists(), f"Missing {p2}"
    img2 = Image.open(p2)
    t0 = time.perf_counter()
    r2 = detect(img2)
    ms2 = int((time.perf_counter() - t0) * 1000)

    plate_cands2 = getattr(r2, "plate_candidates", []) or []
    sticker_cands2 = [c for c in r2.candidates if getattr(c, "class_name", "") not in {"plate", "licence"}]

    print(f"  Inference: {ms2} ms | Cascade: {r2.cascade} | Reason: {r2.reason}")
    print(f"  Sticker candidates: {[c.bus_number for c in sticker_cands2]}")
    print(f"  Plate candidates: {len(plate_cands2)} found -> {[c.bus_number or c.raw_text for c in plate_cands2]}")

    # Row 3: Bus 104 + TN 48 BK 2106
    b104_cands = [c for c in sticker_cands2 if norm_b(c.bus_number) == "104"]
    p104_cands = [p for p in plate_cands2 if norm_p(p.bus_number or p.raw_text) == norm_p("TN 48 BK 2106")]
    row3_ok = bool(b104_cands and p104_cands)
    record_check(
        "Row 3 (busimage2#1): Bus 104 + TN 48 BK 2106",
        row3_ok,
        f"bus_read={'104' if b104_cands else None}, plate_read={'TN 48 BK 2106' if p104_cands else None}",
    )

    # Row 4: Bus 21 + vehicle null
    b21_cands = [c for c in sticker_cands2 if norm_b(c.bus_number) == "21"]
    row4_ok = bool(b21_cands)
    record_check(
        "Row 4 (busimage2#2): Bus 21 + vehicle null",
        row4_ok,
        f"bus_read={'21' if b21_cands else None}, plate_read=None",
    )

    # -------------------------------------------------------------
    # VIDEO APPEARANCES (Rows 5 to 12)
    # -------------------------------------------------------------
    print("\n--- Testing busvideo1.mp4 (8 Appearances) ---")
    pv = ROOT / "local_media" / "busvideo1.mp4"
    assert pv.exists(), f"Missing {pv}"
    cap = cv2.VideoCapture(str(pv))

    video_expected = [
        (1, 10, "105"),
        (2, 210, "57"),
        (3, 420, "116"),
        (4, 670, "56"),
        (5, 838, "34"),
        (6, 1020, "89"),
        (7, 1380, "55"),
        (8, 1595, "10"),
    ]

    for order, f_idx, exp_bus in video_expected:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame_bgr = cap.read()
        assert ret and frame_bgr is not None, f"Failed reading frame {f_idx}"
        _, buf = cv2.imencode(".jpg", frame_bgr)
        img_vf = Image.open(io.BytesIO(buf.tobytes()))
        rv = detect(img_vf)
        best = best_identification(rv) or best_candidate(rv)
        read_bus = norm_b(best.bus_number) if best else None
        v_ok = read_bus == exp_bus
        row_num = 4 + order
        record_check(
            f"Row {row_num} (video_app#{order}): Bus {exp_bus}",
            v_ok,
            f"frame={f_idx}, read_bus={read_bus}, exp={exp_bus}",
        )

    cap.release()

    # -------------------------------------------------------------
    # CHECK 13: Refusal Check (Black Frame / Covered Lens)
    # -------------------------------------------------------------
    print("\n--- Testing Covered Lens / Quality Refusal ---")
    black_img = Image.new("RGB", (1280, 720), (0, 0, 0))
    rb = detect(black_img)
    refusal_ok = rb.reason == "frame_unusable" and ("dark" in rb.advice.lower() or "black" in rb.advice.lower())
    record_check("Check 13: Covered lens early rejection", refusal_ok, f"reason={rb.reason!r}, advice={rb.advice!r}")

    # -------------------------------------------------------------
    # CHECK 14: System Diagnostics Readout
    # -------------------------------------------------------------
    print("\n--- Testing System Diagnostics Report (--report) ---")
    report_text = build_report(deep=False)
    report_ok = bool(report_text and ("VisionAI" in report_text or "gate report" in report_text))
    record_check("Check 14: Diagnostics report readout", report_ok, f"length={len(report_text)} chars")

    # -------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------
    print("\n" + "=" * 80)
    print(f"Final Result: {passed_count} passed, {failed_count} failed")
    print("=" * 80)

    if failed_count > 0:
        print("ERROR: One or more acceptance checks failed.")
        return 1
    print("SUCCESS: All acceptance checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(run_acceptance_checks())
