"""Tests for scripts/frame_report.py — the "what is actually in this frame?" tool."""

from __future__ import annotations

import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "frame_report.py"

pytest.importorskip("PIL", reason="frame_report reads images with Pillow")


def _grey_png(width: int, height: int, pixel) -> bytes:
    """A greyscale PNG built from the standard library only."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    raw = b"".join(
        b"\x00" + bytes(pixel(x, y) for x in range(width)) for y in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=120,
    )


def test_a_flat_frame_is_reported_as_uniform(tmp_path: Path) -> None:
    """A covered lens has no subject in it, and the report must say so."""
    frame = tmp_path / "flat.png"
    frame.write_bytes(_grey_png(64, 48, lambda x, y: 128))

    completed = _run(str(frame))

    assert completed.returncode == 0, completed.stderr
    assert "nearly uniform" in completed.stdout
    assert "luminance map" in completed.stdout


def test_a_frame_with_real_contrast_reports_detail_and_sharpness(tmp_path: Path) -> None:
    frame = tmp_path / "half.png"
    frame.write_bytes(_grey_png(64, 48, lambda x, y: 0 if x < 32 else 255))

    completed = _run(str(frame))

    assert completed.returncode == 0, completed.stderr
    assert "sharpness" in completed.stdout
    assert "nearly uniform" not in completed.stdout
    # The map must show both a dark and a bright side.
    assert "#" in completed.stdout or "@" in completed.stdout


def test_a_folder_is_expanded(tmp_path: Path) -> None:
    for name in ("a.png", "b.png"):
        (tmp_path / name).write_bytes(_grey_png(32, 24, lambda x, y: 40 + x * 4))

    completed = _run(str(tmp_path))

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.count("brightness") == 2


def test_an_unreadable_file_exits_non_zero(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jpg"
    broken.write_bytes(b"not an image")

    completed = _run(str(broken))

    assert completed.returncode == 2
    assert "not a readable image" in completed.stderr
