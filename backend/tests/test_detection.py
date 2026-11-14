"""Tests for the sticker-detection endpoints and the Firebase config route."""

from __future__ import annotations

import base64
import io
from dataclasses import replace

import pytest

from backend.auth import hash_password
from backend.services import naive_now

from .conftest import (
    DEVICE_KEY,
    login,
    login_head_admin,
    login_transport_office,
)


def _png_bytes() -> bytes:
    """A tiny valid PNG, built without depending on Pillow in the test env."""
    # 1x1 transparent PNG
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk"
        "YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
    )


# --------------------------------------------------------------- status route


def test_detection_status_requires_authentication(client):
    response = client.get("/api/detection/status")
    assert response.status_code == 401


def test_detection_status_reports_model_and_ocr(client, users):
    login_head_admin(client, users)
    response = client.get("/api/detection/status")
    assert response.status_code == 200
    payload = response.get_json()
    assert "model_present" in payload
    assert "available" in payload
    assert "problems" in payload
    assert "classes" in payload


def test_detection_status_forbidden_for_transport_office(client, users):
    login_transport_office(client, users)
    response = client.get("/api/detection/status")
    assert response.status_code == 403


# ---------------------------------------------------------------- scan route


def test_scan_rejects_unauthenticated_requests(client):
    response = client.post("/api/detection/scan", data={"image": _png_bytes()})
    assert response.status_code == 401


def test_scan_requires_an_image(client, users):
    login_head_admin(client, users)
    response = client.post("/api/detection/scan", json={})
    assert response.status_code == 400
    assert "image" in response.get_json()["error"].lower()


def test_scan_rejects_a_malformed_body(client, users):
    login_head_admin(client, users)
    response = client.post("/api/detection/scan", data={"not_an_image": "x"})
    # The multipart branch found no "image" part.
    assert response.status_code == 400


def test_scan_with_device_key_is_accepted(client):
    """A device key authorises the scan; the vision stack may be unavailable."""
    response = client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(_png_bytes()), "frame.jpg")},
        headers={"X-Device-Key": DEVICE_KEY},
        content_type="multipart/form-data",
    )
    # 200 when the vision stack is present, 503 when it is not. Both are valid:
    # the request was authorised and the image was parsed.
    assert response.status_code in (200, 503)
    if response.status_code == 503:
        assert "error" in response.get_json()


def test_scan_with_a_bad_device_key_and_no_session_is_rejected(client):
    response = client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(_png_bytes()), "frame.jpg")},
        headers={"X-Device-Key": "wrong-key"},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401


def test_scan_forbidden_for_transport_office(client, users):
    login_transport_office(client, users)
    response = client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(_png_bytes()), "frame.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 403


def test_scan_is_recorded_in_the_audit_log(client, users, db):
    login_head_admin(client, users)
    client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(_png_bytes()), "frame.jpg")},
        content_type="multipart/form-data",
    )
    actions = [entry.get("action") for entry in db.audit_logs.find({})]
    # The attempt is always audited, whether the vision stack was available
    # (detection_scan) or not (detection_scan_failed).
    assert "detection_scan" in actions or "detection_scan_failed" in actions


# --------------------------------------------------------- firebase config


def test_firebase_config_is_public(client):
    response = client.get("/api/config/firebase")
    assert response.status_code == 200
    payload = response.get_json()
    assert "config" in payload
    assert "enabled" in payload
    assert "analytics" in payload


def test_firebase_config_is_disabled_without_environment_values(client):
    payload = client.get("/api/config/firebase").get_json()
    assert payload["enabled"] is False
    assert payload["config"] == {}


def test_firebase_config_exposes_the_public_subset(app, client):
    application = create_with_firebase(app)
    payload = application.test_client().get("/api/config/firebase").get_json()
    assert payload["enabled"] is True
    assert payload["projectId"] == "vision-ai-srmtrp"
    assert payload["analytics"] is True
    assert payload["config"]["authDomain"] == "vision-ai-srmtrp.firebaseapp.com"
    # The private key must never be exposed.
    assert "private_key" not in payload["config"]


def create_with_firebase(app):
    """Rebuild the app with a Firebase configuration present."""
    from backend.app import create_app

    config = replace(
        app.config["TRANSPORT_CONFIG"],
        firebase={
            "apiKey": "test-api-key",
            "authDomain": "vision-ai-srmtrp.firebaseapp.com",
            "projectId": "vision-ai-srmtrp",
            "storageBucket": "vision-ai-srmtrp.firebasestorage.app",
            "messagingSenderId": "235811571442",
            "appId": "1:235811571442:web:342e488e0ac2ee75b0f26b",
            "measurementId": "G-S4HS9TGV4H",
        },
        firebase_project_id="vision-ai-srmtrp",
    )
    application = create_app(config)
    application.config.update(TESTING=True)
    return application


# ------------------------------------------------------------- stream proxy


def test_stream_proxy_requires_authentication(client):
    response = client.get("/api/stream/gate-1-entry")
    assert response.status_code == 401


def test_stream_proxy_returns_404_for_an_unknown_camera(client, users):
    login_head_admin(client, users)
    response = client.get("/api/stream/not-a-camera")
    assert response.status_code == 404


def test_stream_proxy_rejects_hls_cameras(client, users):
    from backend.app import create_app

    config = replace(
        client.application.config["TRANSPORT_CONFIG"],
        camera_streams={
            "gate-1-entry": {
                "type": "hls",
                "url": "https://example.edu/stream.m3u8",
                "label": "Gate 1 Entry",
            }
        },
    )
    application = create_app(config)
    application.config.update(TESTING=True)
    application.extensions["transport_db"].users.insert_many(
        [
            {
                "email": "stream.admin@example.invalid",
                "password_hash": hash_password("StreamAdmin123!"),
                "role": "head_admin",
                "active": True,
                "created_at": naive_now(),
            }
        ]
    )
    stream_client = application.test_client()
    login(stream_client, "stream.admin@example.invalid", "StreamAdmin123!")
    response = stream_client.get("/api/stream/gate-1-entry")
    assert response.status_code == 415


# ------------------------------------------------------------ camera config


def test_camera_config_reports_the_supported_sources(client, users):
    login_head_admin(client, users)
    payload = client.get("/api/config").get_json()
    support = payload["camera_support"]
    assert support["browser_camera"] is True
    assert support["hls"] is True
    assert support["mjpeg"] is True
    assert support["rtsp"] == "gateway_required"
    assert "gateway" in support["notes"].lower()


def test_config_parser_accepts_rtsp_but_rejects_embedded_credentials():
    from backend.config import _parse_camera_streams

    parsed = _parse_camera_streams(
        '{"cam": {"type": "rtsp", "url": "rtsp://192.168.1.64:554/stream", "label": "Cam"}}'
    )
    assert parsed["cam"]["type"] == "rtsp"

    with pytest.raises(ValueError):
        _parse_camera_streams(
            '{"cam": {"type": "mjpeg", "url": "http://u:p@host/stream", "label": "Cam"}}'
        )


def test_scan_surfaces_reason_and_advice(client, users, monkeypatch):
    """The route must pass the detector's diagnosis through to the caller."""
    import backend.app as app_module
    import backend.vision as vision

    login_head_admin(client, users)

    result = vision.DetectionResult(reason="below_threshold", advice="lower VISION_CONFIDENCE")
    result.boxes_total = 2
    result.best_confidence = 0.21
    result.threshold = 0.35

    monkeypatch.setattr(app_module, "decode_image", lambda payload: object())
    monkeypatch.setattr(app_module, "detect", lambda image: result)

    response = client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(_png_bytes()), "frame.jpg")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["bus_number"] is None
    assert payload["reason"] == "below_threshold"
    assert payload["advice"] == "lower VISION_CONFIDENCE"
    assert payload["detection"]["boxes_total"] == 2
    assert payload["detection"]["best_confidence"] == pytest.approx(0.21)
