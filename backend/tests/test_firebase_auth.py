"""Tests for the Firebase Authentication exchange and the access list.

The Firebase ID token is verified against Google's public signing keys, so the
tests stub the verification step and exercise everything around it: provider
filtering, the access list, auto-provisioning, account binding and the audit
trail.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend import app as app_module
from backend.access import AccessDenied, resolve_identity
from backend.firebase_auth import (
    PORTAL_APPROVAL_CLAIM,
    PROVIDER_GOOGLE,
    PROVIDER_PASSWORD,
    email_of,
    provider_of,
)
from backend.services import naive_now

from .conftest import (
    DEVICE_KEY,
    HEAD_ADMIN_EMAIL,
    HEAD_ADMIN_PASSWORD,
    TRANSPORT_EMAIL,
    TRANSPORT_PASSWORD,
    login,
    login_head_admin,
)

GOOGLE_EMAIL = "google.user@srmtrp.edu.in"
FIREBASE_UID = "firebase-uid-123"


def _token(provider: str, email: str, uid: str = FIREBASE_UID) -> str:
    """Build a fake ID token that carries the provider, email and UID.

    The schema requires at least 20 characters, so the token is padded.
    """
    return f"{provider}|{email}|{uid}".ljust(20, "0")


def _claims(email: str, provider: str = PROVIDER_PASSWORD, uid: str = FIREBASE_UID):
    return {
        "sub": uid,
        "email": email,
        "email_verified": True,
        # The existing provisioning tests use an administrator-approved email.
        PORTAL_APPROVAL_CLAIM: email.strip().lower(),
        "iss": "https://securetoken.google.com/srmtrpai",
        "aud": "srmtrpai",
        "firebase": {
            "sign_in_provider": provider,
            "identities": {provider: [email]},
        },
    }


def _rebuild(app, **overrides):
    """Rebuild the app with different settings, reusing the same database."""
    config = replace(app.config["TRANSPORT_CONFIG"], **overrides)
    application = app_module.create_app(
        config, mongo_client=app.extensions["transport_db"].client
    )
    application.config.update(TESTING=True)
    return application


def _stub_verifier(token: str, _project: str) -> dict:
    """Stand in for Google's signature check; decode our fake token."""
    provider, email, uid = token.split("|", 2)
    return _claims(email, provider, uid)


@pytest.fixture()
def firebase_client(app, users, monkeypatch):
    """A client whose Firebase token verification always succeeds."""
    monkeypatch.setattr(app_module, "verify_firebase_id_token", _stub_verifier)
    return app.test_client()


# ---------------------------------------------------------------- helpers


def test_claims_helpers():
    claims = _claims(GOOGLE_EMAIL, PROVIDER_GOOGLE)
    assert email_of(claims) == GOOGLE_EMAIL
    assert provider_of(claims) == PROVIDER_GOOGLE
    assert provider_of({}) == "unknown"
    with pytest.raises(Exception):
        email_of({"firebase": {}})


def test_access_denied_carries_a_status():
    error = AccessDenied("nope", status=403)
    assert error.status == 403
    assert error.message == "nope"


# --------------------------------------------------------- /api/auth/config


def test_auth_config_is_public(client):
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["mode"] in {"firebase", "password"}
    assert "firebase" in payload
    assert "legacy_password_login" in payload


def test_auth_config_reports_firebase_when_configured(app, users):
    application = _rebuild(app, firebase_project_id="srmtrpai")
    payload = application.test_client().get("/api/auth/config").get_json()
    assert payload["mode"] == "firebase"
    assert payload["firebase"]["enabled"] is True
    assert "password" in payload["firebase"]["providers"]


def test_auth_config_reports_password_only_without_a_project(app):
    application = _rebuild(app, firebase_project_id="")
    payload = application.test_client().get("/api/auth/config").get_json()
    assert payload["mode"] == "password"
    assert payload["firebase"]["enabled"] is False


# ------------------------------------------------------- /api/auth/firebase


def test_firebase_login_rejects_a_missing_token(firebase_client):
    response = firebase_client.post("/api/auth/firebase", json={})
    assert response.status_code == 400
    assert "details" in response.get_json()


def test_firebase_login_requires_a_configured_project(app, monkeypatch):
    application = _rebuild(app, firebase_project_id="")
    response = application.test_client().post("/api/auth/firebase", json={"id_token": "x" * 40})
    assert response.status_code == 503


def test_firebase_login_rejects_an_unverifiable_token(app, monkeypatch):
    def boom(_token, _project):
        from backend.firebase_auth import FirebaseAuthError

        raise FirebaseAuthError("The Firebase ID token is not valid.")

    monkeypatch.setattr(app_module, "verify_firebase_id_token", boom)
    response = app.test_client().post("/api/auth/firebase", json={"id_token": "x" * 40})
    assert response.status_code == 401
    assert "not valid" in response.get_json()["error"]


def test_firebase_login_auto_provisions_an_approved_password_user(firebase_client, users, db):
    response = firebase_client.post("/api/auth/firebase", json={"id_token": _token(PROVIDER_PASSWORD, "new.teacher@srmtrp.edu.in")})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["created"] is True
    assert payload["provider"] == PROVIDER_PASSWORD
    assert payload["user"]["role"] == "transport_office"
    # The session cookie was issued.
    assert "__session" in response.headers.get("Set-Cookie", "")


@pytest.mark.parametrize("approval", [None, False, True, "true", 1, "other@example.invalid"])
def test_firebase_login_denies_self_registered_password_users(
    app, users, db, monkeypatch, approval
):
    email = "unlisted@example.invalid"
    claims = _claims(email, PROVIDER_PASSWORD)
    if approval is None:
        claims.pop(PORTAL_APPROVAL_CLAIM)
    else:
        claims[PORTAL_APPROVAL_CLAIM] = approval
    monkeypatch.setattr(app_module, "verify_firebase_id_token", lambda *_: claims)

    response = app.test_client().post(
        "/api/auth/firebase", json={"id_token": _token(PROVIDER_PASSWORD, email)}
    )
    assert response.status_code == 403
    assert "not authorised" in response.get_json()["error"]
    assert "__session" not in response.headers.get("Set-Cookie", "")
    assert db.users.find_one({"email": email}) is None


def test_password_email_change_requires_fresh_administrator_approval(app, users, db, monkeypatch):
    new_email = "new-address@example.invalid"
    claims = _claims(new_email, PROVIDER_PASSWORD)
    claims[PORTAL_APPROVAL_CLAIM] = "previous-address@example.invalid"
    monkeypatch.setattr(app_module, "verify_firebase_id_token", lambda *_: claims)

    response = app.test_client().post(
        "/api/auth/firebase", json={"id_token": _token(PROVIDER_PASSWORD, new_email)}
    )
    assert response.status_code == 403
    assert db.users.find_one({"email": new_email}) is None


@pytest.mark.parametrize("provider", [PROVIDER_PASSWORD, PROVIDER_GOOGLE])
@pytest.mark.parametrize("verified", [False, "true", None])
def test_firebase_login_rejects_unverified_listed_users_before_uid_binding(
    app, users, db, monkeypatch, provider, verified
):
    claims = _claims(HEAD_ADMIN_EMAIL, provider, "untrusted-uid")
    if verified is None:
        claims.pop("email_verified")
    else:
        claims["email_verified"] = verified
    monkeypatch.setattr(app_module, "verify_firebase_id_token", lambda *_: claims)

    response = app.test_client().post(
        "/api/auth/firebase", json={"id_token": _token(provider, HEAD_ADMIN_EMAIL)}
    )
    assert response.status_code == 403
    assert "Verify your email" in response.get_json()["error"]
    assert "__session" not in response.headers.get("Set-Cookie", "")
    assert db.users.find_one({"email": HEAD_ADMIN_EMAIL}).get("firebase_uid") is None


def test_listed_verified_password_user_does_not_need_custom_claim(app, users, monkeypatch):
    claims = _claims(HEAD_ADMIN_EMAIL, PROVIDER_PASSWORD)
    claims.pop(PORTAL_APPROVAL_CLAIM)
    monkeypatch.setattr(app_module, "verify_firebase_id_token", lambda *_: claims)

    response = app.test_client().post(
        "/api/auth/firebase", json={"id_token": _token(PROVIDER_PASSWORD, HEAD_ADMIN_EMAIL)}
    )
    assert response.status_code == 200
    assert response.get_json()["created"] is False


def test_firebase_login_rejects_a_signed_token_without_email(app, users, monkeypatch):
    claims = _claims(HEAD_ADMIN_EMAIL, PROVIDER_PASSWORD)
    claims.pop("email")
    monkeypatch.setattr(app_module, "verify_firebase_id_token", lambda *_: claims)

    response = app.test_client().post(
        "/api/auth/firebase", json={"id_token": _token(PROVIDER_PASSWORD, HEAD_ADMIN_EMAIL)}
    )
    assert response.status_code == 401
    assert "no email" in response.get_json()["error"]


def test_firebase_login_does_not_auto_provision_a_google_user(firebase_client, users, db):
    """A Google account proves nothing, so it must be on the access list."""
    response = firebase_client.post("/api/auth/firebase", json={"id_token": _token(PROVIDER_GOOGLE, GOOGLE_EMAIL)})
    assert response.status_code == 403
    assert "not authorised" in response.get_json()["error"]
    assert db.users.find_one({"email": GOOGLE_EMAIL}) is None


def test_firebase_login_allows_a_listed_google_user(firebase_client, users, db):
    db.users.insert_one({
        "email": GOOGLE_EMAIL,
        "password_hash": None,
        "role": "transport_office",
        "active": True,
        "created_at": naive_now(),
    })
    response = firebase_client.post("/api/auth/firebase", json={"id_token": _token(PROVIDER_GOOGLE, GOOGLE_EMAIL)})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["created"] is False
    assert payload["provider"] == PROVIDER_GOOGLE


def test_firebase_login_rejects_a_deactivated_user(firebase_client, users, db):
    db.users.insert_one({
        "email": GOOGLE_EMAIL,
        "password_hash": None,
        "role": "transport_office",
        "active": False,
        "created_at": naive_now(),
    })
    response = firebase_client.post("/api/auth/firebase", json={"id_token": _token(PROVIDER_GOOGLE, GOOGLE_EMAIL)})
    assert response.status_code == 403
    assert "deactivated" in response.get_json()["error"]


def test_firebase_login_rejects_a_provider_that_is_not_allowed(app, users, monkeypatch):
    config = replace(
        app.config["TRANSPORT_CONFIG"],
        firebase_project_id="srmtrpai",
        firebase_allowed_providers=(PROVIDER_PASSWORD,),
    )
    application = app_module.create_app(config)
    application.config.update(TESTING=True)
    monkeypatch.setattr(
        app_module,
        "verify_firebase_id_token",
        lambda token, project: _claims(GOOGLE_EMAIL, PROVIDER_GOOGLE),
    )
    response = application.test_client().post("/api/auth/firebase", json={"id_token": _token(PROVIDER_GOOGLE, GOOGLE_EMAIL)})
    assert response.status_code == 403
    assert "not enabled" in response.get_json()["error"]


def test_firebase_login_honours_auto_provision_being_off(app, users, monkeypatch):
    application = _rebuild(
        app,
        firebase_project_id="srmtrpai",
        firebase_auto_provision=False,
    )
    monkeypatch.setattr(app_module, "verify_firebase_id_token", _stub_verifier)
    response = application.test_client().post(
        "/api/auth/firebase",
        json={"id_token": _token(PROVIDER_PASSWORD, "someone@srmtrp.edu.in")},
    )
    assert response.status_code == 403


def test_firebase_login_binds_the_firebase_uid(firebase_client, users, db):
    firebase_client.post("/api/auth/firebase", json={"id_token": _token(PROVIDER_PASSWORD, "bound@srmtrp.edu.in")})
    user = db.users.find_one({"email": "bound@srmtrp.edu.in"})
    assert user["firebase_uid"] == FIREBASE_UID
    assert user["auth_provider"] == PROVIDER_PASSWORD


def test_firebase_login_rejects_a_different_firebase_account_for_the_same_email(app, users, db, monkeypatch):
    db.users.insert_one({
        "email": "bound@srmtrp.edu.in",
        "password_hash": None,
        "role": "transport_office",
        "active": True,
        "firebase_uid": "the-original-uid",
        "created_at": naive_now(),
    })
    application = _rebuild(app, firebase_project_id="srmtrpai")
    monkeypatch.setattr(app_module, "verify_firebase_id_token", _stub_verifier)
    response = application.test_client().post(
        "/api/auth/firebase",
        json={"id_token": _token(PROVIDER_PASSWORD, "bound@srmtrp.edu.in", "a-different-uid")},
    )
    assert response.status_code == 403
    assert "different Firebase account" in response.get_json()["error"]


def test_firebase_login_is_audited(firebase_client, users, db):
    firebase_client.post("/api/auth/firebase", json={"id_token": _token(PROVIDER_PASSWORD, "audited@srmtrp.edu.in")})
    actions = [entry.get("action") for entry in db.audit_logs.find({})]
    assert "login_provisioned" in actions


def test_a_denied_google_login_is_audited(firebase_client, users, db):
    firebase_client.post("/api/auth/firebase", json={"id_token": _token(PROVIDER_GOOGLE, GOOGLE_EMAIL)})
    actions = [entry.get("action") for entry in db.audit_logs.find({})]
    assert "login_denied" in actions


# ------------------------------------------------------------ access list


def test_resolve_identity_creates_then_reuses(app, users, db):
    user, created = resolve_identity(db, _claims("fresh@srmtrp.edu.in"))
    assert created is True
    assert user["role"] == "transport_office"
    assert user["active"] is True

    user, created = resolve_identity(db, _claims("fresh@srmtrp.edu.in"))
    assert created is False


def test_resolve_identity_rejects_an_unknown_google_user(app, users, db):
    with pytest.raises(AccessDenied):
        resolve_identity(db, _claims(GOOGLE_EMAIL, PROVIDER_GOOGLE))


def test_resolve_identity_honours_the_default_role(app, users, db):
    user, _ = resolve_identity(
        db, _claims("admin.new@srmtrp.edu.in"), default_role="head_admin"
    )
    assert user["role"] == "head_admin"


def test_manage_access_list_round_trip(app, users, db):
    from backend.access import add_access_entry, list_access_entries, set_access_active

    add_access_entry(db, "listed@srmtrp.edu.in", "transport_office")
    emails = [entry["email"] for entry in list_access_entries(db)]
    assert "listed@srmtrp.edu.in" in emails

    set_access_active(db, "listed@srmtrp.edu.in", False)
    entry = next(e for e in list_access_entries(db) if e["email"] == "listed@srmtrp.edu.in")
    assert entry["active"] is False

    with pytest.raises(ValueError):
        add_access_entry(db, "bad@srmtrp.edu.in", "not_a_role")


# ------------------------------------------------- legacy password login


def test_legacy_password_login_can_be_disabled(app, users):
    application = _rebuild(app, legacy_password_login_enabled=False)
    response = application.test_client().post(
        "/api/auth/login",
        json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD},
    )
    assert response.status_code == 403


def test_legacy_password_login_still_works_by_default(client, users):
    response = login(client, HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD)
    assert response.status_code == 200
    assert response.get_json()["user"]["role"] == "head_admin"


def test_transport_office_cannot_see_the_audit_log(client, users):
    from .conftest import login_transport_office

    login_transport_office(client, users)
    assert client.get("/api/audit").status_code == 403


def test_device_key_still_works(client):
    response = client.post(
        "/api/events",
        json={
            "bus_number": "TN12AB1234",
            "direction": "IN",
            "gate": "Gate 1 Entry",
            "camera_id": "gate-1-entry",
            "confidence": 0.9,
            "timestamp": "2026-11-12T09:15:00+05:30",
        },
        headers={"X-Device-Key": DEVICE_KEY},
    )
    assert response.status_code == 201


def test_transport_office_login_is_unchanged(client, users):
    from .conftest import login_transport_office

    login_transport_office(client, users)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.get_json()["user"]["email"] == TRANSPORT_EMAIL
    assert response.get_json()["user"]["role"] == "transport_office"


def test_head_admin_can_read_its_own_profile(client, users):
    login_head_admin(client, users)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.get_json()["user"]["email"] == HEAD_ADMIN_EMAIL
