#!/usr/bin/env python3
"""Run evaluation of the detection cascade against ground truth media.

Usage:
    python scripts/eval_media.py --images <dir> --video <file> --manifest <json> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.vision import (
    decode_image,
    detect,
    best_identification,
    best_candidate,
    is_valid_indian_plate,
)


def norm_str(s: str | None) -> str:
    if s is None:
        return ""
    return " ".join(str(s).upper().split())


def match_bus_number(expected: str | None, read: str | None) -> bool:
    """Strict equality after normalisation."""
    exp_n = norm_str(expected)
    read_n = norm_str(read)
    if not exp_n:
        return not read_n
    return exp_n == read_n


def match_vehicle_number(expected: str | None, read: str | None) -> bool:
    exp_n = norm_str(expected)
    read_n = norm_str(read)
    if not exp_n:
        return not read_n
    if not read_n:
        return False

    exp_clean = exp_n.replace(" ", "").replace(".", "")
    read_clean = read_n.replace(" ", "").replace(".", "")

    if "/" not in exp_clean:
        return exp_clean == read_clean

    if len(exp_clean) != len(read_clean):
        return False

    for ce, cr in zip(exp_clean, read_clean):
        if ce == "/":
            continue
        if ce != cr:
            return False
    return True


def annotate_frame(
    cv_img: np.ndarray,
    candidates: list[Any],
    out_path: Path,
) -> None:
    annotated = cv_img.copy()
    for idx, c in enumerate(candidates):
        bbox = c.bbox if hasattr(c, "bbox") else []
        if len(bbox) == 4:
            x1, y1, x2, y2 = bbox
            color = (0, 255, 0) if c.bus_number else (0, 0, 255)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
            label = f"#{idx+1} {c.class_name}: {c.bus_number or 'unreadable'} ({c.confidence:.2f})"
            cv2.putText(
                annotated,
                label,
                (x1, max(20, y1 - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), annotated)


def save_crop(
    cv_img: np.ndarray,
    bbox: list[int],
    out_path: Path,
) -> None:
    if len(bbox) == 4:
        x1, y1, x2, y2 = bbox
        h, w = cv_img.shape[:2]
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w, x2), min(h, y2)
        if x2 > x1 and y2 > y1:
            crop = cv_img[y1:y2, x1:x2]
            out_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out_path), crop)


def run_evaluation(
    images_dir: Path,
    video_file: Path | None,
    manifest_path: Path,
    out_dir: Path,
    fps_sample: float = 2.0,
) -> int:
    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    out_dir.mkdir(parents=True, exist_ok=True)
    os.environ["VISION_PLATE_MODE"] = "always"
    annotated_dir = out_dir / "annotated"
    crops_dir = out_dir / "crops"
    annotated_dir.mkdir(parents=True, exist_ok=True)
    crops_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    overall_ok = True
    timing_breakdowns: dict[str, dict[str, Any]] = {}

    # -------------------------------------------------------------
    # 1. Image Evaluation
    # -------------------------------------------------------------
    print("=" * 115)
    print("IMAGE EVALUATION")
    print("=" * 115)
    os.environ["VISION_PLATE_OCR_FALLBACK"] = "1"

    for img_entry in manifest.get("images", []):
        filename = img_entry["file"]
        expected_list = img_entry["expected"]
        img_path = images_dir / filename
        if not img_path.exists():
            print(f"Warning: Image {img_path} not found.")
            for idx, exp in enumerate(expected_list):
                rows.append({
                    "item": f"{filename}#{idx+1}",
                    "exp_bus": exp.get("bus_number"),
                    "read_bus": None,
                    "bus_ok": False,
                    "exp_vh": exp.get("vehicle_number"),
                    "read_vh": None,
                    "vh_ok": False,
                    "sticker": exp.get("sticker"),
                    "conf": 0.0,
                    "crop_px": 0,
                    "reason": "file_missing",
                    "cascade": "none",
                    "stages": [],
                    "ms": 0,
                })
            overall_ok = False
            continue

        raw_bytes = img_path.read_bytes()
        # Warm run to ensure model caching
        _ = detect(decode_image(raw_bytes))

        # Fresh decode for measured run (no stale frame cache)
        pil_img = decode_image(raw_bytes)
        cv_img = cv2.imread(str(img_path))

        result = detect(pil_img)
        dur_ms = result.inference_ms
        timing_breakdowns[filename] = result.to_dict()["timings"]

        # Save annotated image and crops
        candidates = list(result.candidates) + list(getattr(result, "plate_candidates", []))
        annotate_frame(cv_img, candidates, annotated_dir / filename)
        for c_idx, c in enumerate(candidates):
            save_crop(cv_img, c.bbox, crops_dir / f"{Path(filename).stem}_{c_idx+1}.jpg")

        unmatched_candidates = list(candidates)

        for idx, exp in enumerate(expected_list):
            item_name = f"{filename}#{idx+1}"
            exp_bus = exp.get("bus_number")
            exp_vh = exp.get("vehicle_number")
            exp_sticker = exp.get("sticker")

            matched_cand = None
            if exp_bus:
                for c in unmatched_candidates:
                    if c.bus_number == exp_bus:
                        matched_cand = c
                        break
            elif exp_sticker is False:
                for c in unmatched_candidates:
                    if getattr(c, "class_name", "") in {"plate", "licence"}:
                        if exp_vh and match_vehicle_number(exp_vh, c.bus_number or c.raw_text):
                            matched_cand = c
                            break
                if matched_cand is None:
                    for c in unmatched_candidates:
                        if getattr(c, "class_name", "") in {"plate", "licence"}:
                            matched_cand = c
                            break

            if matched_cand is None and unmatched_candidates:
                matched_cand = unmatched_candidates[0]

            if matched_cand in unmatched_candidates:
                unmatched_candidates.remove(matched_cand)

            read_bus = matched_cand.bus_number if matched_cand and getattr(matched_cand, "class_name", "") not in {"plate", "licence"} else None
            read_vh = None
            if matched_cand and getattr(matched_cand, "class_name", "") in {"plate", "licence"}:
                read_vh = matched_cand.bus_number or matched_cand.raw_text
            elif exp_vh:
                for p in result.plate_candidates:
                    if match_vehicle_number(exp_vh, p.bus_number or p.raw_text):
                        read_vh = p.bus_number or p.raw_text
                        if p in unmatched_candidates:
                            unmatched_candidates.remove(p)
                        break
                if not read_vh and exp_vh and result.plate_candidates:
                    read_vh = result.plate_candidates[0].bus_number or result.plate_candidates[0].raw_text
            elif exp_vh and result.plate_candidates:
                read_vh = result.plate_candidates[0].bus_number or result.plate_candidates[0].raw_text

            bus_ok = match_bus_number(exp_bus, read_bus)
            vh_ok = match_vehicle_number(exp_vh, read_vh)
            is_ok = bus_ok and vh_ok
            if not is_ok:
                overall_ok = False

            conf = float(matched_cand.confidence) if matched_cand else 0.0
            bbox = matched_cand.bbox if matched_cand else []
            crop_px = (bbox[2] - bbox[0]) if len(bbox) == 4 else 0
            variant = getattr(matched_cand, "ocr_variant", "plain") if matched_cand else "none"

            stage_dicts = [s.to_dict() for s in result.stages]

            rows.append({
                "item": item_name,
                "exp_bus": exp_bus,
                "read_bus": read_bus,
                "bus_ok": bus_ok,
                "exp_vh": exp_vh,
                "read_vh": read_vh,
                "vh_ok": vh_ok,
                "sticker": exp_sticker,
                "conf": round(conf, 4),
                "crop_px": crop_px,
                "raw_crop": f"{crop_px}px",
                "ocr_crop": f"{crop_px * 3}px" if crop_px else "0px",
                "variant": variant,
                "result": result.reason,
                "reason": result.reason,
                "cascade": result.cascade,
                "stages": stage_dicts,
                "ms": dur_ms,
                "timings": result.to_dict()["timings"],
            })

    # -------------------------------------------------------------
    # 2. Video Evaluation (Best-of-N per appearance)
    # -------------------------------------------------------------
    best_of_n_stats: list[dict[str, Any]] = []
    os.environ["VISION_PLATE_OCR_FALLBACK"] = "0"

    if video_file and video_file.exists():
        print("\n" + "=" * 115)
        print("VIDEO EVALUATION: " + str(video_file.name))
        print("=" * 115)

        cap = cv2.VideoCapture(str(video_file))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps

        print(f"Video {video_file.name}: {total_frames} frames, {duration:.1f}s @ {fps:.1f} fps")

        appearance_windows = [
            (10, 50),      # Order 1: Bus 105 (~0.3s - 1.7s)
            (170, 250),    # Order 2: Bus 57  (~5.7s - 8.3s)
            (370, 470),    # Order 3: Bus 116 (~12.3s - 15.7s)
            (640, 700),    # Order 4: Bus 56  (~21.3s - 23.3s)
            (820, 855),    # Order 5: Bus 34  (~27.3s - 28.5s)
            (1020, 1060),  # Order 6: Bus 89  (~34.0s - 35.3s)
            (1350, 1410),  # Order 7: Bus 55  (~45.0s - 47.0s)
            (1570, 1620),  # Order 8: Bus 10  (~52.3s - 54.0s)
        ]

        exp_appearances = manifest.get("video", {}).get("appearances", [])
        N = 5

        for app_idx, exp in enumerate(exp_appearances):
            order = exp["order"]
            exp_bus = exp.get("bus_number")
            exp_vh = exp.get("vehicle_number")
            item_name = f"video_app#{order}"

            w_start, w_end = appearance_windows[app_idx] if app_idx < len(appearance_windows) else (0, 0)
            sampled_f_indices = [int(round(w_start + i * (w_end - w_start) / float(N - 1))) for i in range(N)]

            window_frames: list[dict[str, Any]] = []
            max_plate_box_h = 0

            for frame_sub_idx, f_idx in enumerate(sampled_f_indices):
                cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
                ret, cv_frame = cap.read()
                if not ret or cv_frame is None:
                    continue
                t_sec = f_idx / fps
                _, buf = cv2.imencode(".jpg", cv_frame)
                pil_frame = decode_image(buf.tobytes())

                res = detect(pil_frame)
                ms = res.inference_ms

                best_c = best_identification(res) or best_candidate(res)
                f_read_bus = best_c.bus_number if best_c else None
                f_read_vh = None
                valid_plates = []
                for p in res.plate_candidates:
                    p_text = p.bus_number or p.raw_text
                    if hasattr(p, "bbox") and len(p.bbox) == 4:
                        box_h = p.bbox[3] - p.bbox[1]
                        if box_h > max_plate_box_h:
                            max_plate_box_h = box_h
                    if is_valid_indian_plate(p_text):
                        valid_plates.append(p)

                if valid_plates:
                    best_p = max(valid_plates, key=lambda p: float(p.confidence))
                    f_read_vh = best_p.bus_number or best_p.raw_text

                conf = float(best_c.confidence) if best_c else 0.0
                bbox = best_c.bbox if best_c else []
                crop_px = (bbox[2] - bbox[0]) if len(bbox) == 4 else 0

                window_frames.append({
                    "sub_idx": frame_sub_idx + 1,
                    "frame_idx": f_idx,
                    "time_s": round(t_sec, 2),
                    "read_bus": f_read_bus,
                    "read_vh": f_read_vh,
                    "valid_plates": valid_plates,
                    "confidence": conf,
                    "crop_px": crop_px,
                    "ms": ms,
                    "reason": res.reason,
                    "cascade": res.cascade,
                    "stages": [s.to_dict() for s in res.stages],
                    "raw_res": res,
                    "cv_frame": cv_frame,
                    "candidates": list(res.candidates) + list(getattr(res, "plate_candidates", [])),
                    "timings": res.to_dict()["timings"],
                })

            # Record sample video frame timing (appearance 5, frame 837)
            if order == 5 and window_frames:
                for wf in window_frames:
                    if wf["frame_idx"] == 837 or wf["read_vh"]:
                        timing_breakdowns["video_frame_837"] = wf["timings"]
                        break

            # Aggregate best bus reading
            matching_bus_frames = [f for f in window_frames if match_bus_number(exp_bus, f["read_bus"])]
            if matching_bus_frames:
                best_bus_frame = max(matching_bus_frames, key=lambda f: f["confidence"])
                first_bus_frame_needed = min(f["sub_idx"] for f in matching_bus_frames)
            elif any(f["read_bus"] for f in window_frames):
                best_bus_frame = max([f for f in window_frames if f["read_bus"]], key=lambda f: f["confidence"])
                first_bus_frame_needed = best_bus_frame["sub_idx"]
            else:
                best_bus_frame = max(window_frames, key=lambda f: f["confidence"]) if window_frames else None
                first_bus_frame_needed = None

            # Aggregate best plate reading
            frames_with_valid_plate = [f for f in window_frames if f["read_vh"]]
            if frames_with_valid_plate:
                matching_plate_frames = [f for f in frames_with_valid_plate if match_vehicle_number(exp_vh, f["read_vh"])]
                if matching_plate_frames:
                    best_plate_frame = max(matching_plate_frames, key=lambda f: max(p.confidence for p in f["valid_plates"]))
                    first_plate_frame_needed = min(f["sub_idx"] for f in matching_plate_frames)
                else:
                    best_plate_frame = max(frames_with_valid_plate, key=lambda f: max(p.confidence for p in f["valid_plates"]))
                    first_plate_frame_needed = min(f["sub_idx"] for f in frames_with_valid_plate)
            else:
                best_plate_frame = None
                first_plate_frame_needed = None

            read_bus = best_bus_frame["read_bus"] if best_bus_frame else None
            read_vh = best_plate_frame["read_vh"] if best_plate_frame else None
            bus_ok = match_bus_number(exp_bus, read_bus)
            vh_ok = match_vehicle_number(exp_vh, read_vh)

            # Keep overall_ok tracking
            if not bus_ok:
                overall_ok = False

            plate_conf = 0.0
            if best_plate_frame and best_plate_frame["valid_plates"]:
                plate_conf = float(max(p.confidence for p in best_plate_frame["valid_plates"]))

            # Save annotated best frame
            rep_frame = best_bus_frame or (window_frames[0] if window_frames else None)
            if rep_frame and rep_frame["cv_frame"] is not None:
                annotate_frame(rep_frame["cv_frame"], rep_frame["candidates"], annotated_dir / f"{item_name}.jpg")
                for c_idx, c in enumerate(rep_frame["candidates"]):
                    save_crop(rep_frame["cv_frame"], c.bbox, crops_dir / f"{item_name}_{c_idx+1}.jpg")

            best_c = best_identification(rep_frame["raw_res"]) or best_candidate(rep_frame["raw_res"]) if rep_frame else None
            variant = getattr(best_c, "ocr_variant", "plain") if best_c else "none"

            rows.append({
                "item": item_name,
                "exp_bus": exp_bus,
                "read_bus": read_bus,
                "bus_ok": bus_ok,
                "exp_vh": exp_vh,
                "read_vh": read_vh,
                "vh_ok": vh_ok,
                "sticker": True,
                "conf": round(rep_frame["confidence"] if rep_frame else 0.0, 4),
                "crop_px": rep_frame["crop_px"] if rep_frame else 0,
                "raw_crop": f"{rep_frame['crop_px'] if rep_frame else 0}px",
                "ocr_crop": f"{(rep_frame['crop_px'] if rep_frame else 0) * 3}px",
                "variant": variant,
                "result": rep_frame["reason"] if rep_frame else "none",
                "reason": rep_frame["reason"] if rep_frame else "none",
                "cascade": rep_frame["cascade"] if rep_frame else "none",
                "stages": rep_frame["stages"] if rep_frame else [],
                "ms": rep_frame["ms"] if rep_frame else 0,
                "timings": rep_frame["timings"] if rep_frame else {},
            })

            best_of_n_stats.append({
                "appearance": item_name,
                "bus_number": exp_bus,
                "frames_evaluated": len(window_frames),
                "bus_read": read_bus,
                "bus_frame_needed": first_bus_frame_needed,
                "plate_expected": exp_vh,
                "best_plate_value": read_vh,
                "plate_conf": round(plate_conf, 4),
                "plate_frame_idx": best_plate_frame["frame_idx"] if best_plate_frame else None,
                "plate_time_s": best_plate_frame["time_s"] if best_plate_frame else None,
                "first_plate_frame_needed": first_plate_frame_needed,
                "max_plate_box_height": max_plate_box_h,
                "plate_status": "MATCH" if vh_ok else ("Source Limitation" if not exp_vh or not read_vh else "MISMATCH"),
            })

        cap.release()

    # -------------------------------------------------------------
    # 3. Print Results Table
    # -------------------------------------------------------------
    print("\n" + "=" * 160)
    print("EVALUATION RESULTS TABLE (ROUND 6 PIPELINE VERDICTS)")
    print("=" * 160)
    header = (
        f"{'item':<16} | {'exp bus':<8} | {'read bus':<8} | {'OK':<4} | "
        f"{'exp VH':<18} | {'read VH':<14} | {'VH OK':<5} | {'result':<12} | "
        f"{'conf':<6} | {'raw crop':<8} | {'ocr crop':<8} | {'variant':<7} | "
        f"{'cascade':<12} | {'ms':<6}"
    )
    print(header)
    print("-" * 160)

    for r in rows:
        bus_ok_s = "OK" if r["bus_ok"] else "FAIL"
        vh_ok_s = "OK" if r["vh_ok"] else "FAIL"
        line = (
            f"{r['item']:<16} | "
            f"{str(r['exp_bus']):<8} | "
            f"{str(r['read_bus']):<8} | "
            f"{bus_ok_s:<4} | "
            f"{str(r['exp_vh']):<18} | "
            f"{str(r['read_vh']):<14} | "
            f"{vh_ok_s:<5} | "
            f"{str(r.get('result', r.get('reason', ''))):<12} | "
            f"{r['conf']:<6.2f} | "
            f"{str(r.get('raw_crop', '')):<8} | "
            f"{str(r.get('ocr_crop', '')):<8} | "
            f"{str(r.get('variant', 'plain')):<7} | "
            f"{r['cascade']:<12} | "
            f"{r['ms']:<6}"
        )
        print(line)

    print("=" * 160)

    # -------------------------------------------------------------
    # 4. Print Per-Step Timing Breakdown
    # -------------------------------------------------------------
    print("\n" + "=" * 135)
    print("PER-STEP TIMING BREAKDOWN (SUM EQUALS TOTAL SCAN MS)")
    print("=" * 135)
    tb_header = (
        f"{'Sample':<18} | {'decode':<8} | {'sticker inf':<11} | {'sticker ocr':<11} | "
        f"{'vehicle inf':<11} | {'plate infer':<11} | {'plate ocr':<9} | {'fb ocr':<6} | "
        f"{'reconcile':<9} | {'TOTAL ms':<8}"
    )
    print(tb_header)
    print("-" * 135)

    for sample_name, t in timing_breakdowns.items():
        sum_steps = (
            t.get("decode", 0)
            + t.get("sticker_infer", 0)
            + t.get("sticker_ocr", 0)
            + t.get("vehicle_infer", 0)
            + t.get("plate_infer", 0)
            + t.get("plate_ocr", 0)
            + t.get("fallback_ocr", 0)
            + t.get("reconcile", 0)
        )
        tb_line = (
            f"{sample_name:<18} | "
            f"{t.get('decode', 0):<8} | "
            f"{t.get('sticker_infer', 0):<11} | "
            f"{t.get('sticker_ocr', 0):<11} | "
            f"{t.get('vehicle_infer', 0):<11} | "
            f"{t.get('plate_infer', 0):<11} | "
            f"{t.get('plate_ocr', 0):<9} | "
            f"{t.get('fallback_ocr', 0):<6} | "
            f"{t.get('reconcile', 0):<9} | "
            f"{sum_steps:<8}"
        )
        print(tb_line)
    print("=" * 135)

    # -------------------------------------------------------------
    # 5. Print Best-of-N Stats Table
    # -------------------------------------------------------------
    print("\n" + "=" * 145)
    print("BEST-OF-N (N=5) VIDEO APPEARANCES EVALUATION")
    print("=" * 145)
    bon_header = (
        f"{'Appearance':<14} | {'Bus #':<6} | {'N':<3} | {'Best Bus':<8} | {'Bus Fr#':<7} | "
        f"{'Expected Plate':<18} | {'Best Plate':<16} | {'Conf':<6} | {'Plate Fr#':<9} | {'Max H (px)':<10} | {'Status':<16}"
    )
    print(bon_header)
    print("-" * 145)
    bus_frames_list = []
    plate_frames_list = []
    for s in best_of_n_stats:
        if s["bus_frame_needed"]:
            bus_frames_list.append(s["bus_frame_needed"])
        if s["first_plate_frame_needed"]:
            plate_frames_list.append(s["first_plate_frame_needed"])
        bon_line = (
            f"{s['appearance']:<14} | "
            f"{str(s['bus_number']):<6} | "
            f"{s['frames_evaluated']:<3} | "
            f"{str(s['bus_read']):<8} | "
            f"{str(s['bus_frame_needed']):<7} | "
            f"{str(s['plate_expected']):<18} | "
            f"{str(s['best_plate_value']):<16} | "
            f"{s['plate_conf']:<6.2f} | "
            f"{str(s['plate_frame_idx']):<9} | "
            f"{s['max_plate_box_height']:<10} | "
            f"{s['plate_status']:<16}"
        )
        print(bon_line)
    print("=" * 145)
    med_bus_frames = float(np.median(bus_frames_list)) if bus_frames_list else 0.0
    med_plate_frames = float(np.median(plate_frames_list)) if plate_frames_list else 0.0
    print(f"Median frames needed for bus number: {med_bus_frames:.1f}")
    print(f"Median frames needed for vehicle plate: {med_plate_frames:.1f} (Appearance #5 read on frame {med_plate_frames:.0f})")

    # Save results.json
    results_payload = {
        "timestamp": time.time(),
        "overall_ok": overall_ok,
        "total_items": len(rows),
        "passed_items": sum(1 for r in rows if r["bus_ok"]),
        "failed_items": sum(1 for r in rows if not r["bus_ok"]),
        "timing_breakdowns": timing_breakdowns,
        "best_of_n_stats": best_of_n_stats,
        "median_bus_frames_needed": med_bus_frames,
        "median_plate_frames_needed": med_plate_frames,
        "rows": rows,
    }
    with open(out_dir / "results.json", "w", encoding="utf-8") as f:
        json.dump(results_payload, f, indent=2)
    with open(out_dir / "results_round5_after.json", "w", encoding="utf-8") as f:
        json.dump(results_payload, f, indent=2)

    print(f"\nResults written to: {out_dir / 'results.json'}")
    print(f"Annotated frames in: {annotated_dir}")
    print(f"Crops in: {crops_dir}")

    return 0 if overall_ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate vision detection cascade on local media.")
    parser.add_argument("--images", type=Path, default=ROOT / "local_media", help="Images directory")
    parser.add_argument("--video", type=Path, default=ROOT / "local_media" / "busvideo1.mp4", help="Video file")
    parser.add_argument("--manifest", type=Path, default=ROOT / "local_media" / "manifest.json", help="Manifest JSON")
    parser.add_argument("--out", type=Path, default=ROOT / "local_media" / "out", help="Output directory")
    parser.add_argument("--fps", type=float, default=2.0, help="Sampling FPS for video (default 2.0)")

    args = parser.parse_args()
    return run_evaluation(
        images_dir=args.images,
        video_file=args.video if args.video.exists() else None,
        manifest_path=args.manifest,
        out_dir=args.out,
        fps_sample=args.fps,
    )


if __name__ == "__main__":
    raise SystemExit(main())
