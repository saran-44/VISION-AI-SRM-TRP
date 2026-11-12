#!/usr/bin/env python3
"""Small device client for POSTing one OCR event to /api/events.

Required environment variables:
  TRANSPORT_API_URL  Base URL of this service, e.g. https://transport.example.edu
  DEVICE_API_KEY     A key listed in the server's DEVICE_API_KEYS allowlist

The key is read from the environment and is never logged or printed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

import requests


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Post one bus gate detection event")
    parser.add_argument("--bus-number", required=True, help="Normalized bus identifier, e.g. BUS-001")
    parser.add_argument("--direction", required=True, choices=["IN", "OUT", "in", "out"])
    parser.add_argument("--gate", required=True, help="Gate label, e.g. 'Gate 1'")
    parser.add_argument("--camera-id", required=True, help="Camera identifier")
    parser.add_argument("--confidence", required=True, type=float, help="OCR confidence between 0 and 1")
    parser.add_argument("--timestamp", help="ISO-8601 timestamp; defaults to current UTC time")
    parser.add_argument("--event-json", help="Read the complete event JSON from this file instead of flags")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    api_url = os.getenv("TRANSPORT_API_URL", "http://localhost:5000").rstrip("/")
    device_key = os.getenv("DEVICE_API_KEY", "")
    if not device_key:
        print("DEVICE_API_KEY is required", file=sys.stderr)
        return 2

    if args.event_json:
        with open(args.event_json, "r", encoding="utf-8") as handle:
            event = json.load(handle)
    else:
        event = {
            "bus_number": args.bus_number,
            "direction": args.direction.upper(),
            "gate": args.gate,
            "camera_id": args.camera_id,
            "confidence": args.confidence,
            "timestamp": args.timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }

    try:
        response = requests.post(
            f"{api_url}/api/events",
            json=event,
            headers={"Content-Type": "application/json", "X-Device-Key": device_key},
            timeout=10,
        )
    except requests.RequestException as exc:
        print(f"Could not reach the transport API: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(f"HTTP {response.status_code}")
    print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
