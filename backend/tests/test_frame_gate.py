"""Tests for the pre-inference quality gate and the sticker-crop upscale.

Both exist because of the same night-time scan: a 98 %-black frame cost 13
seconds of tiled inference and could not have produced a number, and a 50 px
sticker crop that the detector found at 0.85 was handed to the OCR unenlarged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.vision import (
    DetectionResult,
    VisionUnavailable,
    detect,
    frame_brightness,
    frame_problems,
    min_frame_brightness,
    min_frame_sharpness,
    quality_gate,
    sticker_upscale,
)

PIL = pytest.importorskip("PIL.Image")
pytest.importorskip("numpy")


def _dark_frame(width: int = 320, height: int = 240):
    """What the gate laptop actually sent at 23:30: a flat, black frame."""
    return PIL.new("RGB", (width, height), (5, 5, 5))


def _bright_sharp_frame(width: int = 320, height: int = 240):
    image = PIL.new("RGB", (width, height), (200, 200, 190))
    for x in range(0, width, 4):
        for y in range(0, height, 4):
            image.putpixel((x, y), (10, 10, 10))
    return image


# ------------------------------------------------------------------ brightness
def test_brightness_is_the_mean_luminance() -> None:
    assert frame_brightness(PIL.new("RGB", (10, 10), (0, 0, 0))) == 0.0
    assert frame_brightness(PIL.new("RGB", (10, 10), (255, 255, 255))) == 255.0


def test_a_black_frame_is_measured_as_dark() -> None:
    assert frame_brightness(_dark_frame()) < min_frame_brightness()


# ---------------------------------------------------------------- the gate
def test_the_gate_refuses_a_dark_frame_without_loading_a_model() -> None:
    result = detect(_dark_frame())

    assert result.reason == "frame_unusable"
    assert "too dark" in result.advice
    assert f"brightness {result.frame_brightness:.0f}" in result.advice
    # Measured, not guessed: the caller can see the number that caused it.
    assert result.frame_brightness is not None and result.frame_brightness < 12
    assert result.frame_width == 320 and result.frame_height == 240
    # Every stage is reported as skipped rather than silently missing.
    assert [stage.name for stage in result.stages]
    assert all(stage.skipped == "frame_unusable" for stage in result.stages)
    assert result.cascade == "none"
    assert result.candidates == []


def test_a_refusal_is_fast() -> None:
    result = detect(_dark_frame(1280, 720))
    assert result.reason == "frame_unusable"
    assert result.inference_ms < 2000  # tiled inference on this frame took ~13 s


def test_a_bright_sharp_frame_is_not_refused(monkeypatch) -> None:
    """With no checkpoint on this host, falling through means raising — which proves the gate let it past."""
    monkeypatch.setenv("VISION_QUALITY_GATE", "refuse")
    with pytest.raises(VisionUnavailable):
        detect(_bright_sharp_frame())


def test_the_gate_can_be_switched_off(monkeypatch) -> None:
    monkeypatch.setenv("VISION_QUALITY_GATE", "off")
    assert quality_gate() == "off"
    with pytest.raises(VisionUnavailable):
        detect(_dark_frame())


@pytest.mark.parametrize("raw,expected", [("refuse", "refuse"), ("off", "off"), ("0", "off"), ("", "refuse"), ("  OFF ", "off")])
def test_the_gate_setting_is_parsed_defensively(raw: str, expected: str, monkeypatch) -> None:
    monkeypatch.setenv("VISION_QUALITY_GATE", raw)
    assert quality_gate() == expected


def test_the_thresholds_are_configurable(monkeypatch) -> None:
    result = DetectionResult(frame_brightness=50.0, frame_sharpness=50.0)
    assert frame_problems(result) == []

    monkeypatch.setenv("VISION_MIN_BRIGHTNESS", "60")
    monkeypatch.setenv("VISION_MIN_SHARPNESS", "60")
    problems = frame_problems(result)
    assert len(problems) == 2
    assert "minimum 60" in problems[0]


def test_a_missing_measurement_is_not_a_refusal(monkeypatch) -> None:
    """`frame_sharpness()` returns None when numpy is absent; that must never block a scan."""
    monkeypatch.delenv("VISION_MIN_BRIGHTNESS", raising=False)
    monkeypatch.delenv("VISION_MIN_SHARPNESS", raising=False)
    assert frame_problems(DetectionResult()) == []


# ------------------------------------------------------- sticker crop upscale
@pytest.mark.parametrize(
    "raw,expected", [(None, 1), ("1", 1), ("3", 3), ("0", 1), ("99", 6), ("-2", 1), ("abc", 1)]
)
def test_the_sticker_upscale_setting_is_parsed_defensively(raw, expected, monkeypatch) -> None:
    if raw is None:
        monkeypatch.delenv("VISION_STICKER_UPSCALE", raising=False)
    else:
        monkeypatch.setenv("VISION_STICKER_UPSCALE", raw)
    assert sticker_upscale() == expected


def test_a_small_crop_is_enlarged_before_the_ocr(monkeypatch) -> None:
    """The real case: 50 px wide crop, 3× = 150 px, digits readable."""
    import backend.vision as vision

    seen: list[tuple[int, int]] = []

    def fake_read_text(crop, engine_name=None):
        seen.append(crop.size)
        return "57"

    monkeypatch.setattr(vision, "read_text", fake_read_text)
    monkeypatch.setenv("VISION_STICKER_UPSCALE", "3")

    image = PIL.new("RGB", (1280, 720), (90, 90, 90))
    rows = [(0.85, 0, [100, 100, 150, 120])]  # 50 × 20 px
    candidates = vision._ocr_rows(
        image, rows, {0: "sticker"}, threshold=0.3, limit=3, class_filter=0, upscale_factor=sticker_upscale()
    )

    assert seen == [(150, 60)]
    assert candidates[0].bus_number == "57"


def test_the_upscale_is_off_by_default(monkeypatch) -> None:
    import backend.vision as vision

    seen: list[tuple[int, int]] = []
    monkeypatch.delenv("VISION_STICKER_UPSCALE", raising=False)
    monkeypatch.setattr(vision, "read_text", lambda crop, engine_name=None: seen.append(crop.size) or "")

    image = PIL.new("RGB", (1280, 720), (90, 90, 90))
    vision._ocr_rows(
        image,
        [(0.85, 0, [100, 100, 150, 120])],
        {0: "sticker"},
        threshold=0.3,
        limit=3,
        class_filter=0,
        upscale_factor=sticker_upscale(),
    )
    assert seen == [(50, 20)]


def test_a_large_crop_is_not_enlarged(monkeypatch) -> None:
    """A crop the OCR can already read is handed over untouched."""
    import backend.vision as vision

    seen: list[tuple[int, int]] = []
    monkeypatch.setattr(vision, "read_text", lambda crop, engine_name=None: seen.append(crop.size) or "57")

    image = PIL.new("RGB", (1280, 720), (90, 90, 90))
    vision._ocr_rows(
        image,
        [(0.85, 0, [100, 100, 700, 300])],  # 600 px wide, above the 480 px skip
        {0: "sticker"},
        threshold=0.3,
        limit=3,
        class_filter=0,
        upscale_factor=3,
    )
    assert seen == [(600, 200)]


# ------------------------------------------------------------- the advice text
def test_the_unreadable_advice_names_the_sticker_upscale() -> None:
    import backend.vision as vision

    source = Path(vision.__file__).read_text()
    assert "VISION_STICKER_UPSCALE=3" in source
    # The old, wrong suggestion: crops come from the frame, not the tiles.
    assert "raise VISION_IMAGE_SIZE, " not in source


# ------------------------------------------------------------- the API answer
def _scan(client, image_bytes: bytes):
    import io

    from backend.tests.conftest import DEVICE_KEY

    return client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(image_bytes), "frame.jpg")},
        content_type="multipart/form-data",
        headers={"X-Device-Key": DEVICE_KEY},
    )


def _jpeg_bytes(width: int = 320, height: int = 240) -> bytes:
    import io

    buffer = io.BytesIO()
    _dark_frame(width, height).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_a_refused_scan_reports_the_measurements_and_saves_nothing(
    client, users, monkeypatch, tmp_path: Path
) -> None:
    import backend.app as app_module
    from backend.tests.conftest import login_head_admin

    monkeypatch.setenv("VISION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        app_module,
        "detect",
        lambda image, stages=None: DetectionResult(
            frame_width=image.width,
            frame_height=image.height,
            frame_sharpness=4.0,
            frame_brightness=6.5,
            tiles=2,
            reason="frame_unusable",
            advice="Refused before inference: the frame is too dark.",
        ),
    )
    login_head_admin(client, users)
    response = _scan(client, _jpeg_bytes())

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["reason"] == "frame_unusable"
    assert payload["frame"]["brightness"] == 6.5
    assert payload["frame"]["sharpness"] == 4.0
    assert payload["frame"]["saved"] is None
    assert not (tmp_path / "failed-frames").exists()
    assert "too dark" in payload["advice"]


def test_a_normal_failed_scan_still_reports_brightness(client, users, monkeypatch, tmp_path: Path) -> None:
    import backend.app as app_module
    from backend.tests.conftest import login_head_admin

    monkeypatch.setenv("VISION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        app_module,
        "detect",
        lambda image, stages=None: DetectionResult(
            frame_width=image.width,
            frame_height=image.height,
            frame_sharpness=180.0,
            frame_brightness=142.0,
            tiles=1,
            reason="no_detection",
        ),
    )
    login_head_admin(client, users)
    payload = _scan(client, _jpeg_bytes()).get_json()

    assert payload["frame"]["brightness"] == 142.0
    assert payload["frame"]["saved"] and Path(payload["frame"]["saved"]).exists()


def test_a_black_frame_is_refused_end_to_end_without_a_checkpoint(
    client, users, monkeypatch, tmp_path: Path
) -> None:
    """No monkeypatched `detect`: the real cascade, with no torch on this host.

    It answers 200 instead of 503 only because the refusal happens before the
    model is loaded — which is exactly the point of the gate.
    """
    from backend.tests.conftest import login_head_admin

    monkeypatch.setenv("VISION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VISION_QUALITY_GATE", "refuse")
    login_head_admin(client, users)
    response = _scan(client, _jpeg_bytes(640, 480))

    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    assert payload["reason"] == "frame_unusable"
    assert payload["frame"]["brightness"] is not None
    assert payload["frame"]["brightness"] < 20
    assert payload["frame"]["saved"] is None
    assert all(stage["skipped"] == "frame_unusable" for stage in payload["stages"])
