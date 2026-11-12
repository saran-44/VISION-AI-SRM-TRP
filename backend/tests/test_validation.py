from __future__ import annotations

from backend.tests.conftest import DEVICE_KEY, login_head_admin, login_transport_office

VALID_EVENT = {
    "bus_number": "BUS-001",
    "direction": "IN",
    "gate": "Gate 1",
    "camera_id": "gate-1-entry",
    "confidence": 0.95,
    "timestamp": "2026-11-12T09:00:00Z",
}


def post_event(client, payload, key=DEVICE_KEY):
    headers = {"X-Device-Key": key} if key else {}
    return client.post("/api/events", json=payload, headers=headers)


def test_event_rejects_unknown_fields(client, db, users):
    response = post_event(client, {**VALID_EVENT, "driver_name": "Should not be accepted"})
    assert response.status_code == 400
    assert response.get_json()["error"] == "Validation failed"


def test_event_rejects_confidence_out_of_range(client, db, users):
    response = post_event(client, {**VALID_EVENT, "confidence": 1.4})
    assert response.status_code == 400


def test_event_rejects_invalid_direction(client, db, users):
    response = post_event(client, {**VALID_EVENT, "direction": "SIDEWAYS"})
    assert response.status_code == 400


def test_event_rejects_future_timestamp(client, db, users):
    response = post_event(client, {**VALID_EVENT, "timestamp": "2099-01-01T00:00:00Z"})
    assert response.status_code == 400


def test_event_rejects_control_characters_in_gate(client, db, users):
    response = post_event(client, {**VALID_EVENT, "gate": "Gate\x00<script>"})
    assert response.status_code == 400


def test_bus_create_rejects_invalid_bus_number(client, db, users):
    login_transport_office(client, users)
    response = client.post("/api/buses", json={"bus_number": "bad/../plate", "capacity": 40})
    assert response.status_code == 400


def test_bus_create_rejects_unknown_field(client, db, users):
    login_transport_office(client, users)
    response = client.post("/api/buses", json={"bus_number": "BUS-001", "owner_ssn": "123"})
    assert response.status_code == 400


def test_bus_create_rejects_duplicate_bus_number(client, db, users):
    login_transport_office(client, users)
    first = client.post("/api/buses", json={"bus_number": "BUS-001", "capacity": 40})
    assert first.status_code == 201
    second = client.post("/api/buses", json={"bus_number": "BUS-001", "capacity": 40})
    assert second.status_code == 409


def test_driver_create_requires_a_registered_bus(client, db, users):
    login_transport_office(client, users)
    response = client.post(
        "/api/drivers",
        json={"name": "Demo Driver", "bus_number": "BUS-NOT-REGISTERED"},
    )
    assert response.status_code == 400
    assert "bus" in response.get_json()["error"].lower()


def test_event_filter_rejects_invalid_direction(client, db, users):
    login_head_admin(client, users)
    response = client.get("/api/events?direction=SIDEWAYS")
    assert response.status_code == 400


def test_event_filter_rejects_conflicting_date_range(client, db, users):
    login_head_admin(client, users)
    response = client.get("/api/events?date=2026-11-12&date_from=2026-11-01T00:00:00Z")
    assert response.status_code == 400


def test_event_filter_rejects_oversized_page_size(client, db, users):
    login_head_admin(client, users)
    response = client.get("/api/events?page_size=5000")
    assert response.status_code == 400


def test_search_rejects_oversized_query(client, db, users):
    login_head_admin(client, users)
    response = client.get("/api/search?q=" + "x" * 200)
    assert response.status_code == 400


def test_analytics_rejects_out_of_range_hours(client, db, users):
    login_head_admin(client, users)
    response = client.get("/api/analytics?hours=9999")
    assert response.status_code == 400


def test_missing_json_body_is_rejected(client, db, users):
    login_transport_office(client, users)
    response = client.post("/api/buses", data="not json", content_type="application/json")
    assert response.status_code == 400
