"""Scan outcomes must be distinguishable.

"Found no sticker in this frame" used to be printed for three different
situations: nothing detected, everything under the confidence threshold, and a
sticker found whose number the OCR could not read. These tests pin the three
answers so the Test Lab (and any device client) can tell them apart.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import backend.vision as vision


class _Scalar:
    def __init__(self, value):
        self._value = value

    def item(self):
        return self._value

    def tolist(self):
        return list(self._value)


class _Column:
    def __init__(self, values):
        self._values = values

    def __getitem__(self, index):
        return _Scalar(self._values[index])

    def tolist(self):
        return list(self._values)

    def __iter__(self):
        return iter(self._values)


class _Boxes:
    """Mimics the handful of tensor attributes `detect()` touches."""

    def __init__(self, rows):
        # rows: (confidence, class_id, [x1, y1, x2, y2])
        self._rows = rows
        self.conf = _Column([row[0] for row in rows])
        self.cls = _Column([row[1] for row in rows])
        self.xyxy = _Column([row[2] for row in rows])

    def __len__(self):
        return len(self._rows)


class _FakeModel:
    names = {0: "red circle", 1: "sticker"}

    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        return [SimpleNamespace(boxes=_Boxes(self._rows))]


class _FakeImage:
    width = 1280
    height = 720

    def crop(self, box):
        return SimpleNamespace(size=box)


@pytest.fixture
def no_ocr(monkeypatch):
    monkeypatch.setattr(vision, "read_text", lambda image, engine_name=None: "")
    monkeypatch.delenv("VISION_CONFIDENCE", raising=False)
    monkeypatch.delenv("VISION_IMAGE_SIZE", raising=False)


def test_no_boxes_at_all_says_no_detection(no_ocr):
    result = vision.detect(_FakeImage(), model=_FakeModel([]))

    assert result.reason == "no_detection"
    assert result.boxes_total == 0
    assert result.candidates == []
    assert "inspect_model" in result.advice


def test_boxes_below_the_threshold_report_their_best_confidence(no_ocr):
    model = _FakeModel([(0.22, 1, [100, 100, 180, 130]), (0.09, 1, [10, 10, 40, 30])])
    result = vision.detect(_FakeImage(), model=model)

    assert result.reason == "below_threshold"
    assert result.boxes_total == 2
    assert result.boxes_above_threshold == 0
    assert result.best_confidence == pytest.approx(0.22)
    assert result.threshold == pytest.approx(0.25)
    assert "VISION_CONFIDENCE" in result.advice


def test_sticker_found_but_unreadable_is_not_reported_as_missing(no_ocr):
    model = _FakeModel([(0.91, 1, [400, 300, 520, 360])])
    result = vision.detect(_FakeImage(), model=model)

    assert result.reason == "unreadable"
    assert len(result.candidates) == 1
    assert not result.candidates[0].bus_number
    assert "OCR read no text" in result.advice
    assert vision.best_candidate(result) is not None


def test_readable_plate_is_ok(monkeypatch):
    monkeypatch.setattr(vision, "read_text", lambda image, engine_name=None: "TN 12 AB 1234")
    model = _FakeModel([(0.88, 1, [400, 300, 520, 360])])
    result = vision.detect(_FakeImage(), model=model)

    assert result.reason == "ok"
    assert result.advice == ""
    assert vision.best_candidate(result).bus_number == "TN 12 AB 1234"


def test_low_confidence_probe_keeps_the_threshold_for_candidates(no_ocr):
    """Near-misses must be counted, not turned into candidates."""
    model = _FakeModel([(0.05, 1, [1, 1, 9, 9]), (0.80, 1, [400, 300, 520, 360])])
    result = vision.detect(_FakeImage(), model=model)

    assert model.calls[0]["conf"] == pytest.approx(0.05)
    assert model.calls[0]["imgsz"] == 960
    assert result.boxes_total == 2
    assert result.boxes_above_threshold == 1
    assert [c.confidence for c in result.candidates] == [pytest.approx(0.80)]


def test_scan_payload_carries_reason_and_advice(no_ocr):
    model = _FakeModel([(0.12, 0, [5, 5, 25, 25])])
    payload = vision.detect(_FakeImage(), model=model).to_dict()

    assert payload["reason"] == "below_threshold"
    assert payload["advice"]
    assert payload["image_size"] == 960
    assert payload["threshold"] == pytest.approx(0.25)
    assert payload["best_confidence"] == pytest.approx(0.12)


# ------------------------------------------------------- class-1-only filter
def test_only_the_sticker_class_reaches_the_ocr(monkeypatch):
    """class 0 = red circle, class 1 = sticker: only class 1 is OCR'd."""
    seen = []

    def fake_read_text(image, engine_name=None):
        seen.append(image)
        return "TN 12 AB 1234"

    monkeypatch.setattr(vision, "read_text", fake_read_text)
    monkeypatch.delenv("VISION_CONFIDENCE", raising=False)
    monkeypatch.delenv("VISION_STICKER_CLASS", raising=False)

    model = _FakeModel([
        (0.93, 1, [400, 300, 520, 360]),   # sticker  -> OCR
        (0.88, 0, [380, 280, 560, 400]),   # red circle -> skipped
    ])
    result = vision.detect(_FakeImage(), model=model)

    assert result.sticker_class == 1
    assert len(result.candidates) == 1
    assert result.candidates[0].class_id == 1
    assert result.candidates[0].class_name == "sticker"
    assert result.boxes_other_class == 1
    assert len(seen) == 1  # exactly one OCR call


def test_a_red_circle_alone_is_reported_as_other_class(no_ocr):
    model = _FakeModel([(0.80, 0, [380, 280, 560, 400])])
    result = vision.detect(_FakeImage(), model=model)

    assert result.reason == "other_class"
    assert result.candidates == []
    assert result.boxes_other_class == 1
    assert "sticker" in result.advice
    assert vision.best_candidate(result) is None


def test_single_class_checkpoint_uses_its_only_class(no_ocr):
    """A one-class number-plate model has no class 1; do not reject everything."""
    class _PlateModel(_FakeModel):
        names = {0: "number_plate"}

    model = _PlateModel([(0.90, 0, [400, 300, 520, 360])])
    result = vision.detect(_FakeImage(), model=model)

    assert result.sticker_class == 0
    assert len(result.candidates) == 1
    assert result.candidates[0].class_name == "number_plate"


def test_sticker_class_can_be_overridden(no_ocr, monkeypatch):
    monkeypatch.setenv("VISION_STICKER_CLASS", "0")
    model = _FakeModel([(0.90, 0, [400, 300, 520, 360])])
    result = vision.detect(_FakeImage(), model=model)

    assert result.sticker_class == 0
    assert len(result.candidates) == 1


def test_invalid_sticker_class_falls_back_to_the_model(no_ocr, monkeypatch):
    monkeypatch.setenv("VISION_STICKER_CLASS", "sticker-panel")
    result = vision.detect(_FakeImage(), model=_FakeModel([(0.90, 1, [1, 1, 9, 9])]))

    assert result.sticker_class == 1


def test_defaults_match_the_detector_that_was_validated(monkeypatch):
    """imgsz 960, probe from 0.05, OCR gate 0.25."""
    for name in ("VISION_CONFIDENCE", "VISION_IMAGE_SIZE", "VISION_STICKER_CLASS"):
        monkeypatch.delenv(name, raising=False)

    model = _FakeModel([(0.90, 1, [400, 300, 520, 360])])
    monkeypatch.setattr(vision, "read_text", lambda image, engine_name=None: "TN 12 AB 1234")
    result = vision.detect(_FakeImage(), model=model)

    assert model.calls[0]["imgsz"] == 960
    assert model.calls[0]["conf"] == pytest.approx(0.05)
    assert result.threshold == pytest.approx(0.25)
    assert result.image_size == 960
    assert result.bus_number if False else result.reason == "ok"
