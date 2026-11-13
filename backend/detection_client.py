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
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

import requests

RETRYABLE_STATUS_CODES = {502, 503, 504}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Post one bus gate detection event")
    parser.add_argument("--bus-number", required=True, help="Normalized bus identifier, e.g. BUS-001")
    parser.add_argument("--direction", required=True, choices=["IN", "OUT", "in", "out"])
    parser.add_argument("--gate", required=True, help="Gate label, e.g. 'Gate 1'")
    parser.add_argument("--camera-id", required=True, help="Camera identifier")
    parser.add_argument("--confidence", required=True, type=float, help="OCR confidence between 0 and 1")
    parser.add_argument("--timestamp", help="ISO-8601 timestamp; defaults to current UTC time")
    parser.add_argument("--event-json", help="Read the complete event JSON from this file instead of flags")
    parser.add_argument("--idempotency-key", help="Optional X-Idempotency-Key value; defaults to a fresh UUID")
    parser.add_argument("--max-retries", type=int, default=3, help="Retry attempts for transient 502/503/504 or network errors")
    return parser


def _validate_api_url(raw_url: str) -> str:
    url = raw_url.strip().rstrip("/")
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("TRANSPORT_API_URL must be an http:// or https:// URL")
    return url


def post_event_with_retries(
    api_url: str,
    device_key: str,
    event: dict,
    *,
    idempotency_key: str | None = None,
    max_retries: int = 3,
    backoff_seconds: float = 0.5,
    session: requests.Session | None = None,
) -> requests.Response:
    url = f"{_validate_api_url(api_url)}/api/events"
    key = (idempotency_key or str(uuid.uuid4())).strip()
    headers = {
        "Content-Type": "application/json",
        "X-Device-Key": device_key,
        "X-Idempotency-Key": key,
    }
    own_session = session is None
    client = session or requests.Session()
    try:
        attempts = max(1, int(max_retries))
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                response = client.post(url, json=event, headers=headers, timeout=10)
            except requests.RequestException as exc:
                last_exc = exc
                if attempt + 1 >= attempts:
                    raise
                if backoff_seconds > 0:
                    time.sleep(backoff_seconds * (2**attempt))
                continue
            if response.status_code in RETRYABLE_STATUS_CODES and attempt + 1 < attempts:
                if backoff_seconds > 0:
                    time.sleep(backoff_seconds * (2**attempt))
                continue
            return response
        if last_exc is not None:  # pragma: no cover - defensive
            raise last_exc
        raise RuntimeError("No attempts executed")  # pragma: no cover - defensive
    finally:
        if own_session:
            client.close()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 0.0 <= args.confidence <= 1.0:
        print("--confidence must be between 0.0 and 1.0", file=sys.stderr)
        return 2

    try:
        api_url = _validate_api_url(os.getenv("TRANSPORT_API_URL", "http://localhost:5000"))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

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
        response = post_event_with_retries(
            api_url,
            device_key,
            event,
            idempotency_key=args.idempotency_key,
            max_retries=args.max_retries,
        )
    except requests.RequestException as exc:
        print(f"Could not reach the transport API: {type(exc).__name__}", file=sys.stderr)
        return 1

    print(f"HTTP {response.status_code}")
    print(response.text)
    return 0 if response.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
