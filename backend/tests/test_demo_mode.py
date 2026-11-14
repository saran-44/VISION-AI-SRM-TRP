"""The demo/Test Lab surface must be impossible outside DEMO_MODE.

These tests pin the two halves of that promise:
  * configuration refuses demo mode (and unfenced password sign-in) in production,
  * a running app without DEMO_MODE exposes no Test Lab routes and no alias login.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from backend.app import create_app
from backend.config import DEMO_ADMIN_PASSWORD, Config
from backend.tests.conftest import HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD, build_config

DEMO_EMAIL = "admin@demo.local"


def _demo_app(app, **overrides):
    config = replace(app.config["TRANSPORT_CONFIG"], demo_mode=True, **overrides)
    application = create_app(config, database_engine=app.extensions["transport_db"].engine)
    application.config.update(TESTING=True)
    return application


# --------------------------------------------------------------- configuration
def test_production_requires_password_login_to_be_off():
    config = build_config(
        environment="production",
        database_url="postgresql://localhost/db?sslmode=verify-full",
        legacy_password_login_enabled=True,
    )
    with pytest.raises(RuntimeError, match="Password sign-in must be off"):
        config.validate()


def test_production_accepts_password_login_with_an_explicit_acknowledgement():
    config = build_config(
        environment="production",
        database_url="postgresql://localhost/db?sslmode=verify-full",
        legacy_password_login_enabled=True,
        allow_legacy_login_in_production=True,
    )
    config.validate()  # no raise


def test_production_refuses_demo_mode():
    config = build_config(
        environment="production",
        database_url="postgresql://localhost/db?sslmode=verify-full",
        legacy_password_login_enabled=False,
        demo_mode=True,
    )
    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        config.validate()


def test_demo_mode_is_off_by_default(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert Config.from_env().demo_mode is False


def test_password_login_defaults_off_in_production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db?sslmode=verify-full")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    monkeypatch.delenv("LEGACY_PASSWORD_LOGIN_ENABLED", raising=False)
    config = Config.from_env()
    assert config.legacy_password_login_enabled is False


# ------------------------------------------------------------ routes and login
def test_test_lab_page_is_absent_without_demo_mode(app, users):
    client = app.test_client()
    login = client.post(
        "/api/auth/login",
        json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    assert client.get("/test-lab").status_code == 404
    assert client.get("/api/test-lab/checks").status_code == 404
    assert client.post("/api/test-lab/events", json={}).status_code == 404


def test_admin_alias_is_rejected_without_demo_mode(app, users):
    client = app.test_client()
    response = client.post("/api/auth/login", json={"email": "admin", "password": DEMO_ADMIN_PASSWORD})
    assert response.status_code == 400  # "admin" is not an email address


def test_demo_mode_reports_itself_in_the_public_auth_config(app):
    assert app.test_client().get("/api/auth/config").get_json()["demo_mode"] is False
    demo = _demo_app(app)
    assert demo.test_client().get("/api/auth/config").get_json()["demo_mode"] is True


def test_demo_admin_alias_signs_in_and_reaches_the_lab(app, db):
    from backend.auth import hash_password
    from backend.services import naive_now

    db.users.insert_one({
        "email": DEMO_EMAIL,
        "password_hash": hash_password(DEMO_ADMIN_PASSWORD),
        "role": "head_admin",
        "active": True,
        "demo_user": True,
        "created_at": naive_now(),
    })

    demo = _demo_app(app)
    client = demo.test_client()
    login = client.post("/api/auth/login", json={"email": "admin", "password": DEMO_ADMIN_PASSWORD})
    assert login.status_code == 200
    assert login.get_json()["user"]["email"] == DEMO_EMAIL
    assert login.get_json()["user"]["role"] == "head_admin"

    page = client.get("/test-lab")
    assert page.status_code == 200
    assert b"Test Lab" in page.data

    checks = client.get("/api/test-lab/checks")
    assert checks.status_code == 200
    payload = checks.get_json()
    assert payload["demo_mode"] is True
    ids = {check["id"] for check in payload["checks"]}
    assert {"session", "database", "detection", "demo"} <= ids


def test_test_lab_event_insert_is_tagged_and_validated(app, db):
    from backend.auth import hash_password
    from backend.services import naive_now

    db.users.insert_one({
        "email": DEMO_EMAIL,
        "password_hash": hash_password(DEMO_ADMIN_PASSWORD),
        "role": "head_admin",
        "active": True,
        "demo_user": True,
        "created_at": naive_now(),
    })
    demo = _demo_app(app)
    client = demo.test_client()
    client.post("/api/auth/login", json={"email": "admin", "password": DEMO_ADMIN_PASSWORD})

    created = client.post("/api/test-lab/events", json={
        "bus_number": "BUS-001",
        "direction": "IN",
        "gate": "Gate 1 Entry",
        "camera_id": "test-lab",
        "confidence": 0.97,
        "timestamp": "2026-01-01T09:00:00Z",
    })
    assert created.status_code == 201
    event = created.get_json()["event"]
    assert event["source"] == "test-lab"
    assert event["bus_number"] == "BUS-001"

    # The same validation as the device endpoint: a bad payload is refused.
    bad = client.post("/api/test-lab/events", json={"bus_number": "", "direction": "SIDEWAYS"})
    assert bad.status_code == 400


def test_test_lab_requires_head_admin(app, db):
    from backend.auth import hash_password
    from backend.tests.conftest import TRANSPORT_EMAIL, TRANSPORT_PASSWORD
    from backend.services import naive_now

    db.users.insert_one({
        "email": TRANSPORT_EMAIL,
        "password_hash": hash_password(TRANSPORT_PASSWORD),
        "role": "transport_office",
        "active": True,
        "created_at": naive_now(),
    })
    demo = _demo_app(app)
    client = demo.test_client()
    client.post("/api/auth/login", json={"email": TRANSPORT_EMAIL, "password": TRANSPORT_PASSWORD})
    assert client.get("/api/test-lab/checks").status_code == 403
    assert client.get("/test-lab").status_code == 302


# ------------------------------------------------- Firebase configured + demo
def test_demo_mode_hides_a_configured_firebase_project_from_the_login_page(app):
    """A Firebase project in `.env` must not hijack the bench's login form.

    The demo credentials are not Firebase accounts, so the exchange would
    reject every attempt with 403 and the Test Lab would be unreachable —
    which is exactly what happened on a developer machine with a real
    FIREBASE_PROJECT_ID set.
    """
    normal = app.test_client().get("/api/auth/config").get_json()
    assert normal["firebase"]["enabled"] is True  # the test config has a project id

    demo = _demo_app(app, firebase_project_id="vision-ai-srmtrp", firebase_auth_enabled=True)
    payload = demo.test_client().get("/api/auth/config").get_json()
    assert payload["demo_mode"] is True
    assert payload["firebase"]["enabled"] is False
    assert payload["firebase"]["providers"] == []
    assert payload["mode"] == "password"


def test_demo_mode_refuses_a_firebase_token_exchange(app):
    demo = _demo_app(app)
    response = demo.test_client().post("/api/auth/firebase", json={"id_token": "x" * 40})
    assert response.status_code == 503
    assert "demo mode" in response.get_json()["error"]


def test_demo_login_still_works_when_local_passwords_are_disabled(app, db):
    """The bench is self-contained: turning password sign-in off must not lock it."""
    from backend.auth import hash_password
    from backend.services import naive_now

    db.users.insert_one({
        "email": DEMO_EMAIL,
        "password_hash": hash_password(DEMO_ADMIN_PASSWORD),
        "role": "head_admin",
        "active": True,
        "demo_user": True,
        "created_at": naive_now(),
    })

    demo = _demo_app(app, legacy_password_login_enabled=False)
    client = demo.test_client()
    login = client.post("/api/auth/login", json={"email": "admin", "password": DEMO_ADMIN_PASSWORD})
    assert login.status_code == 200
    assert login.get_json()["user"]["email"] == DEMO_EMAIL
    assert client.get("/api/test-lab/checks").status_code == 200

    # Outside demo mode the same switch still blocks password sign-in.
    blocked = app.test_client().post(
        "/api/auth/login", json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD}
    )
    assert blocked.status_code in {200, 401}  # the plain app keeps its own config
    strict = replace(app.config["TRANSPORT_CONFIG"], legacy_password_login_enabled=False)
    strict_app = create_app(strict, database_engine=db.engine)
    strict_app.config.update(TESTING=True)
    denied = strict_app.test_client().post(
        "/api/auth/login", json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD}
    )
    assert denied.status_code == 403
