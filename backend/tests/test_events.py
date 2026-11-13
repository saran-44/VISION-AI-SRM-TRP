from __future__ import annotations

from datetime import timedelta

from backend.services import naive_now
from backend.tests.conftest import DEVICE_KEY, login_head_admin, login_transport_office


def event_payload(**overrides):
    payload = {
        "bus_number": "BUS-001",
        "direction": "IN",
        "gate": "Gate 1",
        "camera_id": "gate-1-entry",
        "confidence": 0.95,
        "timestamp": (naive_now() - timedelta(minutes=5)).isoformat() + "Z",
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


def test_unregistered_plate_is_flagged(client, db, users):
    response = post_event(client, event_payload(bus_number="BUS-UNKNOWN"))
    assert response.status_code == 201
    assert "unregistered_plate" in response.get_json()["event"]["flag_reasons"]


def test_low_confidence_is_flagged(client, db, users):
    register_bus(client, users)
    response = post_event(client, event_payload(confidence=0.2))
    assert "low_ocr_confidence" in response.get_json()["event"]["flag_reasons"]


def test_ingestion_is_audited(client, db, users):
    post_event(client, event_payload(bus_number="BUS-UNKNOWN"))
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
    post_event(client, event_payload(bus_number="BUS-UNKNOWN", confidence=0.95))
    login_head_admin(client, users)
    flagged = client.get("/api/events?flagged=true").get_json()
    assert flagged["total"] == 1
    assert flagged["items"][0]["bus_number"] == "BUS-UNKNOWN"


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


def test_sse_stream_returns_initial_tick_with_id_and_closes_at_max_seconds(db, monkeypatch):
    import json as json_module
    from backend.app import create_app
    from backend.auth import hash_password
    from backend.tests.conftest import HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD, build_config

    now_clock = [0.0]
    monkeypatch.setattr("backend.app.time.monotonic", lambda: now_clock[0])

    def fake_sleep(seconds):
        now_clock[0] += seconds

    monkeypatch.setattr("backend.app.time.sleep", fake_sleep)
    app = create_app(build_config(sse_max_connections=2, sse_max_seconds=5), database_engine=db.engine)
    app.config.update(TESTING=True)
    db.users.insert_one({
        "email": HEAD_ADMIN_EMAIL,
        "password_hash": hash_password(HEAD_ADMIN_PASSWORD),
        "role": "head_admin",
        "active": True,
        "created_at": naive_now(),
    })
    client = app.test_client()
    assert client.post("/api/auth/login", json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD}).status_code == 200
    assert client.post("/api/events", headers={"X-Device-Key": DEVICE_KEY}, json=event_payload()).status_code == 201

    response = client.get("/api/stream")
    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    body = response.get_data(as_text=True)
    data_lines = [line[6:] for line in body.splitlines() if line.startswith("data: ")]
    assert len(data_lines) == 1
    tick = json_module.loads(data_lines[0])
    assert tick["type"] == "tick"
    assert tick["recent_events"]
    assert "id" in tick["recent_events"][0]


def test_sse_stream_rejects_excess_concurrent_connections_with_503_and_releases_slot(db):
    from backend.app import create_app
    from backend.auth import hash_password
    from backend.tests.conftest import HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD, build_config

    app = create_app(build_config(sse_max_connections=1, sse_max_seconds=5), database_engine=db.engine)
    app.config.update(TESTING=True)
    db.users.insert_one({
        "email": HEAD_ADMIN_EMAIL,
        "password_hash": hash_password(HEAD_ADMIN_PASSWORD),
        "role": "head_admin",
        "active": True,
        "created_at": naive_now(),
    })
    client = app.test_client()
    assert client.post("/api/auth/login", json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD}).status_code == 200

    sem = app.extensions["sse_semaphore"]
    assert sem.acquire(blocking=False) is True
    try:
        rejected = client.get("/api/stream")
        assert rejected.status_code == 503
        assert rejected.headers["Retry-After"] == "10"
    finally:
        sem.release()


def test_sse_slot_released_when_response_closed_before_iteration(db):
    from backend.app import create_app
    from backend.auth import hash_password
    from backend.tests.conftest import HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD, build_config

    app = create_app(build_config(sse_max_connections=1, sse_max_seconds=50), database_engine=db.engine)
    app.config.update(TESTING=True)
    db.users.insert_one({
        "email": HEAD_ADMIN_EMAIL,
        "password_hash": hash_password(HEAD_ADMIN_PASSWORD),
        "role": "head_admin",
        "active": True,
        "created_at": naive_now(),
    })
    client = app.test_client()
    assert client.post("/api/auth/login", json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD}).status_code == 200

    response = client.get("/api/stream", buffered=False)
    assert response.status_code == 200
    # Close without iterating the generator — call_on_close must free the slot.
    response.close()

    sem = app.extensions["sse_semaphore"]
    assert sem.acquire(blocking=False) is True
    sem.release()


def test_ready_endpoint_returns_200_when_db_ok_and_503_on_sqlalchemy_error(client, db, monkeypatch):
    from sqlalchemy.exc import OperationalError

    ok = client.get("/api/ready")
    assert ok.status_code == 200
    assert ok.get_json() == {"status": "ready", "database": "ok"}

    def fail_ping():
        raise OperationalError("secret SQL", {}, Exception("sensitive"))

    monkeypatch.setattr(db, "ping", fail_ping)
    failing = client.get("/api/ready")
    assert failing.status_code == 503
    assert failing.get_json() == {"status": "unavailable", "database": "unreachable"}


def test_health_and_ready_are_exempt_from_rate_limits(app):
    limiter = app.extensions["limiter"]
    exempt = limiter._route_exemptions
    assert any(route.endswith(".health") for route in exempt)
    assert any(route.endswith(".ready") for route in exempt)


def test_compute_stats_uses_bus_states_on_out_of_order_events(client, db, users):
    register_bus(client, users)
    login_head_admin(client, users)
    now = naive_now()
    later_out = post_event(
        client,
        event_payload(direction="OUT", timestamp=(now - timedelta(minutes=2)).isoformat() + "Z"),
    )
    assert later_out.status_code == 201
    earlier_in = post_event(
        client,
        event_payload(direction="IN", timestamp=(now - timedelta(minutes=20)).isoformat() + "Z"),
    )
    assert earlier_in.status_code == 201

    stats = client.get("/api/stats").get_json()
    assert stats["buses_inside"] == 0
    state = db.bus_states.find_one({"bus_number": "BUS-001"})
    assert state["direction"] == "OUT"


def test_bus_states_backfills_from_existing_events(db, config):
    from backend.services import compute_stats, sync_bus_states_if_needed

    now = naive_now()
    db.events.insert_one({
        "bus_number": "BUS-BACKFILL",
        "direction": "IN",
        "gate": "Gate 1",
        "camera_id": "cam-1",
        "confidence": 0.9,
        "timestamp": now - timedelta(minutes=10),
        "created_at": now,
        "flag_reasons": [],
        "flagged": False,
    })
    assert db.bus_states.count_documents({}) == 0
    assert sync_bus_states_if_needed(db) == 1
    stats = compute_stats(db, config)
    assert stats["buses_inside"] == 1
    assert stats["inside_buses"][0]["bus_number"] == "BUS-BACKFILL"


def test_compute_stats_cache_invalidated_on_ingest(client, db, users):
    from backend.app import create_app
    from backend.tests.conftest import build_config

    app = create_app(build_config(stats_cache_seconds=30), database_engine=db.engine)
    app.config.update(TESTING=True)
    test_client = app.test_client()
    register_bus(test_client, users)
    login_head_admin(test_client, users)

    assert test_client.get("/api/stats").get_json()["buses_inside"] == 0
    assert post_event(test_client, event_payload(direction="IN")).status_code == 201
    assert test_client.get("/api/stats").get_json()["buses_inside"] == 1


def test_bus_states_duplicate_key_retry_then_ignore_when_newer(db, monkeypatch):
    from sqlalchemy.exc import IntegrityError

    now = naive_now()
    newer_ts = now - timedelta(minutes=1)
    older_ts = now - timedelta(minutes=30)

    db.upsert_bus_state({
        "bus_number": "BUS-RACE",
        "direction": "OUT",
        "last_timestamp": newer_ts,
        "last_event_id": "000000000000000000000002",
        "gate": "Gate 1",
        "camera_id": "cam-1",
        "demo": False,
        "updated_at": now,
    })

    # Simulate an IntegrityError on the initial UPSERT, forcing the fallback UPDATE path.
    orig_begin = db.engine.begin
    calls = [0]

    class FakeConn:
        def __init__(self, real_ctx):
            self._real_ctx = real_ctx
            self._conn = None

        def __enter__(self):
            self._conn = self._real_ctx.__enter__()
            return self

        def __exit__(self, *args):
            return self._real_ctx.__exit__(*args)

        def execute(self, stmt, *args, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                raise IntegrityError("duplicate", {}, Exception("unique violation"))
            return self._conn.execute(stmt, *args, **kwargs)

    monkeypatch.setattr(db.engine, "begin", lambda: FakeConn(orig_begin()))
    db.upsert_bus_state({
        "bus_number": "BUS-RACE",
        "direction": "IN",
        "last_timestamp": older_ts,
        "last_event_id": "000000000000000000000001",
        "gate": "Gate 1",
        "camera_id": "cam-1",
        "demo": False,
        "updated_at": now,
    })
    assert calls[0] == 2
    state = db.bus_states.find_one({"bus_number": "BUS-RACE"})
    assert state["direction"] == "OUT"
    assert state["last_timestamp"] == newer_ts


def test_bus_states_ttl_index_only_when_retention_positive(db):
    from backend.services import purge_expired_records
    from backend.tests.conftest import build_config

    now = naive_now()
    old_ts = now - timedelta(days=400)
    db.events.insert_one({
        "bus_number": "BUS-OLD",
        "direction": "IN",
        "gate": "Gate 1",
        "camera_id": "cam-1",
        "confidence": 0.9,
        "timestamp": old_ts,
        "created_at": old_ts,
        "flag_reasons": [],
        "flagged": False,
    })
    db.upsert_bus_state({
        "bus_number": "BUS-OLD",
        "direction": "IN",
        "last_timestamp": old_ts,
        "last_event_id": "000000000000000000000001",
        "gate": "Gate 1",
        "camera_id": "cam-1",
        "demo": False,
        "updated_at": old_ts,
    })

    # Retention disabled (0) must never purge.
    disabled = purge_expired_records(db, build_config(event_retention_days=0))
    assert disabled == {"events": 0, "bus_states": 0}
    assert db.events.count_documents({}) == 1
    assert db.bus_states.count_documents({}) == 1

    # Retention positive purges expired events and bus_states.
    enabled = purge_expired_records(db, build_config(event_retention_days=365))
    assert enabled == {"events": 1, "bus_states": 1}
    assert db.events.count_documents({}) == 0
    assert db.bus_states.count_documents({}) == 0


def test_manage_states_cli_rebuild_reconstructs_states(db, config, capsys):
    from backend.manage_states import _execute

    now = naive_now()
    db.events.insert_one({
        "bus_number": "BUS-CLI",
        "direction": "IN",
        "gate": "Gate 1",
        "camera_id": "cam-1",
        "confidence": 0.9,
        "timestamp": now - timedelta(minutes=5),
        "created_at": now,
        "flag_reasons": [],
        "flagged": False,
    })
    assert _execute(db, config, "rebuild") == 0
    assert "1 bus" in capsys.readouterr().out
    assert db.bus_states.find_one({"bus_number": "BUS-CLI"})["direction"] == "IN"
    assert _execute(db, config, "purge") == 0
    assert "skipped" in capsys.readouterr().out.lower()


def test_event_idempotency_key_returns_200_deduplicated_and_omits_key_from_response_and_audit(client, db, users):
    register_bus(client, users)
    payload = event_payload(bus_number="BUS-001", direction="IN")
    headers = {"X-Device-Key": DEVICE_KEY, "X-Idempotency-Key": "gate1-abc-123"}

    first = client.post("/api/events", headers=headers, json=payload)
    assert first.status_code == 201
    first_body = first.get_json()
    assert "idempotency_key" not in first_body["event"]

    second = client.post("/api/events", headers=headers, json=payload)
    assert second.status_code == 200
    second_body = second.get_json()
    assert second_body["deduplicated"] is True
    assert second_body["event"]["id"] == first_body["event"]["id"]
    assert "idempotency_key" not in second_body["event"]
    assert db.events.count_documents({}) == 1

    # G-15: idempotency_key must also never leak into audit_logs.
    audit_entries = list(db.audit_logs.find({"action": "event_ingested"}))
    assert len(audit_entries) == 1
    assert "idempotency_key" not in (audit_entries[0].get("after") or {})


def test_event_invalid_idempotency_key_rejected_with_400(client):
    res_long = client.post(
        "/api/events",
        headers={"X-Device-Key": DEVICE_KEY, "X-Idempotency-Key": "k" * 129},
        json=event_payload(),
    )
    assert res_long.status_code == 400


def test_event_sliding_window_deduplicates_without_key_and_allows_opposite_direction(client, db, users):
    register_bus(client, users)
    ts = naive_now() - timedelta(minutes=2)
    first = post_event(client, event_payload(direction="IN", timestamp=ts.isoformat() + "Z"))
    assert first.status_code == 201

    dup = post_event(
        client,
        event_payload(direction="IN", timestamp=(ts + timedelta(seconds=10)).isoformat() + "Z"),
    )
    assert dup.status_code == 200
    assert dup.get_json()["deduplicated"] is True
    assert db.events.count_documents({}) == 1

    # Opposite direction within window is NOT deduplicated.
    out_ev = post_event(
        client,
        event_payload(direction="OUT", timestamp=(ts + timedelta(seconds=10)).isoformat() + "Z"),
    )
    assert out_ev.status_code == 201
    assert db.events.count_documents({}) == 2


def test_event_canonicalizes_plate_variant_via_plate_key(client, db, users):
    login_transport_office(client, users)
    assert (
        client.post("/api/buses", json={"bus_number": "TN-12-AB-1234", "capacity": 40}).status_code
        == 201
    )

    res = post_event(client, event_payload(bus_number="TN 12 AB 1234", direction="IN", confidence=0.95))
    assert res.status_code == 201
    event = res.get_json()["event"]
    assert event["bus_number"] == "TN-12-AB-1234"
    assert "unregistered_plate" not in event["flag_reasons"]
    assert db.bus_states.find_one({"bus_number": "TN-12-AB-1234"})["direction"] == "IN"
    assert db.bus_states.find_one({"bus_number": "TN 12 AB 1234"}) is None


def test_later_out_same_timestamp_tiebreaks_on_id(db, config):
    from backend.services import compute_flag_reasons

    db.buses.insert_one({"bus_number": "BUS-TIE", "plate_key": "BUSTIE", "capacity": 40, "demo": False})
    ts = naive_now() - timedelta(hours=15)
    db.events.insert_one({
        "_id": "000000000000000000000001",
        "bus_number": "BUS-TIE",
        "direction": "IN",
        "gate": "Gate 1",
        "camera_id": "cam-1",
        "confidence": 0.95,
        "timestamp": ts,
        "created_at": ts,
        "flag_reasons": [],
        "flagged": False,
    })
    # Same-timestamp OUT with strictly larger _id closes the prior IN.
    db.events.insert_one({
        "_id": "000000000000000000000002",
        "bus_number": "BUS-TIE",
        "direction": "OUT",
        "gate": "Gate 1",
        "camera_id": "cam-1",
        "confidence": 0.95,
        "timestamp": ts,
        "created_at": ts,
        "flag_reasons": [],
        "flagged": False,
    })
    later_in = {
        "bus_number": "BUS-TIE",
        "direction": "IN",
        "confidence": 0.95,
        "timestamp": naive_now(),
    }
    assert "long_overstay" not in compute_flag_reasons(db, later_in, config)


def test_detection_client_retries_with_stable_idempotency_key_on_503_and_stops_on_400():
    from backend.detection_client import post_event_with_retries

    class FakeResponse:
        def __init__(self, status_code, text=""):
            self.status_code = status_code
            self.text = text
            self.ok = 200 <= status_code < 300

    seen_keys = []
    responses = [FakeResponse(503, "busy"), FakeResponse(502, "bad gateway"), FakeResponse(201, "ok")]

    class FakeSession:
        def post(self, url, *, json, headers, timeout):
            seen_keys.append(headers["X-Idempotency-Key"])
            return responses.pop(0)

    res = post_event_with_retries(
        "https://transport.example.edu",
        "key-123",
        {"bus_number": "BUS-001"},
        max_retries=3,
        backoff_seconds=0,
        session=FakeSession(),
    )
    assert res.status_code == 201
    assert len(seen_keys) == 3
    assert len(set(seen_keys)) == 1

    # 400 is NOT retried.
    calls_400 = [0]

    class BadSession:
        def post(self, url, *, json, headers, timeout):
            calls_400[0] += 1
            return FakeResponse(400, "invalid")

    bad_res = post_event_with_retries(
        "https://transport.example.edu",
        "key-123",
        {"bus_number": "BUS-001"},
        max_retries=3,
        backoff_seconds=0,
        session=BadSession(),
    )
    assert bad_res.status_code == 400
    assert calls_400[0] == 1


def test_export_sets_truncation_headers_before_streaming_csv_and_xlsx(db, users):
    import io
    from openpyxl import load_workbook
    from backend.app import create_app
    from backend.auth import hash_password
    from backend.tests.conftest import HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD, build_config, login

    now = naive_now()
    db.events.insert_many([
        {
            "bus_number": f"BUS-{i:03d}",
            "direction": "IN" if i % 2 == 0 else "OUT",
            "gate": "Gate 1",
            "camera_id": "cam-1",
            "confidence": 0.9,
            "timestamp": now - timedelta(minutes=i),
            "created_at": now,
            "flag_reasons": [],
            "flagged": False,
        }
        for i in range(105)
    ])

    app = create_app(build_config(export_max_rows=100), database_engine=db.engine)
    app.config.update(TESTING=True)
    client = app.test_client()
    login(client, HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD)

    csv_stream = client.get("/api/export/events.csv", buffered=False)
    assert csv_stream.status_code == 200
    # G-12: headers must already be set before consuming the stream.
    assert csv_stream.headers["X-Export-Truncated"] == "true"
    assert csv_stream.headers["X-Export-Limit"] == "100"
    csv_lines = [line for line in csv_stream.get_data(as_text=True).splitlines() if line]
    assert len(csv_lines) == 101  # 1 header + 100 rows

    xlsx_res = client.get("/api/export/events.xlsx")
    assert xlsx_res.status_code == 200
    assert xlsx_res.headers["X-Export-Truncated"] == "true"
    assert xlsx_res.headers["X-Export-Limit"] == "100"
    wb = load_workbook(io.BytesIO(xlsx_res.data))
    ws = wb["Bus Events"]
    assert ws.freeze_panes == "A2"
    assert ws.auto_filter.ref == "A1:H101"
    assert ws.max_row == 101

    # Filtered subset under limit reports X-Export-Truncated: false.
    under_res = client.get("/api/export/events.csv?bus_number=BUS-001", buffered=False)
    assert under_res.headers["X-Export-Truncated"] == "false"
    under_res.close()


def test_analytics_sql_aggregation_buckets_by_local_hour_and_gate(client, db, users):
    now = naive_now().replace(minute=15, second=0, microsecond=0)
    db.events.insert_many([
        {
            "bus_number": "BUS-A",
            "direction": "IN",
            "gate": "Gate 1",
            "camera_id": "cam-1",
            "confidence": 0.9,
            "timestamp": now,
            "created_at": now,
            "flag_reasons": [],
            "flagged": False,
        },
        {
            "bus_number": "BUS-A",
            "direction": "IN",
            "gate": "Gate 1",
            "camera_id": "cam-1",
            "confidence": 0.9,
            "timestamp": now - timedelta(hours=1),
            "created_at": now,
            "flag_reasons": [],
            "flagged": False,
        },
        {
            "bus_number": "BUS-B",
            "direction": "IN",
            "gate": "Gate 2",
            "camera_id": "cam-2",
            "confidence": 0.9,
            "timestamp": now,
            "created_at": now,
            "flag_reasons": [],
            "flagged": False,
        },
    ])
    login_head_admin(client, users)
    res = client.get("/api/analytics?hours=24&direction=IN").get_json()
    assert res["totals"] == {"events": 3, "gates": 2, "buses": 2}
    assert res["per_gate"][0] == {"gate": "Gate 1", "count": 2}
    assert res["per_bus"][0] == {"bus_number": "BUS-A", "count": 2}
    assert sum(item["count"] for item in res["per_hour"]) == 3


def test_delete_bus_with_assigned_driver_returns_409_and_succeeds_after_reassignment(client, db, users):
    bus_a = register_bus(client, users, "BUS-DEL-1")
    bus_b = register_bus(client, users, "BUS-DEL-2")
    login_transport_office(client, users)
    drv = client.post(
        "/api/drivers",
        json={"name": "Assigned Driver", "bus_number": "BUS-DEL-1"},
    )
    assert drv.status_code == 201
    drv_id = drv.get_json()["driver"]["id"]

    blocked = client.delete(f"/api/buses/{bus_a['id']}")
    assert blocked.status_code == 409

    # Reassign driver to another bus, then deletion succeeds.
    assert client.put(f"/api/drivers/{drv_id}", json={"bus_number": "BUS-DEL-2"}).status_code == 200
    assert client.delete(f"/api/buses/{bus_a['id']}").status_code == 200
    assert db.buses.find_one({"_id": bus_b["id"]}) is not None


def test_rename_bus_cascades_to_assigned_drivers_and_bus_states(client, db, users):
    bus = register_bus(client, users, "BUS-OLD-NAME")
    post_event(client, event_payload(bus_number="BUS-OLD-NAME", direction="IN"))
    login_transport_office(client, users)
    drv = client.post(
        "/api/drivers",
        json={"name": "Cascade Driver", "bus_number": "BUS-OLD-NAME"},
    )
    assert drv.status_code == 201
    drv_id = drv.get_json()["driver"]["id"]

    renamed = client.put(f"/api/buses/{bus['id']}", json={"bus_number": "BUS-NEW-NAME"})
    assert renamed.status_code == 200
    assert db.drivers.find_one({"_id": drv_id})["bus_number"] == "BUS-NEW-NAME"
    assert db.bus_states.find_one({"bus_number": "BUS-NEW-NAME"})["direction"] == "IN"
    assert db.bus_states.find_one({"bus_number": "BUS-OLD-NAME"}) is None
