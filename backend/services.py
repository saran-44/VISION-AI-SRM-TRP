from __future__ import annotations

import csv
import io
import threading
import time as monotonic_time
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from openpyxl import Workbook

from sqlalchemy.exc import IntegrityError

from .config import Config
from .db import ASCENDING, DESCENDING, iso_utc, public_doc, utc_naive
from .schemas import AnalyticsFilter, EventCreate, EventFilter, normalize_bus_number, plate_key

_stats_cache_lock = threading.Lock()
_stats_cache: dict[tuple[int, str], tuple[float, dict[str, Any]]] = {}

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


def _canonical_bus_number(db, raw_bus_number: str) -> tuple[str, bool]:
    normalized = normalize_bus_number(raw_bus_number)
    key = plate_key(normalized)
    if key:
        registered = db.buses.find_one({"plate_key": key}, {"bus_number": 1})
        if registered:
            return registered["bus_number"], True
    registered = db.buses.find_one({"bus_number": normalized}, {"bus_number": 1})
    if registered:
        return registered["bus_number"], True
    return normalized, False


def compute_flag_reasons(
    db,
    event: dict[str, Any],
    config: Config,
    *,
    is_registered: bool | None = None,
) -> list[str]:
    reasons: list[str] = []
    bus_number = normalize_bus_number(event["bus_number"])
    if is_registered is None:
        bus_number, is_registered = _canonical_bus_number(db, bus_number)
    if not is_registered:
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
                "$or": [
                    {
                        "timestamp": prior_in["timestamp"],
                        "_id": {"$gt": prior_in["_id"]},
                    },
                    {
                        "timestamp": {"$gt": prior_in["timestamp"], "$lt": event["timestamp"]},
                    },
                ],
            },
            {"_id": 1},
        )
        if not later_out:
            hours_inside = (event["timestamp"] - prior_in["timestamp"]).total_seconds() / 3600
            if hours_inside > config.overstay_hours:
                reasons.append("long_overstay")
    return sorted(set(reasons))


def invalidate_stats_cache(db=None) -> None:
    with _stats_cache_lock:
        if db is None:
            _stats_cache.clear()
            return
        target = id(db)
        for key in [k for k in _stats_cache if k[0] == target]:
            _stats_cache.pop(key, None)


def _bus_state_from_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "bus_number": normalize_bus_number(event["bus_number"]),
        "direction": event["direction"],
        "last_timestamp": utc_naive(event["timestamp"]),
        "last_event_id": str(event["_id"]),
        "gate": event.get("gate"),
        "camera_id": event.get("camera_id"),
        "demo": bool(event.get("demo", False)),
        "updated_at": naive_now(),
    }


def rebuild_bus_states(db) -> int:
    """Idempotently rebuild bus_states from events ordered by (timestamp, _id)."""
    latest_by_bus: dict[str, dict[str, Any]] = {}
    cursor = db.events.find(
        {},
        {
            "_id": 1,
            "bus_number": 1,
            "direction": 1,
            "timestamp": 1,
            "gate": 1,
            "camera_id": 1,
            "demo": 1,
        },
    ).sort([("timestamp", ASCENDING), ("_id", ASCENDING)])
    for event in cursor:
        bus_number = normalize_bus_number(event["bus_number"])
        latest_by_bus[bus_number] = event
    for event in latest_by_bus.values():
        db.upsert_bus_state(_bus_state_from_event(event))
    invalidate_stats_cache(db)
    return len(latest_by_bus)


def sync_bus_states_if_needed(db) -> int:
    """Backfill bus_states once when empty and events already exist."""
    if db.bus_states.find_one({}, {"_id": 1}) is not None:
        return 0
    if db.events.find_one({}, {"_id": 1}) is None:
        return 0
    return rebuild_bus_states(db)


def purge_expired_records(db, config: Config) -> dict[str, int]:
    """Delete expired events and bus_states only when retention_days > 0."""
    deleted = {"events": 0, "bus_states": 0}
    if config.event_retention_days > 0:
        cutoff = naive_now() - timedelta(days=config.event_retention_days)
        ev_res = db.events.delete_many({"timestamp": {"$lt": cutoff}})
        bs_res = db.bus_states.delete_many({"updated_at": {"$lt": cutoff}})
        deleted["events"] = int(getattr(ev_res, "deleted_count", 0) or 0)
        deleted["bus_states"] = int(getattr(bs_res, "deleted_count", 0) or 0)
        if deleted["events"] or deleted["bus_states"]:
            invalidate_stats_cache(db)
    return deleted


def ingest_event_with_status(
    db,
    payload: EventCreate,
    config: Config,
    *,
    source: str = "device",
    idempotency_key: str | None = None,
) -> tuple[dict[str, Any], bool]:
    if idempotency_key:
        existing = db.events.find_one({"idempotency_key": idempotency_key})
        if existing:
            return public_doc(existing), False

    data = payload.model_dump()
    canonical_bus, is_registered = _canonical_bus_number(db, data["bus_number"])
    event_ts = utc_naive(data["timestamp"])

    if config.event_dedup_window_seconds > 0:
        window = timedelta(seconds=config.event_dedup_window_seconds)
        duplicate = db.events.find_one(
            {
                "bus_number": canonical_bus,
                "direction": data["direction"],
                "camera_id": data["camera_id"],
                "timestamp": {"$gte": event_ts - window, "$lte": event_ts + window},
            },
            sort=event_sort(),
        )
        if duplicate:
            return public_doc(duplicate), False

    event: dict[str, Any] = {
        "bus_number": canonical_bus,
        "direction": data["direction"],
        "gate": data["gate"],
        "camera_id": data["camera_id"],
        "confidence": float(data["confidence"]),
        "timestamp": event_ts,
        "created_at": naive_now(),
        "source": source,
    }
    if idempotency_key is not None:
        event["idempotency_key"] = idempotency_key
    event["flag_reasons"] = compute_flag_reasons(db, event, config, is_registered=is_registered)
    event["flagged"] = bool(event["flag_reasons"])
    try:
        result = db.events.insert_one(event)
    except IntegrityError:
        if idempotency_key:
            existing = db.events.find_one({"idempotency_key": idempotency_key})
            if existing:
                return public_doc(existing), False
        raise
    event["_id"] = result.inserted_id
    db.upsert_bus_state(_bus_state_from_event(event))
    invalidate_stats_cache(db)
    return public_doc(event), True


def ingest_event(
    db,
    payload: EventCreate,
    config: Config,
    *,
    source: str = "device",
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    event, _ = ingest_event_with_status(
        db,
        payload,
        config,
        source=source,
        idempotency_key=idempotency_key,
    )
    return event


def compute_stats(db, config: Config) -> dict[str, Any]:
    cache_key = (id(db), config.app_timezone)
    if config.stats_cache_seconds > 0:
        with _stats_cache_lock:
            cached = _stats_cache.get(cache_key)
            if cached and (monotonic_time.monotonic() - cached[0]) < config.stats_cache_seconds:
                return dict(cached[1])

    now = naive_now()
    start, end = day_bounds(config)
    sync_bus_states_if_needed(db)

    inside_buses: list[dict[str, Any]] = []
    for state in db.bus_states.find({"direction": "IN"}, {"bus_number": 1, "last_timestamp": 1}):
        hours_inside = max(0.0, (now - state["last_timestamp"]).total_seconds() / 3600)
        inside_buses.append(
            {
                "bus_number": state["bus_number"],
                "since": iso_utc(state["last_timestamp"]),
                "hours_inside": round(hours_inside, 2),
                "overstay": hours_inside > config.overstay_hours,
            }
        )
    inside_buses.sort(key=lambda item: item["hours_inside"], reverse=True)

    today_query = {"timestamp": {"$gte": start, "$lt": end}}
    entries_today = 0
    exits_today = 0
    events_today = 0
    flagged_today = 0
    unrecognized_today = 0
    reason_counts: Counter[str] = Counter()

    for event in db.events.find(today_query, {"direction": 1, "flagged": 1, "flag_reasons": 1}):
        events_today += 1
        if event.get("direction") == "IN":
            entries_today += 1
        elif event.get("direction") == "OUT":
            exits_today += 1
        if event.get("flagged"):
            flagged_today += 1
            reasons = event.get("flag_reasons") or []
            reason_counts.update(reasons)
            if "unregistered_plate" in reasons:
                unrecognized_today += 1
        elif "unregistered_plate" in (event.get("flag_reasons") or []):
            unrecognized_today += 1

    last_event_doc = db.events.find_one({}, sort=event_sort())
    payload = {
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
    if config.stats_cache_seconds > 0:
        with _stats_cache_lock:
            _stats_cache[cache_key] = (monotonic_time.monotonic(), dict(payload))
    return payload


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
    agg = db.aggregate_analytics(query, config.app_timezone)
    hour_counts = agg["hour_counts"]

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
        "per_gate": agg["per_gate"],
        "per_bus": agg["per_bus"],
        "totals": agg["totals"],
    }


def _export_row(doc: dict[str, Any]) -> dict[str, Any]:
    public = public_doc(doc)
    return {
        "timestamp": public.get("timestamp", ""),
        "bus_number": public.get("bus_number", ""),
        "direction": public.get("direction", ""),
        "gate": public.get("gate", ""),
        "camera_id": public.get("camera_id", ""),
        "confidence": public.get("confidence", ""),
        "flagged": "yes" if public.get("flagged") else "no",
        "flag_reasons": ", ".join(public.get("flag_reasons", [])),
    }


def is_export_truncated(
    db,
    event_filter: EventFilter,
    config: Config,
    *,
    max_rows: int | None = None,
) -> tuple[bool, int]:
    limit = max_rows if max_rows is not None else config.export_max_rows
    query = build_event_query(event_filter, config)
    return db.events.count_documents_capped(query, limit + 1) > limit, limit


def iter_export_rows(
    db,
    event_filter: EventFilter,
    config: Config,
    *,
    max_rows: int | None = None,
    batch_size: int = 500,
):
    limit = max_rows if max_rows is not None else config.export_max_rows
    query = build_event_query(event_filter, config)
    projection = {field: 1 for field in EXPORT_FIELDS}
    offset = 0
    while offset < limit:
        chunk_limit = min(batch_size, limit - offset)
        batch = list(
            db.events.find(query, projection)
            .sort(event_sort())
            .skip(offset)
            .limit(chunk_limit)
        )
        if not batch:
            break
        for doc in batch:
            yield _export_row(doc)
        if len(batch) < chunk_limit:
            break
        offset += len(batch)


def events_for_export(
    db,
    event_filter: EventFilter,
    config: Config,
    *,
    max_rows: int | None = None,
):
    return list(iter_export_rows(db, event_filter, config, max_rows=max_rows))


def safe_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def iter_csv_chunks(rows, *, chunk_rows: int = 250):
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=EXPORT_FIELDS, quoting=csv.QUOTE_MINIMAL)
    writer.writeheader()
    yield ("\ufeff" + buffer.getvalue()).encode("utf-8")
    buffer.seek(0)
    buffer.truncate(0)

    pending = 0
    for row in rows:
        writer.writerow({key: safe_cell(row.get(key, "")) for key in EXPORT_FIELDS})
        pending += 1
        if pending >= chunk_rows:
            yield buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate(0)
            pending = 0
    if pending:
        yield buffer.getvalue().encode("utf-8")


def csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(iter_csv_chunks(rows))


def xlsx_bytes(rows) -> bytes:
    workbook = Workbook(write_only=True)
    sheet = workbook.create_sheet("Bus Events")
    sheet.freeze_panes = "A2"
    widths = {"A": 22, "B": 16, "C": 10, "D": 18, "E": 16, "F": 12, "G": 10, "H": 36}
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width
    sheet.append(EXPORT_FIELDS)
    row_count = 1
    for row in rows:
        sheet.append([safe_cell(row.get(key, "")) for key in EXPORT_FIELDS])
        row_count += 1
    sheet.auto_filter.ref = f"A1:H{row_count}"
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
