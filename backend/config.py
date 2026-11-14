from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)

# The demo account created only when DEMO_MODE is on. The address is reserved
# (`.local`), so it can never receive mail or collide with a real mailbox.
DEMO_ADMIN_EMAIL = "admin@demo.local"
DEMO_ADMIN_PASSWORD = "admin"

# The gate installation: the whole portal on the gate PC, with its own file
# database, so a scan is recorded whether or not the campus link is up. It is a
# real installation, not a bench: the production secret and demo rules apply.
GATE_ENVIRONMENT = "gate"


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _csv(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


def _parse_origins(values: tuple[str, ...]) -> tuple[str, ...]:
    parsed: list[str] = []
    for value in values:
        origin = value.rstrip("/")
        parts = urlparse(origin)
        if parts.scheme not in {"http", "https"} or not parts.netloc or "*" in origin:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit http(s) origins, not wildcards")
        parsed.append(origin)
    return tuple(dict.fromkeys(parsed))


def _firebase_config() -> dict[str, str]:
    """Collect the public Firebase web configuration from the environment.

    These values are public browser identifiers, not database credentials.
    Runtime environment settings can override the identifiers shown in the
    example configuration without changing the application code.
    """
    mapping = {
        "apiKey": "FIREBASE_API_KEY",
        "authDomain": "FIREBASE_AUTH_DOMAIN",
        "projectId": "FIREBASE_PROJECT_ID",
        "storageBucket": "FIREBASE_STORAGE_BUCKET",
        "messagingSenderId": "FIREBASE_MESSAGING_SENDER_ID",
        "appId": "FIREBASE_APP_ID",
        "measurementId": "FIREBASE_MEASUREMENT_ID",
    }
    config = {
        key: os.getenv(env_name, "").strip()
        for key, env_name in mapping.items()
    }
    # A usable configuration needs at least the project id and the app id.
    if not config.get("projectId") or not config.get("appId"):
        return {}
    return {key: value for key, value in config.items() if value}


def _parse_camera_streams(raw: str) -> dict[str, dict[str, str]]:
    if not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("CAMERA_STREAM_URLS must be a JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError("CAMERA_STREAM_URLS must be a JSON object")

    result: dict[str, dict[str, str]] = {}
    for camera_id, entry in value.items():
        if not isinstance(entry, dict):
            raise ValueError("Each camera stream must be a JSON object")
        stream_type = str(entry.get("type", "")).lower()
        url = str(entry.get("url", "")).strip()
        label = str(entry.get("label", camera_id)).strip()
        parts = urlparse(url)
        if stream_type not in {"hls", "mjpeg", "rtsp"}:
            raise ValueError("Camera stream type must be hls, mjpeg or rtsp")
        if parts.scheme not in {"http", "https", "rtsp"} or not parts.netloc:
            raise ValueError("Camera stream URLs must use http, https or rtsp")
        if parts.username or parts.password:
            raise ValueError("Camera stream URLs must not embed credentials")
        if not label or len(label) > 80:
            raise ValueError("Camera labels must be 1-80 characters")
        result[str(camera_id)] = {"type": stream_type, "url": url, "label": label}
    return result


@dataclass(frozen=True)
class Config:
    environment: str
    debug: bool
    testing: bool
    database_url: str
    jwt_secret: str
    jwt_ttl_minutes: int
    cookie_secure: bool
    cors_allowed_origins: tuple[str, ...] = field(default_factory=tuple)
    device_api_keys: tuple[str, ...] = field(default_factory=tuple)
    # Set only when the app runs behind a proxy that appends (does not
    # forward) X-Forwarded-* headers, e.g. Render, Railway or an nginx
    # reverse proxy. Without it, login throttling and the audit log would key
    # on the proxy's address instead of the real client.
    trust_proxy_headers: bool = False
    login_rate_limit: str = "5 per minute;20 per hour"
    rate_limit_enabled: bool = True
    rate_limit_storage_uri: str = "memory://"
    app_timezone: str = "Asia/Kolkata"
    ocr_confidence_threshold: float = 0.75
    overstay_hours: float = 12.0
    camera_streams: dict[str, dict[str, str]] = field(default_factory=dict)
    # The camera the gate PC grabs frames from itself: an HTTP snapshot URL, an
    # RTSP URL, or usb:0. Empty means "use the browser camera only".
    camera_source: str = ""
    frontend_dir: Path = ROOT / "frontend"
    firebase: dict[str, str] = field(default_factory=dict)
    firebase_project_id: str = ""
    firebase_auth_enabled: bool = True
    firebase_allowed_providers: tuple[str, ...] = ("password", "google.com")
    firebase_auto_provision: bool = True
    firebase_default_role: str = "transport_office"
    legacy_password_login_enabled: bool = True
    # A deliberately isolated testing mode: fake sign-in alias, Test Lab page
    # and a loud banner. It is refused outright in production.
    demo_mode: bool = False
    # Escape hatch for a documented, temporary production exception.
    allow_legacy_login_in_production: bool = False

    @classmethod
    def from_env(cls, overrides: dict | None = None) -> "Config":
        environment = os.getenv("ENVIRONMENT", "development").strip().lower()
        debug_requested = _bool("FLASK_DEBUG", False)
        database_url = os.getenv("DATABASE_URL", "").strip()
        jwt_secret = os.getenv("JWT_SECRET", "").strip()
        cors_origins = _parse_origins(_csv("CORS_ALLOWED_ORIGINS"))
        camera_streams = _parse_camera_streams(os.getenv("CAMERA_STREAM_URLS", ""))
        firebase = _firebase_config()
        cfg = cls(
            environment=environment,
            debug=debug_requested and environment == "development",
            testing=_bool("TESTING", False),
            database_url=database_url,
            jwt_secret=jwt_secret,
            jwt_ttl_minutes=_int("JWT_TTL_MINUTES", 15),
            cookie_secure=_bool("COOKIE_SECURE", environment == "production"),
            cors_allowed_origins=cors_origins,
            device_api_keys=_csv("DEVICE_API_KEYS"),
            trust_proxy_headers=_bool("TRUST_PROXY_HEADERS", False),
            login_rate_limit=os.getenv("LOGIN_RATE_LIMIT", "5 per minute;20 per hour"),
            rate_limit_enabled=_bool("RATELIMIT_ENABLED", True),
            rate_limit_storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
            app_timezone=os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
            ocr_confidence_threshold=_float("OCR_CONFIDENCE_THRESHOLD", 0.75),
            overstay_hours=_float("OVERSTAY_HOURS", 12.0),
            camera_streams=camera_streams,
            camera_source=os.getenv("CAMERA_SOURCE", "").strip(),
            firebase=firebase,
            firebase_project_id=firebase.get("projectId", ""),
            # Firebase sign-in is only usable when a project id is configured.
            # The flag stays on by default so that adding the project id is
            # enough to switch it on.
            firebase_auth_enabled=_bool("FIREBASE_AUTH_ENABLED", True)
            and bool(firebase.get("projectId")),
            firebase_allowed_providers=_csv("FIREBASE_ALLOWED_PROVIDERS")
            or ("password", "google.com"),
            firebase_auto_provision=_bool("FIREBASE_AUTO_PROVISION", True),
            firebase_default_role=os.getenv("FIREBASE_DEFAULT_ROLE", "transport_office").strip()
            or "transport_office",
            # Fail closed in production: password sign-in must be asked for
            # explicitly there, and validate() insists on a second opt-in.
            legacy_password_login_enabled=_bool(
                "LEGACY_PASSWORD_LOGIN_ENABLED", environment != "production"
            ),
            demo_mode=_bool("DEMO_MODE", False),
            allow_legacy_login_in_production=_bool("ALLOW_LEGACY_LOGIN_IN_PRODUCTION", False),
        )
        if overrides:
            cfg = replace(cfg, **overrides)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required")
        try:
            parts = urlparse(self.database_url)
            if parts.scheme not in {"postgresql", "postgres", "sqlite"}:
                raise RuntimeError("DATABASE_URL has an unsupported scheme")
            if parts.scheme == "sqlite":
                # In-memory SQLite is the disposable preview/test database. A
                # *file* database is the gate installation's own store: the gate
                # PC must record events with no network and without a second
                # service to install and back up. It is refused everywhere else,
                # so a stray DATABASE_URL can never quietly become a local store.
                in_memory = self.database_url in {"sqlite://", "sqlite:///:memory:"}
                if self.environment == "production":
                    raise RuntimeError(
                        "Production DATABASE_URL must be PostgreSQL; the gate installation "
                        "is the only deployment that stores rows in SQLite"
                    )
                elif in_memory:
                    pass  # the disposable preview/test database
                elif self.environment != GATE_ENVIRONMENT:
                    raise RuntimeError(
                        "SQLite is restricted to disposable in-memory previews and tests, and to a "
                        "file database when ENVIRONMENT=gate"
                    )
                elif not parts.path.strip("/"):
                    raise RuntimeError(
                        "ENVIRONMENT=gate needs a database file, for example "
                        "sqlite:///C:/ProgramData/VisionAI/data/gate.db"
                    )
            else:
                if not parts.hostname or not parts.path.lstrip("/"):
                    raise RuntimeError("DATABASE_URL must include a host and database")
                _ = parts.port  # reject malformed ports without leaking the URL
                modes = parse_qs(parts.query, keep_blank_values=True).get("sslmode", [])
                if self.environment == "production" and modes != ["verify-full"]:
                    raise RuntimeError("Production DATABASE_URL must use sslmode=verify-full")
        except ValueError:
            raise RuntimeError("DATABASE_URL is malformed; URL-encode credentials") from None
        if not self.jwt_secret:
            raise RuntimeError("JWT_SECRET is required")
        if self.environment == "production":
            if len(self.jwt_secret) < 32 or self.jwt_secret.lower().startswith(("replace", "change")):
                raise RuntimeError("JWT_SECRET must be a strong random value in production")
            if self.debug:
                raise RuntimeError("Flask debug must be disabled in production")
            if self.demo_mode:
                raise RuntimeError(
                    "DEMO_MODE must never be enabled in production: it seeds a known "
                    "admin password and exposes the Test Lab page."
                )
            if self.legacy_password_login_enabled and not self.allow_legacy_login_in_production:
                raise RuntimeError(
                    "Password sign-in must be off in production; use Firebase sign-in. "
                    "Set LEGACY_PASSWORD_LOGIN_ENABLED=false, or acknowledge the risk "
                    "with ALLOW_LEGACY_LOGIN_IN_PRODUCTION=true for a temporary exception."
                )
        if self.environment == GATE_ENVIRONMENT:
            # The gate PC is a real installation on a real campus, so it gets the
            # production secret and demo rules. The two differences are
            # deliberate: it may keep its own file database, and it must keep a
            # way for the gate operator to sign in without a network round trip.
            if len(self.jwt_secret) < 32 or self.jwt_secret.lower().startswith(("replace", "change")):
                raise RuntimeError("JWT_SECRET must be a strong random value on the gate PC")
            if self.demo_mode:
                raise RuntimeError(
                    "DEMO_MODE must never be enabled on the gate PC: it seeds a known admin "
                    "password and exposes the Test Lab page."
                )
            if self.debug:
                raise RuntimeError("Flask debug must be disabled on the gate PC")
            if not (self.legacy_password_login_enabled or self.firebase_auth_enabled):
                raise RuntimeError(
                    "ENVIRONMENT=gate with no way to sign in: set "
                    "LEGACY_PASSWORD_LOGIN_ENABLED=true for the gate's own password login, "
                    "or configure Firebase sign-in."
                )
            if self.trust_proxy_headers:
                raise RuntimeError(
                    "ENVIRONMENT=gate serves the portal itself; there is no proxy in front of it, "
                    "so TRUST_PROXY_HEADERS must stay off"
                )
        if self.camera_source:
            from .frame_source import source_kind

            if not source_kind(self.camera_source):
                # Never echo the value: it may contain a camera password.
                raise RuntimeError(
                    "CAMERA_SOURCE must be an http(s) snapshot URL, an rtsp:// URL, or usb:0"
                )
        if not 0 < self.ocr_confidence_threshold < 1:
            raise RuntimeError("OCR_CONFIDENCE_THRESHOLD must be between 0 and 1")
        if self.overstay_hours <= 0:
            raise RuntimeError("OVERSTAY_HOURS must be positive")
        if self.jwt_ttl_minutes < 1 or self.jwt_ttl_minutes > 60:
            raise RuntimeError("JWT_TTL_MINUTES must be between 1 and 60")
        known_providers = {"password", "google.com"}
        unknown = set(self.firebase_allowed_providers) - known_providers
        if unknown:
            raise RuntimeError(
                "FIREBASE_ALLOWED_PROVIDERS contains unsupported providers: "
                + ", ".join(sorted(unknown))
            )
        if self.firebase_default_role not in {"head_admin", "transport_office"}:
            raise RuntimeError("FIREBASE_DEFAULT_ROLE must be head_admin or transport_office")
        if self.firebase_auth_enabled and not self.firebase_project_id:
            raise RuntimeError(
                "Firebase sign-in is enabled but no Firebase project id is configured. "
                "Set FIREBASE_PROJECT_ID, or turn FIREBASE_AUTH_ENABLED off."
            )
