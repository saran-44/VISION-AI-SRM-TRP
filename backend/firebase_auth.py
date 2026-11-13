"""Firebase Authentication for the VISION AI - SRM TRP console.

The browser authenticates with Firebase (email/password or Google), then
exchanges the resulting **Firebase ID token** for this application's own
short-lived session cookie. The ID token is verified server-side against
Google's published signing keys — no service account and no private key are
needed.

Two independent checks protect the portal:

1. **Credential check (Firebase).** Only a credential that Firebase accepts
   can produce a valid ID token. Firebase password accounts can also be
   created by client-side sign-up, so sign-in alone is not administrator
   approval.
2. **Authorisation check (access module + the ``users`` collection).** The
   token must carry a verified email, and the email must be active in the
   access list. An otherwise unknown password user may be auto-provisioned
   only with the administrator-set approval claim. Google users always need
   a pre-existing access-list entry.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

import jwt
from jwt import PyJWKClient

logger = logging.getLogger(__name__)

# Firebase's OpenID discovery document advertises this JSON Web Key Set.
# PyJWKClient expects JWKS, not Google's separate x509 certificate endpoint.
GOOGLE_SECURE_TOKEN_JWKS = (
    "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
)

#: The Firebase sign-in providers this application understands.
PROVIDER_PASSWORD = "password"
PROVIDER_GOOGLE = "google.com"
DEFAULT_PROVIDERS = (PROVIDER_PASSWORD, PROVIDER_GOOGLE)

#: A trusted administrator sets this Firebase custom claim to the approved
#: email before an unknown password account may be auto-provisioned. Matching
#: the email also prevents a later account email change from reusing approval.
PORTAL_APPROVAL_CLAIM = "transport_portal_approved_email"

_jwk_client: PyJWKClient | None = None
_jwk_lock = threading.Lock()


class FirebaseAuthError(Exception):
    """Raised when a Firebase ID token cannot be trusted."""

    def __init__(self, message: str, status: int = 401):
        super().__init__(message)
        self.message = message
        self.status = status


def _signing_key_client() -> PyJWKClient:
    global _jwk_client
    with _jwk_lock:
        if _jwk_client is None:
            # lifespan caches the key set for five minutes, which is enough to
            # pick up Google's key rotation without hammering the endpoint.
            _jwk_client = PyJWKClient(GOOGLE_SECURE_TOKEN_JWKS, lifespan=300)
        return _jwk_client


def verify_id_token(id_token: str, project_id: str) -> dict[str, Any]:
    """Verify a Firebase ID token and return its decoded claims.

    Raises :class:`FirebaseAuthError` if the token is malformed, expired,
    signed by an unknown key, or issued for a different project.
    """
    if not id_token or not isinstance(id_token, str):
        raise FirebaseAuthError("A Firebase ID token is required.")

    if len(id_token) > 8192:
        raise FirebaseAuthError("The Firebase ID token is implausibly long.")

    try:
        signing_key = _signing_key_client().get_signing_key_from_jwt(id_token)
    except jwt.PyJWKClientConnectionError as exc:
        # This is a PyJWTError too, but an unavailable key service is not an
        # invalid credential. Report a retryable failure rather than a 401.
        logger.warning("Could not fetch the Firebase signing keys: %s", exc)
        raise FirebaseAuthError(
            "The authentication service is temporarily unavailable.", status=503
        ) from exc
    except jwt.PyJWTError as exc:
        raise FirebaseAuthError("The Firebase ID token could not be verified.") from exc
    except Exception as exc:  # unexpected key-set problems
        logger.warning("Could not fetch the Firebase signing keys: %s", exc)
        raise FirebaseAuthError(
            "The authentication service is temporarily unavailable.", status=503
        ) from exc

    try:
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=project_id,
            options={"require": ["exp", "iat", "sub", "aud"]},
            leeway=30,
        )
    except jwt.ExpiredSignatureError as exc:
        raise FirebaseAuthError("The Firebase session has expired. Please sign in again.") from exc
    except jwt.InvalidAudienceError as exc:
        raise FirebaseAuthError("This token was not issued for this application.") from exc
    except jwt.PyJWTError as exc:
        raise FirebaseAuthError("The Firebase ID token is not valid.") from exc

    expected_issuer = f"https://securetoken.google.com/{project_id}"
    if claims.get("iss") != expected_issuer:
        raise FirebaseAuthError("This token was not issued by this Firebase project.")

    return claims


def provider_of(claims: dict[str, Any]) -> str:
    """Return the Firebase sign-in provider that produced these claims."""
    firebase_claims = claims.get("firebase") or {}
    provider = str(firebase_claims.get("sign_in_provider") or "").strip()
    return provider or "unknown"


def identity_of(claims: dict[str, Any]) -> dict[str, str]:
    """Return the provider identities, e.g. ``{"email": "…", "google.com": "…"}``.

    Firebase stores each identity as a list of values, so the first entry is
    taken for each provider.
    """
    firebase_claims = claims.get("firebase") or {}
    identities = firebase_claims.get("identities") or {}
    if not isinstance(identities, dict):
        return {}
    result: dict[str, str] = {}
    for key, value in identities.items():
        if isinstance(value, (list, tuple)):
            if value:
                result[str(key)] = str(value[0])
        elif value:
            result[str(key)] = str(value)
    return result


def email_of(claims: dict[str, Any]) -> str:
    """Return the normalised email address carried by the token."""
    email = claims.get("email")
    if not isinstance(email, str) or not email.strip():
        raise FirebaseAuthError("This Firebase account has no email address.")
    return email.strip().lower()


def is_email_verified(claims: dict[str, Any]) -> bool:
    # Do not treat a string such as "false" as proof of verification.
    return claims.get("email_verified") is True


def firebase_uid(claims: dict[str, Any]) -> str:
    uid = claims.get("sub")
    return str(uid) if uid else ""
