from __future__ import annotations

import json
from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "detection"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def test_detection_fixtures_match_expected():
    images = sorted(path for path in FIXTURE_DIR.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    if not images:
        pytest.skip("no owner-supplied detection fixture images")
    expected = json.loads((FIXTURE_DIR / "expected.json").read_text())
    missing = [path.name for path in images if path.name not in expected]
    assert not missing, f"add expected values for: {', '.join(missing)}"
    try:
        from backend.vision import best_identification, decode_image, detect
    except Exception as exc:
        pytest.skip(f"vision stack unavailable: {exc}")

    for path in images:
        result = detect(decode_image(path.read_bytes()))
        candidate = best_identification(result)
        actual = candidate.bus_number if candidate else None
        assert actual == expected[path.name], f"{path.name}: expected {expected[path.name]!r}, got {actual!r}"
