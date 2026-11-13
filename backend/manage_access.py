"""Manage the transport portal's access list.

The access list is the ``users`` table: the authoritative record of which
email addresses may use the portal and what role each one holds. Firebase
supplies the credential; this list supplies the authorisation.

Typical use:

    # see who has access
    python -m backend.manage_access list

    # allow a Google sign-in (Google proves nothing, so the email must be
    # added here first)
    python -m backend.manage_access add transport.office@srmtrp.edu.in \\
        --role transport_office

    # promote somebody to administrator
    python -m backend.manage_access set-role principal@srmtrp.edu.in head_admin

    # suspend access without deleting the record
    python -m backend.manage_access deactivate principal@srmtrp.edu.in
    python -m backend.manage_access activate principal@srmtrp.edu.in

    # let a re-created Firebase account take over an email
    python -m backend.manage_access unlink principal@srmtrp.edu.in

The script reads ``DATABASE_URL`` from the environment
(or a ``.env`` file), exactly like the application.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from sqlalchemy.exc import SQLAlchemyError

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.access import (  # noqa: E402
    ROLES,
    add_access_entry,
    list_access_entries,
    set_access_active,
    unlink_firebase_account,
)
from backend.config import Config  # noqa: E402
from backend.db import get_database  # noqa: E402


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


def _database():
    _load_dotenv()
    if not os.getenv("DATABASE_URL", "").strip():
        raise SystemExit("DATABASE_URL is not set. Add it privately to .env or export it.")
    try:
        config = Config.from_env()
        return get_database(config)
    except SQLAlchemyError:
        # Driver error text may contain connection details or personal data.
        raise SystemExit(
            "Could not initialize PostgreSQL. Check DATABASE_URL format, TLS certificate, "
            "network restrictions, credentials, permissions and the schema migration."
        ) from None
    except RuntimeError as exc:
        # Application-authored messages (schema mismatch, rejected login) contain
        # no driver text and are the only actionable diagnosis, so show them.
        raise SystemExit(f"Could not initialize PostgreSQL: {exc}") from None
    except ValueError:
        raise SystemExit(
            "Could not initialize PostgreSQL. Check DATABASE_URL format, TLS certificate, "
            "network restrictions, credentials, permissions and the schema migration."
        ) from None


def _print_entries(entries: list[dict]) -> None:
    if not entries:
        print("The access list is empty.")
        return
    width = max(len(entry["email"] or "") for entry in entries)
    print(f"{'EMAIL'.ljust(width)}  {'ROLE'.ljust(18)} {'ACTIVE':7} {'PROVIDER':14} FIREBASE")
    for entry in entries:
        print(
            f"{(entry['email'] or '').ljust(width)}  "
            f"{entry['role'].ljust(18)} "
            f"{('yes' if entry['active'] else 'no').ljust(7)} "
            f"{str(entry['auth_provider'] or '-').ljust(14)} "
            f"{'linked' if entry['firebase_linked'] else '-'}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.manage_access",
        description="Manage the transport portal access list.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="Show every account and its access state.")

    add = sub.add_parser("add", help="Allow an email address to sign in.")
    add.add_argument("email")
    add.add_argument("--role", choices=ROLES, default="transport_office")
    add.add_argument("--inactive", action="store_true", help="Add the record but keep it suspended.")

    role = sub.add_parser("set-role", help="Change an account's role.")
    role.add_argument("email")
    role.add_argument("role", choices=ROLES)

    for name, help_text in (("activate", "Restore access."), ("deactivate", "Suspend access.")):
        toggle = sub.add_parser(name, help=help_text)
        toggle.add_argument("email")

    unlink = sub.add_parser(
        "unlink",
        help="Forget the Firebase account bound to an email (needed after the "
             "Firebase user is deleted and re-created).",
    )
    unlink.add_argument("email")

    args = parser.parse_args(argv)
    db = _database()
    try:
        return _execute(db, args)
    except SQLAlchemyError:
        # Query failures may contain access-list data or connection details.
        print("PostgreSQL request failed; check permissions and connectivity.", file=sys.stderr)
        return 1


def _execute(db, args) -> int:
    if args.command == "list":
        _print_entries(list_access_entries(db))
        return 0

    if args.command == "add":
        entry = add_access_entry(db, args.email, args.role, active=not args.inactive)
        print(f"{'Allowed' if entry.get('active') else 'Added (suspended)'}: {entry['email']} ({entry['role']})")
        return 0

    if args.command == "set-role":
        entry = add_access_entry(db, args.email, args.role, active=True)
        print(f"Updated: {entry['email']} -> {entry['role']}")
        return 0

    if args.command in {"activate", "deactivate"}:
        active = args.command == "activate"
        entry = set_access_active(db, args.email, active)
        if not entry:
            print(f"No access entry for {args.email}.", file=sys.stderr)
            return 1
        print(f"{'Access restored' if active else 'Access suspended'}: {entry['email']}")
        return 0

    if args.command == "unlink":
        entry = unlink_firebase_account(db, args.email)
        if not entry:
            print(f"No access entry for {args.email}.", file=sys.stderr)
            return 1
        print(f"Firebase link cleared: {entry['email']}")
        return 0

    raise ValueError("Unknown command")


if __name__ == "__main__":
    raise SystemExit(main())
