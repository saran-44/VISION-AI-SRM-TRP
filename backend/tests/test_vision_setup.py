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
