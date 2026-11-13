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
    assert "__session=" in cookie_header
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


def test_logout_revokes_jti_so_replayed_cookie_is_rejected(client, db, users):
    login_res = login(client, HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD)
    assert login_res.status_code == 200
    cookie = client.get_cookie("__session")
    assert cookie is not None

    logout_res = client.post("/api/auth/logout")
    assert logout_res.status_code == 200
    assert db.revoked_tokens.count_documents({}) == 1

    # Replay the old JWT cookie after logout; must fail with 401.
    client.set_cookie("__session", cookie.value)
    assert client.get("/api/auth/me").status_code == 401


def test_csrf_allows_same_origin_and_public_origin_and_blocks_cross_site(db, users):
    cfg = build_config(
        public_origin="https://vision-ai-srmtrp.web.app",
        cors_allowed_origins=("https://console.example.edu",),
    )
    app = create_app(cfg, database_engine=db.engine)
    app.config.update(TESTING=True)
    client = app.test_client()
    assert login(client, TRANSPORT_EMAIL, TRANSPORT_PASSWORD).status_code == 200
    session_cookie = client.get_cookie("__session").value
    client.set_cookie("__session", session_cookie, domain="srm-trp-transport-abc.a.run.app")

    # Proxied Firebase Hosting request: Host is Cloud Run, Origin is Hosting, Sec-Fetch-Site is same-origin.
    res_same = client.post(
        "/api/buses",
        json={"bus_number": "BUS-CSRF-1", "capacity": 40},
        headers={
            "Host": "srm-trp-transport-abc.a.run.app",
            "Sec-Fetch-Site": "same-origin",
            "Origin": "https://vision-ai-srmtrp.web.app",
        },
    )
    assert res_same.status_code == 201

    # Cross-site from an explicitly allowlisted origin passes.
    res_allowed = client.post(
        "/api/buses",
        json={"bus_number": "BUS-CSRF-2", "capacity": 40},
        headers={
            "Sec-Fetch-Site": "cross-site",
            "Origin": "https://console.example.edu",
        },
    )
    assert res_allowed.status_code == 201

    # Cross-site from an unlisted origin is rejected with 403.
    res_evil = client.post(
        "/api/buses",
        json={"bus_number": "BUS-CSRF-3", "capacity": 40},
        headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
    )
    assert res_evil.status_code == 403

    # same-site from a sibling subdomain is rejected when not allowlisted.
    res_sibling = client.post(
        "/api/buses",
        json={"bus_number": "BUS-CSRF-4", "capacity": 40},
        headers={"Sec-Fetch-Site": "same-site", "Origin": "https://other.web.app"},
    )
    assert res_sibling.status_code == 403

    # Missing Sec-Fetch-Site with unlisted Origin is rejected with 403.
    res_origin_only = client.post(
        "/api/buses",
        json={"bus_number": "BUS-CSRF-5", "capacity": 40},
        headers={"Origin": "https://evil.example"},
    )
    assert res_origin_only.status_code == 403

    # Non-browser client sending neither header is allowed when authenticated.
    res_non_browser = client.post(
        "/api/buses",
        json={"bus_number": "BUS-CSRF-6", "capacity": 40},
    )
    assert res_non_browser.status_code == 201


def test_public_user_omits_internal_fields_such_as_firebase_uid_and_demo_user(client, db, users):
    db.users.update_one(
        {"_id": db.users.find_one({"email": HEAD_ADMIN_EMAIL})["_id"]},
        {"$set": {"firebase_uid": "secret-firebase-uid", "demo_user": True}},
    )
    login_head_admin(client, users)
    me_res = client.get("/api/auth/me")
    assert me_res.status_code == 200
    user = me_res.get_json()["user"]
    assert user["email"] == HEAD_ADMIN_EMAIL
    assert user["role"] == "head_admin"
    assert "firebase_uid" not in user
    assert "demo_user" not in user
    assert "password_hash" not in user
    assert set(user) <= {"id", "email", "role", "active", "auth_provider", "created_at", "last_sign_in_at"}


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


def test_proxy_count_extracts_client_ip_for_rate_limit_and_audit(db, users):
    limited_config = build_config(
        rate_limit_enabled=True,
        login_rate_limit="2 per minute",
        trusted_proxy_count=2,
    )
    app = create_app(limited_config, database_engine=db.engine)
    app.config.update(TESTING=True)
    client = app.test_client()

    for _ in range(2):
        res = client.post(
            "/api/auth/login",
            json={"email": HEAD_ADMIN_EMAIL, "password": "wrong-password-value"},
            headers={"X-Forwarded-For": "198.51.100.10, 10.0.0.1", "X-Forwarded-Proto": "https, https"},
        )
        assert res.status_code == 401

    blocked = client.post(
        "/api/auth/login",
        json={"email": HEAD_ADMIN_EMAIL, "password": "wrong-password-value"},
        headers={"X-Forwarded-For": "198.51.100.10, 10.0.0.1", "X-Forwarded-Proto": "https, https"},
    )
    assert blocked.status_code == 429

    other_client = client.post(
        "/api/auth/login",
        json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD},
        headers={"X-Forwarded-For": "198.51.100.11, 10.0.0.1", "X-Forwarded-Proto": "https, https"},
    )
    assert other_client.status_code == 200
    entry = db.audit_logs.find_one({"action": "login"})
    assert entry["ip"] == "198.51.100.11"
    assert entry["after"]["xff_raw"] == "198.51.100.11, 10.0.0.1"


def test_rate_limit_blocks_firebase_login(db, users, monkeypatch):
    from backend import app as app_module
    from backend.firebase_auth import FirebaseAuthError

    def invalid(_token, _project):
        raise FirebaseAuthError("Invalid Firebase token")

    limited_config = build_config(rate_limit_enabled=True, login_rate_limit="2 per minute")
    app = create_app(limited_config, database_engine=db.engine)
    app.config.update(TESTING=True)
    monkeypatch.setattr(app_module, "verify_firebase_id_token", invalid)
    client = app.test_client()

    for _ in range(2):
        assert client.post("/api/auth/firebase", json={"id_token": "x" * 30}).status_code == 401
    assert client.post("/api/auth/firebase", json={"id_token": "x" * 30}).status_code == 429


def test_limiter_configures_in_memory_fallback_and_swallow_errors(app):
    limiter = app.extensions["limiter"]
    assert limiter._swallow_errors is True
    assert limiter._in_memory_fallback_enabled is True
