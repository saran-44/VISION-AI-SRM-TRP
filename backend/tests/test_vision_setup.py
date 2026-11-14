"""The Test Lab's detector checklist.

A missing package used to surface as one sentence inside a 503. These tests pin
the structured form the UI renders: one row per component, an explicit boolean,
and the command that fixes it.
"""
from __future__ import annotations

from backend.vision import vision_setup, vision_status

COMPONENTS = ["torch", "ultralytics", "opencv", "Pillow", "ocr", "model"]


def test_every_component_is_reported_with_a_fix():
    setup = vision_setup()

    assert [row["name"] for row in setup["components"]] == COMPONENTS
    for row in setup["components"]:
        assert isinstance(row["present"], bool)
        assert row["label"] and row["size"]
        # A missing component must carry a command; a present one keeps it for
        # the "copy everything" button.
        assert row["command"].startswith(("python -m pip", "git checkout"))


def test_ready_means_nothing_is_missing():
    setup = vision_setup()
    assert setup["ready"] is (not setup["missing"])
    assert set(setup["missing"]) <= set(COMPONENTS)
    assert setup["ready"] is (len(setup["missing"]) == 0)


def test_missing_list_matches_the_component_flags():
    setup = vision_setup()
    expected = [row["name"] for row in setup["components"] if not row["present"]]
    assert setup["missing"] == expected


def test_install_all_names_the_pinned_file():
    assert "requirements-vision" in vision_setup()["install_all"]


def test_status_embeds_the_setup_block():
    """The checks endpoint returns `detection.setup`, which the UI renders."""
    status = vision_status()
    assert status["setup"]["components"]
    # `available` stays the authoritative "can a scan work" flag.
    assert status["available"] is (not status["problems"])


# ------------------------------------------------------------ model swapping
def test_image_size_is_configurable_and_clamped(monkeypatch):
    from backend.vision import image_size

    monkeypatch.setenv("VISION_IMAGE_SIZE", "960")
    assert image_size() == 960
    monkeypatch.setenv("VISION_IMAGE_SIZE", "1280")
    assert image_size() == 1280
    monkeypatch.setenv("VISION_IMAGE_SIZE", "64")
    assert image_size() == 320
    monkeypatch.setenv("VISION_IMAGE_SIZE", "99999")
    assert image_size() == 1536
    monkeypatch.setenv("VISION_IMAGE_SIZE", "not-a-number")
    assert image_size() == 960
    monkeypatch.delenv("VISION_IMAGE_SIZE", raising=False)
    assert image_size() == 960


def test_status_labels_come_from_a_loaded_number_plate_model():
    """A one-class plate checkpoint must not be described as sticker/red circle."""
    from types import SimpleNamespace

    import backend.vision as vision

    vision._model_cache["model"] = SimpleNamespace(names={0: "number_plate"})
    try:
        status = vision.vision_status()
        assert status["classes"] == {"0": "number_plate"}
        assert status["classes_source"] == "model"
        assert status["model_loaded"] is True
    finally:
        vision._model_cache.pop("model", None)


def test_status_falls_back_to_the_builtin_labels_without_a_model():
    import backend.vision as vision

    vision._model_cache.pop("model", None)
    status = vision.vision_status()
    assert status["classes_source"] == "default"
    assert status["classes"]["1"] == "sticker"
