"""Tests for the Firebase ID token verification itself.

The sandbox cannot reach Google's key endpoint, so the signing key is
generated locally and the key lookup is stubbed. Everything else — the RS256
signature check, the audience, the issuer, the expiry — is the real code path.
"""

from __future__ import annotations

import io
import json
import time
from urllib.error import URLError

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from backend import firebase_auth
from backend.firebase_auth import FirebaseAuthError, verify_id_token

PROJECT_ID = "srmtrpai"


@pytest.fixture(scope="module")
def keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key, private_key.public_key()


@pytest.fixture()
def stub_keys(monkeypatch, keypair):
    """Point the verifier at our locally generated public key."""
    _private, public_key = keypair

    class FakeSigningKey:
        key = public_key

    class FakeClient:
        def get_signing_key_from_jwt(self, _token):
            return FakeSigningKey()

    monkeypatch.setattr(firebase_auth, "_signing_key_client", lambda: FakeClient())
    return public_key


def _token(keypair, **overrides):
    private_key, _ = keypair
    now = int(time.time())
    payload = {
        "sub": "firebase-uid-1",
        "email": "teacher@srmtrp.edu.in",
        "email_verified": True,
        "iat": now,
        "exp": now + 3600,
        "aud": PROJECT_ID,
        "iss": f"https://securetoken.google.com/{PROJECT_ID}",
        "firebase": {
            "sign_in_provider": "password",
            "identities": {"password": ["teacher@srmtrp.edu.in"]},
        },
    }
    payload.update(overrides)
    return jwt.encode(payload, private_key, algorithm="RS256")


def test_a_valid_token_is_accepted(stub_keys, keypair):
    claims = verify_id_token(_token(keypair), PROJECT_ID)
    assert claims["email"] == "teacher@srmtrp.edu.in"
    assert claims["sub"] == "firebase-uid-1"


def test_jwks_endpoint_and_key_rotation_use_the_real_jwk_client(monkeypatch, keypair):
    # Firebase's OpenID discovery document advertises this JWKS URI. The x509
    # endpoint has a different JSON shape and cannot be used with PyJWKClient.
    expected_url = (
        "https://www.googleapis.com/service_accounts/v1/jwk/"
        "securetoken@system.gserviceaccount.com"
    )
    old_private, old_public = keypair
    new_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    new_public = new_private.public_key()

    def jwk(public_key, kid):
        value = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))
        value.update({"kid": kid, "alg": "RS256", "use": "sig"})
        return value

    responses = [{"keys": [jwk(old_public, "old-key")]}, {"keys": [jwk(new_public, "new-key")]}]
    calls = []

    def fake_urlopen(request, **kwargs):
        assert request.full_url == expected_url
        calls.append(request.full_url)
        return io.BytesIO(json.dumps(responses[len(calls) - 1]).encode())

    monkeypatch.setattr(firebase_auth, "_jwk_client", None)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    payload = jwt.decode(_token(keypair), options={"verify_signature": False})
    old_token = jwt.encode(payload, old_private, algorithm="RS256", headers={"kid": "old-key"})
    new_token = jwt.encode(payload, new_private, algorithm="RS256", headers={"kid": "new-key"})

    assert verify_id_token(old_token, PROJECT_ID)["sub"] == "firebase-uid-1"
    assert verify_id_token(old_token, PROJECT_ID)["sub"] == "firebase-uid-1"
    assert len(calls) == 1  # cached key set
    assert verify_id_token(new_token, PROJECT_ID)["sub"] == "firebase-uid-1"
    assert len(calls) == 2  # unknown key id triggers a refresh


def test_jwks_network_failure_reports_service_unavailable(monkeypatch, keypair):
    def fail_urlopen(*args, **kwargs):
        raise URLError("network unreachable")

    monkeypatch.setattr(firebase_auth, "_jwk_client", None)
    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)
    with pytest.raises(FirebaseAuthError) as excinfo:
        verify_id_token(_token(keypair), PROJECT_ID)
    assert excinfo.value.status == 503


def test_exchange_requires_a_valid_signature_and_matching_admin_approval(
    client, db, stub_keys, keypair
):
    from backend.firebase_auth import PORTAL_APPROVAL_CLAIM

    email = "teacher@srmtrp.edu.in"
    unapproved = _token(keypair)
    response = client.post("/api/auth/firebase", json={"id_token": unapproved})
    assert response.status_code == 403
    assert db.users.find_one({"email": email}) is None

    approved = _token(keypair, **{PORTAL_APPROVAL_CLAIM: email})
    unsigned_claims = jwt.decode(approved, options={"verify_signature": False})
    rogue_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(unsigned_claims, rogue_key, algorithm="RS256")
    response = client.post("/api/auth/firebase", json={"id_token": forged})
    assert response.status_code == 401
    assert db.users.find_one({"email": email}) is None

    response = client.post("/api/auth/firebase", json={"id_token": approved})
    assert response.status_code == 200
    assert response.get_json()["created"] is True
    assert db.users.find_one({"email": email})["firebase_uid"] == "firebase-uid-1"


def test_a_token_for_another_project_is_rejected(stub_keys, keypair):
    token = _token(keypair, aud="someotherproject")
    with pytest.raises(FirebaseAuthError) as excinfo:
        verify_id_token(token, PROJECT_ID)
    assert excinfo.value.status == 401


def test_a_token_from_another_issuer_is_rejected(stub_keys, keypair):
    token = _token(keypair, iss="https://securetoken.google.com/someotherproject")
    with pytest.raises(FirebaseAuthError):
        verify_id_token(token, PROJECT_ID)


def test_an_expired_token_is_rejected(stub_keys, keypair):
    now = int(time.time())
    token = _token(keypair, iat=now - 7200, exp=now - 3600)
    with pytest.raises(FirebaseAuthError) as excinfo:
        verify_id_token(token, PROJECT_ID)
    assert "expired" in excinfo.value.message.lower()


def test_a_token_signed_by_another_key_is_rejected(stub_keys, keypair):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": "x",
            "email": "teacher@srmtrp.edu.in",
            "iat": now,
            "exp": now + 3600,
            "aud": PROJECT_ID,
            "iss": f"https://securetoken.google.com/{PROJECT_ID}",
        },
        other_key,
        algorithm="RS256",
    )
    with pytest.raises(FirebaseAuthError):
        verify_id_token(token, PROJECT_ID)


def test_an_empty_token_is_rejected(stub_keys):
    with pytest.raises(FirebaseAuthError):
        verify_id_token("", PROJECT_ID)


def test_an_absurdly_long_token_is_rejected(stub_keys):
    with pytest.raises(FirebaseAuthError):
        verify_id_token("a" * 9000, PROJECT_ID)


def test_a_key_lookup_failure_reports_service_unavailable(monkeypatch):
    class BrokenClient:
        def get_signing_key_from_jwt(self, _token):
            raise RuntimeError("network unreachable")

    monkeypatch.setattr(firebase_auth, "_signing_key_client", lambda: BrokenClient())
    with pytest.raises(FirebaseAuthError) as excinfo:
        verify_id_token("a.b.c", PROJECT_ID)
    assert excinfo.value.status == 503


def test_provider_and_identity_helpers():
    from backend.firebase_auth import identity_of, provider_of

    claims = {
        "firebase": {
            "sign_in_provider": "google.com",
            "identities": {"google.com": ["a@srmtrp.edu.in"]},
        }
    }
    assert provider_of(claims) == "google.com"
    assert identity_of(claims) == {"google.com": "a@srmtrp.edu.in"}
    assert provider_of({}) == "unknown"
    assert identity_of({"firebase": {"identities": "not-a-dict"}}) == {}
