#!/usr/bin/env python3
"""Run a disposable, in-memory preview. Never seeds a real database by default.

DATABASE_URL from the environment/.env is refused unless ALLOW_REAL_PREVIEW_DB
is true; an external database also requires ALLOW_DEMO_SEED=true to seed.
Even --no-seed can modify data when users interact with the application.
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
from backend.config import DEMO_ADMIN_EMAIL, DEMO_ADMIN_PASSWORD, Config, _bool, _firebase_config  # noqa: E402
from backend.db import create_database_engine, get_database  # noqa: E402
from backend.seed_demo import seed_demo_data  # noqa: E402

PREVIEW_URL = "sqlite:///:memory:"


def build_config(database_url: str, jwt_secret: str) -> Config:
    firebase = _firebase_config()
    project_id = firebase.get("projectId", "")
    cfg = Config(
        environment="development", debug=False, testing=False, database_url=database_url,
        jwt_secret=jwt_secret,
        jwt_ttl_minutes=max(1, min(60, int(os.getenv("JWT_TTL_MINUTES", "60")))),
        cookie_secure=False,
        cors_allowed_origins=tuple(x.strip() for x in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if x.strip()),
        device_api_keys=tuple(x.strip() for x in os.getenv("DEVICE_API_KEYS", "preview-device-key").split(",") if x.strip()),
        rate_limit_enabled=True,
        app_timezone=os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
        firebase=firebase, firebase_project_id=project_id,
        firebase_auth_enabled=_bool("FIREBASE_AUTH_ENABLED", True) and bool(project_id),
        firebase_allowed_providers=tuple(x.strip() for x in os.getenv("FIREBASE_ALLOWED_PROVIDERS", "password,google.com").split(",") if x.strip()) or ("password", "google.com"),
        firebase_auto_provision=_bool("FIREBASE_AUTO_PROVISION", True),
        firebase_default_role=os.getenv("FIREBASE_DEFAULT_ROLE", "transport_office").strip() or "transport_office",
        legacy_password_login_enabled=_bool("LEGACY_PASSWORD_LOGIN_ENABLED", True),
        # A disposable preview is the one place the demo login belongs. The
        # config refuses DEMO_MODE outright when ENVIRONMENT=production.
        demo_mode=True,
    )
    cfg.validate()
    return cfg


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the transport app for preview")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "5055")))
    parser.add_argument("--no-seed", action="store_true", help="do not insert demo records")
    args = parser.parse_args()

    # Deliberately NOT plain DATABASE_URL: `.env` usually holds the real
    # Supabase URL, and a disposable preview must never touch it by accident.
    # Pointing the preview at another database takes PREVIEW_DATABASE_URL plus
    # ALLOW_REAL_PREVIEW_DB=true, two deliberate actions.
    database_url = os.getenv("PREVIEW_DATABASE_URL", "").strip() or PREVIEW_URL
    isolated = database_url == PREVIEW_URL
    if not isolated and not _bool("ALLOW_REAL_PREVIEW_DB", False):
        print(
            "Refusing to use an external database for the preview.\n"
            f"  PREVIEW_DATABASE_URL is set; unset it to get the disposable in-memory database,\n"
            "  or add ALLOW_REAL_PREVIEW_DB=true if you really mean it.",
            file=sys.stderr,
        )
        return 2
    if not isolated and not args.no_seed and not _bool("ALLOW_DEMO_SEED", False):
        print("Refusing to seed an external database without ALLOW_DEMO_SEED=true", file=sys.stderr)
        return 2

    config = build_config(database_url, os.getenv("JWT_SECRET") or secrets.token_urlsafe(48))
    engine = create_database_engine(database_url)
    db = get_database(config, engine)
    password = os.getenv("PREVIEW_PASSWORD") or ("Preview-" + secrets.token_urlsafe(12))
    head_email = os.getenv("PREVIEW_HEAD_ADMIN_EMAIL", "head.admin@example.invalid")
    office_email = os.getenv("PREVIEW_TRANSPORT_EMAIL", "transport.office@example.invalid")
    if not args.no_seed:
        counts = seed_demo_data(db, config, head_password=password, office_password=password,
                                head_email=head_email, office_email=office_email,
                                demo_login=config.demo_mode)
        print(f"Seeded demo data: {counts['buses']} buses, {counts['drivers']} drivers, {counts['events']} events, {counts['users']} users.")
    app = create_app(config, database_engine=engine)
    print("=" * 72)
    print(" VISION AI - SRM TRP — local preview")
    print(f" URL          : http://{args.host}:{args.port}/")
    print(f" Database     : {'in-memory SQLite (disposable)' if isolated else 'external PostgreSQL (URL hidden)'}")
    if not isolated:
        print(" WARNING      : this preview is writing to an EXTERNAL database.")
    if not args.no_seed:
        print(f" Head admin   : {head_email}")
        print(f" Transport    : {office_email}")
        print(f" Password     : {password}   (fake demo data only)")
        print(f" Demo login   : {DEMO_ADMIN_EMAIL} / {DEMO_ADMIN_PASSWORD}")
        print(" DEMO MODE    : ON — Test Lab at /test-lab, no real records.")
    print("=" * 72)
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
