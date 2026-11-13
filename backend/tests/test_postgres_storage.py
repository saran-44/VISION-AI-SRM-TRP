"""Storage contract tests, including the real PostgreSQL path in CI."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import os
import threading

import pytest
from sqlalchemy.exc import IntegrityError

from backend.access import AccessDenied, _record_provider, add_access_entry
from backend.services import naive_now


def test_search_treats_wildcards_as_literal_and_is_case_insensitive(db):
    db.buses.insert_many([
        {"bus_number": "ONE", "route": "Main_100%"},
        {"bus_number": "TWO", "route": "MainX100percent"},
    ])
    assert [row["bus_number"] for row in db.buses.find({"route": {"$contains_ci": "_100%"}})] == ["ONE"]
    assert [row["bus_number"] for row in db.buses.find({"route": {"$contains_ci": "main"}}).sort("bus_number", 1)] == ["ONE", "TWO"]
    assert list(db.buses.find({"route": {"$contains_ci": "' OR 1=1 --"}})) == []


def test_range_array_membership_sort_and_pagination(db):
    for day in (1, 2, 3):
        db.events.insert_one({
            "bus_number": "BUS-001", "direction": "IN", "gate": "Gate", "camera_id": "cam",
            "confidence": 0.5, "timestamp": datetime(2026, 1, day),
            "flag_reasons": ["low_ocr_confidence", "unregistered_plate"] if day != 2 else [],
            "flagged": day != 2,
        })
    query = {"timestamp": {"$gte": datetime(2026, 1, 2), "$lt": datetime(2026, 1, 4)},
             "flag_reasons": "unregistered_plate"}
    assert db.events.count_documents(query) == 1
    assert [r["timestamp"].day for r in db.events.find({}).sort([("timestamp", -1)]).skip(1).limit(1)] == [2]


def test_multi_insert_rolls_back_on_duplicate(db):
    db.buses.insert_one({"bus_number": "EXISTING"})
    with pytest.raises(IntegrityError):
        db.buses.insert_many([{"bus_number": "NEW"}, {"bus_number": "EXISTING"}])
    assert db.buses.find_one({"bus_number": "NEW"}) is None


def test_passwordless_firebase_user_cannot_use_legacy_password(client, db):
    add_access_entry(db, "firebase@example.invalid")
    response = client.post("/api/auth/login", json={"email": "firebase@example.invalid", "password": "not-the-password"})
    assert response.status_code == 401


def test_uid_binding_rejects_stale_competing_identity(db):
    user = add_access_entry(db, "stale@example.invalid")
    _record_provider(db, user.copy(), "password", "uid-first")
    with pytest.raises(AccessDenied):
        _record_provider(db, user.copy(), "password", "uid-second")
    assert db.users.find_one({"_id": user["_id"]})["firebase_uid"] == "uid-first"


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires disposable local PostgreSQL")
def test_concurrent_uid_binding_allows_only_one_identity(db):
    user = add_access_entry(db, "race@example.invalid")
    barrier = threading.Barrier(2)
    def attempt(uid):
        barrier.wait(timeout=5)
        try:
            _record_provider(db, user.copy(), "password", uid)
            return uid
        except AccessDenied:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, ["uid-first", "uid-second"]))
    winners = [result for result in results if result]
    assert len(winners) == 1
    assert db.users.find_one({"_id": user["_id"]})["firebase_uid"] == winners[0]


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires disposable local PostgreSQL")
def test_runtime_role_can_operate_but_cannot_change_schema_or_audit(db, config):
    import psycopg
    from psycopg import sql
    from urllib.parse import urlparse
    from scripts.configure_supabase import create_runtime_role

    url = os.environ["TEST_DATABASE_URL"]
    parts = urlparse(url)
    role = f"transport_test_runtime_{os.getpid()}"
    password = "temporary-test-password"
    with psycopg.connect(url, autocommit=True) as admin:
        try:
            with admin.transaction():
                create_runtime_role(admin, role, password)
            with psycopg.connect(host=parts.hostname, port=parts.port or 5432,
                                 dbname=parts.path.lstrip("/"), user=role, password=password,
                                 autocommit=True) as runtime:
                runtime.execute("SELECT * FROM transport_portal.schema_version")
                runtime.execute("INSERT INTO transport_portal.buses (_id, bus_number) VALUES ('a00000000000000000000001', 'ROLE-TEST')")
                runtime.execute("INSERT INTO transport_portal.audit_logs (_id, timestamp, action) VALUES ('a00000000000000000000002', now(), 'test')")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute("UPDATE transport_portal.audit_logs SET action = 'changed'")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute("CREATE TABLE transport_portal.nope (x int)")
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    runtime.execute("UPDATE transport_portal.schema_version SET version = 2")

            # Start the actual Flask app as the restricted role and exercise a
            # write+audit flow: neither startup nor normal use needs DDL.
            from dataclasses import replace
            from urllib.parse import quote
            from backend.app import create_app
            from backend.tests.conftest import DEVICE_KEY
            runtime_url = f"postgresql://{role}:{quote(password, safe='')}@{parts.hostname}:{parts.port or 5432}/{parts.path.lstrip('/')}"
            app = create_app(replace(config, database_url=runtime_url))
            response = app.test_client().post("/api/events", headers={"X-Device-Key": DEVICE_KEY}, json={
                "bus_number": "ROLE-TEST", "direction": "IN", "gate": "Gate 1", "camera_id": "cam",
                "confidence": 0.9, "timestamp": "2026-01-01T00:00:00Z",
            })
            assert response.status_code == 201
            assert db.audit_logs.find_one({"action": "event_ingested"}) is not None
            app.extensions["transport_db"].engine.dispose()
        finally:
            admin.execute(sql.SQL("DROP OWNED BY {} ").format(sql.Identifier(role)))
            admin.execute(sql.SQL("DROP ROLE {} ").format(sql.Identifier(role)))


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires disposable local PostgreSQL")
def test_initial_migration_never_overwrites_existing_schema(db):
    import psycopg
    from pathlib import Path
    db.buses.insert_one({"bus_number": "KEEP-ME"})
    sql_text = (Path(__file__).resolve().parents[1] / "sql/001_initial.sql").read_text()
    with psycopg.connect(os.environ["TEST_DATABASE_URL"], autocommit=True) as conn:
        with pytest.raises(psycopg.errors.DuplicateSchema):
            conn.execute(sql_text)
        conn.execute("ROLLBACK")
    assert db.buses.find_one({"bus_number": "KEEP-ME"}) is not None


def test_setup_will_not_overwrite_existing_env_or_contact_database(monkeypatch, tmp_path, capsys):
    from scripts import configure_supabase
    env_file = tmp_path / ".env"
    env_file.write_text("existing=private\n")
    monkeypatch.setattr(configure_supabase, "ROOT", tmp_path)
    monkeypatch.setattr(configure_supabase.psycopg, "connect", lambda *a, **k: pytest.fail("must not connect"))
    monkeypatch.setattr("builtins.input", lambda *a: pytest.fail("must not prompt"))
    assert configure_supabase.main() == 2
    assert env_file.read_text() == "existing=private\n"
    assert "already exists" in capsys.readouterr().err


def test_database_errors_are_sanitized_in_http_and_logs(client, db, monkeypatch, caplog):
    from sqlalchemy.exc import OperationalError
    def fail(*args, **kwargs):
        raise OperationalError("secret SQL", {}, Exception("demo-password"))
    monkeypatch.setattr(db.users, "find_one", fail)
    response = client.post("/api/auth/login", json={"email": "user@example.invalid", "password": "demo-password"})
    assert response.status_code == 503
    assert "demo-password" not in response.get_data(as_text=True)
    assert "demo-password" not in caplog.text and "secret SQL" not in caplog.text


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="requires disposable local PostgreSQL")
def test_database_administrator_can_create_runtime_role_without_superuser():
    """Supabase's project postgres user is not a superuser."""
    import psycopg
    from psycopg import sql
    from urllib.parse import urlparse
    from scripts.configure_supabase import create_runtime_role

    url = os.environ["TEST_DATABASE_URL"]
    parts = urlparse(url)
    owner = f"transport_test_owner_{os.getpid()}"
    role = f"transport_test_app_{os.getpid()}"
    with psycopg.connect(url, autocommit=True) as admin:
        try:
            admin.execute(sql.SQL("CREATE ROLE {} LOGIN CREATEROLE PASSWORD 'temporary-test-password'").format(sql.Identifier(owner)))
            admin.execute(sql.SQL("GRANT USAGE ON SCHEMA transport_portal TO {} WITH GRANT OPTION").format(sql.Identifier(owner)))
            admin.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA transport_portal TO {} WITH GRANT OPTION").format(sql.Identifier(owner)))
            with psycopg.connect(host=parts.hostname, port=parts.port or 5432,
                                 dbname=parts.path.lstrip("/"), user=owner, password="temporary-test-password") as conn:
                create_runtime_role(conn, role, "temporary-other-password")
            assert admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
        finally:
            # Removing the non-superuser grantor's grant options with CASCADE
            # also removes grants it issued to the test runtime role.
            if admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (owner,)).fetchone():
                admin.execute(sql.SQL("REVOKE ALL ON ALL TABLES IN SCHEMA transport_portal FROM {} CASCADE").format(sql.Identifier(owner)))
                admin.execute(sql.SQL("REVOKE ALL ON SCHEMA transport_portal FROM {} CASCADE").format(sql.Identifier(owner)))
            for name in (role, owner):
                if admin.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone():
                    admin.execute(sql.SQL("DROP OWNED BY {} CASCADE").format(sql.Identifier(name)))
                    admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


def test_setup_creates_private_config_without_printing_passwords(monkeypatch, tmp_path, capsys):
    from pathlib import Path
    from urllib.parse import urlparse, parse_qs
    from dotenv import dotenv_values
    from scripts import configure_supabase

    original_template = (Path(__file__).resolve().parents[2] / ".env.example").read_text()
    (tmp_path / ".env.example").write_text(original_template)
    certificate = tmp_path / "supabase-ca.crt"
    certificate.write_text("test-only-ca")
    monkeypatch.setattr(configure_supabase, "ROOT", tmp_path)
    answers = iter(["aws-0-ap-south-1.pooler.supabase.com", "abc123", str(certificate), "CREATE"])
    monkeypatch.setattr("builtins.input", lambda _: next(answers))
    monkeypatch.setattr(configure_supabase.getpass, "getpass", lambda _: "private-admin-password")
    calls = []
    class QueryResult:
        def fetchall(self): return [(1,)]
        def fetchone(self): return None
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *_): return False
        def execute(self, *args, **kwargs):
            calls.append(args[0])
            return QueryResult()
    monkeypatch.setattr(configure_supabase.psycopg, "connect", lambda *args, **kwargs: Connection())
    assert configure_supabase.main() == 0
    values = dotenv_values(tmp_path / ".env")
    url = urlparse(values["DATABASE_URL"])
    assert url.hostname == "aws-0-ap-south-1.pooler.supabase.com"
    assert url.username == "transport_portal_app.abc123"
    assert parse_qs(url.query)["sslmode"] == ["verify-full"]
    assert values["PGSSLROOTCERT"] == certificate.as_posix()
    assert values["FIREBASE_PROJECT_ID"] == "vision-ai-srmtrp"
    assert len(values["JWT_SECRET"]) >= 32 and len(values["DEVICE_API_KEYS"]) >= 32
    output = capsys.readouterr()
    assert "private-admin-password" not in output.out + output.err
    assert url.password not in output.out + output.err
    assert len(calls) >= 8


def test_concurrent_table_operations_commit_independently(db):
    def write_and_read(number):
        bus_number = f"T-{number:03}"
        db.buses.insert_one({"bus_number": bus_number})
        return db.buses.find_one({"bus_number": bus_number})["bus_number"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert len(list(pool.map(write_and_read, range(30)))) == 30
    assert db.buses.count_documents({}) == 30


def test_schema_version_error_names_the_database_role_and_observed_versions(app, db, config):
    """A wrong project, an unapplied migration and a bad read look identical in
    logs unless the message states what was actually read."""
    from sqlalchemy import update

    from backend.db import get_database, schema_version

    with db.engine.begin() as conn:
        conn.execute(update(schema_version).values(version=2))
    try:
        with pytest.raises(RuntimeError) as error:
            get_database(config, db.engine)
    finally:
        # Restore the shared test database so later tests still start.
        with db.engine.begin() as conn:
            conn.execute(update(schema_version).values(version=1))

    message = str(error.value)
    assert "Database schema version is missing or incompatible" in message
    assert "expected=[1]" in message
    assert "found=[2]" in message
    assert "database=" in message and "role=" in message
