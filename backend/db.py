from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import mongomock
from bson import ObjectId
from pymongo import ASCENDING, DESCENDING, MongoClient, timeout as mongo_timeout
from pymongo.errors import ConfigurationError, ConnectionFailure, ExecutionTimeout, OperationFailure

from .config import Config


logger = logging.getLogger(__name__)
MONGO_STARTUP_TIMEOUT_SECONDS = 120
MONGO_STARTUP_ATTEMPT_TIMEOUT_SECONDS = 20
MONGO_STARTUP_RETRY_DELAY_SECONDS = 5


def create_mongo_client(uri: str):
    if uri.startswith("mongomock://"):
        return mongomock.MongoClient()
    return MongoClient(uri, serverSelectionTimeoutMS=5_000, connectTimeoutMS=5_000)


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


def get_database_for_startup(config: Config, mongo_client=None):
    """Initialize the DB before serving requests, retrying transient egress delays.

    Cloud Run Direct VPC egress with Cloud NAT can take over a minute to become
    usable on a cold start. Creating the indexes is idempotent, so retry only
    connection and DNS/configuration failures in production. Authentication
    and permission failures still fail immediately. The management CLI uses
    ``get_database`` directly and is not slowed by these startup retries.

    No new attempt starts after the 120-second retry window. PyMongo's
    client-side operation timeout bounds the index operations but does not
    strictly bound SRV/TXT DNS lookups during MongoClient construction; those
    use connectTimeoutMS separately. The window is therefore a target, not a
    hard real-time guarantee under all resolver/OS behavior.
    """
    if config.environment != "production":
        return get_database(config, mongo_client)

    client = mongo_client
    deadline = time.monotonic() + MONGO_STARTUP_TIMEOUT_SECONDS
    attempt = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            # Do not include the connection string or driver exception in logs.
            raise RuntimeError(
                "MongoDB initialization failed after retries; check DNS, "
                "network connectivity, Atlas IP access and connection configuration."
            ) from None
        attempt += 1
        try:
            # Apply one timeout to all index operations in this attempt, and
            # never grant an operation more than the remaining retry window.
            with mongo_timeout(min(MONGO_STARTUP_ATTEMPT_TIMEOUT_SECONDS, remaining)):
                if client is None:
                    client = create_mongo_client(config.mongo_uri)
                return get_database(config, client)
        except (ConfigurationError, ConnectionFailure, ExecutionTimeout):
            remaining = deadline - time.monotonic()
            if remaining > 0:
                logger.warning("MongoDB initialization is not ready; retrying (attempt %s).", attempt)
                time.sleep(min(MONGO_STARTUP_RETRY_DELAY_SECONDS, remaining))
        except OperationFailure:
            # Authentication and authorization failures are not transient.
            raise RuntimeError(
                "MongoDB rejected database initialization; check the database "
                "credentials, permissions and index state."
            ) from None


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
