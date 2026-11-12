from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))


def _csv(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


def _db_name_from_uri(uri: str) -> str:
    path = urlparse(uri).path.lstrip("/")
    return path.split("?", 1)[0] or "transport_db"


def _parse_origins(values: tuple[str, ...]) -> tuple[str, ...]:
    parsed: list[str] = []
    for value in values:
        origin = value.rstrip("/")
        parts = urlparse(origin)
        if parts.scheme not in {"http", "https"} or not parts.netloc or "*" in origin:
            raise ValueError("CORS_ALLOWED_ORIGINS must contain explicit http(s) origins, not wildcards")
        parsed.append(origin)
    return tuple(dict.fromkeys(parsed))


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
        if stream_type not in {"hls", "mjpeg"}:
            raise ValueError("Camera stream type must be hls or mjpeg")
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("Camera stream URLs must use http or https")
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
    mongo_uri: str
    mongo_db_name: str
    jwt_secret: str
    jwt_ttl_minutes: int
    cookie_secure: bool
    cors_allowed_origins: tuple[str, ...] = field(default_factory=tuple)
    device_api_keys: tuple[str, ...] = field(default_factory=tuple)
    login_rate_limit: str = "5 per minute;20 per hour"
    rate_limit_enabled: bool = True
    rate_limit_storage_uri: str = "memory://"
    app_timezone: str = "Asia/Kolkata"
    ocr_confidence_threshold: float = 0.75
    overstay_hours: float = 12.0
    camera_streams: dict[str, dict[str, str]] = field(default_factory=dict)
    frontend_dir: Path = ROOT / "frontend"

    @classmethod
    def from_env(cls, overrides: dict | None = None) -> "Config":
        environment = os.getenv("ENVIRONMENT", "development").strip().lower()
        debug_requested = _bool("FLASK_DEBUG", False)
        mongo_uri = os.getenv("MONGO_URI", "").strip()
        jwt_secret = os.getenv("JWT_SECRET", "").strip()
        cors_origins = _parse_origins(_csv("CORS_ALLOWED_ORIGINS"))
        camera_streams = _parse_camera_streams(os.getenv("CAMERA_STREAM_URLS", ""))
        cfg = cls(
            environment=environment,
            debug=debug_requested and environment == "development",
            testing=_bool("TESTING", False),
            mongo_uri=mongo_uri,
            mongo_db_name=os.getenv("MONGO_DB_NAME", "").strip() or _db_name_from_uri(mongo_uri),
            jwt_secret=jwt_secret,
            jwt_ttl_minutes=_int("JWT_TTL_MINUTES", 15),
            cookie_secure=_bool("COOKIE_SECURE", environment == "production"),
            cors_allowed_origins=cors_origins,
            device_api_keys=_csv("DEVICE_API_KEYS"),
            login_rate_limit=os.getenv("LOGIN_RATE_LIMIT", "5 per minute;20 per hour"),
            rate_limit_enabled=_bool("RATELIMIT_ENABLED", True),
            rate_limit_storage_uri=os.getenv("RATELIMIT_STORAGE_URI", "memory://"),
            app_timezone=os.getenv("APP_TIMEZONE", "Asia/Kolkata"),
            ocr_confidence_threshold=_float("OCR_CONFIDENCE_THRESHOLD", 0.75),
            overstay_hours=_float("OVERSTAY_HOURS", 12.0),
            camera_streams=camera_streams,
        )
        if overrides:
            cfg = replace(cfg, **overrides)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        if not self.mongo_uri:
            raise RuntimeError("MONGO_URI is required")
        allowed_uri_prefixes = ("mongodb://", "mongodb+srv://", "mongomock://")
        if not self.mongo_uri.startswith(allowed_uri_prefixes):
            raise RuntimeError("MONGO_URI has an unsupported scheme")
        if not self.jwt_secret:
            raise RuntimeError("JWT_SECRET is required")
        if self.environment == "production":
            if len(self.jwt_secret) < 32 or self.jwt_secret.lower().startswith(("replace", "change")):
                raise RuntimeError("JWT_SECRET must be a strong random value in production")
            if self.debug:
                raise RuntimeError("Flask debug must be disabled in production")
        if not 0 < self.ocr_confidence_threshold < 1:
            raise RuntimeError("OCR_CONFIDENCE_THRESHOLD must be between 0 and 1")
        if self.overstay_hours <= 0:
            raise RuntimeError("OVERSTAY_HOURS must be positive")
        if self.jwt_ttl_minutes < 1 or self.jwt_ttl_minutes > 60:
            raise RuntimeError("JWT_TTL_MINUTES must be between 1 and 60")
