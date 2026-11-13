from __future__ import annotations

import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook

from .config import Config
from .db import ASCENDING, DESCENDING, iso_utc, public_doc, utc_naive
from .schemas import AnalyticsFilter, EventCreate, EventFilter, normalize_bus_number

FLAG_LABELS = {
    "unregistered_plate": "Unregistered plate",
    "low_ocr_confidence": "Low OCR confidence",
    "long_overstay": "Long overstay",
}

EXPORT_FIELDS = [
    "timestamp",
    "bus_number",
    "direction",
    "gate",
    "camera_id",
    "confidence",
    "flagged",
    "flag_reasons",
]


def aware_now() -> datetime:
    return datetime.now(timezone.utc)


def naive_now() -> datetime:
    return utc_naive(aware_now())


def day_bounds(config: Config, value: date | datetime | None = None) -> tuple[datetime, datetime]:
    zone = ZoneInfo(config.app_timezone)
    if value is None:
        reference = aware_now().astimezone(zone)
    elif isinstance(value, datetime):
        reference = value.astimezone(zone) if value.tzinfo else value.replace(tzinfo=timezone.utc).astimezone(zone)
    else:
        reference = datetime.combine(value, time.min, tzinfo=zone)
    start_local = datetime.combine(reference.date(), time.min, tzinfo=zone)
    end_local = start_local + timedelta(days=1)
    return utc_naive(start_local), utc_naive(end_local)


def build_event_query(event_filter: EventFilter, config: Config) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if event_filter.date:
        start, end = day_bounds(config, event_filter.date)
        query["timestamp"] = {"$gte": start, "$lt": end}
    elif event_filter.date_from or event_filter.date_to:
        timestamp_query: dict[str, datetime] = {}
        if event_filter.date_from:
            timestamp_query["$gte"] = utc_naive(event_filter.date_from)
        if event_filter.date_to:
            timestamp_query["$lte"] = utc_naive(event_filter.date_to)
        query["timestamp"] = timestamp_query
    if event_filter.bus_number:
        query["bus_number"] = event_filter.bus_number
    if event_filter.gate:
        query["gate"] = event_filter.gate
    if event_filter.direction:
        query["direction"] = event_filter.direction
    if event_filter.flagged is not None:
        query["flagged"] = event_filter.flagged
    return query


def event_sort() -> list[tuple[str, int]]:
    return [("timestamp", DESCENDING), ("_id", DESCENDING)]


def query_events(db, event_filter: EventFilter, config: Config, *, limit: int | None = None, skip: int = 0):
    cursor = db.events.find(build_event_query(event_filter, config)).sort(event_sort())
    if skip:
        cursor = cursor.skip(skip)
    if limit is not None:
        cursor = cursor.limit(limit)
    return list(cursor)


def compute_flag_reasons(db, event: dict[str, Any], config: Config) -> list[str]:
    reasons: list[str] = []
    bus_number = normalize_bus_number(event["bus_number"])
    if not db.buses.find_one({"bus_number": bus_number}, {"_id": 1}):
        reasons.append("unregistered_plate")
    if float(event["confidence"]) < config.ocr_confidence_threshold:
        reasons.append("low_ocr_confidence")

    prior_in = db.events.find_one(
        {
            "bus_number": bus_number,
            "direction": "IN",
            "timestamp": {"$lt": event["timestamp"]},
        },
        sort=[("timestamp", DESCENDING), ("_id", DESCENDING)],
    )
    if prior_in:
        later_out = db.events.find_one(
            {
                "bus_number": bus_number,
                "direction": "OUT",
                "timestamp": {"$gt": prior_in["timestamp"], "$lt": event["timestamp"]},
            },
            {"_id": 1},
        )
        if not later_out:
            hours_inside = (event["timestamp"] - prior_in["timestamp"]).total_seconds() / 3600
            if hours_inside > config.overstay_hours:
                reasons.append("long_overstay")
    return sorted(set(reasons))


def ingest_event(db, payload: EventCreate, config: Config, *, source: str = "device") -> dict[str, Any]:
    data = payload.model_dump()
    event = {
        "bus_number": normalize_bus_number(data["bus_number"]),
        "direction": data["direction"],
        "gate": data["gate"],
        "camera_id": data["camera_id"],
        "confidence": float(data["confidence"]),
        "timestamp": utc_naive(data["timestamp"]),
        "created_at": naive_now(),
        "source": source,
    }
    event["flag_reasons"] = compute_flag_reasons(db, event, config)
    event["flagged"] = bool(event["flag_reasons"])
    result = db.events.insert_one(event)
    event["_id"] = result.inserted_id
    return public_doc(event)


def compute_stats(db, config: Config) -> dict[str, Any]:
    now = naive_now()
    start, end = day_bounds(config)
    all_events = list(
        db.events.find(
            {},
            {
                "bus_number": 1,
                "direction": 1,
                "timestamp": 1,
                "flagged": 1,
                "flag_reasons": 1,
                "gate": 1,
                "camera_id": 1,
                "confidence": 1,
            },
        ).sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
    )

    latest_by_bus: dict[str, dict[str, Any]] = {}
    for event in all_events:
        latest_by_bus[event["bus_number"]] = event

    inside_buses: list[dict[str, Any]] = []
    for bus_number, event in latest_by_bus.items():
        if event["direction"] != "IN":
            continue
        hours_inside = max(0.0, (now - event["timestamp"]).total_seconds() / 3600)
        inside_buses.append(
            {
                "bus_number": bus_number,
                "since": iso_utc(event["timestamp"]),
                "hours_inside": round(hours_inside, 2),
                "overstay": hours_inside > config.overstay_hours,
            }
        )
    inside_buses.sort(key=lambda item: item["hours_inside"], reverse=True)

    today_query = {"timestamp": {"$gte": start, "$lt": end}}
    entries_today = db.events.count_documents({**today_query, "direction": "IN"})
    exits_today = db.events.count_documents({**today_query, "direction": "OUT"})
    events_today = db.events.count_documents(today_query)
    flagged_today = db.events.count_documents({**today_query, "flagged": True})
    unrecognized_today = db.events.count_documents(
        {**today_query, "flag_reasons": "unregistered_plate"}
    )

    reason_counts: Counter[str] = Counter()
    flagged_events = db.events.find(
        {**today_query, "flagged": True},
        {"flag_reasons": 1},
    )
    for event in flagged_events:
        reason_counts.update(event.get("flag_reasons", []))

    last_event_doc = db.events.find_one({}, sort=event_sort())
    return {
        "generated_at": iso_utc(now),
        "timezone": config.app_timezone,
        "total_buses": db.buses.count_documents({}),
        "total_drivers": db.drivers.count_documents({}),
        "buses_inside": len(inside_buses),
        "inside_buses": inside_buses,
        "entries_today": entries_today,
        "exits_today": exits_today,
        "events_today": events_today,
        "flagged_today": flagged_today,
        "unrecognized_today": unrecognized_today,
        "flagged_reason_counts": {
            key: reason_counts.get(key, 0) for key in FLAG_LABELS
        },
        "flag_labels": FLAG_LABELS,
        "rules": {
            "ocr_confidence_threshold": config.ocr_confidence_threshold,
            "overstay_hours": config.overstay_hours,
        },
        "last_event": public_doc(last_event_doc),
    }


def compute_analytics(db, analytics_filter: AnalyticsFilter, config: Config) -> dict[str, Any]:
    now = naive_now()
    zone = ZoneInfo(config.app_timezone)
    now_local = now.replace(tzinfo=timezone.utc).astimezone(zone)

    if analytics_filter.date:
        start_utc, end_utc = day_bounds(config, analytics_filter.date)
        start_local = start_utc.replace(tzinfo=timezone.utc).astimezone(zone)
        end_local = end_utc.replace(tzinfo=timezone.utc).astimezone(zone)
    else:
        # Align the window to whole campus-local hours so the chart has exactly
        # `hours` buckets instead of a partial leading hour. The window always
        # reaches the end of the current hour, so "now" is always included.
        end_local = now_local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        start_local = end_local - timedelta(hours=analytics_filter.hours)
        start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)

    event_filter = EventFilter(
        date_from=start_utc.replace(tzinfo=timezone.utc),
        date_to=end_utc.replace(tzinfo=timezone.utc),
        bus_number=analytics_filter.bus_number,
        gate=analytics_filter.gate,
        direction=analytics_filter.direction,
    )
    query = build_event_query(event_filter, config)
    query["timestamp"] = {"$gte": start_utc, "$lt": end_utc}
    events = list(db.events.find(query).sort([("timestamp", ASCENDING)]).limit(50_000))

    def hour_key(timestamp: datetime) -> datetime:
        """Bucket key (UTC) for a timestamp, grouped by campus-local hour."""
        local = timestamp.replace(tzinfo=timezone.utc).astimezone(zone)
        local = local.replace(minute=0, second=0, microsecond=0)
        return local.astimezone(timezone.utc).replace(tzinfo=None)

    hour_counts: Counter[datetime] = Counter()
    gate_counts: Counter[str] = Counter()
    bus_counts: Counter[str] = Counter()
    for event in events:
        hour_counts[hour_key(event["timestamp"])] += 1
        gate_counts[event.get("gate", "Unknown")] += 1
        bus_counts[event.get("bus_number", "Unknown")] += 1

    per_hour: list[dict[str, Any]] = []
    bucket_local = start_local
    while bucket_local < end_local:
        key = bucket_local.astimezone(timezone.utc).replace(tzinfo=None)
        per_hour.append(
            {
                "hour": iso_utc(key),
                "label": bucket_local.strftime("%H:00"),
                "count": hour_counts.get(key, 0),
            }
        )
        bucket_local += timedelta(hours=1)

    return {
        "range": {"from": iso_utc(start_utc), "to": iso_utc(end_utc), "timezone": config.app_timezone},
        "direction": analytics_filter.direction,
        "per_hour": per_hour,
        "per_gate": [
            {"gate": gate, "count": count} for gate, count in gate_counts.most_common(12)
        ],
        "per_bus": [
            {"bus_number": bus, "count": count} for bus, count in bus_counts.most_common(12)
        ],
        "totals": {
            "events": len(events),
            "gates": len(gate_counts),
            "buses": len(bus_counts),
        },
    }

def events_for_export(db, event_filter: EventFilter, config: Config, *, max_rows: int = 10_000):
    docs = query_events(db, event_filter, config, limit=max_rows)
    rows: list[dict[str, Any]] = []
    for doc in docs:
        public = public_doc(doc)
        rows.append(
            {
                "timestamp": public.get("timestamp", ""),
                "bus_number": public.get("bus_number", ""),
                "direction": public.get("direction", ""),
                "gate": public.get("gate", ""),
                "camera_id": public.get("camera_id", ""),
                "confidence": public.get("confidence", ""),
                "flagged": "yes" if public.get("flagged") else "no",
                "flag_reasons": ", ".join(public.get("flag_reasons", [])),
            }
        )
    return rows


def safe_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_FIELDS, quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: safe_cell(row.get(key, "")) for key in EXPORT_FIELDS})
    return buffer.getvalue().encode("utf-8-sig")


def xlsx_bytes(rows: list[dict[str, Any]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Bus Events"
    sheet.append(EXPORT_FIELDS)
    for row in rows:
        sheet.append([safe_cell(row.get(key, "")) for key in EXPORT_FIELDS])
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    widths = {"A": 22, "B": 16, "C": 10, "D": 18, "E": 16, "F": 12, "G": 10, "H": 36}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def sanitized_xff(flask_request) -> str | None:
    if not flask_request:
        return None
    raw = flask_request.headers.get("X-Forwarded-For", "")
    if not raw:
        return None
    cleaned = "".join(ch for ch in raw if 32 <= ord(ch) <= 126).strip()
    return cleaned[:128] or None


def record_audit(db, actor: dict[str, Any] | None, action: str, collection: str,
                 record_id: Any = None, before: dict | None = None,
                 after: dict | None = None, flask_request=None) -> None:
    after_doc = public_doc(after)
    if flask_request and action in {"login", "login_failed", "login_denied", "login_provisioned"}:
        xff_raw = sanitized_xff(flask_request)
        if xff_raw:
            after_doc = dict(after_doc) if isinstance(after_doc, dict) else {}
            after_doc["xff_raw"] = xff_raw
    entry = {
        "timestamp": naive_now(),
        "actor": actor.get("email", "system") if actor else "system",
        "role": actor.get("role", "system") if actor else "system",
        "action": action,
        "collection": collection,
        "record_id": str(record_id) if record_id is not None else None,
        "before": public_doc(before),
        "after": after_doc,
        "ip": flask_request.remote_addr if flask_request else None,
        "user_agent": (
            flask_request.headers.get("User-Agent", "")[:200] if flask_request else None
        ),
    }
    db.audit_logs.insert_one(entry)


def camera_config(config: Config) -> dict[str, Any]:
    definitions = [
        {"id": "gate-1-entry", "label": "Gate 1 Entry"},
        {"id": "gate-1-exit", "label": "Gate 1 Exit"},
        {"id": "gate-2-entry", "label": "Gate 2 Entry"},
        {"id": "gate-2-exit", "label": "Gate 2 Exit"},
    ]
    cameras = []
    for definition in definitions:
        stream = config.camera_streams.get(definition["id"])
        item = dict(definition)
        if stream:
            item.update(
                {
                    "demo": False,
                    "stream_type": stream["type"],
                    "stream_url": stream["url"],
                    "label": stream["label"],
                }
            )
        else:
            item.update({"demo": True, "stream_type": None, "stream_url": None})
        cameras.append(item)
    return {
        "cameras": cameras,
        "flag_labels": FLAG_LABELS,
        "rules": {
            "ocr_confidence_threshold": config.ocr_confidence_threshold,
            "overstay_hours": config.overstay_hours,
        },
        "camera_support": {
            "browser_camera": True,
            "hls": True,
            "mjpeg": True,
            "rtsp": "gateway_required",
            "notes": (
                "Raw RTSP cannot be opened by a browser. Bridge IP cameras through "
                "MediaMTX, FFmpeg or the NVR's own HLS/MJPEG output and point the "
                "stream URL at that gateway."
            ),
        },
    }
