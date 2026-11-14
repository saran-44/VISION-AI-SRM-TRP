"""Bus-sticker detection and plate-number extraction using the trained `best.pt` model.

The model shipped in this repository (`best.pt`) is an Ultralytics YOLOv10n
detector trained for two classes:

    0 -> "red circle"   (the painted red ring around the bus number)
    1 -> "sticker"      (the sticker panel that carries the bus number)

The detector therefore only localises *where* the number is; the actual text
has to be read out of that crop. This module wires the two together:

    frame -> YOLO detection -> sticker crop -> OCR -> normalised bus number

Everything heavy (torch, ultralytics, OpenCV, OCR engine) is imported lazily
so that the Flask application still starts on a machine that has none of the
vision extras installed. `vision_available()` reports what is usable.
"""
from __future__ import annotations

import base64
import binascii
import io
import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# Root of the repository (backend/ -> repo root).
ROOT = Path(__file__).resolve().parents[1]

# Default location of the trained model inside the repository.
DEFAULT_MODEL_PATH = ROOT / "best.pt"

# Class ids as exported by the trained model.
CLASS_STICKER = 1
CLASS_RED_CIRCLE = 0

CLASS_LABELS = {
    CLASS_RED_CIRCLE: "red circle",
    CLASS_STICKER: "sticker",
}

# The only class that is OCR'd. See sticker_class_id().
DEFAULT_STICKER_CLASS = CLASS_STICKER

# --------------------------------------------------------------------------- #
# Detection stages
#
# One frame is read by a cascade of detectors, cheapest and most specific
# first, so a bus that carries no sticker still yields a number:
#
#   sticker  -> best.pt, the trained sticker/red-circle checkpoint
#   plate    -> an optional number-plate checkpoint (weights/number_plate.pt)
#   vehicle  -> an optional COCO-style checkpoint (bus / car / bike / truck)
#
# Each stage can be switched off from the panel (per request) or from the
# environment (per host). A stage whose weights are missing is *skipped*, never
# an error: the console still answers with whatever the other stages found.
# --------------------------------------------------------------------------- #
STAGE_STICKER = "sticker"
STAGE_NUMBER_PLATE = "number_plate"
STAGE_VEHICLE = "vehicle"
STAGE_ORDER = (STAGE_STICKER, STAGE_NUMBER_PLATE, STAGE_VEHICLE)

# Names the panel and the API may use for a stage, including short forms.
STAGE_ALIASES = {
    "sticker": STAGE_STICKER,
    "stickers": STAGE_STICKER,
    "plate": STAGE_NUMBER_PLATE,
    "number_plate": STAGE_NUMBER_PLATE,
    "numberplate": STAGE_NUMBER_PLATE,
    "vehicle": STAGE_VEHICLE,
    "vehicles": STAGE_VEHICLE,
    "type": STAGE_VEHICLE,
}

STAGE_LABELS = {
    STAGE_STICKER: "Sticker",
    STAGE_NUMBER_PLATE: "Number plate",
    STAGE_VEHICLE: "Vehicle type",
}

# Environment variable that switches a stage off for the whole host.
STAGE_ENV = {
    STAGE_STICKER: "VISION_STAGE_STICKER",
    STAGE_NUMBER_PLATE: "VISION_STAGE_PLATE",
    STAGE_VEHICLE: "VISION_STAGE_VEHICLE",
}

# Optional checkpoints. `weights/` is git-ignored: drop your own files there.
#
# The bundled ANPR checkpoint (`anpr_best.pt`) is a YOLOv10n fine-tune of
# `Car_License_Plates` — one class, `licence`, i.e. "this box is a number plate".
# It localises the plate; the OCR still reads the characters. Train something
# better on your own gate footage and point VISION_PLATE_MODEL_PATH at it.
DEFAULT_PLATE_MODEL_PATH = ROOT / "anpr_best.pt"
PLATE_MODEL_FALLBACKS = (ROOT / "weights" / "number_plate.pt",)
DEFAULT_VEHICLE_MODEL_PATH = ROOT / "weights" / "vehicle.pt"

# COCO names that count as "a vehicle", and how they are reported. A two-wheeler
# is the same thing to a gate operator whether the label says motorcycle or
# bicycle, so both collapse to "bike".
VEHICLE_CLASS_MAP = {
    "bicycle": "bike",
    "motorcycle": "bike",
    "motorbike": "bike",
    "scooter": "bike",
    "car": "car",
    "van": "car",
    "bus": "bus",
    "truck": "truck",
    "auto": "auto",
    "autorickshaw": "auto",
}
DEFAULT_VEHICLE_CLASSES = ("bicycle", "motorcycle", "car", "bus", "truck")

# Which stage produced the answer in a frame.
CASCADE_NONE = "none"

# Bus numbers seen in this project look like "TN 12 AB 1234" / "BUS-001".
# The OCR result is normalised to the same shape the API accepts.
PLATE_CLEAN_RE = re.compile(r"[^A-Z0-9 .\-]")

_model_lock = threading.Lock()
_model_cache: dict[str, Any] = {}
_ocr_lock = threading.Lock()
_ocr_cache: dict[str, Any] = {}


class VisionUnavailable(RuntimeError):
    """Raised when a vision dependency or the model file is missing."""


class ImageRejected(ValueError):
    """Raised when the caller's own image cannot be used.

    Separate from VisionUnavailable on purpose: "your upload is unusable" is a
    400, "this server has no detector" is a 503. Conflating them produced an
    install-the-extras message for a photograph that was simply too big.
    """


@dataclass
class PlateCandidate:
    """One detected sticker and the text read from it."""

    bus_number: str | None = None
    confidence: float = 0.0
    raw_text: str = ""
    bbox: list[int] = field(default_factory=list)
    class_id: int = CLASS_STICKER
    class_name: str = "sticker"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bus_number": self.bus_number,
            "confidence": round(float(self.confidence), 4),
            "raw_text": self.raw_text,
            "bbox": list(self.bbox),
            "class_id": self.class_id,
            "class_name": self.class_name,
        }


@dataclass
class StageReport:
    """What one stage of the cascade did on this frame.

    The panel needs this to answer "why is the plate stage not producing
    anything?" without reading a log: a stage is either disabled, skipped
    because its weights are missing, or it ran and found `found` boxes.
    """

    name: str
    enabled: bool = True
    ran: bool = False
    found: int = 0
    best_confidence: float = 0.0
    model: str = ""
    # "" when the stage ran, otherwise disabled | not_needed | model_missing |
    # not_installed | error.
    skipped: str = ""
    detail: str = ""
    ms: int = 0
    # identified | seen_unreadable | none
    result: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": STAGE_LABELS.get(self.name, self.name),
            "enabled": self.enabled,
            "ran": self.ran,
            "found": self.found,
            "best_confidence": round(float(self.best_confidence), 4),
            "model": self.model,
            "skipped": self.skipped,
            "detail": self.detail,
            "ms": self.ms,
            "result": self.result,
        }


@dataclass
class DetectionResult:
    """Outcome of running the detector over a single frame."""

    candidates: list[PlateCandidate] = field(default_factory=list)
    model: str = ""
    inference_ms: int = 0
    frame_width: int = 0
    frame_height: int = 0
    # Diagnostics. "No sticker in this frame" used to cover three very different
    # situations: nothing detected, something detected below the confidence
    # threshold, and a sticker found whose number the OCR could not read. The
    # counters below separate them.
    boxes_total: int = 0
    boxes_above_threshold: int = 0
    boxes_other_class: int = 0
    sticker_class: int = DEFAULT_STICKER_CLASS
    best_confidence: float = 0.0
    threshold: float = 0.0
    image_size: int = 0
    # Frame diagnostics: measured, not guessed. `frame_sharpness` is the
    # Laplacian variance (soft frames explain most "no box at all"), and
    # `tiles` says whether the scan was tiled (see VISION_TILES).
    frame_sharpness: float | None = None
    frame_brightness: float | None = None
    tiles: int = 1
    reason: str = ""
    advice: str = ""
    # Cascade. `stages` records every stage that was asked to run, `cascade`
    # names the one that produced the answer, and `vehicle` carries the
    # classification when the vehicle stage could identify one.
    stages: list[StageReport] = field(default_factory=list)
    stage_flags: dict[str, bool] = field(default_factory=dict)
    plate_candidates: list[PlateCandidate] = field(default_factory=list)
    vehicle: dict[str, Any] | None = None
    cascade: str = CASCADE_NONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "model": self.model,
            "inference_ms": self.inference_ms,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "boxes_total": self.boxes_total,
            "boxes_above_threshold": self.boxes_above_threshold,
            "boxes_other_class": self.boxes_other_class,
            "sticker_class": self.sticker_class,
            "best_confidence": round(float(self.best_confidence), 4),
            "threshold": round(float(self.threshold), 4),
            "image_size": self.image_size,
            "frame_sharpness": (
                round(float(self.frame_sharpness), 1) if self.frame_sharpness is not None else None
            ),
            "frame_brightness": (
                round(float(self.frame_brightness), 1) if self.frame_brightness is not None else None
            ),
            "tiles": self.tiles,
            "reason": self.reason,
            "advice": self.advice,
            # Additive: clients that only know the sticker fields above keep
            # working, the panel reads these to show the cascade.
            "stages": [stage.to_dict() for stage in self.stages],
            "stage_flags": dict(self.stage_flags),
            "plate_candidates": [candidate.to_dict() for candidate in self.plate_candidates],
            "vehicle": self.vehicle,
            "cascade": self.cascade,
        }



# --------------------------------------------------------------------------- #
# Configuration helpers
# --------------------------------------------------------------------------- #
def model_path() -> Path:
    """Resolve the model file location (env override, then the repo copy)."""
    configured = os.getenv("VISION_MODEL_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_MODEL_PATH


def confidence_threshold() -> float:
    """Minimum detection confidence for a sticker that reaches the OCR.

    0.25 is the value the detector was validated with on the gate frames: the
    model is asked for boxes from 0.05, so anything weaker than 0.25 is a
    near-miss that only shows up in the diagnostics, never in a candidate.
    """
    try:
        value = float(os.getenv("VISION_CONFIDENCE", "0.25"))
    except ValueError:
        return 0.25
    return max(0.01, min(0.99, value))


def image_size() -> int:
    """Inference letterbox size for the detector.

    A bus sticker occupies a small part of a 1280×720 gate frame, so the
    COCO default of 640 px was the limiting factor, not the backbone: at 960 the
    sticker survives the letterbox with enough detail for the OCR. Raise it to
    1280 for far plates; it costs quadratic compute, so it is an explicit
    trade-off.

    Train at the size you infer at: a model fine-tuned at 640 and run at 960 is
    usually still fine, the reverse is not.
    """
    try:
        value = int(os.getenv("VISION_IMAGE_SIZE", "960"))
    except ValueError:
        return 960
    return max(320, min(1536, value))


def sticker_class_id(model=None) -> int:
    """Which class id counts as "the sticker".

    The shipped `best.pt` has two classes: 0 = "red circle" (the painted ring)
    and 1 = "sticker" (the panel that carries the number). Only class 1 may be
    cropped and OCR'd — the ring is a separate box around the same bus and
    reading it wastes OCR calls and produces empty text.

    A checkpoint trained as a single-class plate/sticker model has no class 1 at
    all, so when the model declares exactly one class that class is used.
    `VISION_STICKER_CLASS` overrides both rules.
    """
    configured = os.getenv("VISION_STICKER_CLASS", "").strip()
    if configured:
        try:
            return max(0, int(configured))
        except ValueError:
            logger.warning("VISION_STICKER_CLASS=%r is not a number; ignoring it", configured)

    names = getattr(model, "names", None) or {}
    if len(names) == 1:
        return int(next(iter(names)))
    return DEFAULT_STICKER_CLASS


def _env_flag(name: str, default: bool = True) -> bool:
    """Read a boolean environment flag (`1/0`, `true/false`, `on/off`)."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on", "y"}:
        return True
    if value in {"0", "false", "no", "off", "n"}:
        return False
    logger.warning("%s=%r is not a boolean; using %s", name, raw, default)
    return default


def _as_flag(value, default: bool = True) -> bool | None:
    """Coerce a JSON/form value into a boolean, or None when unreadable."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y", ""}:
        return True if text else default
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return None


def stage_enabled(stage: str) -> bool:
    """Is this stage switched on for the host? (`VISION_STAGE_*`)"""
    return _env_flag(STAGE_ENV.get(stage, f"VISION_STAGE_{stage.upper()}"), True)


def normalize_stages(overrides=None) -> dict[str, bool]:
    """Resolve the per-request stage toggles into one flag per stage.

    Anything not named keeps its environment default, so a caller can switch a
    single stage off (`{"sticker": False}`) without having to repeat the rest.
    """
    flags = {stage: stage_enabled(stage) for stage in STAGE_ORDER}
    if overrides is None:
        return flags

    if isinstance(overrides, str):
        pairs: list[tuple[str, Any]] = [(part, True) for part in overrides.split(",") if part.strip()]
    elif isinstance(overrides, dict):
        pairs = list(overrides.items())
    else:
        pairs = [(item, True) for item in overrides]

    for raw_name, raw_value in pairs:
        key = str(raw_name).strip().lower().replace("-", "_").replace(" ", "_")
        stage = STAGE_ALIASES.get(key)
        if stage is None:
            logger.info("Ignoring unknown detection stage %r", raw_name)
            continue
        value = _as_flag(raw_value)
        if value is not None:
            flags[stage] = value
    return flags


def stage_overrides_from_payload(payload: dict[str, Any] | None) -> dict[str, bool]:
    """Pull stage toggles out of a form/JSON body sent by the panel.

    Two shapes are accepted, because the panel posts multipart while devices
    post JSON:

        {"stages": {"sticker": false}}       or  "stages=sticker,plate"
        {"sticker": "0", "vehicle": "1"}     or  form fields of the same name
    """
    payload = payload or {}
    overrides: dict[str, bool] = {}

    raw_stages = payload.get("stages")
    if isinstance(raw_stages, dict):
        overrides.update(normalize_stages_subset(raw_stages))
    elif isinstance(raw_stages, str) and raw_stages.strip().startswith("{"):
        import json

        try:
            parsed = json.loads(raw_stages)
        except ValueError:
            logger.info("Ignoring unreadable stages JSON: %r", raw_stages)
            parsed = None
        if isinstance(parsed, dict):
            overrides.update(normalize_stages_subset(parsed))
    elif isinstance(raw_stages, str) and raw_stages.strip():
        # A plain list only switches stages on; anything omitted keeps its default.
        for part in raw_stages.split(","):
            key = part.strip().lower().replace("-", "_")
            stage = STAGE_ALIASES.get(key)
            if stage is not None:
                overrides[stage] = True

    for key, value in payload.items():
        name = str(key).strip().lower().replace("-", "_").replace(" ", "_")
        stage = STAGE_ALIASES.get(name)
        if stage is None:
            continue
        flag = _as_flag(value)
        if flag is not None:
            overrides[stage] = flag

    return overrides


def normalize_stages_subset(values: dict[str, Any]) -> dict[str, bool]:
    """Like `normalize_stages`, but only for the keys present in `values`."""
    subset: dict[str, bool] = {}
    for raw_name, raw_value in values.items():
        key = str(raw_name).strip().lower().replace("-", "_").replace(" ", "_")
        stage = STAGE_ALIASES.get(key)
        if stage is None:
            continue
        flag = _as_flag(raw_value)
        if flag is not None:
            subset[stage] = flag
    return subset


def plate_model_path() -> Path:
    """Checkpoint used by the number-plate stage.

    Order: `VISION_PLATE_MODEL_PATH`, then the bundled `anpr_best.pt`, then a
    model of your own in `weights/number_plate.pt`.
    """
    configured = os.getenv("VISION_PLATE_MODEL_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    if DEFAULT_PLATE_MODEL_PATH.exists():
        return DEFAULT_PLATE_MODEL_PATH
    for candidate in PLATE_MODEL_FALLBACKS:
        if candidate.exists():
            return candidate
    return DEFAULT_PLATE_MODEL_PATH


def vehicle_model_path() -> Path:
    """Checkpoint used by the vehicle stage (`weights/vehicle.pt`)."""
    configured = os.getenv("VISION_VEHICLE_MODEL_PATH", "").strip()
    return Path(configured).expanduser() if configured else DEFAULT_VEHICLE_MODEL_PATH


def plate_threshold() -> float:
    """Minimum confidence for a plate box (`VISION_PLATE_CONFIDENCE`).

    Separate from VISION_CONFIDENCE on purpose: the sticker model and the ANPR
    model are different checkpoints with different score distributions, and
    tuning one must not silently retune the other.
    """
    try:
        value = float(os.getenv("VISION_PLATE_CONFIDENCE", "0.25"))
    except ValueError:
        return 0.25
    return max(0.01, min(0.99, value))


def plate_upscale() -> int:
    """How much a small plate crop is enlarged before OCR (`VISION_PLATE_UPSCALE`).

    A plate that is 90 px wide in a 1280x720 frame carries ~10 px per character:
    enough for a human, below what an OCR engine wants. Upscaling the crop is
    the cheapest accuracy win there is, and it costs one resize.
    """
    try:
        value = int(os.getenv("VISION_PLATE_UPSCALE", "3"))
    except ValueError:
        return 3
    return max(1, min(6, value))


def vehicle_threshold() -> float:
    """Minimum confidence for a vehicle box (`VISION_VEHICLE_CONFIDENCE`)."""
    try:
        value = float(os.getenv("VISION_VEHICLE_CONFIDENCE", "0.35"))
    except ValueError:
        return 0.35
    return max(0.01, min(0.99, value))


def vehicle_classes() -> set[str]:
    """Which model labels count as a vehicle (`VISION_VEHICLE_CLASSES`)."""
    configured = os.getenv("VISION_VEHICLE_CLASSES", "").strip()
    if not configured:
        return set(DEFAULT_VEHICLE_CLASSES)
    values = {part.strip().lower() for part in configured.split(",") if part.strip()}
    return values or set(DEFAULT_VEHICLE_CLASSES)


def vehicle_label(class_name: str) -> str:
    """Collapse a detector class name into the label the console shows."""
    return VEHICLE_CLASS_MAP.get(str(class_name).strip().lower(), str(class_name).strip().lower())


def ocr_engine_name() -> str:
    """Which OCR backend to use: `auto`, `tesseract`, `easyocr` or `none`."""
    return os.getenv("VISION_OCR_ENGINE", "auto").strip().lower() or "auto"


def _require_cv2():
    try:
        import cv2  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise VisionUnavailable(
            "OpenCV is not installed. Install the vision extras with "
            "`pip install -r backend/requirements-vision.txt`."
        ) from exc
    return cv2


def _require_pil():
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise VisionUnavailable(
            "Pillow is not installed. Install the vision extras with "
            "`pip install -r backend/requirements-vision.txt`."
        ) from exc
    return Image


def _ocr_tesseract():
    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise VisionUnavailable("pytesseract is not installed") from exc
    try:
        pytesseract.get_tesseract_version()
    except Exception as exc:  # pragma: no cover - depends on environment
        raise VisionUnavailable(
            "The tesseract binary is not available on this machine. Install the "
            "`tesseract-ocr` system package or choose another OCR engine."
        ) from exc
    return pytesseract


def _ocr_easyocr():
    try:
        import easyocr  # type: ignore
    except ImportError as exc:
        raise VisionUnavailable("easyocr is not installed") from exc
    with _ocr_lock:
        reader = _ocr_cache.get("easyocr")
        if reader is None:
            reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            _ocr_cache["easyocr"] = reader
        return reader


# --------------------------------------------------------------------------- #
# Model loading
# --------------------------------------------------------------------------- #
class StageNotConfigured(VisionUnavailable):
    """A cascade stage has no usable checkpoint on this host.

    Carries `reason` (model_missing | not_installed | load_failed) so the stage
    report can say why it was skipped instead of turning a missing optional
    model into a failed scan.
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def load_model_at(path: Path, cache_key: str, label: str):
    """Load (and cache) a YOLO checkpoint from `path` under `cache_key`."""
    if not path.exists():
        raise StageNotConfigured(
            "model_missing",
            f"{label} model not found at {path}.",
        )
    with _model_lock:
        cached = _model_cache.get(cache_key)
        if cached is not None:
            return cached
        try:
            from ultralytics import YOLO  # type: ignore
        except ImportError as exc:
            raise StageNotConfigured(
                "not_installed",
                "ultralytics is not installed. Install the vision extras with "
                "`pip install -r backend/requirements-vision.txt`.",
            ) from exc
        logger.info("Loading %s model from %s", label.lower(), path)
        try:
            model = YOLO(str(path))
        except Exception as exc:  # a corrupt or half-downloaded checkpoint
            raise StageNotConfigured(
                "load_failed",
                f"{label} model at {path} could not be loaded: {type(exc).__name__}",
            ) from exc
        _model_cache[cache_key] = model
        return model


def load_model():
    """Load (and cache) the sticker model. Raises VisionUnavailable."""
    try:
        return load_model_at(model_path(), "model", "Detection")
    except StageNotConfigured as exc:
        # Report what actually failed. Collapsing "ultralytics is not installed"
        # and "the checkpoint could not be loaded" into "model not found" sent
        # operators to look for a file that was already on disk.
        detail = str(exc) or f"Detection model at {model_path()} is unusable."
        if exc.reason == "model_missing":
            detail = f"{detail} Set VISION_MODEL_PATH to a valid best.pt file."
        raise VisionUnavailable(detail) from exc


def load_stage_model(stage: str):
    """Load the checkpoint that belongs to one cascade stage."""
    if stage == STAGE_STICKER:
        return load_model()
    if stage == STAGE_NUMBER_PLATE:
        return load_model_at(plate_model_path(), "plate", "Number-plate")
    if stage == STAGE_VEHICLE:
        return load_model_at(vehicle_model_path(), "vehicle", "Vehicle")
    raise StageNotConfigured("model_missing", f"Unknown detection stage {stage!r}")


def unload_model() -> None:
    with _model_lock:
        _model_cache.clear()


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #
def _ocr_rapidocr():
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
    except ImportError as exc:
        raise VisionUnavailable("rapidocr-onnxruntime is not installed") from exc
    with _ocr_lock:
        engine = _ocr_cache.get("rapidocr")
        if engine is None:
            engine = RapidOCR()
            _ocr_cache["rapidocr"] = engine
        return engine


def _run_tesseract(image, engine) -> str:
    text = engine.image_to_string(image, config="--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 -")
    return text or ""


def _run_easyocr(image, reader) -> str:
    results = reader.readtext(image, detail=0, paragraph=False)
    return " ".join(str(item) for item in results)


def _run_rapidocr(image, engine) -> str:
    import numpy as np

    array = np.array(image.convert("RGB"))
    result, _ = engine(array)
    if not result:
        return ""
    return " ".join(str(item[1]) for item in result)


def read_text(image, engine_name: str | None = None) -> str:
    """Read text out of an image using the configured OCR backend."""
    engine_name = (engine_name or ocr_engine_name()).lower()
    if engine_name == "none":
        return ""
    errors: list[str] = []
    order: Iterable[str]
    if engine_name == "auto":
        order = ("rapidocr", "tesseract", "easyocr")
    else:
        order = (engine_name,)

    for name in order:
        try:
            if name == "tesseract":
                engine = _ocr_tesseract()
                return _run_tesseract(image, engine)
            if name == "easyocr":
                reader = _ocr_easyocr()
                return _run_easyocr(image, reader)
            if name == "rapidocr":
                engine = _ocr_rapidocr()
                return _run_rapidocr(image, engine)
            raise VisionUnavailable(f"Unknown OCR engine '{name}'")
        except VisionUnavailable as exc:
            errors.append(str(exc))
    raise VisionUnavailable("; ".join(errors) or "No OCR engine is available")


def normalize_plate(text: str) -> str:
    """Normalise raw OCR output into the bus-number format used by the API."""
    if not text:
        return ""
    upper = text.upper().replace("\n", " ").strip()
    cleaned = PLATE_CLEAN_RE.sub("", upper)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned


# --------------------------------------------------------------------------- #
# Detection
# --------------------------------------------------------------------------- #
# Frame guards. A 1 MB request body can still decode into a gigantic bitmap,
# so the pixel count is capped before any pixel data is allocated, and the
# side length is capped before the decoder touches it.
# The detector resizes every frame to `VISION_IMAGE_SIZE` (960 px) before the
# model sees it, so the only thing a huge upload costs is decode time. These are
# therefore *resize targets*, not refusals: a 12 MP phone photo — the single most
# common thing a gate operator will upload — used to be rejected outright with
# "Image is larger than the 12 MP limit", which reads as a broken install.
MAX_IMAGE_PIXELS = 12_000_000
# Beyond this, downscaling still means holding a multi-hundred-megabyte bitmap in
# memory, so it stays a hard refusal. 120 MP is far above any camera frame.
MAX_INPUT_PIXELS = 120_000_000
MAX_IMAGE_SIDE = 6_000
MAX_IMAGE_BYTES = 8_000_000


def decode_image(payload: bytes | str) -> "Any":
    """Decode raw image bytes or a base64 string into a PIL image.

    Oversized frames are downscaled to the detector's working size rather than
    refused: `VISION_IMAGE_SIZE` is 960 px, so a 4096x3072 phone photo costs a
    resize and nothing else. Only a genuinely bomb-sized canvas (over
    `MAX_INPUT_PIXELS`) and unreadable bytes are rejected.
    """
    Image = _require_pil()
    # PIL's own guard warns at this size before we ever resize. Keep it well
    # above anything we accept so a large-but-legitimate photo is not noisy.
    Image.MAX_IMAGE_PIXELS = MAX_INPUT_PIXELS
    if isinstance(payload, str):
        if len(payload) > MAX_IMAGE_BYTES * 2:
            raise ImageRejected("The image payload is too large")
        data = payload.split(",", 1)[-1] if payload.startswith("data:") else payload
        try:
            payload = base64.b64decode(data, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise ImageRejected("The image payload is not valid base64") from exc
    if len(payload) > MAX_IMAGE_BYTES:
        raise ImageRejected(
            f"The image is larger than the {MAX_IMAGE_BYTES // 1_000_000} MB limit"
        )
    try:
        with Image.open(io.BytesIO(payload)) as probe:
            width, height = probe.size
            if width * height > MAX_INPUT_PIXELS or max(width, height) > MAX_IMAGE_SIDE:
                raise ImageRejected(
                    f"Image is larger than the {MAX_INPUT_PIXELS // 1_000_000} MP limit"
                )
            probe.load()
            image = probe.copy()
    except ImageRejected:
        raise
    except Exception as exc:
        raise ImageRejected("The uploaded data is not a readable image") from exc

    # Fit inside both budgets, keeping the aspect ratio the detector expects.
    scale = 1.0
    if max(image.size) > MAX_IMAGE_SIDE:
        scale = min(scale, MAX_IMAGE_SIDE / max(image.size))
    if image.width * image.height > MAX_IMAGE_PIXELS:
        scale = min(scale, (MAX_IMAGE_PIXELS / (image.width * image.height)) ** 0.5)
    if scale < 1.0:
        target = (max(1, int(image.width * scale)), max(1, int(image.height * scale)))
        image = image.resize(target, Image.LANCZOS)
    return image


def frame_sharpness(image) -> float | None:
    """Laplacian variance of the frame, the same number `scan_image.py` prints.

    "No box at all" has two very different causes — a sticker too small to
    resolve, or a frame too soft to resolve anything — and this separates them
    at the moment of failure instead of asking the operator to guess.
    """
    try:
        import numpy as np
    except ImportError:
        return None
    try:
        pixels = np.asarray(image.convert("L"), dtype=np.float64)
    except Exception:  # noqa: BLE001 - a diagnostic must never break a scan
        return None
    if pixels.ndim != 2 or min(pixels.shape) < 3:
        return None
    lap = (
        -4.0 * pixels[1:-1, 1:-1]
        + pixels[:-2, 1:-1]
        + pixels[2:, 1:-1]
        + pixels[1:-1, :-2]
        + pixels[1:-1, 2:]
    )
    return float(lap.var())


def frame_brightness(image) -> float | None:
    """Mean luminance of the frame, 0-255. The other half of "the frame is unusable"."""
    try:
        import numpy as np
    except ImportError:
        return None
    try:
        pixels = np.asarray(image.convert("L"), dtype=np.float64)
    except Exception:  # noqa: BLE001 - a diagnostic must never break a scan
        return None
    if pixels.size == 0:
        return None
    return float(pixels.mean())


def quality_gate() -> str:
    """`VISION_QUALITY_GATE`: refuse (default) or off.

    A frame that is 98 % black costs 13 seconds of tiled inference and cannot
    produce a number. Refusing it before the model loads is the difference
    between a 0.2 s answer and a 13 s shrug.
    """
    raw = os.getenv("VISION_QUALITY_GATE", "refuse").strip().lower()
    return "off" if raw in {"off", "0", "false", "no", "none"} else "refuse"


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def min_frame_brightness() -> float:
    return _float_env("VISION_MIN_BRIGHTNESS", 12.0)


def min_frame_sharpness() -> float:
    return _float_env("VISION_MIN_SHARPNESS", 20.0)


def frame_problems(result: "DetectionResult") -> list[str]:
    """Measured reasons this frame cannot contain a detectable sticker."""
    problems: list[str] = []
    if result.frame_brightness is not None and result.frame_brightness < min_frame_brightness():
        problems.append(
            f"too dark (mean brightness {result.frame_brightness:.0f} of 255, "
            f"minimum {min_frame_brightness():.0f})"
        )
    if result.frame_sharpness is not None and result.frame_sharpness < min_frame_sharpness():
        problems.append(
            f"too soft (sharpness {result.frame_sharpness:.0f}, minimum {min_frame_sharpness():.0f})"
        )
    return problems


def frame_unusable_advice(result: "DetectionResult", problems: list[str]) -> str:
    shape = f" ({result.frame_width}×{result.frame_height})" if result.frame_width else ""
    return (
        f"Refused before inference{shape}: the frame is "
        + " and ".join(problems)
        + ". No threshold finds a sticker in a frame like this. Turn a light on the gate "
        "(or use the camera's own IR/illuminator), let autofocus settle, then scan again. "
        "Set VISION_QUALITY_GATE=off to scan anyway."
    )


def tile_settings() -> int:
    """`VISION_TILES`: 1 (default, off), 2-4, or `auto`.

    Tiling exists for one reason: a gate sticker that is ~20 px wide in a
    1280×720 frame never survives the letterbox, while the same sticker is
    comfortable once it is cropped out and enlarged. 0 means "decide per frame".
    """
    raw = os.getenv("VISION_TILES", "1").strip().lower()
    if raw in {"", "off", "none", "false", "0"}:
        return 1
    if raw == "auto":
        return 0
    try:
        return max(1, min(4, int(raw)))
    except ValueError:
        return 1


def tile_count(width: int, height: int, requested: int | None = None) -> int:
    """How many tiles per axis to use for a frame this size."""
    wanted = tile_settings() if requested is None else requested
    if wanted == 0:  # auto: a gate-sized frame gets 2×2, a small crop does not
        return 2 if max(width, height) >= 1024 else 1
    return max(1, min(4, wanted))


def tile_boxes(width: int, height: int, tiles: int) -> list[tuple[int, int, int, int]]:
    """Overlapping crops, 25 % of each tile, so a sticker on a seam is whole once."""
    if tiles <= 1 or width <= 0 or height <= 0:
        return [(0, 0, width, height)]
    boxes: list[tuple[int, int, int, int]] = []
    for row in range(tiles):
        for column in range(tiles):
            x0, y0 = int(column * width / tiles), int(row * height / tiles)
            x1, y1 = int((column + 1) * width / tiles), int((row + 1) * height / tiles)
            pad_x, pad_y = int((x1 - x0) * 0.25), int((y1 - y0) * 0.25)
            boxes.append(
                (max(0, x0 - pad_x), max(0, y0 - pad_y), min(width, x1 + pad_x), min(height, y1 + pad_y))
            )
    return boxes


def box_iou(first: list[int], second: list[int]) -> float:
    """Intersection over union of two [x1, y1, x2, y2] boxes."""
    left = max(first[0], second[0])
    top = max(first[1], second[1])
    right = min(first[2], second[2])
    bottom = min(first[3], second[3])
    if right <= left or bottom <= top:
        return 0.0
    overlap = (right - left) * (bottom - top)
    area_first = max(0, first[2] - first[0]) * max(0, first[3] - first[1])
    area_second = max(0, second[2] - second[0]) * max(0, second[3] - second[1])
    union = area_first + area_second - overlap
    return overlap / union if union > 0 else 0.0


def merge_rows(
    rows: list[tuple[float, int, list[int]]], iou_threshold: float = 0.45
) -> list[tuple[float, int, list[int]]]:
    """One sticker found in two overlapping tiles stays one box.

    Greedy NMS by confidence, per class: without it a tiled scan reports the
    same sticker twice and the OCR is asked to read it twice.
    """
    kept: list[tuple[float, int, list[int]]] = []
    for row in sorted(rows, key=lambda item: item[0], reverse=True):
        duplicate = any(
            other[1] == row[1] and box_iou(other[2], row[2]) >= iou_threshold for other in kept
        )
        if not duplicate:
            kept.append(row)
    return kept


def _predict_tiled(model, image, size: int, conf: float, tiles: int):
    """Run the detector over overlapping crops and merge what it finds."""
    width = getattr(image, "width", 0) or 0
    height = getattr(image, "height", 0) or 0
    if tiles <= 1 or not width or not height:
        return _predict_rows(model, image, size, conf)
    found: list[tuple[float, int, list[int]]] = []
    for x0, y0, x1, y1 in tile_boxes(width, height, tiles):
        crop = image.crop((x0, y0, x1, y1))
        for confidence, class_id, bbox in _predict_rows(model, crop, size, conf):
            found.append(
                (confidence, class_id, [bbox[0] + x0, bbox[1] + y0, bbox[2] + x0, bbox[3] + y0])
            )
    return merge_rows(found)


def max_crops() -> int:
    """Maximum number of sticker crops that are OCR'd in a single frame."""
    try:
        value = int(os.getenv("VISION_MAX_CROPS", "8"))
    except ValueError:
        return 8
    return max(1, value)


def _predict_rows(model, image, size: int, conf: float) -> list[tuple[float, int, list[int]]]:
    """Run one forward pass and return sorted (confidence, class, bbox) rows."""
    results = model.predict(source=image, conf=conf, imgsz=size, verbose=False)
    if not results:
        return []
    boxes = getattr(results[0], "boxes", None)
    if boxes is None or len(boxes) == 0:
        return []
    rows = [
        (
            float(boxes.conf[index].item()),
            int(boxes.cls[index].item()),
            [int(value) for value in boxes.xyxy[index].tolist()],
        )
        for index in range(len(boxes))
    ]
    # Ultralytics sorts by confidence already; do not rely on it.
    rows.sort(key=lambda row: row[0], reverse=True)
    return rows


def sticker_upscale() -> int:
    """How much a small *sticker* crop is enlarged before OCR.

    `VISION_STICKER_UPSCALE`, default 1 (off). The sticker path is validated as
    it is, so it stays off by default; but a sticker that is 50 px wide in the
    frame — which tiling can find at 0.85 while the OCR cannot read it — gets
    three times the pixels with this on, and the number usually appears.
    """
    try:
        value = int(os.getenv("VISION_STICKER_UPSCALE", "1"))
    except ValueError:
        return 1
    return max(1, min(6, value))


def _prepare_crop_for_ocr(crop, factor: int):
    """Enlarge a small crop so the OCR has pixels to work with."""
    size = getattr(crop, "size", None)
    try:
        if not size or len(size) != 2:
            return crop  # not a plain 2-D crop: hand it to the OCR untouched
        width, height = int(size[0]), int(size[1])
    except (TypeError, ValueError):
        return crop
    if width <= 0 or height <= 0:
        return crop
    if factor <= 1 or width >= 480:
        return crop
    try:
        Image = _require_pil()
    except VisionUnavailable:
        # No Pillow on this host: the OCR still gets the original crop.
        return crop
    resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS", 1)
    try:
        return crop.resize((width * factor, height * factor), resample)
    except Exception:  # pragma: no cover - defensive
        return crop


def _prepare_plate_crop(crop):
    """The plate stage's enlargement, see `plate_upscale`."""
    return _prepare_crop_for_ocr(crop, plate_upscale())


def _ocr_rows(
    image,
    rows: list[tuple[float, int, list[int]]],
    names: dict,
    *,
    threshold: float,
    limit: int,
    class_filter: int | None = None,
    upscale: bool = False,
    upscale_factor: int | None = None,
) -> list[PlateCandidate]:
    """Crop the boxes above `threshold` and OCR each one.

    `class_filter` keeps a single class id; `None` keeps every class, which is
    what a single-class number-plate checkpoint (`Class 0 = licence`) needs.
    `upscale` applies the plate enlargement; `upscale_factor` applies an
    explicit one (the sticker path passes `VISION_STICKER_UPSCALE`).
    """
    candidates: list[PlateCandidate] = []
    for confidence, class_id, coords in rows:
        if confidence < threshold:
            break  # everything after this one is weaker still
        if class_filter is not None and class_id != class_filter:
            continue
        if len(candidates) >= limit:
            break
        class_name = names.get(class_id, CLASS_LABELS.get(class_id, str(class_id)))
        candidate = PlateCandidate(
            confidence=confidence,
            bbox=coords,
            class_id=class_id,
            class_name=str(class_name),
        )
        crop = _crop(image, coords)
        if crop is not None:
            if upscale_factor and upscale_factor > 1:
                crop = _prepare_crop_for_ocr(crop, upscale_factor)
            elif upscale:
                crop = _prepare_plate_crop(crop)
            try:
                raw = read_text(crop)
            except VisionUnavailable as exc:
                logger.info("OCR unavailable for this frame: %s", exc)
                raw = ""
            candidate.raw_text = raw.strip()
            candidate.bus_number = normalize_plate(candidate.raw_text)
        candidates.append(candidate)
    return candidates


def _stage_outcome(candidates: list[PlateCandidate]) -> str:
    if any(candidate.bus_number for candidate in candidates):
        return "identified"
    return "seen_unreadable" if candidates else "none"


def _run_sticker_stage(image, result: DetectionResult, *, model=None, threshold: float, size: int) -> None:
    """Stage 1: the trained sticker/red-circle checkpoint (best.pt)."""
    import time

    report = StageReport(name=STAGE_STICKER, enabled=True, model=str(model_path().name))
    result.stages.append(report)
    started = time.perf_counter()

    # A missing sticker model is the one failure that still means "the detector
    # is not installed": raise, so the API keeps answering 503 with the checklist.
    model = model or load_model()

    rows = _predict_tiled(model, image, size, min(threshold, 0.05), result.tiles)
    report.ran = True
    report.ms = int((time.perf_counter() - started) * 1000)

    names = getattr(model, "names", {}) or {}
    sticker_id = sticker_class_id(model)
    result.sticker_class = sticker_id
    result.boxes_total = len(rows)
    result.best_confidence = rows[0][0] if rows else 0.0
    # Only the sticker class reaches the OCR. The red circle is a box around the
    # same bus: cropping it costs an OCR call and yields no number.
    result.boxes_other_class = sum(
        1 for confidence, class_id, _ in rows if confidence >= threshold and class_id != sticker_id
    )
    result.candidates = _ocr_rows(
        image,
        rows,
        names,
        threshold=threshold,
        limit=max_crops(),
        class_filter=sticker_id,
        upscale_factor=sticker_upscale(),
    )
    result.boxes_above_threshold = len(result.candidates)

    report.found = len(result.candidates)
    report.best_confidence = max((candidate.confidence for candidate in result.candidates), default=0.0)
    report.result = _stage_outcome(result.candidates)


def _run_plate_stage(image, result: DetectionResult, *, threshold: float, size: int) -> None:
    """Stage 2: an optional number-plate checkpoint, used when no sticker read."""
    import time

    path = plate_model_path()
    report = StageReport(name=STAGE_NUMBER_PLATE, enabled=True, model=str(path.name))
    result.stages.append(report)
    started = time.perf_counter()

    if not path.exists():
        report.skipped = "model_missing"
        report.detail = (
            f"No number-plate checkpoint at {path}. Put an ANPR model there (the bundled "
            "anpr_best.pt is the default) or point VISION_PLATE_MODEL_PATH at one."
        )
        return
    gate = plate_threshold()
    try:
        model = load_stage_model(STAGE_NUMBER_PLATE)
        rows = _predict_rows(model, image, size, min(gate, 0.05))
    except StageNotConfigured as exc:
        report.skipped = exc.reason
        report.detail = str(exc)
        return
    except Exception as exc:  # pragma: no cover - defensive
        report.skipped = "error"
        report.detail = f"{type(exc).__name__}: {exc}"
        return

    report.ran = True
    report.ms = int((time.perf_counter() - started) * 1000)
    names = getattr(model, "names", {}) or {}
    result.plate_candidates = _ocr_rows(
        image,
        rows,
        names,
        threshold=gate,
        limit=max_crops(),
        upscale=True,
    )
    report.found = len(result.plate_candidates)
    report.best_confidence = max(
        (candidate.confidence for candidate in result.plate_candidates), default=0.0
    )
    report.result = _stage_outcome(result.plate_candidates)
    if not report.detail:
        report.detail = (
            f"{path.name} · classes: "
            + ", ".join(str(name) for name in sorted(names.values()))
            + f" · gate {gate:.2f}"
        )


def _run_vehicle_stage(image, result: DetectionResult, *, threshold: float, size: int) -> None:
    """Stage 3: bus / car / bike classification, independent of the number."""
    import time

    path = vehicle_model_path()
    report = StageReport(name=STAGE_VEHICLE, enabled=True, model=str(path.name))
    result.stages.append(report)
    started = time.perf_counter()

    if not path.exists():
        report.skipped = "model_missing"
        report.detail = (
            f"No vehicle checkpoint at {path}. Copy yolo11n.pt (or any COCO model) there, "
            "or set VISION_VEHICLE_MODEL_PATH."
        )
        return
    try:
        model = load_stage_model(STAGE_VEHICLE)
        rows = _predict_rows(model, image, size, min(vehicle_threshold(), 0.05))
    except StageNotConfigured as exc:
        report.skipped = exc.reason
        report.detail = str(exc)
        return
    except Exception as exc:  # pragma: no cover - defensive
        report.skipped = "error"
        report.detail = f"{type(exc).__name__}: {exc}"
        return

    report.ran = True
    report.ms = int((time.perf_counter() - started) * 1000)
    names = getattr(model, "names", {}) or {}
    accepted = vehicle_classes()
    gate = vehicle_threshold()
    best: tuple[float, str, list[int]] | None = None
    for confidence, class_id, coords in rows:
        if confidence < gate:
            break
        class_name = str(names.get(class_id, class_id)).strip().lower()
        if class_name not in accepted:
            continue
        if best is None or confidence > best[0]:
            best = (confidence, class_name, coords)

    if best is None:
        report.result = "none"
        return
    report.found = 1
    report.best_confidence = best[0]
    report.result = "identified"
    result.vehicle = {
        "label": vehicle_label(best[1]),
        "class_name": best[1],
        "confidence": round(float(best[0]), 4),
        "bbox": list(best[2]),
        "model": str(path.name),
    }


def _cascade_name(result: DetectionResult) -> str:
    """Which stage produced the answer for this frame."""
    if any(candidate.bus_number for candidate in result.candidates):
        return STAGE_STICKER
    if any(candidate.bus_number for candidate in result.plate_candidates):
        return STAGE_NUMBER_PLATE
    if result.vehicle:
        return STAGE_VEHICLE
    return CASCADE_NONE


def detect(
    image,
    *,
    model=None,
    threshold: float | None = None,
    stages=None,
) -> DetectionResult:
    """Run the detection cascade over an image.

    Sticker first: `best.pt` localises the sticker panel and the OCR reads the
    number out of it. If that yields no number, the optional number-plate
    checkpoint gets a turn, and the optional vehicle stage classifies what is in
    the frame (bus / car / bike / truck) whether or not a number was read.

    `stages` overrides the per-host switches for this one call, e.g.
    `{"sticker": False}`. Every stage is asked for boxes down to 0.05 and
    filtered here, so a "nothing found" answer can say *why*.
    """
    import time

    enabled = normalize_stages(stages)
    threshold = confidence_threshold() if threshold is None else threshold
    size = image_size()
    started = time.perf_counter()

    result = DetectionResult(
        model=str(model_path().name),
        frame_width=getattr(image, "width", 0) or 0,
        frame_height=getattr(image, "height", 0) or 0,
        threshold=float(threshold),
        image_size=size,
        stage_flags=dict(enabled),
        frame_sharpness=frame_sharpness(image),
        frame_brightness=frame_brightness(image),
        tiles=tile_count(
            getattr(image, "width", 0) or 0, getattr(image, "height", 0) or 0
        ),
    )

    problems = frame_problems(result)
    if problems and quality_gate() == "refuse":
        # Asked and answered without touching a checkpoint: this frame cannot
        # contain a readable sticker, and the caller gets the measurements.
        for stage in STAGE_ORDER:
            result.stages.append(
                StageReport(
                    name=stage,
                    enabled=enabled[stage],
                    skipped="frame_unusable",
                    detail=frame_unusable_advice(result, problems),
                )
            )
        result.reason = "frame_unusable"
        result.advice = frame_unusable_advice(result, problems)
        result.inference_ms = int((time.perf_counter() - started) * 1000)
        result.cascade = CASCADE_NONE
        return result

    if enabled[STAGE_STICKER]:
        _run_sticker_stage(image, result, model=model, threshold=threshold, size=size)
    else:
        result.stages.append(StageReport(
            name=STAGE_STICKER,
            enabled=False,
            model=str(model_path().name),
            skipped="disabled",
            detail="Sticker detection is switched off for this scan.",
        ))

    number_read = any(candidate.bus_number for candidate in result.candidates)
    if not enabled[STAGE_NUMBER_PLATE]:
        result.stages.append(StageReport(
            name=STAGE_NUMBER_PLATE,
            enabled=False,
            model=str(plate_model_path().name),
            skipped="disabled",
            detail="Number-plate detection is switched off for this scan.",
        ))
    elif number_read:
        result.stages.append(StageReport(
            name=STAGE_NUMBER_PLATE,
            enabled=True,
            model=str(plate_model_path().name),
            skipped="not_needed",
            detail="The sticker stage already read a number from this frame.",
        ))
    else:
        _run_plate_stage(image, result, threshold=threshold, size=size)

    if enabled[STAGE_VEHICLE]:
        _run_vehicle_stage(image, result, threshold=threshold, size=size)
    else:
        result.stages.append(StageReport(
            name=STAGE_VEHICLE,
            enabled=False,
            model=str(vehicle_model_path().name),
            skipped="disabled",
            detail="Vehicle classification is switched off for this scan.",
        ))

    result.inference_ms = int((time.perf_counter() - started) * 1000)
    result.cascade = _cascade_name(result)
    return _explain(result)


def no_detection_advice(result: DetectionResult) -> str:
    """Explain a zero-box scan with the numbers that were actually measured.

    The old text ("point the camera at the sticker, fill more of the frame")
    was the same sentence for a lens that never focused and for a sticker 15 px
    wide, so it could not be acted on. This names the frame size, the sharpness
    and whether the scan was tiled, then gives the fix that matches.
    """
    facts = []
    if result.frame_width and result.frame_height:
        facts.append(f"frame {result.frame_width}×{result.frame_height}")
    soft = result.frame_sharpness is not None and result.frame_sharpness < 60
    if result.frame_sharpness is not None:
        facts.append(f"sharpness {result.frame_sharpness:.0f}" + (" (soft)" if soft else ""))
    if result.tiles > 1:
        facts.append(f"{result.tiles}×{result.tiles} tiled at {result.image_size}px")
    measured = f" — {', '.join(facts)}" if facts else ""

    hints = []
    if soft:
        hints.append("clean the lens and let the camera focus before scanning again")
    if result.tiles <= 1:
        hints.append(
            "if the sticker is smaller than about 45 px in the frame, set VISION_TILES=2 "
            "(or auto) to infer on overlapping crops"
        )
    hints.append("move closer so the sticker fills more of the frame")
    hints.append("confirm the checkpoint matches these stickers: python scripts/inspect_model.py")
    return f"No box at all, even at 0.05 confidence{measured}. Try: " + "; ".join(hints) + "."


def _explain(result: DetectionResult) -> DetectionResult:
    """Fill in `reason`/`advice` so the caller never has to guess."""
    readable = [candidate for candidate in result.candidates if candidate.bus_number]

    # A number read by the plate stage is just as good an answer as one read
    # from a sticker, so the reason stays "ok" whichever stage found it.
    if not readable and any(candidate.bus_number for candidate in result.plate_candidates):
        result.reason = "ok"
        result.advice = ""
        return result

    sticker_named = CLASS_LABELS.get(result.sticker_class, f"class {result.sticker_class}")

    if result.boxes_total == 0:
        result.reason = "no_detection"
        result.advice = no_detection_advice(result)
    elif not result.candidates and result.boxes_other_class:
        # The red circle was found, the sticker panel was not: usually a bus
        # whose sticker is dirty, in shadow, or half out of frame.
        result.reason = "other_class"
        result.advice = (
            f"{result.boxes_other_class} box(es) of another class were found, none of "
            f"{sticker_named} (class {result.sticker_class}). The painted ring is visible but the "
            "sticker panel is not: check the mounting, clean the sticker, or lower VISION_CONFIDENCE."
        )
    elif not result.candidates:
        result.reason = "below_threshold"
        result.advice = (
            f"{result.boxes_total} box(es) found, best {result.best_confidence:.2f} is under the "
            f"{result.threshold:.2f} threshold. Lower VISION_CONFIDENCE (0.15-0.25) to confirm the "
            "sticker is being seen, or raise VISION_IMAGE_SIZE when it is small in the frame."
        )
    elif not readable:
        largest = max(
            (abs(candidate.bbox[2] - candidate.bbox[0]) for candidate in result.candidates),
            default=0,
        )
        result.reason = "unreadable"
        factor = sticker_upscale()
        if factor <= 1:
            # Raising VISION_IMAGE_SIZE does nothing here: the crop is taken from
            # the frame's own pixels, not from the letterboxed inference image.
            hint = (
                "that is small for the OCR, and raising VISION_IMAGE_SIZE will not change it — "
                "set VISION_STICKER_UPSCALE=3 to enlarge the crop before reading, or scan from closer"
            )
        else:
            hint = (
                f"still small even at VISION_STICKER_UPSCALE={factor}: scan from closer, or install a "
                "stronger OCR engine (see docs/DETECTION.md)"
            )
        result.advice = (
            f"Sticker detected at {result.candidates[0].confidence:.2f} but the OCR read no text. "
            f"The crop was about {largest} px wide — {hint}."
        )
    else:
        result.reason = "ok"
        result.advice = ""

    if result.reason != "ok":
        notes = [
            f"{STAGE_LABELS.get(stage.name, stage.name)}: {stage.detail}"
            for stage in result.stages
            if stage.skipped in {"disabled", "model_missing", "not_installed", "load_failed", "error"}
            and stage.detail
        ]
        if notes:
            result.advice = " ".join([result.advice, *notes]).strip()
    return result


def _crop(image, coords: list[int]):
    """Crop a bbox out of a PIL image, returning None when it is degenerate."""
    try:
        left, top, right, bottom = coords
    except (TypeError, ValueError):
        return None
    width = getattr(image, "width", 0)
    height = getattr(image, "height", 0)
    left = max(0, min(left, width - 1))
    top = max(0, min(top, height - 1))
    right = max(left + 1, min(right, width))
    bottom = max(top + 1, min(bottom, height))
    if right <= left or bottom <= top:
        return None
    return image.crop((left, top, right, bottom))


def best_identification(result: DetectionResult) -> PlateCandidate | None:
    """Best candidate across the cascade: a readable number always wins.

    Sticker candidates are preferred over plate candidates at equal standing
    because the sticker is the trained-in path and its crop is the one the
    operators recognise.
    """
    for pool in (result.candidates, result.plate_candidates):
        with_number = [candidate for candidate in pool if candidate.bus_number]
        if with_number:
            return max(with_number, key=lambda candidate: candidate.confidence)
    pool = result.candidates or result.plate_candidates
    if not pool:
        return None
    return max(pool, key=lambda candidate: candidate.confidence)


def best_candidate(result: DetectionResult) -> PlateCandidate | None:
    """Pick the most trustworthy candidate: a readable number beats confidence."""
    if not result.candidates:
        return None
    with_number = [candidate for candidate in result.candidates if candidate.bus_number]
    pool = with_number or result.candidates
    return max(pool, key=lambda candidate: candidate.confidence)


# --------------------------------------------------------------------------- #
# Health reporting
# --------------------------------------------------------------------------- #
def _module_present(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:  # ImportError plus any broken native dependency
        return False


def vision_setup() -> dict[str, Any]:
    """The one-screen install checklist the Test Lab shows.

    A missing Pillow used to surface as a bare `503` sentence with a single
    "install the vision extras" line. That is not actionable on a machine that
    half-installed the stack, so every component reports its own state and the
    exact command that fixes it.
    """
    requirements = "-r backend/requirements-vision.txt"
    rows = [
        {
            "name": "torch",
            "label": "PyTorch (model runtime)",
            "present": _module_present("torch"),
            "size": "~200 MB (CPU wheel)",
            "command": "python -m pip install torch==2.9.1 torchvision==0.24.1 --index-url https://download.pytorch.org/whl/cpu",
        },
        {
            "name": "ultralytics",
            "label": "Ultralytics (YOLO loader)",
            "present": _module_present("ultralytics"),
            "size": "~15 MB",
            "command": "python -m pip install ultralytics==8.4.20",
        },
        {
            "name": "opencv",
            "label": "OpenCV headless (framing)",
            "present": _module_present("cv2"),
            "size": "~35 MB",
            "command": "python -m pip install opencv-python-headless==4.10.0.84",
        },
        {
            "name": "Pillow",
            "label": "Pillow (image decode)",
            "present": _module_present("PIL"),
            "size": "~4 MB",
            "command": 'python -m pip install "Pillow>=10.0.0"',
        },
        {
            "name": "ocr",
            "label": "OCR engine (reads the sticker)",
            "present": _ocr_usable(),
            "size": "~60 MB (RapidOCR, no system packages)",
            "command": "python -m pip install rapidocr-onnxruntime==1.4.4",
        },
        {
            "name": "model",
            "label": "best.pt (sticker model)",
            "present": DEFAULT_MODEL_PATH.exists(),
            "size": "5.5 MB, tracked in git",
            "command": "git checkout -- best.pt   # restore the tracked weights",
        },
        {
            "name": "anpr",
            "label": "anpr_best.pt (number-plate model)",
            "present": plate_model_path().exists(),
            "size": "5.8 MB, tracked in git",
            "command": "git checkout -- anpr_best.pt   # restore the tracked weights",
            "optional": True,
        },
    ]
    # Only required components gate `ready`: the plate and vehicle stages are
    # optional, and a missing one is a skipped stage, not a broken detector.
    missing = [row for row in rows if not row["present"] and not row.get("optional")]
    return {
        "ready": not missing,
        "missing": [row["name"] for row in missing],
        "components": rows,
        "install_all": f"python -m pip install {requirements}",
        "note": (
            "Everything stays optional: without these the console, tables, filters and "
            "exports work normally and only the detector answers 503 with this checklist."
        ),
    }


def _ocr_usable() -> bool:
    """True when at least one configured OCR backend can be imported."""
    engine = ocr_engine_name()
    if engine == "none":
        return False
    probes = ("rapidocr", "tesseract", "easyocr") if engine == "auto" else (engine,)
    loaders = {"rapidocr": _ocr_rapidocr, "tesseract": _ocr_tesseract, "easyocr": _ocr_easyocr}
    for probe in probes:
        try:
            loaders[probe]()
            return True
        except (VisionUnavailable, KeyError):
            continue
    return False


def stage_status() -> list[dict[str, Any]]:
    """Describe each cascade stage for the status endpoint and the panel."""
    paths = {
        STAGE_STICKER: model_path(),
        STAGE_NUMBER_PLATE: plate_model_path(),
        STAGE_VEHICLE: vehicle_model_path(),
    }
    default_paths = {
        STAGE_STICKER: DEFAULT_MODEL_PATH,
        STAGE_NUMBER_PLATE: DEFAULT_PLATE_MODEL_PATH,
        STAGE_VEHICLE: DEFAULT_VEHICLE_MODEL_PATH,
    }
    notes = {
        STAGE_STICKER: "Runs first: localises the sticker panel and OCRs the bus number.",
        STAGE_NUMBER_PLATE: "Runs only when the sticker stage reads no number.",
        STAGE_VEHICLE: "Classifies bus / car / bike / truck; runs every scan.",
    }
    rows: list[dict[str, Any]] = []
    for stage in STAGE_ORDER:
        path = paths[stage]
        rows.append({
            "name": stage,
            "label": STAGE_LABELS[stage],
            "enabled": stage_enabled(stage),
            "env": STAGE_ENV[stage],
            "model": str(path),
            "model_present": path.exists(),
            # Bundled = tracked in git and shipped with the repo (best.pt,
            # anpr_best.pt). weights/vehicle.pt is fetched, never shipped.
            "bundled": path in {DEFAULT_MODEL_PATH, DEFAULT_PLATE_MODEL_PATH},
            "required": stage == STAGE_STICKER,
            "note": notes[stage],
        })
    return rows


def vision_status() -> dict[str, Any]:
    """Describe what the vision stack can currently do."""
    path = model_path()
    loaded = _model_cache.get("model")
    status: dict[str, Any] = {
        "model_path": str(path),
        "model_present": path.exists(),
        "model_loaded": loaded is not None,
        "confidence_threshold": confidence_threshold(),
        "image_size": image_size(),
        "sticker_class": sticker_class_id(loaded),
        "sticker_class_name": str(
            (getattr(loaded, "names", None) or CLASS_LABELS).get(
                sticker_class_id(loaded), f"class {sticker_class_id(loaded)}"
            )
        ),
        "ocr_engine": ocr_engine_name(),
        # The labels the loaded checkpoint actually carries. A freshly trained
        # number-plate model (one class, "number_plate") must not be described
        # with this repository's old sticker/red-circle pair.
        "classes": {
            str(key): value
            for key, value in (
                (getattr(loaded, "names", None) or CLASS_LABELS).items()
            )
        },
        "classes_source": "model" if loaded is not None else "default",
        # Every stage of the cascade, with the switch state the panel starts
        # from and whether its optional checkpoint is on disk.
        "stages": stage_status(),
        "available": False,
        "problems": [],
    }
    if not path.exists():
        status["problems"].append(f"Model file missing at {path}")

    try:
        import torch  # type: ignore  # noqa: F401
    except ImportError:
        status["problems"].append("torch is not installed")
    try:
        import ultralytics  # type: ignore  # noqa: F401
    except ImportError:
        status["problems"].append("ultralytics is not installed")
    try:
        import cv2  # type: ignore  # noqa: F401
    except ImportError:
        status["problems"].append("opencv is not installed")
    try:
        import PIL  # type: ignore  # noqa: F401
    except ImportError:
        status["problems"].append("Pillow is not installed")

    engine = ocr_engine_name()
    if engine != "none":
        usable = False
        for probe in ("rapidocr", "tesseract", "easyocr"):
            try:
                if probe == "rapidocr":
                    _ocr_rapidocr()
                elif probe == "tesseract":
                    _ocr_tesseract()
                else:
                    _ocr_easyocr()
                usable = True
                status["ocr_available"] = probe
                break
            except VisionUnavailable:
                continue
        if not usable:
            status["problems"].append(
                "no OCR engine is usable (install rapidocr-onnxruntime, tesseract-ocr or easyocr)"
            )
    else:
        status["problems"].append("OCR is disabled (VISION_OCR_ENGINE=none)")

    status["available"] = not status["problems"]
    status["setup"] = vision_setup()
    return status
