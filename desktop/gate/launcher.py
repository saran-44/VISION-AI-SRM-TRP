"""VISION AI - SRM TRP: the gate PC entry point.

One executable does four jobs, so an operator never needs a terminal:

    VisionAI.exe                 start the portal, open the browser, sit in the tray
    VisionAI.exe --setup         first-run wizard: database, secret, admin account, camera
    VisionAI.exe --check         run the preflight and print what is missing
    VisionAI.exe --setup --force rewrite an existing configuration

Why waitress: `deploy/render/entrypoint.sh` uses gunicorn, which needs `fork` and
therefore does not run on Windows at all. Waitress is a pure-Python WSGI server
and is the supported Windows answer. The portal is bound to 127.0.0.1 because
this installation is for the gate PC alone; nothing on the LAN can reach it.

State lives in %PROGRAMDATA%\\VisionAI on Windows (or ~/.visionai elsewhere):
gate.env (the configuration), data/gate.db (SQLite), logs/portal.log.
"""
from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from logging.handlers import RotatingFileHandler
from pathlib import Path

# When run from a source checkout, the repository root has to be importable.
# In the frozen bundle `backend` is inside the archive, so this is a no-op there.
if not getattr(sys, "frozen", False):
    _ROOT = Path(__file__).resolve().parents[2]
    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))

APP_NAME = "VISION AI - SRM TRP"
DEFAULT_PORT = 8080
PORT_SCAN = 8

# The gate configuration. Everything here is either a safe default or a value
# the setup wizard overwrites; nothing is a credential.
GATE_DEFAULTS = {
    "ENVIRONMENT": "gate",
    "COOKIE_SECURE": "false",
    "RATELIMIT_ENABLED": "true",
    "LEGACY_PASSWORD_LOGIN_ENABLED": "true",
    "FIREBASE_AUTH_ENABLED": "false",
    "DEMO_MODE": "false",
    "JWT_TTL_MINUTES": "15",
    "APP_TIMEZONE": "Asia/Kolkata",
    # The gate frames are full-resolution stills; 1280 px is where the sticker
    # stage was validated. Compute cost is quadratic, so this is deliberate.
    "VISION_IMAGE_SIZE": "1280",
    "VISION_CONFIDENCE": "0.25",
    "OCR_CONFIDENCE_THRESHOLD": "0.55",
    # A gate camera sees stickers 40-60 px wide in the frame: 3x is what makes
    # the digits legible to the OCR. 1 = the library default (off).
    "VISION_STICKER_UPSCALE": "3",
    # Measure the frame before loading a checkpoint and refuse the ones that
    # cannot contain a sticker (a dark frame cost 13 s and read nothing).
    "VISION_QUALITY_GATE": "refuse",
    "CAMERA_TIMEOUT": "8",
}


# --------------------------------------------------------------------- paths
def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def base_dir() -> Path:
    """Where the bundled frontend and checkpoints live."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def data_dir() -> Path:
    override = os.getenv("VISION_DATA_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = os.getenv("PROGRAMDATA", r"C:\ProgramData")
        return Path(root) / "VisionAI"
    return Path.home() / ".visionai"


def config_file() -> Path:
    return data_dir() / "gate.env"


def log_file() -> Path:
    return data_dir() / "logs" / "portal.log"


# ------------------------------------------------------------------ console
def hide_console() -> None:
    """The bundle is a console program so that --setup and --check can talk.

    Double-clicking it to *run* the portal must not leave a black window on the
    gate desk, so the console is hidden when the portal starts. It is kept for
    --setup (the wizard reads input) and --check (it prints the report).
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        handle = ctypes.windll.kernel32.GetConsoleWindow()
        if handle:
            ctypes.windll.user32.ShowWindow(handle, 0)  # SW_HIDE
    except Exception:  # noqa: BLE001 - a visible console is ugly the portal otherwise works
        pass


# ------------------------------------------------------------------ logging
def configure_logging(verbose: bool = False) -> logging.Logger:
    log_file().parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("visionai")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    if logger.handlers:
        return logger
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s")
    file_handler = RotatingFileHandler(log_file(), maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    if sys.stdout and sys.stdout.isatty():
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        logger.addHandler(stream)
    return logger


# -------------------------------------------------------------- environment
def read_env_file(path: Path) -> dict[str, str]:
    """Minimal KEY=VALUE reader — the file is also valid for python-dotenv."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_file(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# VISION AI - SRM TRP gate configuration.",
        "# Written by VisionAI.exe --setup. Keep this file out of source control:",
        "# it holds the signing secret for this installation.",
        "",
    ]
    lines += [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def apply_environment(values: dict[str, str] | None = None) -> dict[str, str]:
    """Defaults < gate.env < the real environment (so a shell can override)."""
    merged = dict(GATE_DEFAULTS)
    merged.update(values if values is not None else read_env_file(config_file()))
    merged["VISION_DATA_DIR"] = str(data_dir())
    merged["VISION_GATE_CONFIG"] = str(config_file())
    merged.setdefault("DATABASE_URL", f"sqlite:///{(data_dir() / 'data' / 'gate.db').as_posix()}")
    for key, value in merged.items():
        os.environ.setdefault(key, str(value))
    return merged


# ------------------------------------------------------------------- server
def health(port: int, timeout: float = 1.0) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


def running_port() -> int | None:
    """The port of an instance already running, so a double-click is harmless."""
    for port in range(DEFAULT_PORT, DEFAULT_PORT + PORT_SCAN):
        payload = health(port)
        if payload and payload.get("service") == "srm-trp-transport":
            return port
    return None


def free_port(preferred: int) -> int:
    for port in range(preferred, preferred + PORT_SCAN):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError(f"No free port in {preferred}-{preferred + PORT_SCAN - 1}")


def serve(app, port: int, logger: logging.Logger, host: str = "127.0.0.1"):
    try:
        from waitress import create_server
    except ImportError:  # pragma: no cover - the bundle always ships waitress
        logger.warning("waitress is not installed; falling back to the Flask development server")
        return None, lambda: app.run(host=host, port=port, threaded=True, use_reloader=False)
    # 8 threads: the detector holds one for seconds at a time while the console
    # still needs to answer reads, and the SQLite write lock serialises writes.
    server = create_server(app, host=host, port=port, threads=8, channel_timeout=180,
                           ident="VisionAI")
    return server, server.run


def open_browser(port: int, logger: logging.Logger) -> None:
    url = f"http://127.0.0.1:{port}/"
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 - a missing browser must not stop the server
        logger.info("Open %s in a browser", url)


def tray_icon(port: int, server, logger: logging.Logger):
    """A tray icon, if pystray and a desktop are available. Never fatal."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    image = Image.new("RGB", (64, 64), (12, 18, 32))
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 10, 54, 54), outline=(90, 190, 255), width=5)
    draw.rectangle((26, 26, 38, 38), fill=(90, 190, 255))

    def _stop(*_):
        icon.stop()
        if server is not None:
            try:
                server.close()
            except Exception:  # noqa: BLE001
                pass

    icon = pystray.Icon(
        "VisionAI",
        image,
        f"{APP_NAME} — port {port}",
        menu=pystray.Menu(
            pystray.MenuItem("Open portal", lambda *_: open_browser(port, logger), default=True),
            pystray.MenuItem("Open data folder", lambda *_: _open_folder()),
            pystray.MenuItem("Quit", _stop),
        ),
    )

    def _run():
        try:
            icon.run()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tray icon unavailable: %s", exc)

    threading.Thread(target=_run, name="tray", daemon=True).start()
    return icon


def _open_folder() -> None:
    path = data_dir()
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.as_uri())
    except Exception:  # noqa: BLE001
        pass


# -------------------------------------------------------------------- setup
def run_setup(email: str | None = None, password: str | None = None, camera: str | None = None,
              port: int | None = None, force: bool = False, logger: logging.Logger | None = None) -> int:
    """Create the gate configuration and the first administrator.

    Interactive when a value is omitted; the values are never echoed back and
    the password is hashed before it touches the database.
    """
    logger = logger or configure_logging()
    target = config_file()
    existing = read_env_file(target)
    if existing and not force:
        print(f"A configuration already exists at {target}")
        print("Use --force to rewrite it (the database and its rows are kept).")

    print(f"\n{APP_NAME} — gate setup\n" + "-" * 46)
    if email is None:
        email = input("Administrator email: ").strip()
    if not email or "@" not in email:
        print("An email address is required.", file=sys.stderr)
        return 2
    if password is None:
        # Ask up to three times instead of aborting the whole wizard: a
        # rejected password used to send the operator back through the email
        # prompt with nothing written, which reads as "setup is broken".
        for attempt in range(1, 4):
            typed = getpass.getpass("Administrator password (min 12 characters): ")
            if len(typed) < 12:
                print(
                    f"That was {len(typed)} characters; 12 is the minimum "
                    f"(attempt {attempt} of 3).",
                    file=sys.stderr,
                )
                continue
            if typed != getpass.getpass("Repeat the password: "):
                print(f"The passwords did not match (attempt {attempt} of 3).", file=sys.stderr)
                continue
            password = typed
            break
        else:
            print(
                "Setup stopped and NOTHING was written. Run it again when you have a "
                "password of at least 12 characters.",
                file=sys.stderr,
            )
            return 2
    elif len(password) < 12:
        print("Use at least 12 characters: this account can edit every record.", file=sys.stderr)
        return 2
    if camera is None:
        print("\nCamera source, one of:")
        print("  http://user:pass@192.168.1.64/ISAPI/Streaming/channels/101/picture")
        print("  rtsp://user:pass@192.168.1.64:554/Streaming/Channels/101")
        print("  usb:0")
        camera = input("Camera source (blank: browser camera only): ").strip()
    if port is None:
        answer = input(f"Portal port [{DEFAULT_PORT}]: ").strip()
        port = int(answer) if answer.isdigit() else DEFAULT_PORT

    values = {
        "ENVIRONMENT": "gate",
        "PORT": str(port),
        "DATABASE_URL": f"sqlite:///{(data_dir() / 'data' / 'gate.db').as_posix()}",
        "JWT_SECRET": secrets.token_urlsafe(48),
        "LEGACY_PASSWORD_LOGIN_ENABLED": "true",
        "FIREBASE_AUTH_ENABLED": "false",
        "COOKIE_SECURE": "false",
        "RATELIMIT_ENABLED": "true",
        "DEMO_MODE": "false",
        "APP_TIMEZONE": "Asia/Kolkata",
        "VISION_IMAGE_SIZE": "1280",
        "VISION_CONFIDENCE": "0.25",
        "OCR_CONFIDENCE_THRESHOLD": "0.55",
        "CAMERA_TIMEOUT": "8",
        "CAMERA_SOURCE": camera,
        "GATE_NAME": "Gate 1",
    }
    write_env_file(target, values)
    apply_environment(values)
    (data_dir() / "data").mkdir(parents=True, exist_ok=True)
    print(f"\nWrote {target}")

    # Create the administrator through the same code path the API uses.
    from backend.auth import hash_password
    from backend.config import Config
    from backend.db import get_database_for_startup

    config = Config.from_env()
    database = get_database_for_startup(config)
    existing_user = database.users.find_one({"email": email.lower()})
    if existing_user:
        print(f"The account {email} already exists; its password was left unchanged.")
    else:
        from backend.services import naive_now

        now = naive_now()
        database.users.insert_one(
            {
                "_id": secrets.token_hex(12),
                "email": email.lower(),
                "password_hash": hash_password(password),
                "role": "head_admin",
                "active": True,
                "auth_provider": "password",
                "demo_user": False,
                "created_at": now,
                "updated_at": now,
            }
        )
        print(f"Created the head administrator {email}")

    print("\nNext:")
    print("  VisionAI.exe --check     verify this PC against the real configuration")
    print("  VisionAI.exe             start the portal")
    logger.info("Gate setup completed for %s", email)
    return 0


# ------------------------------------------------------------------- backup
def run_backup(target: str | None = None, keep: int = 30) -> int:
    """Copy the gate database with SQLite's own backup API.

    Copying gate.db while the portal runs can produce a file that is missing
    the last transactions (or, with WAL, missing the -wal sidecar). The backup
    API takes a consistent snapshot of a live database, so this is safe to run
    while the gate is open.
    """
    import sqlite3
    from datetime import datetime

    source = config_file()
    values = read_env_file(source)
    url = values.get("DATABASE_URL") or os.environ.get("DATABASE_URL", "")
    if not url.startswith("sqlite:"):
        print("Only the gate file database can be backed up from here.", file=sys.stderr)
        return 2
    source_path = Path(url.split("///", 1)[-1])
    if not source_path.exists():
        print(f"No database at {source_path} yet: run --setup first.", file=sys.stderr)
        return 2
    destination_dir = Path(target).expanduser() if target else data_dir() / "backups"
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / f"gate-{datetime.now():%Y%m%d-%H%M%S}.db"

    with sqlite3.connect(f"file:{source_path}?mode=ro", uri=True) as src:
        with sqlite3.connect(destination) as dst:
            src.backup(dst)
    size = destination.stat().st_size
    print(f"Backed up {source_path} -> {destination} ({size // 1024} KB)")

    backups = sorted(destination_dir.glob("gate-*.db"))
    for stale in backups[:-keep] if keep > 0 else []:
        try:
            stale.unlink()
        except OSError:
            pass
    return 0


# --------------------------------------------------------------------- main
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} — gate portal")
    parser.add_argument("--port", type=int, default=None, help="port to listen on (default 8080)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="interface to bind; the gate PC needs the default 127.0.0.1")
    parser.add_argument("--setup", action="store_true", help="first-run wizard: configuration and administrator")
    parser.add_argument("--force", action="store_true", help="with --setup: rewrite an existing configuration")
    parser.add_argument("--check", action="store_true", help="run the preflight and exit")
    parser.add_argument("--backup", nargs="?", const="", default=None, metavar="DIR",
                        help="copy the gate database safely (default: %PROGRAMDATA%%\\VisionAI\\backups)")
    parser.add_argument("--deep", action="store_true", help="with --check: also load the detector")
    parser.add_argument("--json", action="store_true", help="with --check: machine-readable output")
    parser.add_argument("--no-browser", action="store_true", help="do not open the portal in a browser")
    parser.add_argument("--no-tray", action="store_true", help="run without the tray icon")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    values = apply_environment()
    logger = configure_logging(args.verbose)

    if args.setup:
        return run_setup(force=args.force, logger=logger)

    if args.backup is not None:
        return run_backup(args.backup or None)

    if args.check:
        from backend.preflight import format_report, main as preflight_main

        argv_out = ["--deep"] if args.deep else []
        if args.json:
            argv_out.append("--json")
        code = preflight_main(argv_out + ["--env-file", str(config_file())] if config_file().exists() else argv_out)
        if not args.json and sys.stdin and sys.stdin.isatty():
            # Started from a Start Menu shortcut the window would vanish before
            # anyone read the failure that just told them what to fix.
            try:
                input("\nPress Enter to close...")
            except (EOFError, KeyboardInterrupt):
                pass
        return code

    port = args.port or int(values.get("PORT", DEFAULT_PORT))
    already = running_port()
    if already:
        logger.info("The portal is already running on port %s", already)
        if not args.no_browser:
            open_browser(already, logger)
        return 0

    hide_console()
    port = free_port(port)
    logger.info("%s starting on http://%s:%s", APP_NAME, args.host, port)
    try:
        from backend.app import create_app
        from backend.config import Config, GATE_ENVIRONMENT

        config = Config.from_env()
        if config.environment == GATE_ENVIRONMENT and not config_file().exists():
            logger.warning("No configuration at %s — run VisionAI.exe --setup", config_file())
        app = create_app(config)
    except Exception as exc:  # noqa: BLE001 - a first run with no config must explain itself
        logger.error("Cannot start: %s", exc)
        print(f"Cannot start: {exc}", file=sys.stderr)
        print("Run VisionAI.exe --setup to create the configuration.", file=sys.stderr)
        return 2

    server, run = serve(app, port, logger, host=args.host)
    if not args.no_browser:
        threading.Timer(1.0, lambda: open_browser(port, logger)).start()
    if not args.no_tray:
        tray_icon(port, server, logger)
    try:
        run()
    except KeyboardInterrupt:
        logger.info("Stopped by the operator")
    finally:
        if server is not None:
            try:
                server.close()
            except Exception:  # noqa: BLE001
                pass
        logger.info("Portal stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
