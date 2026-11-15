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
)


def norm_str(s: str | None) -> str:
    if s is None:
        return ""
    return " ".join(str(s).upper().split())


def match_bus_number(expected: str | None, read: str | None) -> bool:
    exp_n = norm_str(expected)
    read_n = norm_str(read)
    if not exp_n:
        return not read_n
    return exp_n == read_n or exp_n in read_n.split() or read_n.startswith(exp_n + " ")


def match_vehicle_number(expected: str | None, read: str | None) -> bool:
    exp_n = norm_str(expected)
    read_n = norm_str(read)
    if not exp_n:
        return not read_n
    if not read_n:
        return False

    exp_clean = exp_n.replace(" ", "")
    read_clean = read_n.replace(" ", "")

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

    # -------------------------------------------------------------
    # 1. Image Evaluation
    # -------------------------------------------------------------
    print("=" * 115)
    print("IMAGE EVALUATION")
    print("=" * 115)

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
        pil_img = decode_image(raw_bytes)
        cv_img = cv2.imread(str(img_path))

        # Measure warm latency (second run) for reporting
        _ = detect(pil_img)
        t0 = time.perf_counter()
        result = detect(pil_img)
        dur_ms = int((time.perf_counter() - t0) * 1000)

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
            })

    # -------------------------------------------------------------
    # 2. Video Evaluation
    # -------------------------------------------------------------
    if video_file and video_file.exists():
        print("\n" + "=" * 115)
        print("VIDEO EVALUATION: " + str(video_file.name))
        print("=" * 115)

        cap = cv2.VideoCapture(str(video_file))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps
        step = max(1, int(round(fps / fps_sample)))

        print(f"Video {video_file.name}: {total_frames} frames, {duration:.1f}s @ {fps:.1f} fps (step: {step})")

        frame_results: list[dict[str, Any]] = []
        frame_idx = 0
        sampled_count = 0

        while True:
            ret, cv_frame = cap.read()
            if not ret:
                break

            if frame_idx % step == 0:
                sampled_count += 1
                t_sec = frame_idx / fps
                _, buf = cv2.imencode(".jpg", cv_frame)
                pil_frame = decode_image(buf.tobytes())

                t0 = time.perf_counter()
                res = detect(pil_frame)
                ms = int((time.perf_counter() - t0) * 1000)

                best_c = best_identification(res) or best_candidate(res)
                read_bus = best_c.bus_number if best_c else None
                read_vh = None
                if res.plate_candidates:
                    read_vh = res.plate_candidates[0].bus_number or res.plate_candidates[0].raw_text

                conf = float(best_c.confidence) if best_c else 0.0
                bbox = best_c.bbox if best_c else []
                crop_px = (bbox[2] - bbox[0]) if len(bbox) == 4 else 0

                frame_results.append({
                    "frame_idx": frame_idx,
                    "time_s": round(t_sec, 2),
                    "read_bus": read_bus,
                    "read_vh": read_vh,
                    "confidence": conf,
                    "crop_px": crop_px,
                    "ms": ms,
                    "reason": res.reason,
                    "cascade": res.cascade,
                    "stages": [s.to_dict() for s in res.stages],
                    "raw_res": res,
                    "candidates": list(res.candidates) + list(getattr(res, "plate_candidates", [])),
                })
                if sampled_count % 15 == 0:
                    print(f"  Processed {sampled_count} frames ({t_sec:.1f}s / {duration:.1f}s)...", flush=True)

            frame_idx += 1
        cap.release()

        # Provisional appearance windows based on video frame timeline
        # (Since manifest has blank start/end, grouped by chronological vehicle passage windows)
        appearance_windows = [
            (0, 45),       # Order 1: Bus 105 (~0.0s - 1.5s)
            (180, 240),    # Order 2: Bus 57  (~6.0s - 8.0s)
            (375, 480),    # Order 3: Bus 116 (~12.5s - 16.0s)
            (660, 705),    # Order 4: Bus 56  (~22.0s - 23.5s)
            (810, 870),    # Order 5: Bus 34  (~27.0s - 29.0s)
            (1020, 1080),  # Order 6: Bus 89  (~34.0s - 36.0s)
            (1365, 1410),  # Order 7: Bus 55  (~45.5s - 47.0s)
            (1575, 1635),  # Order 8: Bus 10  (~52.5s - 54.5s)
        ]

        exp_appearances = manifest.get("video", {}).get("appearances", [])
        for app_idx, exp in enumerate(exp_appearances):
            order = exp["order"]
            exp_bus = exp.get("bus_number")
            exp_vh = exp.get("vehicle_number")
            item_name = f"video_app#{order}"

            w_start, w_end = appearance_windows[app_idx] if app_idx < len(appearance_windows) else (0, 0)
            window_frames = [f for f in frame_results if w_start <= f["frame_idx"] <= w_end]

            if window_frames:
                # Select best frame: prefer frame with readable bus, otherwise highest confidence
                with_bus = [f for f in window_frames if f["read_bus"]]
                if with_bus:
                    best_fr = max(with_bus, key=lambda f: f["confidence"])
                else:
                    best_fr = max(window_frames, key=lambda f: f["confidence"])

                read_bus = best_fr["read_bus"]
                read_vh = best_fr["read_vh"]
                bus_ok = match_bus_number(exp_bus, read_bus)
                vh_ok = match_vehicle_number(exp_vh, read_vh)
                is_ok = bus_ok and vh_ok
                if not is_ok:
                    overall_ok = False

                conf = best_fr["confidence"]
                crop_px = best_fr["crop_px"]
                dur_ms = best_fr["ms"]
                reason = best_fr["reason"]
                cascade = best_fr["cascade"]
                stages = best_fr["stages"]

                # Save best frame as annotated and crop
                cap_ref = cv2.VideoCapture(str(video_file))
                cap_ref.set(cv2.CAP_PROP_POS_FRAMES, best_fr["frame_idx"])
                _, best_cv = cap_ref.read()
                cap_ref.release()

                if best_cv is not None:
                    annotate_frame(best_cv, best_fr["candidates"], annotated_dir / f"{item_name}.jpg")
                    for c_idx, c in enumerate(best_fr["candidates"]):
                        save_crop(best_cv, c.bbox, crops_dir / f"{item_name}_{c_idx+1}.jpg")

                best_c = best_identification(best_fr["raw_res"]) or best_candidate(best_fr["raw_res"])
                variant = getattr(best_c, "ocr_variant", "plain") if best_c else "none"

            else:
                bus_ok = False
                vh_ok = False
                read_bus = None
                read_vh = None
                conf = 0.0
                crop_px = 0
                dur_ms = 0
                reason = "no_frames_in_window"
                cascade = "none"
                stages = []
                variant = "none"
                overall_ok = False

            rows.append({
                "item": item_name,
                "exp_bus": exp_bus,
                "read_bus": read_bus,
                "bus_ok": bus_ok,
                "exp_vh": exp_vh,
                "read_vh": read_vh,
                "vh_ok": vh_ok,
                "sticker": True,
                "conf": round(conf, 4),
                "crop_px": crop_px,
                "raw_crop": f"{crop_px}px",
                "ocr_crop": f"{crop_px * 3}px" if crop_px else "0px",
                "variant": variant,
                "result": reason,
                "reason": reason,
                "cascade": cascade,
                "stages": stages,
                "ms": dur_ms,
            })

    # -------------------------------------------------------------
    # 3. Print Results Table
    # -------------------------------------------------------------
    print("\n" + "=" * 160)
    print("EVALUATION RESULTS TABLE (PIPELINE VERDICTS)")
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

    # Save results.json
    results_payload = {
        "timestamp": time.time(),
        "overall_ok": overall_ok,
        "total_items": len(rows),
        "passed_items": sum(1 for r in rows if r["bus_ok"] and r["vh_ok"]),
        "failed_items": sum(1 for r in rows if not (r["bus_ok"] and r["vh_ok"])),
        "rows": rows,
    }
    with open(out_dir / "results.json", "w", encoding="utf-8") as f:
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
