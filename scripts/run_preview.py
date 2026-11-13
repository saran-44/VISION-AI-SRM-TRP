#!/usr/bin/env python3
"""Run the SRM TRP Transport app locally for a browser preview.

The preview uses an in-memory MongoDB (``mongomock``) by default. It refuses
an external database unless explicitly allowed, because the application also
loads ``MONGO_URI`` from the repository's ``.env``. The fake demo dataset is
seeded into the same database handle the app serves from.

Usage:
    python scripts/run_preview.py [--port 5055] [--host 0.0.0.0] [--no-seed]

Environment overrides:
    MONGO_URI             database URI (defaults to in-memory)
    ALLOW_REAL_PREVIEW_DB explicitly allow an external database (default false)
    ALLOW_DEMO_SEED       also required to seed an external database
    JWT_SECRET            signing key for the preview session (auto-generated if unset)
    PREVIEW_PASSWORD      password for the seeded demo accounts (generated per run if unset)
    PREVIEW_HEAD_ADMIN_EMAIL / PREVIEW_TRANSPORT_EMAIL

Never allow an external preview database to point at production data. Even
with --no-seed, the application may create indexes or modify data.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app import create_app  # noqa: E402
from backend.config import Config, _bool, _firebase_config  # noqa: E402
from backend.db import create_mongo_client, get_database  # noqa: E402
from backend.seed_demo import seed_demo_data  # noqa: E402

# The preview password is a throwaway local credential for fake demo data.
# It is generated per run unless PREVIEW_PASSWORD is supplied, so no usable
# credential is ever stored in the repository.


def build_config(mongo_uri: str, jwt_secret: str) -> Config:
    firebase = _firebase_config()
    project_id = firebase.get("projectId", "")
    base = Config(
        environment="development",
        debug=False,
        testing=False,
        mongo_uri=mongo_uri,
        mongo_db_name=os.getenv("MONGO_DB_NAME", "srm_trp_transport_preview"),
        jwt_secret=jwt_secret,
        jwt_ttl_minutes=max(1, min(60, int(os.getenv("JWT_TTL_MINUTES", "60")))),
        cookie_secure=False,
        cors_allowed_origins=tuple(
            origin.strip()
            for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        ),
        device_api_keys=tuple(
            key.strip()
            for key in os.getenv("DEVICE_API_KEYS", "preview-device-key").split(",")
            if key.strip()
        ),
        rate_limit_enabled=True,
        app_timezone=os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
        firebase=firebase,
        firebase_project_id=project_id,
        # Firebase sign-in is only usable once a project id is configured.
        firebase_auth_enabled=_bool("FIREBASE_AUTH_ENABLED", True) and bool(project_id),
        firebase_allowed_providers=tuple(
            provider.strip()
            for provider in os.getenv(
                "FIREBASE_ALLOWED_PROVIDERS", "password,google.com"
            ).split(",")
            if provider.strip()
        )
        or ("password", "google.com"),
        firebase_auto_provision=_bool("FIREBASE_AUTO_PROVISION", True),
        firebase_default_role=os.getenv(
            "FIREBASE_DEFAULT_ROLE", "transport_office"
        ).strip()
        or "transport_office",
        legacy_password_login_enabled=_bool("LEGACY_PASSWORD_LOGIN_ENABLED", True),
    )
    base.validate()
    return base


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the transport app for preview")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "5055")))
    parser.add_argument("--no-seed", action="store_true", help="do not insert demo records")
    args = parser.parse_args()

    mongo_uri = os.getenv("MONGO_URI", "mongomock://transport_preview").strip()
    using_memory = mongo_uri.startswith("mongomock://")
    # Check before constructing a client or creating indexes. MONGO_URI may
    # have been loaded from .env, not deliberately set for the preview.
    if not using_memory and not _bool("ALLOW_REAL_PREVIEW_DB", False):
        print(
            "Refusing to connect the preview to an external database. Set "
            "MONGO_URI=mongomock://transport_preview for an isolated preview.",
            file=sys.stderr,
        )
        return 2
    if not using_memory and not args.no_seed and not _bool("ALLOW_DEMO_SEED", False):
        print("Refusing to seed an external database without ALLOW_DEMO_SEED=true", file=sys.stderr)
        return 2

    jwt_secret = os.getenv("JWT_SECRET") or secrets.token_urlsafe(48)
    config = build_config(mongo_uri, jwt_secret)
    client = create_mongo_client(mongo_uri)
    db = get_database(config, client)

    password = os.getenv("PREVIEW_PASSWORD") or ("Preview-" + secrets.token_urlsafe(12))
    head_email = os.getenv("PREVIEW_HEAD_ADMIN_EMAIL", "head.admin@example.invalid")
    office_email = os.getenv("PREVIEW_TRANSPORT_EMAIL", "transport.office@example.invalid")

    if not args.no_seed:
        counts = seed_demo_data(
            db,
            config,
            head_password=password,
            office_password=password,
            head_email=head_email,
            office_email=office_email,
        )
        print(
            f"Seeded demo data: {counts['buses']} buses, {counts['drivers']} drivers, "
            f"{counts['events']} events, {counts['users']} users."
        )

    app = create_app(config, mongo_client=client)
    print("=" * 72)
    print(" SRM TRP Transport — local preview")
    print(f" URL          : http://{args.host}:{args.port}/")
    print(f" Database     : {'in-memory (mongomock)' if using_memory else 'external MongoDB (URI hidden)'}")
    print(f" Head admin   : {head_email}")
    print(f" Transport    : {office_email}")
    print(f" Password     : {password}   (fake demo data only — change it for anything real)")
    print("=" * 72)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
