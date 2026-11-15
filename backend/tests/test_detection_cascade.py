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


def test_plate_mode_always_runs_plate_stage_after_sticker_hit(clean_env, tmp_path):
    """VISION_PLATE_MODE=always forces the plate stage to run even after sticker hit."""
    clean_env.setenv("VISION_PLATE_MODE", "always")
    clean_env.setattr(vision, "read_text", lambda image, engine_name=None: "TN 48 BK 2129")
    sticker = _FakeModel([(0.91, 1, [400, 300, 520, 360])])
    _plate_model(tmp_path, clean_env, [(0.85, 0, [500, 400, 620, 450])])

    result = vision.detect(_FakeImage(), model=sticker, stages={"vehicle": False})

    assert result.cascade == "sticker"
    assert len(result.candidates) == 1
    assert result.candidates[0].bus_number == "TN 48 BK 2129"
    plate = next(stage for stage in result.stages if stage.name == vision.STAGE_NUMBER_PLATE)
    assert plate.ran is True
    assert plate.skipped == ""
    assert len(result.plate_candidates) == 1
    assert result.plate_candidates[0].raw_text == "TN 48 BK 2129"


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
    assert vision.best_identification(result).bus_number is None
    assert vision.best_identification(result).raw_text == "KL 07 AB 1234"


def test_a_missing_plate_checkpoint_is_skipped_not_fatal(clean_env, tmp_path):
    clean_env.setenv("VISION_PLATE_MODEL_PATH", str(tmp_path / "absent.pt"))
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
    # The bundled ANPR checkpoint is stage 2's default, not a file to install.
    assert rows[1]["model"].endswith("anpr_best.pt")
    assert rows[1]["required"] is False
    assert rows[1]["bundled"] is True
    assert rows[2]["bundled"] is False  # weights/vehicle.pt is fetched
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


# ------------------------------------------------ the bundled ANPR checkpoint
#
# `anpr_best.pt` is a YOLOv10n fine-tune of Car_License_Plates with exactly one
# class, `licence`. These tests pin the assumptions the plate stage makes about
# it: it is the default checkpoint, it needs no class filter, and its crops are
# enlarged before the OCR reads them.


def test_the_bundled_anpr_checkpoint_is_the_plate_default(clean_env):
    assert vision.plate_model_path().name == "anpr_best.pt"
    assert vision.DEFAULT_PLATE_MODEL_PATH.exists()


def test_the_plate_checkpoint_can_be_overridden(clean_env, tmp_path):
    target = tmp_path / "mine.pt"
    clean_env.setenv("VISION_PLATE_MODEL_PATH", str(target))

    assert vision.plate_model_path() == target


def test_a_missing_bundled_model_falls_back_to_weights(clean_env, tmp_path, monkeypatch):
    fallback = tmp_path / "number_plate.pt"
    fallback.write_bytes(b"fake")
    monkeypatch.setattr(vision, "DEFAULT_PLATE_MODEL_PATH", tmp_path / "absent.pt")
    monkeypatch.setattr(vision, "PLATE_MODEL_FALLBACKS", (fallback,))

    assert vision.plate_model_path() == fallback


def test_a_single_class_licence_model_is_read_without_a_class_filter(clean_env, tmp_path):
    clean_env.setattr(vision, "read_text", lambda image, engine_name=None: "TN 12 AB 1234")
    _plate_model(tmp_path, clean_env, [(0.77, 0, [500, 400, 620, 450])], names={0: "licence"})

    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"vehicle": False})

    assert result.plate_candidates[0].class_name == "licence"
    assert vision.best_identification(result).bus_number is None
    assert vision.best_identification(result).raw_text == "TN 12 AB 1234"


def test_plate_only_frame_yields_null_bus_number(clean_env, tmp_path):
    """best_identification() must never return a plate candidate as bus_number."""
    clean_env.setattr(vision, "read_text", lambda image, engine_name=None: "TN 48 BK 2129")
    _plate_model(tmp_path, clean_env, [(0.85, 0, [100, 100, 200, 150])])

    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"vehicle": False})
    candidate = vision.best_identification(result)
    assert candidate is not None
    assert candidate.bus_number is None
    assert candidate.raw_text == "TN 48 BK 2129"


def test_the_plate_stage_has_its_own_confidence_gate(clean_env, tmp_path):
    clean_env.setenv("VISION_PLATE_CONFIDENCE", "0.80")
    clean_env.setattr(vision, "read_text", lambda image, engine_name=None: "KA 01 AB 9999")
    _plate_model(tmp_path, clean_env, [(0.60, 0, [500, 400, 620, 450])])

    result = vision.detect(_FakeImage(), model=_FakeModel([]), stages={"vehicle": False})

    assert result.plate_candidates == []  # 0.60 is under the plate gate
    assert vision.confidence_threshold() == pytest.approx(0.25)  # sticker gate untouched


class _Crop:
    def __init__(self, width, height):
        self.size = (width, height)
        self.resized = None

    def resize(self, size, resample):
        self.resized = (size, resample)
        return self


@pytest.fixture
def fake_pil(clean_env):
    clean_env.setattr(
        vision, "_require_pil", lambda: SimpleNamespace(Resampling=SimpleNamespace(LANCZOS=1))
    )
    return clean_env


def test_a_small_plate_crop_is_enlarged_before_ocr(fake_pil):
    crop = _Crop(100, 40)

    enlarged = vision._prepare_plate_crop(crop)

    assert enlarged is crop
    assert crop.resized == ((300, 120), 1)  # 3x by default


def test_a_large_plate_crop_is_left_alone(fake_pil):
    crop = _Crop(600, 200)

    vision._prepare_plate_crop(crop)

    assert crop.resized is None


def test_the_upscale_can_be_switched_off(fake_pil):
    fake_pil.setenv("VISION_PLATE_UPSCALE", "1")
    crop = _Crop(100, 40)

    vision._prepare_plate_crop(crop)

    assert crop.resized is None


def test_a_crop_without_a_two_dimensional_size_is_passed_through(fake_pil):
    crop = SimpleNamespace(size=(1, 2, 3, 4))

    assert vision._prepare_plate_crop(crop) is crop


def test_the_setup_checklist_separates_required_from_optional():
    setup = vision.vision_setup()
    rows = {row["name"]: row for row in setup["components"]}

    assert rows["model"]["present"] is True
    assert rows["anpr"]["present"] is True
    assert rows["anpr"]["optional"] is True
    # An optional model never makes the detector "not ready"; only the runtime
    # components (torch, OCR, …) can, and this test host has none of them.
    assert "anpr" not in setup["missing"]
    assert setup["missing"] == [name for name in setup["missing"] if name != "anpr"]


def test_map_box_to_full_frame_with_scaling():
    box_in_crop = [20, 30, 100, 60]
    crop_offset = (500, 400)
    scale = (2.0, 2.0)
    full_box = vision.map_box_to_full_frame(box_in_crop, crop_offset, scale)
    assert full_box == [510, 415, 550, 430]

    full_box_unscaled = vision.map_box_to_full_frame(box_in_crop, crop_offset)
    assert full_box_unscaled == [520, 430, 600, 460]


def test_plate_stage_runs_on_vehicle_crop_when_vehicle_present(clean_env, tmp_path, monkeypatch):
    """When the vehicle stage identifies a vehicle box, plate detector runs on the crop."""
    v_model = _vehicle_model(tmp_path, clean_env, [(0.90, 5, [100, 100, 400, 400])])
    p_model = _plate_model(tmp_path, clean_env, [(0.85, 0, [20, 30, 80, 50])], names={0: "licence"})
    monkeypatch.setattr(
        vision,
        "load_stage_model",
        lambda stage: v_model if stage == vision.STAGE_VEHICLE else (p_model if stage == vision.STAGE_NUMBER_PLATE else None),
    )
    monkeypatch.setattr(vision, "read_text", lambda img: "TN 48 BK 2106")

    class MockImage:
        width = 1000
        height = 1000
        def crop(self, box):
            return MockImage()

    result = vision.DetectionResult()
    result.stage_flags = {s: True for s in vision.STAGE_ORDER}

    vision._run_vehicle_stage(MockImage(), result, threshold=0.25, size=960)
    assert len(result.vehicle_boxes) == 1

    vision._run_plate_stage(MockImage(), result, threshold=0.25, size=960)
    assert len(result.plate_candidates) == 1
    assert result.plate_candidates[0].bbox == [105, 665, 165, 685]
    assert result.plate_candidates[0].confidence == 0.85
    assert result.plate_candidates[0].bus_number == "TN 48 BK 2106"


def test_clahe_dual_pass_recovers_text_when_plain_fails(monkeypatch):
    """When plain OCR returns empty/low score, CLAHE variant is selected."""
    pytest.importorskip("PIL")
    from PIL import Image

    def mock_ocr(crop):
        if getattr(crop, "_is_clahe", False):
            return ("116", 0.95)
        return ("", 0.0)

    monkeypatch.setattr(vision, "read_text_with_score", mock_ocr)

    def mock_clahe(crop):
        c = Image.new("RGB", (30, 30))
        c._is_clahe = True
        return c

    monkeypatch.setattr(vision, "apply_clahe", mock_clahe)

    img = Image.new("RGB", (100, 100))
    rows = [(0.92, 1, [10, 10, 40, 40])]
    candidates = vision._ocr_rows(img, rows, {1: "sticker"}, threshold=0.25, limit=5)

    assert len(candidates) == 1
    assert candidates[0].bus_number == "116"
    assert candidates[0].ocr_variant == "clahe"


def test_sticker_overlapping_plate_is_disqualified():
    """A sticker candidate that overlaps a plate box has its bus_number cleared."""
    sticker_overlap = vision.PlateCandidate(
        bus_number="19",
        confidence=0.77,
        bbox=[200, 200, 250, 240],
        class_name="sticker",
    )
    sticker_valid = vision.PlateCandidate(
        bus_number="57",
        confidence=0.93,
        bbox=[1000, 1000, 1100, 1100],
        class_name="sticker",
    )
    plate = vision.PlateCandidate(
        bus_number="TN 48 BK 2129",
        raw_text="TN48BK2129",
        confidence=0.99,
        bbox=[190, 195, 300, 245],
        class_name="plate",
    )

    result = vision.DetectionResult(
        candidates=[sticker_overlap, sticker_valid],
        plate_candidates=[plate],
    )

    vision.reconcile_candidates(result)

    assert sticker_overlap.bus_number is None
    assert sticker_valid.bus_number == "57"


def test_warm_models_reports_warm_status_and_latency(monkeypatch):
    """vision_status() reports warm=True and warmup_ms >= 0."""
    res = vision.warm_models(force=True)
    assert res["warm"] is True
    assert res["warmup_ms"] >= 0

    status = vision.vision_status()
    assert status["warm"] is True
    assert status["warmup_ms"] >= 0


def test_validate_fallback_text_rejects_campus_banner():
    """A1: Fallback text must reject non-plate banners like '一 CHIRAPPALLCAMPUS'."""
    banner = "一 CHIRAPPALLCAMPUS"
    assert not vision.is_valid_indian_plate(banner)
    assert not vision.is_valid_indian_plate("MEDICAL&ALLIEDENGINEERIN")
    assert not vision.is_valid_indian_plate("MANAGEMENT PHYSIOTE")
    assert not vision.is_valid_indian_plate("STOP")
    # Valid Indian plates must pass
    assert vision.is_valid_indian_plate("TN 48 BK 2129")
    assert vision.is_valid_indian_plate("TN.48.BF.1480")
    assert vision.is_valid_indian_plate("TN48BK2129")


def test_plate_stage_cached_per_frame(monkeypatch):
    """A2: If plate stage is called multiple times on one frame, it runs once and caches."""
    pytest.importorskip("PIL")
    from pathlib import Path
    from PIL import Image

    calls = 0

    def fake_predict(model, crop, size, conf):
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(vision, "_predict_rows", fake_predict)
    monkeypatch.setattr(vision, "load_stage_model", lambda s: object())
    monkeypatch.setattr(vision, "plate_model_path", lambda: Path("fake.pt"))
    monkeypatch.setattr(Path, "exists", lambda self: True)

    img = Image.new("RGB", (640, 480))
    res1 = vision.DetectionResult(vehicle_boxes=[[10, 10, 250, 250]])
    vision._run_plate_stage(img, res1, threshold=0.25, size=640)
    assert getattr(img, "_plate_call_count", 0) == 1
    assert calls == 1

    # Second run on the same image frame
    res2 = vision.DetectionResult(vehicle_boxes=[[10, 10, 250, 250]])
    vision._run_plate_stage(img, res2, threshold=0.25, size=640)
    assert getattr(img, "_plate_call_count", 0) == 2
    # Inference did not run again
    assert calls == 1


def test_resolve_orphan_single_digit_bus_numbers():
    """Defect 1: Orphan single digit next to complete number resolved or rejected."""
    from backend import schemas

    # Exactly the prompt strings: "89 9" and "10 5"
    assert vision.normalize_plate("89 9") == "89"
    assert vision.normalize_plate("10 5") == "10"
    assert schemas.normalize_bus_number("89 9") == "89"
    assert schemas.normalize_bus_number("10 5") == "10"

    # Leading orphan digit
    assert vision.normalize_plate("9 89") == "89"
    assert schemas.normalize_bus_number("9 89") == "89"

    # Ambiguous cases rejected
    assert vision.normalize_plate("89 10 5") == ""
    assert vision.normalize_plate("1 2") == ""


def test_plate_ocr_fallback_default_and_toggle(clean_env, monkeypatch):
    """Cost change 1: fallback OCR defaults to OFF, toggling ON works."""
    assert vision.plate_ocr_fallback_enabled() is False

    monkeypatch.setenv("VISION_PLATE_OCR_FALLBACK", "1")
    assert vision.plate_ocr_fallback_enabled() is True

    monkeypatch.setenv("VISION_PLATE_OCR_FALLBACK", "on")
    assert vision.plate_ocr_fallback_enabled() is True

    monkeypatch.setenv("VISION_PLATE_OCR_FALLBACK", "0")
    assert vision.plate_ocr_fallback_enabled() is False


def test_vehicle_image_size_default_and_override(clean_env, monkeypatch):
    """Cost change 2: vehicle detector image size defaults to 640 and accepts overrides."""
    assert vision.vehicle_image_size() == 640

    monkeypatch.setenv("VISION_VEHICLE_IMAGE_SIZE", "960")
    assert vision.vehicle_image_size() == 960

    monkeypatch.setenv("VISION_VEHICLE_IMAGE_SIZE", "invalid")
    assert vision.vehicle_image_size() == 640
