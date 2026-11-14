#!/usr/bin/env python3
"""Seed clearly fake demo data. Requires explicit passwords from the environment."""
from __future__ import annotations

import os
from datetime import timedelta


from .auth import hash_password
from .config import DEMO_ADMIN_EMAIL, DEMO_ADMIN_PASSWORD, Config
from .db import get_database
from .schemas import EventCreate
from .services import aware_now, ingest_event, naive_now

DEMO_BUSES = [
    {
        "bus_number": "BUS-001",
        "registration_number": "DEMO-REG-001",
        "route": "Demo Route A",
        "capacity": 42,
        "insurance_expiry": "2027-01-31",
        "status": "active",
        "notes": "Fictional demo bus",
    },
    {
        "bus_number": "BUS-002",
        "registration_number": "DEMO-REG-002",
        "route": "Demo Route B",
        "capacity": 38,
        "insurance_expiry": "2027-02-28",
        "status": "active",
        "notes": "Fictional demo bus",
    },
    {
        "bus_number": "BUS-003",
        "registration_number": "DEMO-REG-003",
        "route": "Demo Route C",
        "capacity": 45,
        "insurance_expiry": "2027-03-31",
        "status": "active",
        "notes": "Fictional demo bus",
    },
    {
        "bus_number": "BUS-004",
        "registration_number": "DEMO-REG-004",
        "route": "Demo Route D",
        "capacity": 40,
        "insurance_expiry": "2027-04-30",
        "status": "active",
        "notes": "Fictional demo bus",
    },
]

DEMO_DRIVERS = [
    {
        "name": "Demo Driver One",
        "phone": "+91 00000 00001",
        "bus_number": "BUS-001",
        "license_number": "DEMO-LIC-001",
        "notes": "Fictional demo record",
        "active": True,
    },
    {
        "name": "Demo Driver Two",
        "phone": "+91 00000 00002",
        "bus_number": "BUS-002",
        "license_number": "DEMO-LIC-002",
        "notes": "Fictional demo record",
        "active": True,
    },
    {
        "name": "Demo Driver Three",
        "phone": "+91 00000 00003",
        "bus_number": "BUS-003",
        "license_number": "DEMO-LIC-003",
        "notes": "Fictional demo record",
        "active": True,
    },
]


def iso_ago(hours: float, minutes: float = 0) -> str:
    value = aware_now() - timedelta(hours=hours, minutes=minutes)
    return value.isoformat().replace("+00:00", "Z")


def demo_events() -> list[EventCreate]:
    return [
        EventCreate(bus_number="BUS-001", direction="IN", gate="Gate 1", camera_id="demo-cam-01", confidence=0.96, timestamp=iso_ago(2, 15)),
        EventCreate(bus_number="BUS-001", direction="OUT", gate="Gate 1", camera_id="demo-cam-02", confidence=0.94, timestamp=iso_ago(1, 30)),
        EventCreate(bus_number="BUS-002", direction="IN", gate="Gate 2", camera_id="demo-cam-03", confidence=0.91, timestamp=iso_ago(1, 5)),
        EventCreate(bus_number="BUS-003", direction="IN", gate="Gate 1", camera_id="demo-cam-01", confidence=0.97, timestamp=iso_ago(3)),
        EventCreate(bus_number="BUS-003", direction="OUT", gate="Gate 2", camera_id="demo-cam-04", confidence=0.93, timestamp=iso_ago(2, 30)),
        EventCreate(bus_number="BUS-004", direction="IN", gate="Gate 2", camera_id="demo-cam-03", confidence=0.95, timestamp=iso_ago(14)),
        EventCreate(bus_number="BUS-004", direction="IN", gate="Gate 2", camera_id="demo-cam-03", confidence=0.88, timestamp=iso_ago(0, 30)),
        EventCreate(bus_number="BUS-099", direction="IN", gate="Gate 1", camera_id="demo-cam-01", confidence=0.41, timestamp=iso_ago(0, 10)),
    ]


def seed_demo_data(
    db,
    config: Config,
    *,
    head_password: str,
    office_password: str,
    head_email: str = "head.admin@example.invalid",
    office_email: str = "transport.office@example.invalid",
    demo_login: bool = False,
) -> dict[str, int]:
    """Insert the fake demo dataset into an existing database handle.

    Only fictional records are written: demo bus numbers, demo driver names and
    reserved `example.invalid` addresses.

    With ``demo_login`` the known ``admin`` / ``admin`` account is added for the
    isolated Test Lab. Callers must only pass it when ``DEMO_MODE`` is on, and
    that flag is refused in production.
    """
    db.users.delete_many({"demo_user": True})
    db.buses.delete_many({"demo": True})
    db.drivers.delete_many({"demo": True})
    db.events.delete_many({"demo": True})

    now = naive_now()
    users = [
        {
            "email": head_email,
            "password_hash": hash_password(head_password),
            "role": "head_admin",
            "active": True,
            "demo_user": True,
            "created_at": now,
        },
        {
            "email": office_email,
            "password_hash": hash_password(office_password),
            "role": "transport_office",
            "active": True,
            "demo_user": True,
            "created_at": now,
        },
    ]
    if demo_login:
        users.append({
            "email": DEMO_ADMIN_EMAIL,
            "password_hash": hash_password(DEMO_ADMIN_PASSWORD),
            "role": "head_admin",
            "active": True,
            "demo_user": True,
            "created_at": now,
        })
    db.users.insert_many(users)

    for bus in DEMO_BUSES:
        db.buses.insert_one({**bus, "demo": True, "created_at": now, "updated_at": now})
    for driver in DEMO_DRIVERS:
        db.drivers.insert_one({**driver, "demo": True, "created_at": now, "updated_at": now})

    events = demo_events()
    for event in events:
        created = ingest_event(db, event, config, source="demo")
        db.events.update_one({"_id": created["id"]}, {"$set": {"demo": True}})

    return {
        "buses": len(DEMO_BUSES),
        "drivers": len(DEMO_DRIVERS),
        "events": len(events),
        "users": len(users),
    }


def main() -> None:
    if os.getenv("ALLOW_DEMO_SEED", "false").lower() not in {"1", "true", "yes", "on"}:
        raise SystemExit("Set ALLOW_DEMO_SEED=true to seed demo data.")
    head_password = os.getenv("SEED_HEAD_ADMIN_PASSWORD", "")
    office_password = os.getenv("SEED_TRANSPORT_PASSWORD", "")
    if len(head_password) < 8 or len(office_password) < 8:
        raise SystemExit("Set SEED_HEAD_ADMIN_PASSWORD and SEED_TRANSPORT_PASSWORD to values of at least 8 characters. Values are never printed.")

    config = Config.from_env()
    db = get_database(config)
    counts = seed_demo_data(
        db,
        config,
        head_password=head_password,
        office_password=office_password,
        head_email=os.getenv("SEED_HEAD_ADMIN_EMAIL", "head.admin@example.invalid"),
        office_email=os.getenv("SEED_TRANSPORT_EMAIL", "transport.office@example.invalid"),
    )
    print(
        "Demo seed complete: "
        f"{counts['buses']} buses, {counts['drivers']} drivers, "
        f"{counts['events']} events, {counts['users']} users."
    )


if __name__ == "__main__":
    main()
