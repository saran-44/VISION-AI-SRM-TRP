from __future__ import annotations

import sys
import os
import re
from urllib.parse import urlparse
from dataclasses import replace
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import create_app  # noqa: E402
from backend.auth import hash_password  # noqa: E402
from backend.config import Config  # noqa: E402
from backend.services import naive_now  # noqa: E402

HEAD_ADMIN_EMAIL = "head.admin@example.invalid"
TRANSPORT_EMAIL = "transport.office@example.invalid"
HEAD_ADMIN_PASSWORD = "HeadAdminPass123!"
TRANSPORT_PASSWORD = "TransportPass123!"
DEVICE_KEY = "test-device-api-key"


def build_config(**overrides) -> Config:
    base = Config(
        environment="testing",
        debug=False,
        testing=True,
        database_url=os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:"),
        jwt_secret="test-only-secret-value-" + ("x" * 32),
        jwt_ttl_minutes=15,
        cookie_secure=False,
        cors_allowed_origins=("http://localhost:3000",),
        device_api_keys=(DEVICE_KEY,),
        rate_limit_enabled=False,
        # A Firebase project id so the Firebase sign-in paths are exercised.
        # The "not configured" behaviour is tested with an explicit override.
        firebase_project_id="vision-ai-srmtrp",
    )
    return replace(base, **overrides) if overrides else base


@pytest.fixture(scope="session", autouse=True)
def prepare_postgres_test_database():
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        yield
        return
    parts = urlparse(url)
    if (os.getenv("ALLOW_TEST_DATABASE_RESET") != "true" or
        parts.scheme not in {"postgresql", "postgres"} or
        parts.hostname not in {"localhost", "127.0.0.1", "::1"} or
        not re.fullmatch(r"/[A-Za-z0-9_]+_test", parts.path) or
        parts.query or parts.fragment):
        raise RuntimeError("PostgreSQL tests require ALLOW_TEST_DATABASE_RESET=true and a local *_test database with no URL options")
    # libpq can otherwise take PGHOSTADDR from the environment even when the
    # URL names localhost, silently redirecting destructive tests elsewhere.
    old_hostaddr = os.environ.get("PGHOSTADDR")
    os.environ["PGHOSTADDR"] = "::1" if parts.hostname == "::1" else "127.0.0.1"
    import psycopg
    sql = (ROOT / "backend/sql/001_initial.sql").read_text()
    with psycopg.connect(url, autocommit=True) as conn:
        # A deliberately disposable local database only. Never point tests at Supabase.
        conn.execute("DROP SCHEMA IF EXISTS transport_portal CASCADE")
        conn.execute(sql)
    try:
        yield
    finally:
        if old_hostaddr is None:
            os.environ.pop("PGHOSTADDR", None)
        else:
            os.environ["PGHOSTADDR"] = old_hostaddr


@pytest.fixture(autouse=True)
def clean_postgres_test_database(prepare_postgres_test_database):
    url = os.getenv("TEST_DATABASE_URL", "")
    if url:
        import psycopg
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("TRUNCATE transport_portal.users, transport_portal.buses, transport_portal.drivers, transport_portal.events, transport_portal.audit_logs, transport_portal.bus_states")
    yield


@pytest.fixture()
def config() -> Config:
    return build_config()


@pytest.fixture()
def app(config):
    application = create_app(config)
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def db(app):
    return app.extensions["transport_db"]


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def users(db):
    db.users.insert_many(
        [
            {
                "email": HEAD_ADMIN_EMAIL,
                "password_hash": hash_password(HEAD_ADMIN_PASSWORD),
                "role": "head_admin",
                "active": True,
                "created_at": naive_now(),
            },
            {
                "email": TRANSPORT_EMAIL,
                "password_hash": hash_password(TRANSPORT_PASSWORD),
                "role": "transport_office",
                "active": True,
                "created_at": naive_now(),
            },
        ]
    )
    return {"head_admin": HEAD_ADMIN_EMAIL, "transport_office": TRANSPORT_EMAIL}


def login(client, email: str, password: str):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def login_head_admin(client, users) -> None:
    response = login(client, users["head_admin"], HEAD_ADMIN_PASSWORD)
    assert response.status_code == 200


def login_transport_office(client, users) -> None:
    response = login(client, users["transport_office"], TRANSPORT_PASSWORD)
    assert response.status_code == 200
