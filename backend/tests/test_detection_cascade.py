"""The detection cascade: sticker -> number plate -> vehicle type.

A bus that carries no sticker used to answer "no detection" even when the plate
was plainly visible and the vehicle was obviously a bus. These tests pin the
three-stage order, the per-scan switches the panel sends, and the rule that an
optional checkpoint which is not installed is *skipped*, never an error.

No torch, ultralytics or OCR is needed here: the models are fakes that mimic the
handful of attributes `detect()` touches, exactly as in
`test_detection_diagnostics.py`.
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
    """Mimics the tensor attributes `_predict_rows()` reads."""

    def __init__(self, rows):
        self._rows = rows
        self.conf = _Column([row[0] for row in rows])
        self.cls = _Column([row[1] for row in rows])
        self.xyxy = _Column([row[2] for row in rows])

    def __len__(self):
        return len(self._rows)


class _FakeModel:
    def __init__(self, rows, names=None):
        self._rows = rows
        self.names = names or {0: "red circle", 1: "sticker"}
        self.calls = []

    def predict(self, **kwargs):
        self.calls.append(kwargs)
        return [SimpleNamespace(boxes=_Boxes(self._rows))]


class _FakeImage:
    width = 1280
    height = 720

    def crop(self, box):
        return SimpleNamespace(size=box)


COCO_NAMES = {0: "person", 2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}


@pytest.fixture
def clean_env(monkeypatch):
    for name in (
        "VISION_CONFIDENCE",
        "VISION_IMAGE_SIZE",
        "VISION_STICKER_CLASS",
        "VISION_STAGE_STICKER",
        "VISION_STAGE_PLATE",
        "VISION_STAGE_VEHICLE",
        "VISION_PLATE_MODEL_PATH",
        "VISION_VEHICLE_MODEL_PATH",
        "VISION_VEHICLE_CLASSES",
        "VISION_VEHICLE_CONFIDENCE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(vision, "read_text", lambda image, engine_name=None: "")
    return monkeypatch


def _plate_model(tmp_path, monkeypatch, rows, names=None):
    """Install a fake number-plate checkpoint for one test."""
    path = tmp_path / "number_plate.pt"
    path.write_bytes(b"fake")
    monkeypatch.setattr(vision, "plate_model_path", lambda: path)
    model = _FakeModel(rows, names or {0: "number_plate"})
    monkeypatch.setattr(
        vision, "load_stage_model", lambda stage: model if stage == vision.STAGE_NUMBER_PLATE else None
    )
    return model


def _vehicle_model(tmp_path, monkeypatch, rows, names=None):
    path = tmp_path / "vehicle.pt"
    path.write_bytes(b"fake")
    monkeypatch.setattr(vision, "vehicle_model_path", lambda: path)
    model = _FakeModel(rows, names or COCO_NAMES)
    monkeypatch.setattr(
        vision, "load_stage_model", lambda stage: model if stage == vision.STAGE_VEHICLE else None
    )
    return model


# --------------------------------------------------------------- stage order


def test_a_readable_sticker_short_circuits_the_plate_stage(clean_env):
    clean_env.setattr(vision, "read_text", lambda image, engine_name=None: "TN 12 AB 1234")
    sticker = _FakeModel([(0.91, 1, [400, 300, 520, 360])])

    result = vision.detect(_FakeImage(), model=sticker, stages={"vehicle": False})

    assert result.cascade == "sticker"
    assert vision.best_identification(result).bus_number == "TN 12 AB 1234"
    plate = next(stage for stage in result.stages if stage.name == vision.STAGE_NUMBER_PLATE)
    assert plate.skipped == "not_needed"
    assert plate.ran is False
    assert result.reason == "ok"


def test_the_sticker_stage_can_be_switched_off_for_one_scan(clean_env):
    """Panel toggle: sticker off must not even load the sticker model."""
    result = vision.detect(_FakeImage(), stages={"sticker": False, "vehicle": False})

    sticker = next(stage for stage in result.stages if stage.name == vision.STAGE_STICKER)
    assert sticker.enabled is False
    assert sticker.ran is False
    assert sticker.skipped == "disabled"
    assert result.candidates == []
    assert result.cascade == vision.CASCADE_NONE


def test_the_plate_stage_reads_a_number_when_no_sticker_was_found(clean_env, tmp_path):
    clean_env.setattr(vision, "read_text", lambda image, engine_name=None: "KL 07 AB 1234")
    sticker = _FakeModel([])
    _plate_model(tmp_path, clean_env, [(0.83, 0, [500, 400, 620, 450])])

    result = vision.detect(_FakeImage(), model=sticker, stages={"vehicle": False})

    assert result.reason == "ok"
    assert result.cascade == "number_plate"
    assert result.candidates == []  # the sticker contract is untouched
    assert len(result.plate_candidates) == 1
    assert vision.best_identification(result).bus_number == "KL 07 AB 1234"


def test_a_missing_plate_checkpoint_is_skipped_not_fatal(clean_env):
    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"vehicle": False})

    plate = next(stage for stage in result.stages if stage.name == vision.STAGE_NUMBER_PLATE)
    assert plate.skipped == "model_missing"
    assert "VISION_PLATE_MODEL_PATH" in plate.detail
    assert result.reason == "no_detection"
    # The advice explains the gap instead of pretending nothing was asked for.
    assert "Number plate" in result.advice


def test_the_plate_stage_can_be_switched_off(clean_env, tmp_path):
    _plate_model(tmp_path, clean_env, [(0.83, 0, [500, 400, 620, 450])])

    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"plate": False, "vehicle": False})

    plate = next(stage for stage in result.stages if stage.name == vision.STAGE_NUMBER_PLATE)
    assert plate.skipped == "disabled"
    assert result.plate_candidates == []


# ------------------------------------------------------------ vehicle stage


def test_a_bus_is_classified_even_without_a_number(clean_env, tmp_path):
    _vehicle_model(tmp_path, clean_env, [(0.88, 5, [100, 100, 900, 600])])

    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"plate": False})

    assert result.vehicle["label"] == "bus"
    assert result.vehicle["class_name"] == "bus"
    assert result.cascade == "vehicle"
    assert result.stages[-1].result == "identified"


def test_a_motorcycle_is_reported_as_a_bike(clean_env, tmp_path):
    _vehicle_model(tmp_path, clean_env, [(0.71, 3, [200, 200, 400, 500])])

    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"plate": False})

    assert result.vehicle["label"] == "bike"


def test_a_person_box_is_not_a_vehicle(clean_env, tmp_path):
    _vehicle_model(tmp_path, clean_env, [(0.95, 0, [10, 10, 60, 200])])

    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"plate": False})

    assert result.vehicle is None
    assert result.stages[-1].result == "none"


def test_the_vehicle_stage_can_be_switched_off(clean_env, tmp_path):
    _vehicle_model(tmp_path, clean_env, [(0.88, 5, [100, 100, 900, 600])])

    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"plate": False, "vehicle": False})

    assert result.vehicle is None
    assert result.stages[-1].skipped == "disabled"


def test_vehicle_classes_can_be_narrowed_by_env(clean_env, tmp_path):
    clean_env.setenv("VISION_VEHICLE_CLASSES", "car")
    _vehicle_model(tmp_path, clean_env, [(0.88, 5, [100, 100, 900, 600])])

    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"plate": False})

    assert result.vehicle is None


# ------------------------------------------------------- toggles from a body


def test_stage_overrides_accept_form_fields(clean_env):
    overrides = vision.stage_overrides_from_payload({"sticker": "0", "vehicle": "on", "source": "panel"})

    assert overrides == {vision.STAGE_STICKER: False, vision.STAGE_VEHICLE: True}


def test_stage_overrides_accept_a_json_stages_map(clean_env):
    overrides = vision.stage_overrides_from_payload({"stages": {"plate": "false"}})

    assert overrides == {vision.STAGE_NUMBER_PLATE: False}


def test_stage_overrides_accept_a_json_string(clean_env):
    overrides = vision.stage_overrides_from_payload({"stages": '{"sticker": "no"}'})

    assert overrides == {vision.STAGE_STICKER: False}


def test_stage_overrides_accept_a_comma_list(clean_env):
    overrides = vision.stage_overrides_from_payload({"stages": "sticker,plate"})

    assert overrides == {vision.STAGE_STICKER: True, vision.STAGE_NUMBER_PLATE: True}


def test_stage_overrides_ignore_unknown_names(clean_env):
    assert vision.stage_overrides_from_payload({"turbo": "1"}) == {}


def test_env_switches_change_the_default(clean_env):
    clean_env.setenv("VISION_STAGE_STICKER", "0")

    flags = vision.normalize_stages()

    assert flags[vision.STAGE_STICKER] is False
    assert flags[vision.STAGE_NUMBER_PLATE] is True
    # A per-scan override still wins over the host default.
    assert vision.normalize_stages({"sticker": True})[vision.STAGE_STICKER] is True


# --------------------------------------------------------------- API contract


def test_the_payload_stays_backwards_compatible(clean_env):
    result = vision.detect(_FakeImage(), model=_FakeModel([]))
    payload = result.to_dict()

    for key in (
        "candidates",
        "model",
        "inference_ms",
        "frame_width",
        "frame_height",
        "boxes_total",
        "boxes_above_threshold",
        "boxes_other_class",
        "sticker_class",
        "best_confidence",
        "threshold",
        "image_size",
        "reason",
        "advice",
    ):
        assert key in payload
    assert payload["cascade"] == vision.CASCADE_NONE
    assert [stage["name"] for stage in payload["stages"]] == list(vision.STAGE_ORDER)
    assert payload["stages"][0]["label"] == "Sticker"
    assert payload["vehicle"] is None
    assert payload["stage_flags"] == {stage: True for stage in vision.STAGE_ORDER}


def test_stage_status_lists_the_three_stages():
    rows = vision.stage_status()

    assert [row["name"] for row in rows] == list(vision.STAGE_ORDER)
    assert rows[0]["required"] is True and rows[0]["bundled"] is True
    assert rows[1]["model"].endswith("number_plate.pt")
    assert rows[2]["model"].endswith("vehicle.pt")


# ------------------------------------------------------------- scan endpoint


def test_the_scan_route_forwards_the_panel_switches(client, users, monkeypatch, clean_env):
    """The Test Lab posts its toggles as form fields; they must reach detect()."""
    import io

    import backend.app as app_module
    from .conftest import login_head_admin

    captured = {}

    def fake_detect(image, stages=None, **kwargs):
        captured["stages"] = stages
        result = vision.DetectionResult(reason="no_detection")
        result.cascade = vision.CASCADE_NONE
        return result

    monkeypatch.setattr(app_module, "detect", fake_detect)
    monkeypatch.setattr(app_module, "decode_image", lambda payload: _FakeImage())
    login_head_admin(client, users)

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(png), "frame.jpg"), "sticker": "0", "vehicle": "1"},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    assert captured["stages"] == {vision.STAGE_STICKER: False, vision.STAGE_VEHICLE: True}
    payload = response.get_json()
    assert payload["stage"] == vision.CASCADE_NONE
    assert "vehicle" in payload and "stages" in payload
