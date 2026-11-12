from __future__ import annotations

from backend.auth import verify_password
from backend.tests.conftest import (
    HEAD_ADMIN_EMAIL,
    HEAD_ADMIN_PASSWORD,
    TRANSPORT_EMAIL,
    TRANSPORT_PASSWORD,
    build_config,
    login,
    login_head_admin,
    login_transport_office,
)
from backend.app import create_app


def test_login_succeeds_and_sets_httponly_cookie(client, users):
    response = login(client, HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["user"]["role"] == "head_admin"
    assert "password" not in str(payload["user"]).lower()
    cookie_header = response.headers.get("Set-Cookie", "")
    assert "transport_token=" in cookie_header
    assert "HttpOnly" in cookie_header
    assert "SameSite=Lax" in cookie_header


def test_login_rejects_wrong_password(client, users):
    response = login(client, HEAD_ADMIN_EMAIL, "not-the-right-password")
    assert response.status_code == 401
    assert response.get_json()["error"] == "Invalid email or password"


def test_login_rejects_unknown_user(client, users):
    response = login(client, "nobody@example.invalid", HEAD_ADMIN_PASSWORD)
    assert response.status_code == 401


def test_login_validates_email_format(client, users):
    response = client.post("/api/auth/login", json={"email": "not-an-email", "password": "password123"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "Validation failed"


def test_login_requires_password(client, users):
    response = client.post("/api/auth/login", json={"email": HEAD_ADMIN_EMAIL})
    assert response.status_code == 400


def test_me_requires_authentication(client, users):
    response = client.get("/api/auth/me")
    assert response.status_code == 401


def test_me_returns_authenticated_user(client, users):
    login_head_admin(client, users)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.get_json()["user"]["email"] == HEAD_ADMIN_EMAIL


def test_logout_clears_session(client, users):
    login_head_admin(client, users)
    response = client.post("/api/auth/logout")
    assert response.status_code == 200
    assert client.get("/api/auth/me").status_code == 401


def test_transport_office_cannot_read_head_admin_stats(client, users):
    login_transport_office(client, users)
    assert client.get("/api/stats").status_code == 403
    assert client.get("/api/audit").status_code == 403


def test_head_admin_cannot_modify_records(client, users):
    login_head_admin(client, users)
    response = client.post("/api/buses", json={"bus_number": "BUS-900", "capacity": 40})
    assert response.status_code == 403


def test_transport_office_can_manage_records(client, users):
    login_transport_office(client, users)
    created = client.post("/api/buses", json={"bus_number": "BUS-900", "capacity": 40})
    assert created.status_code == 201
    assert client.get("/api/buses").status_code == 200


def test_protected_pages_redirect_to_login(client, users):
    for path in ("/dashboard", "/logs", "/analytics", "/audit", "/manage"):
        response = client.get(path)
        assert response.status_code in (301, 302), path
        assert "/login" in response.headers.get("Location", "") or response.headers.get("Location", "").endswith("/"), path


def test_page_access_respects_roles(client, users):
    login_transport_office(client, users)
    response = client.get("/dashboard")
    assert response.status_code in (301, 302)
    assert "forbidden" in response.headers.get("Location", "")


def test_password_is_hashed_with_argon2(db, users):
    stored = db.users.find_one({"email": HEAD_ADMIN_EMAIL})
    assert stored["password_hash"] != HEAD_ADMIN_PASSWORD
    assert stored["password_hash"].startswith("$argon2")
    assert verify_password(stored["password_hash"], HEAD_ADMIN_PASSWORD)
    assert not verify_password(stored["password_hash"], "wrong-password")


def test_login_rate_limit_blocks_repeated_failures(users):
    limited_config = build_config(rate_limit_enabled=True, login_rate_limit="3 per minute")
    app = create_app(limited_config)
    app.config.update(TESTING=True)
    client = app.test_client()
    for _ in range(3):
        response = login(client, HEAD_ADMIN_EMAIL, "wrong-password-value")
        assert response.status_code == 401
    blocked = login(client, HEAD_ADMIN_EMAIL, "wrong-password-value")
    assert blocked.status_code == 429
    assert blocked.get_json()["error"].startswith("Too many requests")


def test_security_headers_are_present(client, users):
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert "Content-Security-Policy" in response.headers


def test_login_email_is_normalised_to_lowercase(client, db, users):
    db.users.insert_one(
        {
            "email": "mixed.case@example.invalid",
            "password_hash": db.users.find_one({"email": TRANSPORT_EMAIL})["password_hash"],
            "role": "transport_office",
            "active": True,
        }
    )
    response = login(client, "Mixed.Case@Example.Invalid", TRANSPORT_PASSWORD)
    assert response.status_code == 200
