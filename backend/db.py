from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import mongomock
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient

from .config import Config


def create_mongo_client(uri: str):
    if uri.startswith("mongomock://"):
        return mongomock.MongoClient()
    return MongoClient(uri, serverSelectionTimeoutMS=5_000)


def ensure_indexes(db) -> None:
    db.users.create_index([("email", ASCENDING)], unique=True, name="users_email_unique")
    db.buses.create_index([("bus_number", ASCENDING)], unique=True, name="buses_number_unique")
    db.drivers.create_index([("name", ASCENDING)], name="drivers_name")
    db.drivers.create_index([("bus_number", ASCENDING)], name="drivers_bus_number")
    db.events.create_index([("timestamp", DESCENDING)], name="events_timestamp")
    db.events.create_index(
        [("bus_number", ASCENDING), ("timestamp", DESCENDING)],
        name="events_bus_timestamp",
    )
    db.events.create_index(
        [("gate", ASCENDING), ("direction", ASCENDING), ("timestamp", DESCENDING)],
        name="events_gate_direction_timestamp",
    )
    db.events.create_index(
        [("camera_id", ASCENDING), ("timestamp", DESCENDING)],
        name="events_camera_timestamp",
    )
    db.events.create_index(
        [("flagged", ASCENDING), ("timestamp", DESCENDING)],
        name="events_flagged_timestamp",
    )
    db.events.create_index(
        [("flag_reasons", ASCENDING), ("timestamp", DESCENDING)],
        name="events_reason_timestamp",
    )
    db.audit_logs.create_index([("timestamp", DESCENDING)], name="audit_timestamp")
    db.audit_logs.create_index([("actor", ASCENDING), ("timestamp", DESCENDING)], name="audit_actor")


def get_database(config: Config, mongo_client=None):
    client = mongo_client or create_mongo_client(config.mongo_uri)
    db = client[config.mongo_db_name]
    ensure_indexes(db)
    return db


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def iso_utc(value: datetime) -> str:
    return utc_naive(value).isoformat(timespec="seconds") + "Z"


def public_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    result: dict[str, Any] = {}
    for key, value in doc.items():
        if key == "_id":
            result["id"] = str(value)
        elif isinstance(value, ObjectId):
            result[key] = str(value)
        elif isinstance(value, datetime):
            result[key] = iso_utc(value)
        elif isinstance(value, dict):
            result[key] = public_doc(value)
        elif isinstance(value, list):
            result[key] = [
                public_doc(item) if isinstance(item, dict) else
                iso_utc(item) if isinstance(item, datetime) else
                str(item) if isinstance(item, ObjectId) else item
                for item in value
            ]
        else:
            result[key] = value
    return result
