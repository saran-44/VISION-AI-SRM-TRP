from __future__ import annotations

import hmac
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import current_app, g, jsonify, make_response, redirect, request

from .config import Config
from .db import public_doc

# Firebase Hosting forwards only the __session cookie to Cloud Run. Direct
# deployments use the same host-only, HttpOnly cookie for consistency.
COOKIE_NAME = "__session"
AUDIENCE = "transport-ui"
ISSUER = "srm-trp-transport"

password_hasher = PasswordHasher(
    time_cost=2,
    memory_cost=19_456,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    if not password_hash:
        return False
    try:
        return password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def public_user(doc: dict | None) -> dict | None:
    result = public_doc(doc)
    if result is None:
        return None
    for key in ("password_hash", "_id"):
        result.pop(key, None)
    return result


def create_access_token(config: Config, user: dict) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=config.jwt_ttl_minutes)
    payload = {
        "sub": user["email"],
        "email": user["email"],
        "role": user["role"],
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": expires_at,
        "aud": AUDIENCE,
        "iss": ISSUER,
    }
    token = jwt.encode(payload, config.jwt_secret, algorithm="HS256")
    return token, expires_at


def decode_access_token(config: Config, token: str) -> dict:
    return jwt.decode(
        token,
        config.jwt_secret,
        algorithms=["HS256"],
        audience=AUDIENCE,
        issuer=ISSUER,
        options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        leeway=10,
    )


def user_from_token(config: Config, db, token: str) -> dict | None:
    try:
        payload = decode_access_token(config, token)
    except jwt.PyJWTError:
        return None
    email = payload.get("email") or payload.get("sub")
    user = db.users.find_one({"email": email, "active": True})
    if not user or user.get("role") != payload.get("role"):
        return None
    return public_user(user)


def set_auth_cookie(response, token: str, config: Config) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=config.jwt_ttl_minutes * 60,
        httponly=True,
        secure=config.cookie_secure,
        samesite="Lax",
        path="/",
    )


def clear_auth_cookie(response, config: Config) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        path="/",
        secure=config.cookie_secure,
        httponly=True,
        samesite="Lax",
    )


def _config_and_db():
    return current_app.config["TRANSPORT_CONFIG"], current_app.extensions["transport_db"]


def authenticate_request():
    config, db = _config_and_db()
    token = request.cookies.get(COOKIE_NAME, "")
    if not token:
        return None, (jsonify({"error": "Authentication required"}), 401)
    user = user_from_token(config, db, token)
    if not user:
        return None, (jsonify({"error": "Invalid or expired session"}), 401)
    return user, None


def require_roles(*roles: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user, error = authenticate_request()
            if error:
                return error
            if roles and user["role"] not in roles:
                return jsonify({"error": "Forbidden for this role"}), 403
            g.current_user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_page_roles(*roles: str):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user, error = authenticate_request()
            if error:
                return redirect("/")
            if roles and user["role"] not in roles:
                return redirect("/?error=forbidden")
            g.current_user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_device_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        config = current_app.config["TRANSPORT_CONFIG"]
        provided = request.headers.get("X-Device-Key", "")
        if not config.device_api_keys:
            return jsonify({"error": "Device ingestion is not configured"}), 503
        matched = any(
            hmac.compare_digest(provided, expected)
            for expected in config.device_api_keys
        )
        if not provided or not matched:
            return jsonify({"error": "Invalid device API key"}), 401
        g.device_authenticated = True
        return fn(*args, **kwargs)

    return wrapper


def require_device_key_or_roles(*roles: str):
    """Allow either a device API key or an authenticated session of a given role.

    The camera-detection endpoint is used both by an on-site detector device
    (which presents `X-Device-Key`) and by an operator scanning a frame from
    the browser console (which presents the normal session cookie).
    """

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            config = current_app.config["TRANSPORT_CONFIG"]
            provided = request.headers.get("X-Device-Key", "")
            if provided and config.device_api_keys:
                matched = any(
                    hmac.compare_digest(provided, expected)
                    for expected in config.device_api_keys
                )
                if matched:
                    g.device_authenticated = True
                    return fn(*args, **kwargs)

            user, error = authenticate_request()
            if error:
                return jsonify({"error": "Authentication required"}), 401
            if roles and user["role"] not in roles:
                return jsonify({"error": "Forbidden for this role"}), 403
            g.current_user = user
            return fn(*args, **kwargs)

        return wrapper

    return decorator
