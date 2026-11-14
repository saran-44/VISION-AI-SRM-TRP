"""Tests for the gate installation: its own database, its own camera, its own preflight.

The gate PC is the one deployment that runs the whole portal on Windows with a
file database and a camera the operator configures, so these are the tests that
stand between "it works on the laptop" and "it works at the gate".
"""

from __future__ import annotations

import io
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from backend.config import Config
from backend.frame_source import FrameSourceError, mask_source, snapshot, source_kind

DEVICE_KEY = "gate-device-api-key"


def gate_config(tmp_path: Path, **overrides) -> Config:
    base = Config(
        environment="gate",
        debug=False,
        testing=False,
        database_url=f"sqlite:///{(tmp_path / 'gate.db').as_posix()}",
        jwt_secret="gate-test-secret-" + "z" * 32,
        jwt_ttl_minutes=15,
        cookie_secure=False,
        legacy_password_login_enabled=True,
        firebase_auth_enabled=False,
        rate_limit_enabled=False,
        device_api_keys=(DEVICE_KEY,),
    )
    return replace(base, **overrides) if overrides else base


# ------------------------------------------------------------------ config
def test_the_gate_install_accepts_a_file_database(tmp_path: Path) -> None:
    gate_config(tmp_path).validate()


def test_production_still_refuses_sqlite(tmp_path: Path) -> None:
    config = gate_config(tmp_path, environment="production", legacy_password_login_enabled=False)
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        config.validate()


def test_a_laptop_cannot_quietly_use_a_sqlite_file(tmp_path: Path) -> None:
    """Only the gate may keep rows on disk: anywhere else it is a mistake."""
    config = gate_config(tmp_path, environment="development")
    with pytest.raises(RuntimeError, match="ENVIRONMENT=gate"):
        config.validate()


def test_the_gate_refuses_demo_mode(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        gate_config(tmp_path, demo_mode=True).validate()


def test_the_gate_needs_a_way_to_sign_in(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no way to sign in"):
        gate_config(tmp_path, legacy_password_login_enabled=False, firebase_auth_enabled=False).validate()


def test_a_bad_camera_source_is_refused_without_echoing_its_password(tmp_path: Path) -> None:
    config = gate_config(tmp_path, camera_source="ftp://admin:hunter2@camera/snap.jpg")
    with pytest.raises(RuntimeError) as caught:
        config.validate()
    assert "hunter2" not in str(caught.value)
    assert "CAMERA_SOURCE" in str(caught.value)


# ---------------------------------------------------------------- database
def test_the_gate_database_creates_its_schema_and_keeps_its_rows(tmp_path: Path) -> None:
    from backend.app import create_app

    from backend.services import naive_now

    config = gate_config(tmp_path)
    app = create_app(config)
    now = naive_now()
    app.extensions["transport_db"].buses.insert_one(
        {"_id": "a" * 24, "bus_number": "57", "created_at": now, "updated_at": now}
    )

    assert (tmp_path / "gate.db").exists()
    reopened = create_app(gate_config(tmp_path))
    assert reopened.extensions["transport_db"].buses.count_documents({}) == 1


def test_the_gate_database_runs_in_wal_mode(tmp_path: Path) -> None:
    """Readers must not block behind the write an event performs."""
    from backend.db import create_database_engine

    engine = create_database_engine(f"sqlite:///{(tmp_path / 'gate.db').as_posix()}")
    with engine.connect() as connection:
        from sqlalchemy import text

        assert connection.execute(text("PRAGMA journal_mode")).scalar() == "wal"


def test_automatic_schema_creation_is_still_refused_for_an_unexpected_file(tmp_path: Path) -> None:
    from backend.db import create_database_engine, initialize_preview

    engine = create_database_engine(f"sqlite:///{(tmp_path / 'gate.db').as_posix()}")
    with pytest.raises(RuntimeError, match="in-memory"):
        initialize_preview(engine)


# ------------------------------------------------------------ frame source
def test_the_password_never_appears_in_a_masked_source() -> None:
    masked = mask_source("rtsp://admin:hunter2@10.0.0.5:554/Streaming/Channels/101")
    assert "hunter2" not in masked
    assert masked.startswith("rtsp://admin:***@10.0.0.5")


@pytest.mark.parametrize(
    "source,kind",
    [
        ("http://192.168.1.64/snap.jpg", "http"),
        ("https://camera.local/axis-cgi/jpg/image.cgi", "http"),
        ("rtsp://192.168.1.64:554/stream", "rtsp"),
        ("usb:0", "usb"),
        ("1", "usb"),
        ("", ""),
        ("ftp://camera/snap", ""),
    ],
)
def test_the_source_shape_is_recognised(source: str, kind: str) -> None:
    assert source_kind(source) == kind


def test_an_unconfigured_camera_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAMERA_SOURCE", raising=False)
    with pytest.raises(FrameSourceError, match="No camera is configured"):
        snapshot()


@pytest.fixture
def camera_server():
    """A stand-in for a camera's JPEG snapshot endpoint."""
    PIL = pytest.importorskip("PIL.Image")

    buffer = io.BytesIO()
    PIL.new("RGB", (320, 240), (90, 90, 90)).save(buffer, format="JPEG", quality=80)
    jpeg = buffer.getvalue()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            if self.path == "/snapshot.jpg":
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.end_headers()
                self.wfile.write(jpeg)
            elif self.path == "/login":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"<html>sign in</html>")
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *_args):  # keep pytest output clean
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_a_snapshot_is_fetched_and_measured(camera_server: str) -> None:
    frame = snapshot(f"{camera_server}/snapshot.jpg")
    assert frame.content_type == "image/jpeg"
    assert (frame.width, frame.height) == (320, 240)


def test_an_html_login_page_is_not_mistaken_for_a_frame(camera_server: str) -> None:
    with pytest.raises(FrameSourceError, match="not an image"):
        snapshot(f"{camera_server}/login")


def test_a_wrong_snapshot_path_explains_the_404(camera_server: str) -> None:
    with pytest.raises(FrameSourceError, match="429|404|snapshot path is wrong"):
        snapshot(f"{camera_server}/missing.jpg")


def test_an_unreachable_camera_is_a_frame_source_error() -> None:
    with pytest.raises(FrameSourceError, match="Could not reach"):
        snapshot("http://127.0.0.1:9/snapshot.jpg", timeout=1)


# ------------------------------------------------------------- the routes
def _client(config: Config):
    from backend.app import create_app

    return create_app(config).test_client()


def test_the_snapshot_route_returns_the_camera_frame(tmp_path: Path, camera_server: str) -> None:
    client = _client(gate_config(tmp_path, camera_source=f"{camera_server}/snapshot.jpg"))
    response = client.get("/api/camera/snapshot", headers={"X-Device-Key": DEVICE_KEY})
    assert response.status_code == 200
    assert response.mimetype == "image/jpeg"
    assert response.headers["X-Frame-Size"] == "320x240"
    assert "hunter2" not in response.headers.get("X-Camera-Source", "")


def test_the_snapshot_route_without_a_camera_is_explicit(tmp_path: Path) -> None:
    client = _client(gate_config(tmp_path))
    response = client.get("/api/camera/snapshot", headers={"X-Device-Key": DEVICE_KEY})
    assert response.status_code == 400
    assert response.get_json()["code"] == "camera_not_configured"


def test_a_failing_camera_is_a_502_not_a_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.app as app_module

    def boom(*_args, **_kwargs):
        raise FrameSourceError("camera refused the connection")

    monkeypatch.setattr(app_module, "camera_snapshot_frame", boom)
    client = _client(gate_config(tmp_path, camera_source="http://camera.local/snap.jpg"))
    response = client.get("/api/camera/snapshot", headers={"X-Device-Key": DEVICE_KEY})
    assert response.status_code == 502
    assert response.get_json()["code"] == "camera_unavailable"


def test_a_scan_can_capture_from_the_gate_camera(tmp_path: Path, camera_server: str) -> None:
    """`{"capture": true}` grabs the frame and scans it in one call."""
    client = _client(gate_config(tmp_path, camera_source=f"{camera_server}/snapshot.jpg"))
    response = client.post(
        "/api/detection/scan", json={"capture": True}, headers={"X-Device-Key": DEVICE_KEY}
    )
    # No torch in this environment: the point is that the frame reached the
    # detector instead of the route rejecting the request for having no image.
    assert response.status_code in {200, 503}
    if response.status_code == 503:
        assert response.get_json()["code"] in {"vision_unavailable", "vision_local_agent_required"}


def test_the_gate_scan_failure_talks_about_this_pc(tmp_path: Path, camera_server: str) -> None:
    client = _client(gate_config(tmp_path, camera_source=f"{camera_server}/snapshot.jpg"))
    response = client.post(
        "/api/detection/scan", json={"capture": True}, headers={"X-Device-Key": DEVICE_KEY}
    )
    if response.status_code != 503:
        pytest.skip("the vision stack is installed here, so there is no failure to describe")
    payload = response.get_json()
    assert payload["code"] == "vision_unavailable"
    assert "VisionAI.exe --check" in payload["error"]
    assert "Render" not in payload["error"]


# --------------------------------------------------------------- preflight
def test_the_preflight_checks_the_gate_it_is_configured_for(tmp_path: Path) -> None:
    from backend.preflight import FAIL, PASS, format_report, run

    report = run(deep=False, port=8099, data_dir=tmp_path, config=gate_config(tmp_path))
    statuses = {check.name: check.status for check in report.checks}

    assert statuses["environment"] == PASS
    assert statuses["data folder"] == PASS
    assert statuses["database"] == PASS
    assert statuses["database write"] == PASS
    assert statuses["frontend"] == PASS
    assert statuses["camera"] != FAIL  # a warning when none is configured
    text = format_report(report)
    assert "VisionAI gate preflight" in text
    assert "READY" in text


def test_the_preflight_reports_an_unusable_camera_as_a_failure(tmp_path: Path) -> None:
    from backend.preflight import FAIL, run

    config = gate_config(tmp_path, camera_source="http://127.0.0.1:9/snapshot.jpg")
    report = run(deep=False, port=8099, data_dir=tmp_path, config=config)
    camera = next(check for check in report.checks if check.name == "camera")
    assert camera.status == FAIL
    assert "Could not reach" in camera.detail


def test_the_preflight_never_reports_a_skipped_check_as_ready(tmp_path: Path) -> None:
    from backend.preflight import SKIP, run

    report = run(deep=False, port=8099, data_dir=tmp_path, config=gate_config(tmp_path))
    detector = next(check for check in report.checks if check.name == "detector")
    assert detector.status == SKIP
    assert "--deep" in detector.detail
