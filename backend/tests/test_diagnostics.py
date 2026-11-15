"""The error log and the one-block report.

The gate PC hides its console, so these two things are the only way a failure
reaches the person who can fix it: the blocks written to
`<data>/logs/errors.log`, and `VisionAI.exe --report` / `scripts/gate_report.py`
turning them into text that can be pasted. The redaction tests are the
important ones — that text leaves the building.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from backend import diagnostics
from backend.report import build_report


@pytest.fixture(autouse=True)
def isolated_data_dir(monkeypatch, tmp_path: Path):
    """Every test writes to its own data dir, never to the developer's home."""
    monkeypatch.setenv("VISION_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("VISION_ERROR_LOG", raising=False)
    return tmp_path


# ------------------------------------------------------------------ redaction
@pytest.mark.parametrize(
    "text,secret",
    [
        ("rtsp://admin:hunter2@10.0.0.5:554/Streaming/Channels/101", "hunter2"),
        ("http://user:s3cr3t@192.168.1.64/ISAPI/Streaming/channels/101/picture", "s3cr3t"),
        ("VISION_DEVICE_KEY=device-key-abc123", "device-key-abc123"),
        ("password=SuperSecret1", "SuperSecret1"),
        ("Authorization: Bearer abcdef1234567890", "abcdef1234567890"),
        ("token: eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U", "eyJhbGciOiJIUzI1NiJ9"),
        ("hash $argon2id$v=19$m=65536,t=3,p=4$c2FsdA$aGFzaA", "argon2id$v=19"),
    ],
)
def test_credentials_never_reach_the_report(text: str, secret: str) -> None:
    cleaned = diagnostics.redact(text)
    assert secret not in cleaned
    assert "***" in cleaned or "<" in cleaned


def test_an_rtsp_password_is_masked_but_the_host_survives() -> None:
    cleaned = diagnostics.redact("rtsp://admin:hunter2@10.0.0.5:554/s")
    assert cleaned == "rtsp://admin:***@10.0.0.5:554/s"


def test_ordinary_text_is_left_alone() -> None:
    assert diagnostics.redact("frame 1280x720 sharpness 93") == "frame 1280x720 sharpness 93"


# ---------------------------------------------------------------- error blocks
def test_an_error_is_written_with_a_reference_and_a_traceback() -> None:
    try:
        raise RuntimeError("detector exploded")
    except RuntimeError as exc:
        ref = diagnostics.log_error("unhandled", "RuntimeError: detector exploded", exc=exc)

    text = diagnostics.error_log_path().read_text()
    assert ref in text
    assert "UNHANDLED" in text
    assert "message  : RuntimeError: detector exploded" in text
    assert "Traceback" in text
    assert "detector exploded" in text


def test_a_scan_failure_is_written_with_its_measurements() -> None:
    diagnostics.log_scan(
        {
            "reason": "unreadable",
            "advice": "Sticker detected at 0.85 but the OCR read no text.",
            "frame": {"width": 1280, "height": 720, "sharpness": 93.0, "brightness": 142.0, "tiles": 2},
            "stages": [{"name": "vehicle", "skipped": "model_missing"}],
        },
        source="device",
    )

    text = diagnostics.read_errors(kinds=("SCAN",))
    assert "reason   : unreadable" in text
    assert "sharpness 93.0" in text and "brightness 142.0" in text
    assert "tiles 2" in text
    assert "vehicle=model_missing" in text
    assert "OCR read no text" in text


def test_a_successful_scan_is_not_recorded() -> None:
    diagnostics.log_scan({"reason": "ok", "bus_number": "57"})
    assert not diagnostics.error_log_path().exists()


def test_the_newest_blocks_come_last_and_can_be_limited() -> None:
    for index in range(5):
        diagnostics.log_error("http", f"failure {index}")
    text = diagnostics.read_errors(limit=2)
    assert "failure 3" in text and "failure 4" in text
    assert "failure 2" not in text


def test_kinds_can_be_filtered() -> None:
    diagnostics.log_error("unhandled", "an exception")
    diagnostics.log_scan({"reason": "no_detection", "frame": {"width": 640, "height": 480}})
    assert "an exception" not in diagnostics.read_errors(kinds=("SCAN",))
    assert "no_detection" not in diagnostics.read_errors(exclude=("SCAN",))


def test_the_log_rotates_instead_of_growing_forever() -> None:
    path = diagnostics.error_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x" * (diagnostics.ERROR_LOG_MAX_BYTES + 10))

    diagnostics.log_error("http", "after rotation")

    assert (path.parent / "errors.log.1").exists()
    assert diagnostics.error_log_path().stat().st_size < 10_000


def test_logging_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setenv("VISION_ERROR_LOG", "false")
    ref = diagnostics.log_error("http", "not written")
    assert ref  # the caller still gets a reference
    assert not diagnostics.error_log_path().exists()


def test_a_missing_log_reads_as_empty_rather_than_raising() -> None:
    assert diagnostics.read_errors() == ""
    assert diagnostics.summary()["blocks"] == 0


def test_clearing_reports_what_went_away() -> None:
    diagnostics.log_error("http", "one")
    diagnostics.log_error("http", "two")
    assert diagnostics.clear() == 2
    assert diagnostics.read_errors() == ""


# -------------------------------------------------------------------- report
def test_the_report_has_every_section_and_leaks_nothing(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "never-print-me")
    monkeypatch.setenv("CAMERA_SOURCE", "rtsp://admin:hunter2@10.0.0.5:554/s")
    monkeypatch.setenv("VISION_STICKER_UPSCALE", "3")
    diagnostics.log_error("unhandled", "CameraSourceError: rtsp://admin:hunter2@10.0.0.5/s is down")

    text = build_report(errors=5, scans=5, log_lines=5)

    for section in (
        "1. Configuration",
        "2. Vision stack",
        "3. Camera",
        "4. Model files",
        "5. Preflight",
        "6. Recent errors",
        "7. Recent scans",
        "8. portal.log",
        "===== end of report =====",
    ):
        assert section in text
    assert "never-print-me" not in text
    assert "hunter2" not in text
    assert "VISION_STICKER_UPSCALE=3" in text
    assert "CameraSourceError" in text


def test_the_report_still_appears_when_everything_is_missing() -> None:
    text = build_report(errors=5, scans=5, log_lines=5)
    assert "===== VisionAI gate report =====" in text
    assert "no errors recorded" in text or "no gate.env" in text


def test_the_report_names_the_gate_config_file(tmp_path: Path, monkeypatch) -> None:
    config = tmp_path / "gate.env"
    config.write_text("VISION_TILES=auto\nSECRET_KEY=hidden\nCAMERA_SOURCE=usb:0\n")
    monkeypatch.setenv("VISION_TILES", "auto")
    text = build_report(errors=1, scans=1, log_lines=1)
    assert "VISION_TILES=auto" in text
    assert "CAMERA_SOURCE=usb:0" in text
    assert "hidden" not in text


# ------------------------------------------------------- the portal writes them
def test_an_unhandled_exception_becomes_a_reference_not_a_blank_page(
    client, users, monkeypatch
) -> None:
    import backend.app as app_module
    from backend.tests.conftest import login_head_admin

    def explode():
        raise RuntimeError("vision status exploded")

    monkeypatch.setattr(app_module, "vision_status", explode)
    login_head_admin(client, users)
    response = client.get("/api/detection/status")

    assert response.status_code == 500
    payload = response.get_json()
    assert payload["error"] == "An unexpected server error occurred"
    assert payload["ref"]
    logged = diagnostics.read_errors()
    assert payload["ref"] in logged
    assert "vision status exploded" in logged


def test_a_missing_page_is_not_an_error(client) -> None:
    client.get("/no-such-page")
    assert diagnostics.read_errors() == ""


def test_a_failed_scan_is_recorded_through_the_api(client, users, monkeypatch, tmp_path: Path) -> None:
    import backend.app as app_module
    from backend.tests.conftest import DEVICE_KEY, login_head_admin
    from backend.vision import DetectionResult

    PIL = pytest.importorskip("PIL.Image")
    monkeypatch.setattr(
        app_module,
        "detect",
        lambda image, stages=None: DetectionResult(
            frame_width=image.width,
            frame_height=image.height,
            frame_sharpness=93.0,
            frame_brightness=142.0,
            tiles=1,
            reason="unreadable",
            advice="Sticker detected at 0.85 but the OCR read no text.",
        ),
    )
    login_head_admin(client, users)
    buffer = io.BytesIO()
    PIL.new("RGB", (320, 240), (150, 150, 150)).save(buffer, format="JPEG")
    client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(buffer.getvalue()), "frame.jpg")},
        content_type="multipart/form-data",
        headers={"X-Device-Key": DEVICE_KEY},
    )

    text = diagnostics.read_errors(kinds=("SCAN",))
    assert "reason   : unreadable" in text
    assert "sharpness 93.0" in text
