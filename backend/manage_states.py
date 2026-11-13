"""Operational maintenance CLI for ``bus_states`` and optional retention purge.

Examples:

    python -m backend.manage_states rebuild
    python -m backend.manage_states purge
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

from backend.config import Config  # noqa: E402
from backend.db import get_database  # noqa: E402
from backend.services import purge_expired_records, rebuild_bus_states  # noqa: E402


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
        return config, get_database(config)
    except (SQLAlchemyError, RuntimeError, ValueError):
        raise SystemExit(
            "Could not initialize database. Check DATABASE_URL, TLS certificate, and schema."
        ) from None


def _execute(db, config: Config, command: str) -> int:
    if command == "rebuild":
        count = rebuild_bus_states(db)
        print(f"Rebuilt bus_states for {count} bus(es).")
        return 0
    if command == "purge":
        if config.event_retention_days <= 0:
            print("Retention purge skipped (EVENT_RETENTION_DAYS=0).")
            return 0
        deleted = purge_expired_records(db, config)
        print(
            f"Purged {deleted['events']} expired event(s) and {deleted['bus_states']} bus_state(s)."
        )
        return 0
    raise ValueError("Unknown command")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.manage_states",
        description="Rebuild bus_states or run retention purge.",
    )
    parser.add_argument("command", choices=("rebuild", "purge"))
    args = parser.parse_args(argv)
    config, db = _database()
    try:
        return _execute(db, config, args.command)
    except SQLAlchemyError:
        print("Database operation failed; check permissions and connectivity.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
