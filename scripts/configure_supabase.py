#!/usr/bin/env python3
"""Create a least-privilege Supabase login and a new private .env, interactively.

First apply backend/sql/001_initial.sql in the intended project's SQL Editor.
This script never drops schema/data or changes an existing role or .env.
Passwords are never printed. It is intentionally for the hosted session pooler.
"""
from __future__ import annotations

import getpass
import os
import re
import secrets
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
ROLE = "transport_portal_app"


def create_runtime_role(conn, role: str, password: str) -> None:
    """Called in one admin transaction; existing roles are never modified."""
    versions = conn.execute("SELECT version FROM transport_portal.schema_version").fetchall()
    if versions != [(1,)]:
        raise ValueError("The transport schema version is missing or incompatible")
    if conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
        raise ValueError("The application database role already exists; inspect it instead of overwriting it")
    ident = sql.Identifier(role)
    conn.execute(sql.SQL("CREATE ROLE {} LOGIN NOSUPERUSER NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD {}").format(ident, sql.Literal(password)))
    conn.execute(sql.SQL("GRANT USAGE ON SCHEMA transport_portal TO {}").format(ident))
    conn.execute(sql.SQL("GRANT SELECT ON transport_portal.schema_version TO {}").format(ident))
    conn.execute(sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON transport_portal.users, transport_portal.buses, transport_portal.drivers, transport_portal.events TO {}").format(ident))
    conn.execute(sql.SQL("GRANT SELECT, INSERT ON transport_portal.audit_logs TO {}").format(ident))


def main() -> int:
    env_file = ROOT / ".env"
    if env_file.exists():
        print("STOP: .env already exists. Back it up or deliberately move it outside the repository before running this script; it will not be overwritten.", file=sys.stderr)
        return 2
    print("Use the exact Supabase Connect > Session pooler host and project reference.")
    host = input("Pooler host (host only): ").strip().lower()
    ref = input("Supabase project reference: ").strip().lower()
    ca = Path(input("Absolute Windows path to downloaded Supabase CA certificate: ").strip().strip('"')).expanduser().resolve()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.pooler\.supabase\.com", host) or not re.fullmatch(r"[a-z0-9]+", ref) or not ca.is_file():
        print("STOP: invalid pooler host, project reference or CA certificate path.", file=sys.stderr)
        return 2
    admin_password = getpass.getpass("Supabase database administrator password (hidden): ")
    if not admin_password:
        print("STOP: the password cannot be empty.", file=sys.stderr)
        return 2
    print("The schema must already exist and be version 1. A new role and .env will be created; no existing role or data will be replaced.")
    if input("Type CREATE to continue: ").strip() != "CREATE":
        print("Cancelled; nothing changed.")
        return 1

    app_password = secrets.token_urlsafe(40)
    uri = (f"postgresql://{ROLE}.{ref}:{quote(app_password, safe='')}@{host}:5432/postgres"
           "?sslmode=verify-full")
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    substitutions = {
        "DATABASE_URL=": f"DATABASE_URL={uri}",
        "PGSSLROOTCERT=": f'PGSSLROOTCERT="{ca.as_posix()}"',
        "JWT_SECRET=replace-me-with-a-long-random-value": "JWT_SECRET=" + secrets.token_urlsafe(48),
        "DEVICE_API_KEYS=replace-me-with-a-device-api-key": "DEVICE_API_KEYS=" + secrets.token_urlsafe(48),
    }
    for old, new in substitutions.items():
        if template.count(old) != 1:
            print("STOP: .env.example has changed unexpectedly; no database change was made.", file=sys.stderr)
            return 2
        template = template.replace(old, new, 1)

    try:
        with psycopg.connect(host=host, port=5432, dbname="postgres", user=f"postgres.{ref}",
                             password=admin_password, sslmode="verify-full", sslrootcert=str(ca),
                             connect_timeout=8, prepare_threshold=None) as conn:
            # Do not overwrite .env, even if another process created it in the meantime.
            # File creation precedes the role transaction so the generated password is
            # not lost if a network failure makes commit outcome ambiguous.
            fd = os.open(env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as out:
                out.write(template)
            try:
                os.chmod(env_file, 0o600)  # best effort; Windows ACLs should also be reviewed
            except OSError:
                pass
            create_runtime_role(conn, ROLE, app_password)
        print("Role creation completed. Private .env created; secure it using Windows file permissions.")
        # Test the actual dedicated login, not merely the administrator's connection.
        with psycopg.connect(uri, sslrootcert=str(ca), connect_timeout=8, prepare_threshold=None) as conn:
            for name in ("schema_version", "users", "buses", "drivers", "events", "audit_logs"):
                conn.execute(sql.SQL("SELECT 1 FROM transport_portal.{} LIMIT 0").format(sql.Identifier(name)))
        print("Dedicated login and table read permissions verified. No application records were changed.")
        return 0
    except (psycopg.Error, OSError, ValueError):
        print("STOP: setup or verification failed. Check the intended project, CA/TLS, network access, schema and existing role. Details are hidden to protect credentials.", file=sys.stderr)
        if env_file.exists():
            print("A private .env may have been created and role creation may have committed. Inspect both before retrying; do not overwrite an existing role blindly.", file=sys.stderr)
        return 1
    finally:
        admin_password = app_password = ""


if __name__ == "__main__":
    raise SystemExit(main())
