#!/usr/bin/env python3
"""Run live gate camera replay test of busvideo1.mp4.

Requirements:
- 8 buses -> 8 events
- 8 bus numbers correct
- No duplicates when the same bus stays in frame (EVENT_DEBOUNCE_SECONDS=60)
- Process survives 10 minutes with stable memory
- Reports: events created, numbers, duplicates suppressed, memory before/after
"""
from __future__ import annotations

import os
import sys
import time
import secrets
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cv2
import psutil

# Configure environment for live gate replay
db_path = ROOT / "local_media" / "live.db"
if db_path.exists():
    try:
        db_path.unlink()
    except Exception:
        pass

temp_dir = Path(os.environ.get("TEMP", "/tmp")) / "vision-live"
temp_dir.mkdir(parents=True, exist_ok=True)

os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
os.environ["ENVIRONMENT"] = "gate"
os.environ["JWT_SECRET"] = os.environ.get("JWT_SECRET") or secrets.token_hex(32)
os.environ["VISION_DATA_DIR"] = str(temp_dir)
os.environ["EVENT_DEBOUNCE_SECONDS"] = "60"

from backend.config import Config
from backend.db import get_database
from backend.schemas import EventCreate
from backend.services import ingest_event
from backend.vision import decode_image, detect, best_identification


def get_process_memory_mb() -> float:
    return psutil.Process().memory_info().rss / (1024 * 1024)


def run_live_replay(video_path: Path, max_duration_sec: float = 600.0) -> dict:
    cfg = Config.from_env()
    db = get_database(cfg)

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_duration_s = total_frames / fps

    print(f"Loaded {video_path.name}: {total_frames} frames ({video_duration_s:.1f}s @ {fps:.1f} fps)")
    print(f"Target DB: {cfg.database_url}")
    print(f"Data Dir: {temp_dir}")
    print(f"Debounce Window: {cfg.event_debounce_seconds}s")

    mem_start = get_process_memory_mb()
    print(f"Initial Memory RSS: {mem_start:.2f} MB\n")

    events_created = []
    duplicates_suppressed = []

    # 1. First run: full pass to verify 8 buses -> 8 events
    print("=" * 70)
    print("PASS 1: LIVE REPLAY PASS (8 BUSES -> 8 EVENTS VERIFICATION)")
    print("=" * 70)

    f_idx = 0
    base_time = datetime.now(timezone.utc)

    while f_idx < total_frames:
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            break
        t_sec = f_idx / fps
        sim_time = base_time + timedelta(seconds=t_sec)

        _, buf = cv2.imencode(".jpg", frame)
        pil_img = decode_image(buf.tobytes())
        # Live path: sticker stage only (imgsz=640)
        res = detect(pil_img, stages={"sticker": True, "number_plate": False, "vehicle": False})
        c = best_identification(res)

        if c and c.bus_number:
            box_h = abs(c.bbox[2] - c.bbox[0]) if len(c.bbox) == 4 else 0
            box_w = abs(c.bbox[3] - c.bbox[1]) if len(c.bbox) == 4 else 0
            # Min dimensions: require at least 18px to avoid far-field pixel noise
            if min(box_h, box_w) >= 18:
                payload = EventCreate(
                    bus_number=c.bus_number,
                    direction="IN",
                    gate="Gate 1 Entry",
                    camera_id="gate-1-entry",
                    confidence=float(c.confidence),
                    timestamp=sim_time,
                )
                ev = ingest_event(db, payload, cfg, source="gate-camera")
                if ev.get("duplicate"):
                    duplicates_suppressed.append((c.bus_number, round(t_sec, 2), float(c.confidence)))
                    print(f"  [DUP SUPPRESSED] Bus {c.bus_number} at {t_sec:.1f}s (conf {c.confidence:.2f})")
                else:
                    events_created.append((c.bus_number, round(t_sec, 2), float(c.confidence)))
                    print(f"  [EVENT CREATED]  Bus {c.bus_number} at {t_sec:.1f}s (conf {c.confidence:.2f})")

        f_idx += 15  # Sample cadence at 2 fps

    mem_after_pass1 = get_process_memory_mb()
    print("-" * 70)
    print(f"Pass 1 complete. Events: {len(events_created)}, Dups: {len(duplicates_suppressed)}")
    print(f"Memory after Pass 1: {mem_after_pass1:.2f} MB (Delta: {mem_after_pass1 - mem_start:+.2f} MB)\n")

    # 2. 10-minute continuous longevity loop
    print("=" * 70)
    print(f"LONGEVITY TEST: CONTINUOUS LIVE CADENCE FOR 10 MINUTES ({max_duration_sec}s)")
    print("=" * 70)

    loop_start = time.monotonic()
    last_log_time = loop_start
    minute_readings = [(0, mem_after_pass1)]
    loop_pass = 1

    while (time.monotonic() - loop_start) < max_duration_sec:
        loop_pass += 1
        f_idx = 0
        while f_idx < total_frames and (time.monotonic() - loop_start) < max_duration_sec:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            _, buf = cv2.imencode(".jpg", frame)
            pil_img = decode_image(buf.tobytes())
            res = detect(pil_img, stages={"sticker": True, "number_plate": False, "vehicle": False})
            c = best_identification(res)
            if c and c.bus_number:
                box_h = abs(c.bbox[2] - c.bbox[0]) if len(c.bbox) == 4 else 0
                box_w = abs(c.bbox[3] - c.bbox[1]) if len(c.bbox) == 4 else 0
                if min(box_h, box_w) >= 18:
                    now_utc = datetime.now(timezone.utc)
                    payload = EventCreate(
                        bus_number=c.bus_number,
                        direction="IN",
                        gate="Gate 1 Entry",
                        camera_id="gate-1-entry",
                        confidence=float(c.confidence),
                        timestamp=now_utc,
                    )
                    # All subsequent scans are debounced or recorded
                    ev = ingest_event(db, payload, cfg, source="gate-camera")
                    if ev.get("duplicate"):
                        duplicates_suppressed.append((c.bus_number, 0, float(c.confidence)))

            f_idx += 30  # Cadence during longevity run

            # Log memory every 60 seconds
            now = time.monotonic()
            if now - last_log_time >= 60.0:
                elapsed_min = int(round((now - loop_start) / 60.0))
                current_rss = get_process_memory_mb()
                minute_readings.append((elapsed_min, current_rss))
                print(f"  T+{elapsed_min:02d}m: Memory RSS = {current_rss:.2f} MB (Delta: {current_rss - mem_start:+.2f} MB)")
                last_log_time = now

    cap.release()
    mem_final = get_process_memory_mb()
    print("-" * 70)
    print(f"Longevity run finished after {(time.monotonic() - loop_start) / 60.0:.1f} minutes.")
    print(f"Final Memory RSS: {mem_final:.2f} MB")
    print(f"Total Memory Change over 10m: {mem_final - mem_start:+.2f} MB")
    print("=" * 70)

    return {
        "events_created": events_created,
        "duplicates_suppressed_count": len(duplicates_suppressed),
        "mem_start_mb": round(mem_start, 2),
        "mem_after_pass1_mb": round(mem_after_pass1, 2),
        "mem_final_mb": round(mem_final, 2),
        "minute_readings": minute_readings,
    }


if __name__ == "__main__":
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
    res = run_live_replay(ROOT / "local_media" / "busvideo1.mp4", max_duration_sec=dur)
