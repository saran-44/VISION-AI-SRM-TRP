"""Private PostgreSQL storage for the transport portal.

The small table facade intentionally supports only the predicates used by the
application. All values are bound parameters and all columns are predefined.
The production schema is installed separately by an administrator; the runtime
role never needs DDL privileges. SQLite in-memory is for isolated previews/tests.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from sqlalchemy import (
    JSON, Boolean, Column, DateTime, Float, Index, Integer, MetaData, String, Table,
    Text, and_, create_engine, delete, func, insert, or_, select, update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError
from sqlalchemy.pool import StaticPool

from .config import Config

logger = logging.getLogger(__name__)
SCHEMA = "transport_portal"
SCHEMA_VERSION = 1
STARTUP_TIMEOUT_SECONDS = 120
STARTUP_RETRY_DELAY_SECONDS = 5
ASCENDING, DESCENDING = 1, -1

metadata = MetaData(schema=SCHEMA)
json_type = JSON().with_variant(JSONB(), "postgresql")


def _id_column():
    return Column("_id", String(24), primary_key=True)


def _timestamps():
    return [Column("created_at", DateTime()), Column("updated_at", DateTime())]


schema_version = Table("schema_version", metadata, Column("version", Integer, primary_key=True))
users = Table(
    "users", metadata, _id_column(), Column("email", String(254), nullable=False, unique=True),
    Column("password_hash", Text), Column("role", String(32), nullable=False),
    Column("active", Boolean, nullable=False, default=True), Column("auth_provider", Text),
    Column("firebase_uid", Text), Column("demo_user", Boolean, nullable=False, default=False),
    *_timestamps(), Column("last_sign_in_at", DateTime()),
)
buses = Table(
    "buses", metadata, _id_column(), Column("bus_number", String(20), nullable=False, unique=True),
    Column("registration_number", Text), Column("route", Text), Column("capacity", Integer),
    Column("insurance_expiry", Text), Column("status", Text), Column("notes", Text),
    Column("demo", Boolean, nullable=False, default=False), *_timestamps(),
)
drivers = Table(
    "drivers", metadata, _id_column(), Column("name", Text, nullable=False), Column("phone", Text),
    Column("bus_number", String(20), nullable=False), Column("license_number", Text),
    Column("notes", Text), Column("active", Boolean, nullable=False, default=True),
    Column("demo", Boolean, nullable=False, default=False), *_timestamps(),
)
events = Table(
    "events", metadata, _id_column(), Column("bus_number", String(20), nullable=False),
    Column("direction", String(3), nullable=False), Column("gate", Text, nullable=False),
    Column("camera_id", Text, nullable=False), Column("confidence", Float, nullable=False),
    Column("timestamp", DateTime(), nullable=False), Column("created_at", DateTime()),
    Column("source", Text), Column("flag_reasons", json_type, nullable=False, default=list),
    Column("flagged", Boolean, nullable=False, default=False),
    Column("demo", Boolean, nullable=False, default=False),
)
audit_logs = Table(
    "audit_logs", metadata, _id_column(), Column("timestamp", DateTime(), nullable=False),
    Column("actor", Text), Column("role", Text), Column("action", Text),
    Column("collection", Text), Column("record_id", Text), Column("before", json_type),
    Column("after", json_type), Column("ip", Text), Column("user_agent", Text),
)
Index("users_firebase_uid", users.c.firebase_uid)
Index("audit_collection_action_timestamp", audit_logs.c.collection, audit_logs.c.action, audit_logs.c.timestamp.desc())
TABLES = {table.name: table for table in (users, buses, drivers, events, audit_logs)}

# IDs remain 24 hexadecimal characters, preserving URLs and allowing a future
# explicit import of existing record IDs. They are identifiers, not secrets.
_id_lock = threading.Lock()
_id_random = secrets.token_bytes(5)
_id_counter = secrets.randbits(24)
_id_process = os.getpid()


def new_id() -> str:
    global _id_counter, _id_random, _id_process
    with _id_lock:
        if _id_process != os.getpid():
            _id_process = os.getpid()
            _id_random = secrets.token_bytes(5)
            _id_counter = secrets.randbits(24)
        _id_counter = (_id_counter + 1) % (1 << 24)
        return (int(time.time()).to_bytes(4, "big") + _id_random + _id_counter.to_bytes(3, "big")).hex()


def valid_id(value: str) -> bool:
    return isinstance(value, str) and len(value) == 24 and all(c in "0123456789abcdefABCDEF" for c in value)


def create_database_engine(url: str):
    if url == "sqlite:///:memory:":
        # One shared connection keeps the preview truly in memory across threads.
        engine = create_engine(url, connect_args={"check_same_thread": False}, poolclass=StaticPool,
                               execution_options={"schema_translate_map": {SCHEMA: None}}, hide_parameters=True)
        # A StaticPool shares one SQLite connection; serialize its transactions
        # across preview threads so a concurrent request cannot roll back another.
        engine._transport_preview_lock = threading.RLock()
        return engine
    if not url.startswith(("postgresql://", "postgres://")):
        raise RuntimeError("DATABASE_URL must use PostgreSQL or the isolated preview database")
    normalized = "postgresql+psycopg://" + url.split("://", 1)[1]
    # No prepared statements/session state: compatible with Supabase transaction
    # pooling. Bound connection counts also protect small Supabase instances
    # while allowing concurrent threads to run exports/SSE without queue stalls.
    return create_engine(
        normalized,
        connect_args={"connect_timeout": 5, "prepare_threshold": None},
        pool_size=4,
        max_overflow=2,
        pool_timeout=10,
        pool_recycle=300,
        pool_pre_ping=True,
        hide_parameters=True,
    )


def initialize_preview(engine) -> None:
    """Only create schema automatically for the disposable in-memory database."""
    if engine.dialect.name != "sqlite" or engine.url.database not in (None, "", ":memory:"):
        raise RuntimeError("Automatic initialization is restricted to in-memory SQLite")
    metadata.create_all(engine)
    with engine.begin() as conn:
        if conn.execute(select(schema_version.c.version)).first() is None:
            conn.execute(insert(schema_version).values(version=SCHEMA_VERSION))


def _predicate(table, query: dict, dialect: str):
    clauses = []
    for key, condition in query.items():
        if key == "$or":
            if not isinstance(condition, list) or not condition:
                raise ValueError("Invalid OR predicate")
            clauses.append(or_(*(_predicate(table, part, dialect) for part in condition)))
            continue
        if key not in table.c:
            raise ValueError("Unknown database field")
        column = table.c[key]
        if isinstance(condition, dict):
            for operator, value in condition.items():
                if operator == "$gte": clauses.append(column >= value)
                elif operator == "$lte": clauses.append(column <= value)
                elif operator == "$gt": clauses.append(column > value)
                elif operator == "$lt": clauses.append(column < value)
                elif operator == "$contains_ci": clauses.append(column.icontains(value, autoescape=True))
                else: raise ValueError("Unsupported database predicate")
        elif key == "flag_reasons" and isinstance(condition, str):
            if dialect == "postgresql":
                # SQLAlchemy's generic JSON comparator doesn't expose JSONB's @>.
                from sqlalchemy import cast
                clauses.append(cast(column, JSONB).contains([condition]))
            else:
                values = func.json_each(column).table_valued("value").alias("array_items")
                clauses.append(select(1).select_from(values).where(values.c.value == condition).exists())
        else:
            clauses.append(column.is_(None) if condition is None else column == condition)
    return and_(*clauses) if clauses else True


class ResultCursor:
    def __init__(self, collection, query, projection=None):
        self.collection, self.query, self.projection = collection, query, projection
        self.order, self.offset, self.maximum = [], 0, None

    def sort(self, fields, direction=None):
        self.order = [(fields, direction)] if isinstance(fields, str) else list(fields)
        return self

    def skip(self, count):
        self.offset = count
        return self

    def limit(self, count):
        self.maximum = count
        return self

    def __iter__(self):
        collection = self.collection
        table = collection.table
        fields = list(table.c)
        if self.projection:
            included = {key for key, value in self.projection.items() if value}
            excluded = {key for key, value in self.projection.items() if not value}
            if included:
                if "_id" not in excluded:
                    included.add("_id")
                fields = [col for col in fields if col.name in included]
            else:
                fields = [col for col in fields if col.name not in excluded]
        stmt = select(*fields).where(_predicate(table, self.query, collection.engine.dialect.name))
        for name, direction in self.order:
            if name not in table.c or direction not in (ASCENDING, DESCENDING):
                raise ValueError("Invalid database ordering")
            stmt = stmt.order_by(table.c[name].asc() if direction == ASCENDING else table.c[name].desc())
        if self.offset:
            stmt = stmt.offset(self.offset)
        if self.maximum is not None:
            stmt = stmt.limit(self.maximum)
        with collection.guard(), collection.engine.connect() as conn:
            return iter([dict(row) for row in conn.execute(stmt).mappings().all()])


class TableStore:
    def __init__(self, engine, table):
        self.engine, self.table = engine, table

    def guard(self):
        return getattr(self.engine, "_transport_preview_lock", None) or nullcontext()

    def find(self, query=None, projection=None):
        return ResultCursor(self, query or {}, projection)

    def find_one(self, query=None, projection=None, *, sort=None):
        cursor = self.find(query, projection)
        if sort:
            cursor.sort(sort)
        return next(iter(cursor.limit(1)), None)

    def count_documents(self, query):
        stmt = select(func.count()).select_from(self.table).where(_predicate(self.table, query, self.engine.dialect.name))
        with self.guard(), self.engine.connect() as conn:
            return conn.execute(stmt).scalar_one()

    def insert_one(self, document):
        data = dict(document)
        data.setdefault("_id", new_id())
        with self.guard(), self.engine.begin() as conn:
            conn.execute(insert(self.table).values(**data))
        return SimpleNamespace(inserted_id=data["_id"])

    def insert_many(self, documents):
        data = [dict(doc) for doc in documents]
        for row in data:
            row.setdefault("_id", new_id())
        # Different records may have different optional fields, so issue each
        # INSERT within one transaction instead of letting executemany omit keys.
        with self.guard(), self.engine.begin() as conn:
            for row in data:
                conn.execute(insert(self.table).values(**row))
        return SimpleNamespace(inserted_ids=[row["_id"] for row in data])

    def update_one(self, query, changes):
        if not query or not set(changes).issubset({"$set", "$unset"}):
            raise ValueError("Invalid database update")
        data = dict(changes.get("$set", {}))
        data.update({key: None for key in changes.get("$unset", {})})
        # Every mutation targets a primary key. Keep all predicates directly in
        # the UPDATE so PostgreSQL rechecks them after waiting on a row lock;
        # this is essential for atomic Firebase UID binding.
        if "_id" not in query or not isinstance(query["_id"], str):
            raise ValueError("A primary key is required for a single-row update")
        stmt = update(self.table).where(_predicate(self.table, query, self.engine.dialect.name)).values(**data)
        with self.guard(), self.engine.begin() as conn:
            result = conn.execute(stmt)
            return SimpleNamespace(matched_count=result.rowcount)

    def delete_one(self, query):
        if not query:
            raise ValueError("A delete predicate is required")
        selection = select(self.table.c._id).where(_predicate(self.table, query, self.engine.dialect.name)).limit(1)
        with self.guard(), self.engine.begin() as conn:
            result = conn.execute(delete(self.table).where(self.table.c._id.in_(selection)))
            return SimpleNamespace(deleted_count=result.rowcount)

    def delete_many(self, query):
        if not query:
            raise ValueError("A delete predicate is required")
        with self.guard(), self.engine.begin() as conn:
            result = conn.execute(delete(self.table).where(_predicate(self.table, query, self.engine.dialect.name)))
            return SimpleNamespace(deleted_count=result.rowcount)


class Database:
    def __init__(self, engine):
        self.engine = engine
        for name, table in TABLES.items():
            setattr(self, name, TableStore(engine, table))


def get_database(config: Config, engine=None):
    owned_engine = engine is None
    engine = engine or create_database_engine(config.database_url)
    try:
        if engine.dialect.name == "sqlite":
            initialize_preview(engine)
        with engine.connect() as conn:
            versions = conn.execute(select(schema_version.c.version)).scalars().all()
            if versions != [SCHEMA_VERSION]:
                raise RuntimeError("Database schema version is missing or incompatible; apply the documented migration")
            # Check runtime SELECT permission and that all tables exist without
            # touching or changing real rows.
            for table in TABLES.values():
                conn.execute(select(table.c._id).limit(0))
        return Database(engine)
    except Exception:
        if owned_engine:
            engine.dispose()
        raise


def get_database_for_startup(config: Config, engine=None):
    if config.environment != "production":
        return get_database(config, engine)
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    attempt = 0
    while time.monotonic() < deadline:
        attempt += 1
        try:
            return get_database(config, engine)
        except DBAPIError as exc:
            # Authentication, permissions and missing objects aren't transient.
            sqlstate = getattr(exc.orig, "sqlstate", None) or ""
            if sqlstate.startswith(("28", "42")):
                raise RuntimeError("PostgreSQL rejected database initialization; check credentials, permissions and schema") from None
            if not isinstance(exc, OperationalError) and not exc.connection_invalidated:
                raise RuntimeError("PostgreSQL database initialization failed; check schema and configuration") from None
            remaining = deadline - time.monotonic()
            if remaining > 0:
                logger.warning("PostgreSQL is not ready; retrying (attempt %s).", attempt)
                time.sleep(min(STARTUP_RETRY_DELAY_SECONDS, remaining))
        except (SQLAlchemyError, ValueError):
            raise RuntimeError("PostgreSQL connection configuration is invalid; check DATABASE_URL") from None
    raise RuntimeError("PostgreSQL initialization failed after retries; check TLS, DNS and network access") from None


def utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def iso_utc(value: datetime) -> str:
    return utc_naive(value).isoformat(timespec="seconds") + "Z"


def public_doc(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    result = {}
    for key, value in doc.items():
        if key == "_id": result["id"] = str(value)
        elif isinstance(value, datetime): result[key] = iso_utc(value)
        elif isinstance(value, dict): result[key] = public_doc(value)
        elif isinstance(value, list):
            result[key] = [public_doc(item) if isinstance(item, dict) else iso_utc(item) if isinstance(item, datetime) else item for item in value]
        else: result[key] = value
    return result
