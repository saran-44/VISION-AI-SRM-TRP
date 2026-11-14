"""Is this gate PC actually ready to run the portal?

Every check runs against the same configuration the portal will use, and each
one answers a question that has already cost this project a debugging round:
is the database writable, is the camera returning a *usable* frame, is the OCR
engine installed, does the detector load, is the port free.

`VisionAI.exe --check` calls this, and so does `scripts/preflight.py`. Nothing
here guesses: a check that cannot run is reported as `skip`, never as `pass`.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

PASS, WARN, FAIL, SKIP = "pass", "warn", "fail", "skip"
MIN_FREE_BYTES = 2_000_000_000


@dataclass
class Check:
    name: str
    status: str
    detail: str
    fix: str = ""

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "status": self.status, "detail": self.detail, "fix": self.fix}


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, status: str, detail: str, fix: str = "") -> None:
        self.checks.append(Check(name, status, detail, fix))

    @property
    def failures(self) -> int:
        return sum(1 for check in self.checks if check.status == FAIL)

    @property
    def warnings(self) -> int:
        return sum(1 for check in self.checks if check.status == WARN)

    @property
    def ready(self) -> bool:
        return self.failures == 0

    def to_dict(self) -> dict:
        return {
            "ready": self.ready,
            "failures": self.failures,
            "warnings": self.warnings,
            "checks": [check.to_dict() for check in self.checks],
        }


# ------------------------------------------------------------------ helpers
def _project_root() -> Path:
    """Repository root when run from source, bundle root when frozen."""
    return Path(__file__).resolve().parents[1]


def _free_bytes(path: Path) -> int | None:
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def _port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex((host, port)) == 0


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def frame_sharpness(data: bytes) -> float | None:
    """Laplacian variance of a JPEG, or None where numpy is unavailable."""
    try:
        from PIL import Image
        import numpy as np
    except ImportError:
        return None
    import io

    with Image.open(io.BytesIO(data)) as opened:
        gray = opened.convert("L")
    pixels = np.asarray(gray, dtype=np.float64)
    if min(pixels.shape) < 3:
        return None
    lap = (
        -4.0 * pixels[1:-1, 1:-1]
        + pixels[:-2, 1:-1]
        + pixels[2:, 1:-1]
        + pixels[1:-1, :-2]
        + pixels[1:-1, 2:]
    )
    return float(lap.var())


# ------------------------------------------------------------------- checks
def check_environment(report: Report, config) -> None:
    problems = []
    if config.environment != "gate":
        problems.append(f"ENVIRONMENT is {config.environment!r}, not 'gate'")
    if config.demo_mode:
        problems.append("DEMO_MODE is on")
    scheme = config.database_url.split(":", 1)[0]
    if len(config.jwt_secret) < 32:
        problems.append("JWT_SECRET is shorter than 32 characters")
    if not (config.legacy_password_login_enabled or config.firebase_auth_enabled):
        problems.append("no way to sign in")
    if problems:
        report.add("environment", FAIL, "; ".join(problems), "Re-run VisionAI.exe --setup")
    else:
        sign_in = "password login" if config.legacy_password_login_enabled else "Firebase sign-in"
        report.add(
            "environment",
            PASS,
            f"ENVIRONMENT=gate, {scheme} storage, demo off, {sign_in}",
        )


def check_gate_config(report: Report) -> None:
    """Is the portal running on the configuration --setup wrote, or on defaults?

    Without this check a gate PC whose wizard was never finished passes every
    other test: the database is created on demand and the values come from
    whatever .env happens to be in the checkout.
    """
    configured = os.environ.get("VISION_GATE_CONFIG", "").strip()
    if not configured:
        report.add("gate config", SKIP, "no gate configuration path was given")
        return
    path = Path(configured)
    if path.exists():
        report.add("gate config", PASS, str(path))
    else:
        report.add(
            "gate config",
            FAIL,
            f"{path} does not exist: the portal is running on borrowed defaults, "
            "not on a configuration created for this PC",
            "Run VisionAI.exe --setup (the wizard only writes once it has a usable password)",
        )


def check_admin_account(report: Report, database) -> None:
    """READY with nobody able to sign in is not ready."""
    try:
        admins = database.users.count_documents({"role": "head_admin", "active": True})
    except Exception as exc:  # noqa: BLE001
        report.add("administrator", FAIL, f"cannot read the users table ({type(exc).__name__})",
                   "Run VisionAI.exe --setup")
        return
    if admins == 0:
        report.add(
            "administrator",
            FAIL,
            "no active head_admin account: nobody can sign in to the portal",
            "Run VisionAI.exe --setup to create the administrator",
        )
    else:
        report.add("administrator", PASS, f"{admins} active head_admin account(s)")


def check_database(report: Report, config, database) -> None:
    try:
        from sqlalchemy import select

        from .db import schema_version

        with database.engine.connect() as connection:
            version = connection.execute(select(schema_version.c.version)).scalar_one_or_none()
        rows = database.buses.count_documents({})
        location = config.database_url.split("///", 1)[-1]
        report.add(
            "database",
            PASS,
            f"schema v{version}, {rows} bus row(s), {database.engine.dialect.name} at {location}",
        )
    except Exception as exc:  # noqa: BLE001 - report the failure, do not crash the check
        report.add("database", FAIL, f"cannot read the schema ({type(exc).__name__}: {exc})",
                   "Run VisionAI.exe --setup to create the gate database")


def check_database_write(report: Report, database) -> None:
    """Prove the store accepts a write, not just a read.

    A read-only folder, a locked file or a full disk all pass a SELECT and fail
    the first scan of the day, which is the worst possible time to find out.
    """
    import secrets

    probe = {"_id": secrets.token_hex(12), "bus_number": f"PREFLIGHT-{secrets.token_hex(3)}"}
    try:
        database.buses.insert_one(dict(probe))
        database.buses.delete_many({"_id": probe["_id"]})
        report.add("database write", PASS, "inserted and removed a probe row")
    except Exception as exc:  # noqa: BLE001
        report.add(
            "database write",
            FAIL,
            f"{type(exc).__name__}: {exc}",
            "The data folder must be writable by the account that runs the portal",
        )


def check_frontend(report: Report, config) -> None:
    root: Path = config.frontend_dir
    required = [root / "index.html", root / "js" / "api.js", root / "pages"]
    missing = [path.name for path in required if not path.exists()]
    if missing:
        report.add(
            "frontend",
            FAIL,
            f"missing {', '.join(missing)} under {root}",
            "The bundle is incomplete: rebuild with desktop/gate/build_gate.ps1",
        )
        return
    pages = len(list((root / "pages").glob("*.html")))
    scripts = len(list((root / "js").glob("*.js")))
    report.add("frontend", PASS, f"{pages} page(s), {scripts} script(s) at {root}")


def check_models(report: Report) -> None:
    from .vision import DEFAULT_MODEL_PATH, DEFAULT_PLATE_MODEL_PATH, DEFAULT_VEHICLE_MODEL_PATH, model_path

    sticker = model_path()
    present = [path for path in (sticker, DEFAULT_PLATE_MODEL_PATH, DEFAULT_VEHICLE_MODEL_PATH) if path.exists()]
    missing = [path.name for path in (sticker, DEFAULT_PLATE_MODEL_PATH) if not path.exists()]
    if not sticker.exists():
        report.add(
            "models",
            FAIL,
            f"the sticker checkpoint {sticker.name} is missing next to the application",
            "Copy best.pt and anpr_best.pt beside VisionAI.exe, then run the check again",
        )
        return
    detail = ", ".join(f"{path.name} {path.stat().st_size // 1024} KB" for path in present)
    if missing:
        report.add("models", WARN, f"{detail}; missing {', '.join(missing)}", "The plate stage will be skipped")
    else:
        report.add("models", PASS, detail)


def check_ocr(report: Report) -> None:
    try:
        from .vision import vision_status

        status = vision_status()
    except Exception as exc:  # noqa: BLE001
        report.add("ocr", FAIL, f"the vision stack did not import ({type(exc).__name__})",
                   "python -m pip install -r backend/requirements-vision.txt")
        return
    if status.get("ocr_available"):
        report.add("ocr", PASS, f"{status.get('ocr_engine')} is available")
    else:
        report.add(
            "ocr",
            FAIL,
            "no OCR engine: a sticker will be found but never read",
            "python -m pip install -r backend/requirements-vision.txt",
        )


def check_vision_settings(report: Report) -> None:
    """The settings that decide whether a scan can read anything.

    Reported on every run: after changing `gate.env` the operator needs to see
    the new value in the process that is serving, not in the file that was
    edited.
    """
    from .vision import quality_settings

    try:
        settings = quality_settings()
    except Exception as exc:  # noqa: BLE001 - a readout must never fail a run
        report.add("vision settings", WARN, f"could not be read: {type(exc).__name__}: {exc}")
        return
    report.add(
        "vision settings",
        PASS,
        f"gate={settings['quality_gate']} (dark under {settings['min_brightness']:.0f}/255"
        + (f", soft under {settings['min_sharpness']:.0f}" if settings["min_sharpness"] > 0 else ", softness allowed")
        + f"), sticker upscale={settings['sticker_upscale']}x, plate upscale={settings['plate_upscale']}x, "
        f"tiles={settings['tiles']}, {settings['image_size']}px, confidence {settings['confidence']:.2f}",
    )


def check_detector(report: Report, deep: bool) -> None:
    if not deep:
        report.add("detector", SKIP, "not run (pass --deep: it loads torch, ~10 s)")
        return
    started = time.perf_counter()
    # A blank frame is exactly what the quality gate refuses; this check exists
    # to prove the checkpoint loads, so the gate is stood down for it.
    previous = os.environ.get("VISION_QUALITY_GATE")
    os.environ["VISION_QUALITY_GATE"] = "off"
    try:
        from PIL import Image

        from .vision import detect

        result = detect(Image.new("RGB", (1280, 720), (24, 24, 24)))
    except Exception as exc:  # noqa: BLE001
        report.add("detector", FAIL, f"{type(exc).__name__}: {exc}", "Check the vision extras install")
        return
    finally:
        if previous is None:
            os.environ.pop("VISION_QUALITY_GATE", None)
        else:
            os.environ["VISION_QUALITY_GATE"] = previous
    elapsed = int((time.perf_counter() - started) * 1000)
    report.add(
        "detector",
        PASS,
        f"one 1280×720 pass in {elapsed} ms at {result.image_size}px, model {result.model}, "
        f"{result.boxes_total} box(es) on a blank frame",
    )


def check_camera(report: Report, config) -> None:
    from .frame_source import FrameSourceError, describe, snapshot

    info = describe(config.camera_source)
    if not info["configured"]:
        report.add(
            "camera",
            WARN,
            "no CAMERA_SOURCE: the portal will only work with a browser camera on this PC",
            "Set CAMERA_SOURCE to the gate camera's snapshot or RTSP URL",
        )
        return
    started = time.perf_counter()
    try:
        frame = snapshot(config.camera_source)
    except FrameSourceError as exc:
        report.add("camera", FAIL, str(exc), "Check the cable, the IP address, the credentials and the URL path")
        return
    elapsed = int((time.perf_counter() - started) * 1000)
    detail = f"{info['kind']} at {info['source']} → {frame.width}×{frame.height} in {elapsed} ms"
    sharp = frame_sharpness(frame.data)
    if sharp is None:
        report.add("camera", PASS, detail)
        return
    if sharp < 60:
        report.add(
            "camera",
            WARN,
            f"{detail}, sharpness {sharp:.0f}",
            "The frame is soft: clean the lens, check focus, and confirm the snapshot is full resolution",
        )
    else:
        report.add("camera", PASS, f"{detail}, sharpness {sharp:.0f}")


def check_port(report: Report, port: int) -> None:
    if _port_busy("127.0.0.1", port):
        report.add(
            "port",
            WARN,
            f"127.0.0.1:{port} is already in use (the portal may already be running)",
            "Open http://127.0.0.1:%d, or start with --port %d" % (port, port + 1),
        )
    elif _port_free(port):
        report.add("port", PASS, f"127.0.0.1:{port} is free")
    else:
        report.add("port", FAIL, f"127.0.0.1:{port} cannot be bound", "Choose another port with --port")


def check_disk(report: Report, data_dir: Path) -> None:
    free = _free_bytes(data_dir if data_dir.exists() else data_dir.parent)
    if free is None:
        report.add("disk", WARN, f"cannot read free space for {data_dir}")
        return
    gigabytes = free / 1_000_000_000
    if free < MIN_FREE_BYTES:
        report.add("disk", FAIL, f"{gigabytes:.1f} GB free on the data drive",
                   "Free at least 2 GB: event history and database backups live here")
    else:
        report.add("disk", PASS, f"{gigabytes:.1f} GB free on the data drive")


def check_data_dir(report: Report, data_dir: Path) -> None:
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        probe = data_dir / ".preflight"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        report.add("data folder", FAIL, f"{data_dir} is not writable ({exc.strerror})",
                   "Install for all users, or point the data folder at a writable disk")
        return
    report.add("data folder", PASS, f"{data_dir} is writable")


def check_clock(report: Report, api_url: str) -> None:
    """A wrong clock makes every event out of order and breaks TLS checks."""
    if not api_url:
        report.add("clock", SKIP, "no API_URL configured (this gate may be stand-alone)")
        return
    request = urllib.request.Request(api_url, method="HEAD")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            header = response.headers.get("Date")
    except (urllib.error.URLError, OSError) as exc:
        report.add("clock", WARN, f"could not reach {api_url} ({exc})",
                   "Only matters if this gate is expected to sync with the cloud portal")
        return
    if not header:
        report.add("clock", SKIP, "the server sent no Date header")
        return
    try:
        remote = datetime.strptime(header, "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
    except ValueError:
        report.add("clock", SKIP, "the Date header could not be parsed")
        return
    skew = abs((datetime.now(timezone.utc) - remote).total_seconds())
    if skew > 120:
        report.add("clock", FAIL, f"the PC clock is {int(skew)} s off the server",
                   "Enable Windows time sync: w32tm /resync")
    else:
        report.add("clock", PASS, f"within {int(skew)} s of the server clock")


# --------------------------------------------------------------------- run
def run(deep: bool = False, port: int = 8080, data_dir: Path | None = None, config=None) -> Report:
    report = Report()
    from .config import Config

    try:
        config = config or Config.from_env()
    except Exception as exc:  # noqa: BLE001
        report.add("configuration", FAIL, f"{exc}", "Run VisionAI.exe --setup to write the gate configuration")
        return report
    report.add("configuration", PASS, f"loaded ({config.environment})")
    check_gate_config(report)

    check_env_gate = getattr(config, "environment", "")
    check_environment(report, config)
    if check_env_gate != "gate":
        # Everything below assumes the gate layout; still run the read-only
        # checks so a laptop install gets useful output.
        pass

    data_root = data_dir or Path(os.getenv("VISION_DATA_DIR", Path.home() / "VisionAI"))
    check_data_dir(report, data_root)
    check_disk(report, data_root)

    database = None
    try:
        from .db import get_database_for_startup

        database = get_database_for_startup(config)
    except Exception as exc:  # noqa: BLE001
        report.add("database", FAIL, f"{exc}", "Run VisionAI.exe --setup to create the gate database")
    if database is not None:
        check_database(report, config, database)
        check_database_write(report, database)
        check_admin_account(report, database)

    check_frontend(report, config)
    check_models(report)
    check_ocr(report)
    check_vision_settings(report)
    check_detector(report, deep)
    check_camera(report, config)
    check_port(report, port)
    check_clock(report, os.getenv("API_URL", "").strip())
    return report


def format_report(report: Report) -> str:
    lines = [f"VisionAI gate preflight — {len(report.checks)} checks"]
    symbols = {PASS: "PASS", WARN: "WARN", FAIL: "FAIL", SKIP: "SKIP"}
    for check in report.checks:
        lines.append(f"  {symbols.get(check.status, check.status):<4}  {check.name:<16} {check.detail}")
        if check.fix and check.status in {WARN, FAIL}:
            lines.append(f"        fix: {check.fix}")
    verdict = "READY" if report.ready else "NOT READY"
    lines.append("")
    lines.append(f"{verdict}: {report.failures} failed, {report.warnings} warning(s)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check that this PC can run the gate portal")
    parser.add_argument("--deep", action="store_true", help="also load the detector and run one inference (~10 s)")
    parser.add_argument("--json", action="store_true", help="print machine-readable output")
    parser.add_argument("--port", type=int, default=None,
                        help="port the portal will use (default: PORT from the environment, then 8080)")
    parser.add_argument("--data-dir", default=os.getenv("VISION_DATA_DIR", ""))
    parser.add_argument("--env-file", default="", help="load this .env before checking (the gate config)")
    args = parser.parse_args(argv)

    if args.env_file:
        try:
            from dotenv import load_dotenv

            load_dotenv(Path(args.env_file).expanduser(), override=True)
        except ImportError:
            print("python-dotenv is required for --env-file", file=sys.stderr)
            return 2

    data_dir = Path(args.data_dir).expanduser() if args.data_dir else None
    try:
        port = args.port if args.port is not None else int(os.getenv("PORT", "8080"))
    except ValueError:
        port = 8080
    report = run(deep=args.deep, port=port, data_dir=data_dir)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(format_report(report))
    return 0 if report.ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
