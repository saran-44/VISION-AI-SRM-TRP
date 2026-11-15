"""One text block that answers "what is this machine doing?".

Pasting a gate problem into a chat means collecting six things from four
places — the version, the configuration, what the detector is set to, what the
camera answered, the preflight verdict and the tracebacks. This module prints
all of it as one block, with every credential masked, so the operator runs one
command and copies one screen:

    python scripts/gate_report.py              # print it
    python scripts/gate_report.py --out r.txt  # keep it, ready to attach

Everything here is defensive: a broken database or a missing model must make
the section say so, never make the report fail to appear.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from . import diagnostics

# Only these may appear in a report. Everything else in the environment —
# SECRET_KEY, JWT_SECRET, database URLs with passwords — stays out of it, and
# what does get printed is still passed through `diagnostics.redact`.
CONFIG_PREFIXES = ("VISION_", "CAMERA_", "OCR_")
CONFIG_KEYS = ("ENVIRONMENT", "PORT", "APP_TIMEZONE", "DATABASE_URL_KIND")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _git() -> str:
    root = _project_root()
    if not (root / ".git").exists():
        return "not a checkout (bundled build)"
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "log", "-1", "--pretty=%h %s"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:  # noqa: BLE001 - git is optional
        return "unknown"
    text = (result.stdout or "").strip()
    return text or "unknown"


def _configuration() -> list[str]:
    lines = ["  (a key in the environment overrides the same key in gate.env)"]
    for key in sorted(os.environ):
        if not (key in CONFIG_KEYS or key.startswith(CONFIG_PREFIXES)):
            continue
        if any(word in key for word in ("SECRET", "PASSWORD", "TOKEN", "KEY")):
            continue  # never printed, not even masked
        value = os.environ.get(key, "")
        if value == "":
            value = "(empty)"
        lines.append(f"  {key}={diagnostics.redact(str(value))}")
    return lines or ["  (nothing set: the defaults in the code are in use)"]


def _portal(port: int) -> list[str]:
    """Whether the portal is up right now — an empty error log means nothing
    if the process has not been running since the last change."""
    import socket

    if not port:
        return ["  port not configured"]
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return [f"  running on http://127.0.0.1:{port}"]
    except OSError:
        return [
            f"  not running (nothing answers on 127.0.0.1:{port}) — "
            "scans are only recorded while it runs"
        ]


def _port() -> int:
    try:
        return int(os.getenv("PORT", "8080"))
    except ValueError:
        return 8080


def _config_file() -> Path:
    return diagnostics.data_root() / "gate.env"


def _config_file_lines() -> list[str]:
    """The gate file itself, masked — the environment may be only a subset."""
    path = _config_file()
    if not path.exists():
        return [f"  (no gate.env at {path})"]
    lines = [f"  file: {path}"]
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            if any(word in key for word in ("SECRET", "PASSWORD", "TOKEN", "KEY")):
                lines.append(f"  {key}=***")
            else:
                lines.append(f"  {key}={diagnostics.redact(value.strip()) or '(empty)'}")
    except OSError as exc:
        lines.append(f"  (unreadable: {exc})")
    return lines


def _vision() -> list[str]:
    try:
        from .vision import quality_settings, vision_status

        status = vision_status()
        settings = quality_settings()
    except Exception as exc:  # noqa: BLE001
        return [f"  could not be read: {type(exc).__name__}: {exc}"]
    lines = [
        f"  model      : {status.get('model_path')} (present={status.get('model_present')}, "
        f"loaded={status.get('model_loaded')})",
        f"  ocr engine : {status.get('ocr_engine')} -> {status.get('ocr_available') or 'NONE USABLE'}",
        f"  classes    : {status.get('classes')} (from {status.get('classes_source')})",
        "  settings   : " + ", ".join(f"{key}={value}" for key, value in settings.items()),
    ]
    problems = status.get("problems") or []
    if problems:
        lines.append("  problems   : " + "; ".join(str(problem) for problem in problems))
    for stage in status.get("stages") or []:
        lines.append(
            f"  stage {stage.get('name'):<13} enabled={stage.get('enabled')} "
            f"model={Path(str(stage.get('model'))).name} present={stage.get('model_present')}"
        )
    return lines


def _camera() -> list[str]:
    try:
        from .frame_source import describe

        info = describe()
    except Exception as exc:  # noqa: BLE001
        return [f"  could not be read: {type(exc).__name__}: {exc}"]
    return [f"  {key}: {diagnostics.redact(str(value))}" for key, value in info.items()]


def _models() -> list[str]:
    lines = []
    root = _project_root()
    for name in ("best.pt", "anpr_best.pt", "weights/vehicle.pt", "weights/number_plate.pt"):
        path = Path(name) if Path(name).is_absolute() else root / name
        if path.exists():
            lines.append(f"  {name:<24} {path.stat().st_size / 1024:8.0f} KB")
        else:
            lines.append(f"  {name:<24} missing")
    return lines


def _preflight(deep: bool) -> list[str]:
    try:
        from . import preflight

        report = preflight.run(deep=deep)
        lines = ["  " + line for line in preflight.format_report(report).splitlines()]
        if len(report.checks) <= 2:
            lines.append(
                "  (preflight stopped after the configuration: fix that first — "
                "the sections above still show what this PC is set to)"
            )
        return lines
    except Exception as exc:  # noqa: BLE001
        return [f"  preflight could not run: {type(exc).__name__}: {exc}"]


def _portal_log(lines: int) -> list[str]:
    path = diagnostics.logs_dir() / "portal.log"
    if not path.exists():
        return [f"  (no portal.log at {path})"]
    try:
        tail = path.read_text(encoding="utf-8", errors="replace").splitlines()[-400:]
    except OSError as exc:
        return [f"  (unreadable: {exc})"]
    interesting = [
        line
        for line in tail
        if any(word in line for word in ("WARNING", "ERROR", "Traceback", "critical"))
    ]
    if not interesting:
        if not tail:
            return ["  (portal.log is empty)"]
        return [f"  (nothing above INFO in the last {len(tail)} lines)"]
    return ["  " + diagnostics.redact(line) for line in interesting[-lines:]]


def _errors(limit: int) -> list[str]:
    text = diagnostics.read_errors(limit=limit, exclude=("SCAN",))
    if not text:
        return [f"  (no errors recorded in {diagnostics.error_log_path()})"]
    return ["  " + line if line else "" for line in text.splitlines()]


def _scans(limit: int) -> list[str]:
    text = diagnostics.read_errors(limit=limit, kinds=("SCAN",))
    if not text:
        return [f"  (no failed scans recorded in {diagnostics.error_log_path()})"]
    return ["  " + line if line else "" for line in text.splitlines()]


def build_report(*, deep: bool = False, errors: int = 20, scans: int = 15, log_lines: int = 25) -> str:
    """The whole report as text, ready to copy."""
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    frozen = bool(getattr(sys, "frozen", False))
    header = [
        "===== VisionAI gate report =====",
        f"generated : {stamp}",
        f"build     : {'bundled exe' if frozen else 'source checkout'}",
        f"git       : {_git()}",
        f"python    : {platform.python_version()} ({sys.platform}, {platform.machine()})",
        f"machine   : {platform.platform()}",
        f"cwd       : {Path.cwd()}",
        f"data dir  : {diagnostics.data_root()}",
        f"error log : {diagnostics.error_log_path()} (enabled={diagnostics.enabled()})",
    ]
    sections = [
        ("1. Configuration (environment)", _configuration() + _config_file_lines()),
        ("2. Vision stack", _vision()),
        ("3. Camera", _camera()),
        ("3a. Portal", _portal(_port())),
        ("4. Model files", _models()),
        ("5. Preflight", _preflight(deep)),
        ("6. Recent errors", _errors(errors)),
        ("7. Recent scans that produced no number", _scans(scans)),
        ("8. portal.log (warnings and errors)", _portal_log(log_lines)),
    ]
    out = list(header)
    for title, lines in sections:
        out.append("")
        out.append(f"--- {title} " + "-" * max(0, 40 - len(title)))
        out.extend(lines)
    out.append("")
    out.append("===== end of report =====")
    return "\n".join(out)


def summary() -> dict[str, Any]:
    """A tiny version for a status endpoint."""
    return {
        "errors": diagnostics.summary(),
        "git": _git(),
        "frozen": bool(getattr(sys, "frozen", False)),
    }
