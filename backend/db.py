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
from sqlalchemy.dialects.postgresql import JSONB, insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError, SQLAlchemyError
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
    Column("plate_key", String(20)),
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
    Column("source", Text), Column("idempotency_key", String(128)),
    Column("flag_reasons", json_type, nullable=False, default=list),
    Column("flagged", Boolean, nullable=False, default=False),
    Column("demo", Boolean, nullable=False, default=False),
)
audit_logs = Table(
    "audit_logs", metadata, _id_column(), Column("timestamp", DateTime(), nullable=False),
    Column("actor", Text), Column("role", Text), Column("action", Text),
    Column("collection", Text), Column("record_id", Text), Column("before", json_type),
    Column("after", json_type), Column("ip", Text), Column("user_agent", Text),
)
bus_states = Table(
    "bus_states", metadata, _id_column(),
    Column("bus_number", String(20), nullable=False, unique=True),
    Column("direction", String(3), nullable=False),
    Column("last_timestamp", DateTime(), nullable=False),
    Column("last_event_id", String(24), nullable=False),
    Column("gate", Text), Column("camera_id", Text),
    Column("demo", Boolean, nullable=False, default=False),
    Column("updated_at", DateTime(), nullable=False),
)
revoked_tokens = Table(
    "revoked_tokens", metadata, _id_column(),
    Column("jti", String(64), nullable=False, unique=True),
    Column("expires_at", DateTime(), nullable=False),
    Column("revoked_at", DateTime(), nullable=False),
)
Index("users_firebase_uid", users.c.firebase_uid)
Index("buses_plate_key", buses.c.plate_key)
Index("events_idempotency_key", events.c.idempotency_key, unique=True)
Index("events_dedup", events.c.bus_number, events.c.direction, events.c.camera_id, events.c.timestamp.desc())
Index("audit_collection_action_timestamp", audit_logs.c.collection, audit_logs.c.action, audit_logs.c.timestamp.desc())
Index("bus_states_direction", bus_states.c.direction)
Index("bus_states_updated_at", bus_states.c.updated_at)
Index("revoked_tokens_expires_at", revoked_tokens.c.expires_at)
TABLES = {table.name: table for table in (users, buses, drivers, events, audit_logs, bus_states, revoked_tokens)}

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

    def count_documents_capped(self, query, limit: int) -> int:
        sub = (
            select(self.table.c._id)
            .where(_predicate(self.table, query, self.engine.dialect.name))
            .limit(limit)
            .subquery()
        )
        stmt = select(func.count()).select_from(sub)
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

    def ping(self) -> None:
        guard = getattr(self.engine, "_transport_preview_lock", None) or nullcontext()
        with guard, self.engine.connect() as conn:
            conn.execute(select(schema_version.c.version).limit(1))

    def upsert_bus_state(self, state: dict[str, Any]) -> None:
        """Atomically upsert a bus's latest state only if (last_timestamp, last_event_id) is newer."""
        row = dict(state)
        row.setdefault("_id", new_id())
        insert_fn = pg_insert if self.engine.dialect.name == "postgresql" else sqlite_insert
        stmt = insert_fn(bus_states).values(**row)
        excluded = stmt.excluded
        newer_pred = or_(
            bus_states.c.last_timestamp < excluded.last_timestamp,
            and_(
                bus_states.c.last_timestamp == excluded.last_timestamp,
                bus_states.c.last_event_id < excluded.last_event_id,
            ),
        )
        upsert_stmt = stmt.on_conflict_do_update(
            index_elements=[bus_states.c.bus_number],
            set_={
                "direction": excluded.direction,
                "last_timestamp": excluded.last_timestamp,
                "last_event_id": excluded.last_event_id,
                "gate": excluded.gate,
                "camera_id": excluded.camera_id,
                "demo": excluded.demo,
                "updated_at": excluded.updated_at,
            },
            where=newer_pred,
        )
        try:
            with self.bus_states.guard(), self.engine.begin() as conn:
                conn.execute(upsert_stmt)
        except IntegrityError:
            # Defensive retry once on concurrent first-insert race, then ignore if existing row is newer.
            fallback_stmt = (
                update(bus_states)
                .where(
                    and_(
                        bus_states.c.bus_number == row["bus_number"],
                        or_(
                            bus_states.c.last_timestamp < row["last_timestamp"],
                            and_(
                                bus_states.c.last_timestamp == row["last_timestamp"],
                                bus_states.c.last_event_id < row["last_event_id"],
                            ),
                        ),
                    )
                )
                .values(
                    direction=row["direction"],
                    last_timestamp=row["last_timestamp"],
                    last_event_id=row["last_event_id"],
                    gate=row.get("gate"),
                    camera_id=row.get("camera_id"),
                    demo=bool(row.get("demo", False)),
                    updated_at=row["updated_at"],
                )
            )
            with self.bus_states.guard(), self.engine.begin() as conn:
                conn.execute(fallback_stmt)

    def aggregate_analytics(
        self,
        query: dict[str, Any],
        timezone_name: str,
        *,
        gate_limit: int = 12,
        bus_limit: int = 12,
    ) -> dict[str, Any]:
        """Compute analytics totals, top gates/buses, and hourly buckets using SQL."""
        from collections import Counter
        from datetime import timezone as dt_timezone
        from zoneinfo import ZoneInfo

        dialect = self.engine.dialect.name
        pred = _predicate(events, query, dialect)
        totals_stmt = select(
            func.count().label("events"),
            func.count(func.distinct(events.c.gate)).label("gates"),
            func.count(func.distinct(events.c.bus_number)).label("buses"),
        ).where(pred)
        gate_stmt = (
            select(events.c.gate, func.count().label("cnt"))
            .where(pred)
            .group_by(events.c.gate)
            .order_by(func.count().desc(), events.c.gate.asc())
            .limit(gate_limit)
        )
        bus_stmt = (
            select(events.c.bus_number, func.count().label("cnt"))
            .where(pred)
            .group_by(events.c.bus_number)
            .order_by(func.count().desc(), events.c.bus_number.asc())
            .limit(bus_limit)
        )

        hour_counts: dict[datetime, int] = {}
        with self.events.guard(), self.engine.connect() as conn:
            totals_row = conn.execute(totals_stmt).mappings().one()
            gate_rows = conn.execute(gate_stmt).mappings().all()
            bus_rows = conn.execute(bus_stmt).mappings().all()
            if dialect == "postgresql":
                local_ts = func.timezone(timezone_name, func.timezone("UTC", events.c.timestamp))
                local_hour = func.date_trunc("hour", local_ts)
                utc_bucket = func.timezone("UTC", func.timezone(timezone_name, local_hour)).label("hour")
                hour_stmt = (
                    select(utc_bucket, func.count().label("cnt"))
                    .where(pred)
                    .group_by(utc_bucket)
                    .order_by(utc_bucket.asc())
                )
                for row in conn.execute(hour_stmt).mappings().all():
                    hour_counts[utc_naive(row["hour"])] = int(row["cnt"])
            else:
                zone = ZoneInfo(timezone_name)
                counter: Counter[datetime] = Counter()
                ts_stmt = select(events.c.timestamp).where(pred)
                for (ts,) in conn.execute(ts_stmt):
                    local = ts.replace(tzinfo=dt_timezone.utc).astimezone(zone)
                    local = local.replace(minute=0, second=0, microsecond=0)
                    counter[local.astimezone(dt_timezone.utc).replace(tzinfo=None)] += 1
                hour_counts = dict(counter)

        return {
            "hour_counts": hour_counts,
            "per_gate": [
                {"gate": row["gate"] or "Unknown", "count": int(row["cnt"])} for row in gate_rows
            ],
            "per_bus": [
                {"bus_number": row["bus_number"] or "Unknown", "count": int(row["cnt"])}
                for row in bus_rows
            ],
            "totals": {
                "events": int(totals_row["events"] or 0),
                "gates": int(totals_row["gates"] or 0),
                "buses": int(totals_row["buses"] or 0),
            },
        }

    def rename_bus(self, oid: str, old_number: str, changes: dict[str, Any]) -> int:
        """Atomically update a bus and cascade bus_number rename to drivers and bus_states."""
        new_number = changes["bus_number"]
        now = changes["updated_at"]
        with self.buses.guard(), self.engine.begin() as conn:
            conn.execute(update(buses).where(buses.c._id == oid).values(**changes))
            drv_res = conn.execute(
                update(drivers)
                .where(drivers.c.bus_number == old_number)
                .values(bus_number=new_number, updated_at=now)
            )
            old_state = conn.execute(
                select(bus_states).where(bus_states.c.bus_number == old_number)
            ).mappings().first()
            if old_state is not None:
                existing_new = conn.execute(
                    select(bus_states).where(bus_states.c.bus_number == new_number)
                ).mappings().first()
                if existing_new is None:
                    conn.execute(
                        update(bus_states)
                        .where(bus_states.c._id == old_state["_id"])
                        .values(bus_number=new_number, updated_at=now)
                    )
                else:
                    old_key = (old_state["last_timestamp"], old_state["last_event_id"])
                    new_key = (existing_new["last_timestamp"], existing_new["last_event_id"])
                    if old_key > new_key:
                        conn.execute(
                            update(bus_states)
                            .where(bus_states.c._id == existing_new["_id"])
                            .values(
                                direction=old_state["direction"],
                                last_timestamp=old_state["last_timestamp"],
                                last_event_id=old_state["last_event_id"],
                                gate=old_state["gate"],
                                camera_id=old_state["camera_id"],
                                demo=old_state["demo"],
                                updated_at=now,
                            )
                        )
                    conn.execute(delete(bus_states).where(bus_states.c._id == old_state["_id"]))
            return int(drv_res.rowcount or 0)


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
        if key == "idempotency_key":
            continue
        if key == "_id": result["id"] = str(value)
        elif isinstance(value, datetime): result[key] = iso_utc(value)
        elif isinstance(value, dict): result[key] = public_doc(value)
        elif isinstance(value, list):
            result[key] = [public_doc(item) if isinstance(item, dict) else iso_utc(item) if isinstance(item, datetime) else item for item in value]
        else: result[key] = value
    return result
