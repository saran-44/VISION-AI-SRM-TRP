"""Tests for the "no box at all" diagnostics: sharpness, tiling, saved frames.

The sentence this replaces ("fill more of the frame with it") was identical for
a lens that never focused and a sticker 15 px wide, so it could not be acted
on. These tests pin the measured replacement.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from backend.vision import (
    DetectionResult,
    PlateCandidate,
    box_iou,
    frame_sharpness,
    merge_rows,
    no_detection_advice,
    tile_boxes,
    tile_count,
)


# --------------------------------------------------------------- sharpness
def test_a_flat_frame_has_near_zero_sharpness() -> None:
    PIL = pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    assert frame_sharpness(PIL.new("RGB", (320, 240), (120, 120, 120))) < 1.0


def test_a_frame_with_edges_is_sharp() -> None:
    PIL = pytest.importorskip("PIL.Image")
    pytest.importorskip("numpy")
    image = PIL.new("RGB", (320, 240), (0, 0, 0))
    for x in range(0, 320, 8):
        for y in range(0, 240, 8):
            image.putpixel((x, y), (255, 255, 255))
    assert frame_sharpness(image) > 100


# ------------------------------------------------------------------ tiling
def test_four_tiles_cover_the_whole_frame_with_overlap() -> None:
    boxes = tile_boxes(1280, 720, 2)
    assert len(boxes) == 4
    assert boxes[0][0] == 0 and boxes[0][1] == 0
    assert boxes[-1][2] == 1280 and boxes[-1][3] == 720
    # Neighbouring tiles overlap, so a sticker on a seam is whole in one of them.
    assert box_iou(boxes[0], boxes[1]) > 0


def test_a_single_tile_is_the_whole_frame() -> None:
    assert tile_boxes(1280, 720, 1) == [(0, 0, 1280, 720)]


def test_tile_count_auto_uses_four_crops_for_a_gate_frame() -> None:
    assert tile_count(1280, 720, requested=0) == 2
    assert tile_count(320, 240, requested=0) == 1
    assert tile_count(1280, 720, requested=3) == 3


def test_the_same_sticker_found_in_two_tiles_is_one_box() -> None:
    rows = [
        (0.91, 1, [100, 100, 180, 160]),
        (0.88, 1, [104, 103, 182, 162]),  # the same sticker, seen in the next tile
        (0.40, 1, [600, 400, 640, 440]),  # a different sticker
    ]
    assert len(merge_rows(rows)) == 2


def test_two_classes_in_the_same_place_are_both_kept() -> None:
    rows = [(0.9, 0, [10, 10, 90, 90]), (0.8, 1, [10, 10, 90, 90])]
    assert len(merge_rows(rows)) == 2


# ------------------------------------------------------------------ advice
def test_the_advice_names_the_measured_frame() -> None:
    result = DetectionResult(
        frame_width=1280,
        frame_height=720,
        frame_sharpness=34.4,
        tiles=1,
        image_size=1280,
        threshold=0.25,
    )
    advice = no_detection_advice(result)

    assert "No box at all" in advice
    assert "1280×720" in advice
    assert "sharpness 34 (soft)" in advice
    assert "VISION_TILES=2" in advice


def test_the_advice_stops_suggesting_tiles_when_tiling_is_on() -> None:
    result = DetectionResult(frame_width=1280, frame_height=720, frame_sharpness=210.0, tiles=2, image_size=960)
    advice = no_detection_advice(result)

    assert "2×2 tiled at 960px" in advice
    assert "VISION_TILES=2" not in advice


# ------------------------------------------------------- the API response
def _jpeg(width: int = 640, height: int = 480) -> bytes:
    PIL = pytest.importorskip("PIL.Image")
    buffer = io.BytesIO()
    PIL.new("RGB", (width, height), (100, 110, 120)).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_the_scan_response_carries_the_frame_facts(client, users, monkeypatch, tmp_path: Path) -> None:
    import backend.app as app_module
    from backend.tests.conftest import DEVICE_KEY, login_head_admin

    from backend.vision import best_identification  # noqa: F401  (keeps the import path honest)

    monkeypatch.setenv("VISION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        app_module,
        "detect",
        lambda image, stages=None: DetectionResult(
            frame_width=image.width, frame_height=image.height, frame_sharpness=12.5, tiles=1
        ),
    )
    login_head_admin(client, users)
    response = client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(_jpeg()), "frame.jpg")},
        content_type="multipart/form-data",
        headers={"X-Device-Key": DEVICE_KEY},
    )

    assert response.status_code == 200, response.get_data(as_text=True)
    frame = response.get_json()["frame"]
    assert frame["width"] == 640 and frame["height"] == 480
    assert frame["sharpness"] == 12.5
    assert frame["tiles"] == 1
    assert frame["saved"] and Path(frame["saved"]).exists()
    assert Path(frame["saved"]).parent == tmp_path / "failed-frames"


def test_a_failed_scan_can_leave_no_frame_when_switched_off(client, users, monkeypatch, tmp_path: Path) -> None:
    import backend.app as app_module
    from backend.tests.conftest import DEVICE_KEY, login_head_admin

    monkeypatch.setenv("VISION_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("VISION_SAVE_FAILURES", "false")
    monkeypatch.setattr(
        app_module,
        "detect",
        lambda image, stages=None: DetectionResult(frame_width=image.width, frame_height=image.height),
    )
    login_head_admin(client, users)
    response = client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(_jpeg()), "frame.jpg")},
        content_type="multipart/form-data",
        headers={"X-Device-Key": DEVICE_KEY},
    )

    assert response.status_code == 200
    assert response.get_json()["frame"]["saved"] is None
    assert not (tmp_path / "failed-frames").exists()


def test_a_read_number_does_not_keep_a_frame(client, users, monkeypatch, tmp_path: Path) -> None:
    import backend.app as app_module
    from backend.tests.conftest import DEVICE_KEY, login_head_admin

    readable = DetectionResult(
        frame_width=640,
        frame_height=480,
        candidates=[PlateCandidate(bus_number="57", confidence=0.93, bbox=[10, 10, 90, 60])],
    )
    monkeypatch.setenv("VISION_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(app_module, "detect", lambda image, stages=None: readable)
    login_head_admin(client, users)
    response = client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(_jpeg()), "frame.jpg")},
        content_type="multipart/form-data",
        headers={"X-Device-Key": DEVICE_KEY},
    )

    assert response.status_code == 200
    assert response.get_json()["bus_number"] == "57"
    assert response.get_json()["frame"]["saved"] is None


def test_tiled_prediction_offsets_boxes_back_into_frame_coordinates() -> None:
    """A box found in tile (1,1) must be reported in frame coordinates."""
    numpy = pytest.importorskip("numpy")
    PIL = pytest.importorskip("PIL.Image")
    from backend.vision import _predict_tiled

    class Boxes:
        def __init__(self) -> None:
            self.conf = numpy.array([0.94])
            self.cls = numpy.array([1])
            self.xyxy = numpy.array([[10.0, 10.0, 60.0, 50.0]])

        def __len__(self) -> int:
            return 1

    class Result:
        def __init__(self) -> None:
            self.boxes = Boxes()

    class Model:
        def __init__(self) -> None:
            self.calls = 0

        def predict(self, source=None, conf=0.05, imgsz=960, verbose=False):
            self.calls += 1
            return [Result()]

    model = Model()
    rows = _predict_tiled(model, PIL.new("RGB", (1280, 720)), 960, 0.05, 2)

    assert model.calls == 4, "four tiles, four forward passes"
    assert len(rows) == 4, "the same offsets in different tiles are different boxes"
    # 1280 wide, 2 tiles, 25 % pad: the second column starts at x=480, so a box
    # at x=10 inside it is x=490 in the frame.
    xs = sorted({row[2][0] for row in rows})
    ys = sorted({row[2][1] for row in rows})
    assert xs == [10, 490], f"horizontal tile offsets were not applied: {xs}"
    assert ys == [10, 280], f"vertical tile offsets were not applied: {ys}"


@pytest.mark.parametrize(
    "raw,expected",
    [("", 1), ("1", 1), ("off", 1), ("auto", 0), ("2", 2), ("3", 3), ("9", 4), ("nonsense", 1)],
)
def test_the_tiling_setting_is_parsed_defensively(raw: str, expected: int, monkeypatch) -> None:
    from backend.vision import tile_settings

    monkeypatch.setenv("VISION_TILES", raw)
    assert tile_settings() == expected
