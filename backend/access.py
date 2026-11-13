"""Access control for the SRM TRP Transport console.

The ``users`` collection is the authoritative **authorisation list**: it holds
the email address, the role and whether the account is active. Firebase
supplies the *credential*; this module decides whether a successfully
authenticated identity is allowed into the portal.

The two are deliberately separate. Firebase password and Google accounts
can be created without an administrator's approval. The backend requires a
verified email and an active access-list entry, except that a password account
with an administrator-set Firebase approval claim may be auto-provisioned.
"""
from __future__ import annotations

from typing import Any

from .firebase_auth import (
    PORTAL_APPROVAL_CLAIM,
    PROVIDER_GOOGLE,
    PROVIDER_PASSWORD,
    email_of,
    firebase_uid,
    is_email_verified,
    provider_of,
)

ROLES = ("head_admin", "transport_office")


class AccessDenied(Exception):
    """Raised when an authenticated identity may not use the portal."""

    def __init__(self, message: str, status: int = 403):
        super().__init__(message)
        self.message = message
        self.status = status


def _now():
    from .services import naive_now

    return naive_now()


def find_user(db, email: str) -> dict[str, Any] | None:
    return db.users.find_one({"email": email})


def is_authorised(user: dict[str, Any] | None) -> bool:
    return bool(user) and bool(user.get("active", True))


def resolve_identity(
    db,
    claims: dict[str, Any],
    *,
    allowed_providers: tuple[str, ...] = (PROVIDER_PASSWORD, PROVIDER_GOOGLE),
    auto_provision: bool = True,
    default_role: str = "transport_office",
) -> tuple[dict[str, Any], bool]:
    """Authorise a verified Firebase identity against the access list.

    Returns ``(user, created)`` where ``user`` is the stored user document and
    ``created`` says whether the authorisation record was just created.

    Raises :class:`AccessDenied` when the identity may not use the portal.
    """
    provider = provider_of(claims)
    email = email_of(claims)

    if provider not in allowed_providers:
        raise AccessDenied(
            f"Sign-in with '{provider}' is not enabled for this portal.",
            status=403,
        )

    # An unverified password account can be created with somebody else's
    # email. Check ownership before accepting an existing access-list entry or
    # binding a Firebase UID to it.
    if not is_email_verified(claims):
        raise AccessDenied("Verify your email address before signing in.", status=403)

    user = find_user(db, email)

    if user is None:
        # A valid password token alone is not approval: Firebase permits
        # self-sign-up. The custom claim must come from a trusted Firebase
        # administrator, match this exact email, and is never accepted for
        # Google users. An email change therefore requires fresh approval.
        approved_email = claims.get(PORTAL_APPROVAL_CLAIM)
        approved = isinstance(approved_email, str) and approved_email.strip().lower() == email
        if provider != PROVIDER_PASSWORD or not auto_provision or not approved:
            raise AccessDenied(
                "This email address is not authorised for the transport portal. "
                "Ask the transport office to add it to the access list.",
                status=403,
            )
        user = _create_user(db, email, provider, default_role)
        _record_provider(db, user, provider, firebase_uid(claims))
        return user, True

    if not user.get("active", True):
        raise AccessDenied(
            "This account has been deactivated. Contact the transport office.",
            status=403,
        )

    bound_uid = user.get("firebase_uid")
    incoming_uid = firebase_uid(claims)
    if bound_uid and incoming_uid and bound_uid != incoming_uid:
        raise AccessDenied(
            "This email is already bound to a different Firebase account. "
            "Contact the transport office to reset the link.",
            status=403,
        )

    _record_provider(db, user, provider, incoming_uid)
    return user, False


def _create_user(db, email: str, provider: str, default_role: str) -> dict[str, Any]:
    from .auth import hash_password  # noqa: F401  (kept for symmetry / future use)
    from .services import naive_now

    now = naive_now()
    document = {
        "email": email,
        # No usable local password: this account authenticates through
        # Firebase. The field exists so the document shape stays uniform.
        "password_hash": None,
        "role": default_role,
        "active": True,
        "auth_provider": provider,
        "created_at": now,
        "updated_at": now,
    }
    result = db.users.insert_one(document)
    document["_id"] = result.inserted_id
    return document


def _record_provider(db, user: dict[str, Any], provider: str, uid: str) -> None:
    updates: dict[str, Any] = {"last_sign_in_at": _now(), "auth_provider": provider}
    if uid and not user.get("firebase_uid"):
        updates["firebase_uid"] = uid
    db.users.update_one({"_id": user["_id"]}, {"$set": updates})


def list_access_entries(db) -> list[dict[str, Any]]:
    """Return the access list for administration."""
    entries = []
    for user in db.users.find({}).sort("email", 1):
        entries.append(
            {
                "email": user.get("email"),
                "role": user.get("role"),
                "active": bool(user.get("active", True)),
                "auth_provider": user.get("auth_provider"),
                "firebase_linked": bool(user.get("firebase_uid")),
                "last_sign_in_at": user.get("last_sign_in_at"),
                "created_at": user.get("created_at"),
            }
        )
    return entries


def add_access_entry(db, email: str, role: str = "transport_office", active: bool = True) -> dict[str, Any]:
    """Add or update an authorisation record."""
    if role not in ROLES:
        raise ValueError(f"Unknown role '{role}'. Use one of: {', '.join(ROLES)}")

    from .services import naive_now

    email = email.strip().lower()
    now = naive_now()
    existing = find_user(db, email)
    if existing:
        db.users.update_one(
            {"_id": existing["_id"]},
            {"$set": {"role": role, "active": active, "updated_at": now}},
        )
        return db.users.find_one({"_id": existing["_id"]})

    result = db.users.insert_one(
        {
            "email": email,
            "password_hash": None,
            "role": role,
            "active": active,
            "auth_provider": "allowlist",
            "created_at": now,
            "updated_at": now,
        }
    )
    return db.users.find_one({"_id": result.inserted_id})


def set_access_active(db, email: str, active: bool) -> dict[str, Any] | None:
    from .services import naive_now

    email = email.strip().lower()
    user = find_user(db, email)
    if not user:
        return None
    db.users.update_one(
        {"_id": user["_id"]},
        {"$set": {"active": active, "updated_at": naive_now()}},
    )
    return db.users.find_one({"_id": user["_id"]})


def unlink_firebase_account(db, email: str) -> dict[str, Any] | None:
    """Forget the Firebase UID bound to an email, so it may be re-linked."""
    from .services import naive_now

    email = email.strip().lower()
    user = find_user(db, email)
    if not user:
        return None
    db.users.update_one(
        {"_id": user["_id"]},
        {"$unset": {"firebase_uid": ""}, "$set": {"updated_at": naive_now()}},
    )
    return db.users.find_one({"_id": user["_id"]})


__all__ = [
    "AccessDenied",
    "PROVIDER_GOOGLE",
    "PROVIDER_PASSWORD",
    "ROLES",
    "add_access_entry",
    "find_user",
    "is_authorised",
    "list_access_entries",
    "resolve_identity",
    "set_access_active",
    "unlink_firebase_account",
]
