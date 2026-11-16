"""Everything that goes wrong, written down where it can be copied.

The gate PC runs the portal with its console hidden, so a traceback that only
reaches stderr is lost by the time anyone looks. This module appends labelled
blocks to `<data dir>/logs/errors.log` — one block per failure, never raising,
never holding a secret — and `backend/report.py` turns that file plus the live
configuration into a single text block the operator can paste into a bug report.

Two kinds of block:

    --- 2026-11-13T09:12:44+05:30 ERROR ref=3f9c1a2b
    message  : RuntimeError: detector exploded
    request  : POST /api/detection/scan from 127.0.0.1
    traceback:
    Traceback (most recent call last): ...

    --- 2026-11-13T09:12:44+05:30 SCAN ref=8b1e04cc
    reason   : unreadable
    frame    : 1280x720 sharpness 93 brightness 142 tiles 1
    advice   : Sticker detected at 0.85 but the OCR read no text. ...

`VISION_ERROR_LOG=false` switches it off; a full log is rotated once to
`errors.log.1` and then started again, so the file never grows without bound.
"""

from __future__ import annotations

import os
import re
import traceback
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ERROR_LOG_MAX_BYTES = 1_000_000
MAX_DETAIL_LINES = 60

# Anything that looks like a credential is replaced before it reaches the file.
# The report is meant to be pasted into a chat window, so this is the only
# thing standing between an RTSP password and the internet.
_REDACTIONS: list[tuple[re.Pattern[str], str]] = [
    # rtsp://admin:hunter2@10.0.0.5/... -> rtsp://admin:***@10.0.0.5/...
    (re.compile(r"\b([a-zA-Z][a-zA-Z0-9+.\-]*://[^:/@\s]+):[^@/\s]+@"), r"\1:***@"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer ***"),
    (re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{4,}"), "<jwt>"),
    (re.compile(r"\$argon2[a-z0-9]*\$[^\s'\"]+"), "<argon2-hash>"),
    (
        # No leading \b: the key is usually inside a longer name
        # (VISION_DEVICE_KEY=...) where an underscore is already a word char.
        re.compile(
            r"(?i)(password|passwd|pwd|secret|token|api[_-]?key|device[_-]?key|"
            r"authorization|x-device-key)\s*[=:]\s*[^\s,;]+"
        ),
        r"\1=***",
    ),
]


# ------------------------------------------------------------------- paths
def data_root() -> Path:
    """The same directory the launcher and the portal use for their data."""
    override = os.getenv("VISION_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(root) / "VisionAI"
    return Path.home() / ".visionai"


def logs_dir() -> Path:
    return data_root() / "logs"


def failed_crops_dir() -> Path:
    """The exact pixels the OCR was given, when it read nothing."""
    return data_root() / "failed-crops"


def failed_frames_dir() -> Path:
    """Where a scan that produced no number leaves its frame.

    Resolved here rather than in the two callers, because they disagreed: on
    Windows the portal wrote to PROGRAMDATA/VisionAI/failed-frames while the
    preflight reported (and checked) the home folder, so the "data folder" line
    in a report described a directory nothing wrote to.
    """
    return data_root() / "failed-frames"


def error_log_path() -> Path:
    return logs_dir() / "errors.log"


def enabled() -> bool:
    return os.getenv("VISION_ERROR_LOG", "true").strip().lower() not in {"0", "false", "no", "off"}


# --------------------------------------------------------------- redaction
def redact(text: str) -> str:
    """Strip passwords, keys and tokens out of `text`."""
    if not text:
        return ""
    cleaned = str(text)
    for pattern, replacement in _REDACTIONS:
        cleaned = pattern.sub(replacement, cleaned)
    return cleaned


# ----------------------------------------------------------------- writing
def _timestamp() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _rotate(path: Path) -> None:
    try:
        if path.exists() and path.stat().st_size > ERROR_LOG_MAX_BYTES:
            backup = path.parent / (path.name + ".1")
            if backup.exists():
                backup.unlink()
            path.rename(backup)
    except OSError:
        pass  # a full disk must not break the scan that is failing


def log_block(kind: str, *, lines: list[str] | None = None, request=None) -> str:
    """Append one block and return its reference (`ref=` in the header).

    Never raises: this runs inside error handlers, where a second exception
    would hide the first.
    """
    ref = uuid.uuid4().hex[:8]
    if not enabled():
        return ref
    try:
        parts = [f"--- {_timestamp()} {kind.upper()} ref={ref}"]
        if request is not None:
            try:
                parts.append(
                    f"request  : {request.method} {request.path} from {request.remote_addr}"
                )
            except Exception:  # noqa: BLE001 - a strange request object is not an error
                pass
        for line in lines or []:
            if line:
                parts.append(line)
        payload = redact("\n".join(parts)) + "\n\n"
        path = error_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(payload)
        # A hosted deployment (Render, Fly, Railway) has an ephemeral disk, so
        # the file dies with the container and `--report` cannot read it. The
        # platform's log stream is the only thing that survives there, so every
        # block is mirrored to it as well.
        logger.log(logging.INFO if kind.upper() == "SCAN" else logging.WARNING, "%s", payload.rstrip())
    except Exception:  # noqa: BLE001 - see the docstring
        pass
    return ref


def log_error(kind: str, message: str, *, detail: str = "", exc: BaseException | None = None,
              request=None) -> str:
    """Record a failure. `exc` adds its traceback."""
    lines: list[str] = []
    if detail:
        lines.append(f"detail   : {detail.strip()}")
    if exc is not None:
        formatted = traceback.format_exception(type(exc), exc, exc.__traceback__)
        block = "".join(formatted).rstrip().splitlines()
        lines.append("traceback:")
        lines.extend(block[-MAX_DETAIL_LINES:])
    lines.insert(0, f"message  : {message}")
    return log_block(kind, lines=lines, request=request)


def log_scan(payload: dict[str, Any], *, source: str = "") -> str:
    """Record a scan that produced no number, with the numbers that explain it.

    These are not exceptions, but on this portal they are the errors that
    matter: "no box at all" three hundred times in a row is the whole story of
    a broken gate, and it is invisible in a traceback log.
    """
    reason = str(payload.get("reason") or "")
    frame = payload.get("frame") or {}
    if not reason or reason == "ok":
        return ""
    pieces = []
    if frame:
        size = f"{frame.get('width')}x{frame.get('height')}"
        facts = [size]
        if frame.get("sharpness") is not None:
            facts.append(f"sharpness {frame['sharpness']}")
        if frame.get("brightness") is not None:
            facts.append(f"brightness {frame['brightness']}")
        if frame.get("tiles"):
            facts.append(f"tiles {frame['tiles']}")
        pieces.append("frame    : " + ", ".join(str(fact) for fact in facts))
        if frame.get("saved"):
            pieces.append(f"saved    : {frame['saved']}")
    stages = [
        f"{stage.get('name')}={stage.get('skipped')}"
        for stage in payload.get("stages") or []
        if stage.get("skipped")
    ]
    if stages:
        pieces.append("stages   : " + ", ".join(stages))
    crops = [
        str(item.get("crop"))
        for item in (payload.get("detection") or {}).get("candidates") or []
        if item.get("crop")
    ]
    if crops:
        pieces.append("crop     : " + ", ".join(crops[:3]))
    if payload.get("advice"):
        pieces.append(f"advice   : {payload['advice']}")
    if source:
        pieces.append(f"source   : {source}")
    return log_block("SCAN", lines=[f"reason   : {reason}", *pieces])


def save_ocr_crop(image, keep: int = 20) -> str:
    """Write the crop the OCR saw, so the pixels can be looked at.

    "The crop was about 25 px wide" is a measurement; this file is the
    evidence. Returns the path, or "" when saving is off or impossible.
    """
    if not enabled():
        return ""
    try:
        directory = failed_crops_dir()
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"crop-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jpg"
        image.save(target, format="JPEG", quality=95)
        # Keep the newest `keep`, so a bad night cannot fill the disk.
        for stale in sorted(directory.glob("crop-*.jpg"))[:-keep] if keep > 0 else []:
            try:
                stale.unlink()
            except OSError:
                pass
        return str(target)
    except Exception:  # noqa: BLE001 - evidence collection must never fail a scan
        return ""


# ----------------------------------------------------------------- reading
def read_blocks() -> list[tuple[list[str], str]]:
    """`[(header_words, block_text)]`, oldest first."""
    path = error_log_path()
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    blocks: list[tuple[list[str], str]] = []
    for chunk in raw.split("\n--- "):
        text = chunk.strip()
        if not text:
            continue
        if not text.startswith("--- "):
            text = "--- " + text
        header = text.splitlines()[0]
        blocks.append((header.split(), text))
    return blocks


def read_errors(
    limit: int = 20,
    kinds: tuple[str, ...] | None = None,
    exclude: tuple[str, ...] | None = None,
) -> str:
    """The newest `limit` blocks as text.

    `kinds` keeps only those labels (UNHANDLED, DATABASE, HTTP, SCAN);
    `exclude` drops them.
    """
    blocks = read_blocks()

    def label(item: tuple[list[str], str]) -> str:
        return item[0][2].upper() if len(item[0]) > 2 else ""

    if kinds:
        wanted = {kind.upper() for kind in kinds}
        blocks = [item for item in blocks if label(item) in wanted]
    if exclude:
        unwanted = {kind.upper() for kind in exclude}
        blocks = [item for item in blocks if label(item) not in unwanted]
    if not blocks:
        return ""
    return "\n\n".join(text for _, text in blocks[-max(1, limit):])


def clear() -> int:
    """Delete the log; returns how many blocks went away."""
    count = len(read_blocks())
    try:
        error_log_path().unlink()
    except OSError:
        pass
    return count


def summary() -> dict[str, Any]:
    """One line worth putting in a status payload."""
    blocks = read_blocks()
    return {
        "path": str(error_log_path()),
        "enabled": enabled(),
        "blocks": len(blocks),
        "last": blocks[-1][0][:4] if blocks else [],
    }


def mirror_log_block(block: str | dict[str, Any], level: int = logging.INFO) -> None:
    """Log a diagnostic text block or structured dictionary to the Python logger."""
    import json
    if isinstance(block, dict):
        formatted = json.dumps(block, default=str)
    else:
        formatted = str(block).strip()
    logger.log(level, formatted)


def log_diagnostic(category: str, message: str, level: int = logging.INFO, **kwargs: Any) -> None:
    """Record an operational diagnostic event with category and metadata."""
    payload = {"category": category, "message": message, **kwargs}
    mirror_log_block(payload, level=level)


def log_audit(action: str, actor: str, record_id: str | None = None, **details: Any) -> None:
    """Record an audit trail entry mirrored to the application logger."""
    payload = {
        "audit_action": action,
        "actor": actor,
        "record_id": record_id,
        "details": details,
    }
    mirror_log_block(payload, level=logging.INFO)

