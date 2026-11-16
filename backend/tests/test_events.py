from __future__ import annotations

from datetime import timedelta

from backend.schemas import EventCreate
from backend.services import ingest_event
from backend.services import naive_now
from backend.tests.conftest import DEVICE_KEY, build_config, login_head_admin, login_transport_office


def event_payload(**overrides):
    payload = {
        "bus_number": "BUS-001",
        "direction": "IN",
        "gate": "Gate 1",
        "camera_id": "gate-1-entry",
        "confidence": 0.95,
        # "Now", not "five minutes ago": app_timezone is Asia/Kolkata, so for the
        # first five minutes after local midnight a five-minute-old event belongs
        # to yesterday and every "today" assertion in this file fails.
        "timestamp": naive_now().isoformat() + "Z",
    }
    payload.update(overrides)
    return payload


def post_event(client, payload, key=DEVICE_KEY):
    headers = {"X-Device-Key": key} if key else {}
    return client.post("/api/events", json=payload, headers=headers)


def register_bus(client, users, bus_number="BUS-001"):
    login_transport_office(client, users)
    response = client.post(
        "/api/buses",
        json={"bus_number": bus_number, "registration_number": "DEMO-REG", "route": "Demo Route", "capacity": 40},
    )
    assert response.status_code == 201
    return response.get_json()["bus"]


def test_event_ingestion_requires_a_device_key(client, db, users):
    response = post_event(client, event_payload(), key=None)
    assert response.status_code == 401
    assert "device" in response.get_json()["error"].lower()


def test_event_ingestion_rejects_a_wrong_device_key(client, db, users):
    response = post_event(client, event_payload(), key="not-the-key")
    assert response.status_code == 401


def test_event_ingestion_stores_a_valid_event(client, db, users):
    register_bus(client, users)
    response = post_event(client, event_payload())
    assert response.status_code == 201
    stored = db.events.find_one({"bus_number": "BUS-001"})
    assert stored is not None
    assert stored["direction"] == "IN"
    assert stored["flagged"] is False
    assert stored["source"] == "device"


def test_event_ingestion_debounces_same_bus_direction_and_gate(client, db, users):
    register_bus(client, users)
    timestamp = naive_now().isoformat() + "Z"
    payload = event_payload(timestamp=timestamp)

    first = post_event(client, payload)
    second = post_event(client, payload)
    third = post_event(client, payload)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.get_json()["duplicate"] is True
    assert third.status_code == 200
    assert third.get_json()["duplicate"] is True
    assert db.events.count_documents({}) == 1

    login_head_admin(client, users)
    events_res = client.get("/api/events").get_json()
    assert events_res["total"] == 1
    assert len(events_res["items"]) == 1

    dedup_audit = db.audit_logs.find_one({"action": "event_deduplicated"})
    assert dedup_audit is not None
    assert dedup_audit["collection"] == "events"


def test_event_ingestion_allows_events_after_debounce_window(client, db, users):
    timestamp = naive_now()
    first = post_event(client, event_payload(timestamp=timestamp.isoformat() + "Z"))
    later = timestamp.replace(microsecond=0)
    later = later + timedelta(seconds=61)
    second = post_event(client, event_payload(timestamp=later.isoformat() + "Z"))

    assert first.status_code == 201
    assert second.status_code == 201
    assert db.events.count_documents({}) == 2


def test_event_ingestion_does_not_debounce_direction_or_gate_changes(client, db, users):
    timestamp = naive_now().isoformat() + "Z"
    first = post_event(client, event_payload(timestamp=timestamp))
    different_direction = post_event(client, event_payload(timestamp=timestamp, direction="OUT"))
    different_gate = post_event(client, event_payload(timestamp=timestamp, gate="Gate 2"))

    assert first.status_code == 201
    assert different_direction.status_code == 201
    assert different_gate.status_code == 201
    assert db.events.count_documents({}) == 3


def test_event_ingestion_debounce_zero_preserves_old_behaviour(client, db, users, monkeypatch):
    config = build_config(event_debounce_seconds=0)
    timestamp = naive_now()
    payload = EventCreate(**event_payload(timestamp=timestamp.isoformat() + "Z"))
    assert "duplicate" not in ingest_event(db, payload, config)
    assert "duplicate" not in ingest_event(db, payload, config)
    assert db.events.count_documents({}) == 2


def test_unregistered_plate_is_flagged(client, db, users):
    response = post_event(client, event_payload(bus_number="BUS-999"))
    assert response.status_code == 201
    assert "unregistered_plate" in response.get_json()["event"]["flag_reasons"]


def test_low_confidence_is_flagged(client, db, users):
    register_bus(client, users)
    response = post_event(client, event_payload(confidence=0.2))
    assert "low_ocr_confidence" in response.get_json()["event"]["flag_reasons"]


def test_ingestion_is_audited(client, db, users):
    post_event(client, event_payload(bus_number="BUS-999"))
    entry = db.audit_logs.find_one({"action": "event_ingested"})
    assert entry is not None
    assert entry["actor"] == "device-client"


def test_stats_are_computed_from_events(client, db, users):
    register_bus(client, users)
    login_head_admin(client, users)
    post_event(client, event_payload(bus_number="BUS-001", direction="IN"))
    post_event(client, event_payload(bus_number="BUS-002", direction="IN"))
    post_event(client, event_payload(bus_number="BUS-002", direction="OUT"))

    stats = client.get("/api/stats").get_json()
    assert stats["entries_today"] == 2
    assert stats["buses_inside"] == 1
    assert stats["total_buses"] == 1
    assert stats["flagged_today"] == 2  # BUS-002 is unregistered


def test_event_flags_distinguish_duplicate_entry_and_exit_without_entry(client, db, users):
    first = post_event(client, event_payload(bus_number="BUS-101"))
    duplicate = post_event(
        client,
        event_payload(bus_number="BUS-101", gate="Gate 2", timestamp=(naive_now() + timedelta(seconds=1)).isoformat() + "Z"),
    )
    exit_without_entry = post_event(
        client,
        event_payload(bus_number="BUS-202", direction="OUT"),
    )

    assert first.status_code == 201
    assert duplicate.status_code == 201
    assert "duplicate_in" in duplicate.get_json()["event"]["flag_reasons"]
    assert exit_without_entry.status_code == 201
    assert "out_without_in" in exit_without_entry.get_json()["event"]["flag_reasons"]


def test_events_endpoint_filters_and_paginates(client, db, users):
    register_bus(client, users)
    post_event(client, event_payload(bus_number="BUS-001", gate="Gate 1"))
    post_event(client, event_payload(bus_number="BUS-002", gate="Gate 2"))
    login_head_admin(client, users)

    filtered = client.get("/api/events?gate=Gate 2").get_json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["gate"] == "Gate 2"

    by_bus = client.get("/api/events?bus_number=BUS-001").get_json()
    assert by_bus["total"] == 1

    by_direction = client.get("/api/events?direction=IN").get_json()
    assert by_direction["total"] == 2

    paged = client.get("/api/events?page=1&page_size=1").get_json()
    assert len(paged["items"]) == 1
    assert paged["pages"] == 2


def test_flagged_filter_works(client, db, users):
    register_bus(client, users)
    post_event(client, event_payload(bus_number="BUS-001", confidence=0.95))
    post_event(client, event_payload(bus_number="BUS-999", confidence=0.95))
    login_head_admin(client, users)
    flagged = client.get("/api/events?flagged=true").get_json()
    assert flagged["total"] == 1
    assert flagged["items"][0]["bus_number"] == "BUS-999"


def test_csv_export_is_protected_and_contains_headers(client, db, users):
    register_bus(client, users)
    post_event(client, event_payload())
    login_head_admin(client, users)
    response = client.get("/api/export/events.csv")
    assert response.status_code == 200
    assert "text/csv" in response.headers["Content-Type"]
    body = response.get_data(as_text=True)
    assert "bus_number" in body
    assert "BUS-001" in body


def test_csv_export_requires_head_admin(client, db, users):
    login_transport_office(client, users)
    assert client.get("/api/export/events.csv").status_code == 403


def test_xlsx_export_returns_a_workbook(client, db, users):
    register_bus(client, users)
    post_event(client, event_payload())
    login_head_admin(client, users)
    response = client.get("/api/export/events.xlsx")
    assert response.status_code == 200
    assert response.get_data()[:2] == b"PK"


def test_audit_log_records_record_changes(client, db, users):
    bus = register_bus(client, users, "BUS-042")
    login_head_admin(client, users)
    entries = client.get("/api/audit").get_json()
    assert entries["total"] >= 1
    create_entry = [item for item in entries["items"] if item["action"] == "create"]
    assert create_entry
    assert create_entry[0]["actor"] == "transport.office@example.invalid"
    assert create_entry[0]["collection"] == "buses"


def test_audit_log_is_not_visible_to_transport_office(client, db, users):
    login_transport_office(client, users)
    assert client.get("/api/audit").status_code == 403


def test_analytics_returns_bucketed_series(client, db, users):
    register_bus(client, users)
    post_event(client, event_payload())
    login_head_admin(client, users)
    payload = client.get("/api/analytics?hours=24&direction=IN").get_json()
    assert payload["totals"]["events"] == 1
    assert len(payload["per_hour"]) == 24
    assert payload["per_gate"][0]["gate"] == "Gate 1"
    assert payload["per_bus"][0]["bus_number"] == "BUS-001"


def test_search_matches_drivers_and_buses(client, db, users):
    register_bus(client, users, "BUS-777")
    login_transport_office(client, users)
    client.post("/api/drivers", json={"name": "Demo Driver Seven", "bus_number": "BUS-777"})
    login_head_admin(client, users)
    payload = client.get("/api/search?q=BUS-777").get_json()
    assert payload["buses"]
    assert payload["drivers"]


def test_driver_crud_round_trip(client, db, users):
    register_bus(client, users, "BUS-555")
    login_transport_office(client, users)
    created = client.post(
        "/api/drivers",
        json={"name": "Demo Driver Five", "bus_number": "BUS-555", "phone": "+91 00000 00005"},
    )
    assert created.status_code == 201
    driver_id = created.get_json()["driver"]["id"]
    updated = client.put(f"/api/drivers/{driver_id}", json={"name": "Demo Driver Five Updated"})
    assert updated.status_code == 200
    assert updated.get_json()["driver"]["name"] == "Demo Driver Five Updated"
    assert client.delete(f"/api/drivers/{driver_id}").status_code == 200
    assert client.get(f"/api/drivers/{driver_id}").status_code == 404


def test_update_without_fields_is_rejected(client, db, users):
    register_bus(client, users, "BUS-556")
    login_transport_office(client, users)
    response = client.put("/api/buses/" + "0" * 24, json={})
    assert response.status_code in (400, 404)
