from __future__ import annotations

import pytest
from sqlalchemy import inspect

from backend.config import Config
from backend.tests.conftest import build_config


def test_production_requires_a_strong_jwt_secret():
    config = build_config(environment="production", jwt_secret="short", database_url="postgresql://localhost/test?sslmode=verify-full")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        config.validate()


def test_production_rejects_debug_mode():
    config = build_config(environment="production", debug=True, database_url="postgresql://localhost/test?sslmode=verify-full")
    with pytest.raises(RuntimeError, match="debug"):
        config.validate()


@pytest.mark.parametrize("url", ["sqlite:///:memory:", "postgresql://localhost/db", "postgresql://localhost/db?sslmode=require", "postgresql://localhost/db?sslmode=verify-full&sslmode=disable"])
def test_production_rejects_unverified_database_connections(url):
    with pytest.raises(RuntimeError):
        build_config(environment="production", database_url=url).validate()


def test_production_accepts_verified_postgres_url():
    build_config(environment="production", database_url="postgresql://localhost/db?sslmode=verify-full").validate()


def test_cors_wildcards_are_rejected(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    with pytest.raises(ValueError):
        Config.from_env()


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://user:pass@example.edu/stream"])
def test_camera_stream_rejects_invalid_url(monkeypatch, url):
    monkeypatch.setenv("CAMERA_STREAM_URLS", '{"gate-1-entry": {"type": "hls", "url": "' + url + '"}}')
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    with pytest.raises(ValueError):
        Config.from_env()


def test_camera_stream_is_parsed(monkeypatch):
    monkeypatch.setenv("CAMERA_STREAM_URLS", '{"gate-1-entry": {"type": "hls", "url": "https://example.edu/s.m3u8", "label": "Gate 1 Entry"}}')
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    config = Config.from_env()
    assert config.camera_streams["gate-1-entry"]["type"] == "hls"
    assert config.camera_streams["gate-1-entry"]["label"] == "Gate 1 Entry"


def test_missing_database_url_is_rejected(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        Config.from_env()


def test_missing_jwt_secret_is_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        Config.from_env()


def test_production_defaults_cookie_secure_to_true(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/db?sslmode=verify-full")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    config = Config.from_env()
    assert config.cookie_secure is True
    assert config.debug is False


def test_private_tables_exist(db):
    inspector = inspect(db.engine)
    schema = "transport_portal" if db.engine.dialect.name == "postgresql" else None
    assert {"users", "buses", "drivers", "events", "audit_logs", "schema_version"} <= set(inspector.get_table_names(schema=schema))


def test_invalid_app_timezone_is_rejected_at_startup():
    with pytest.raises(RuntimeError, match="APP_TIMEZONE"):
        build_config(app_timezone="Mars/Olympus_Mons").validate()


@pytest.mark.parametrize(
    ("env_name", "value"),
    [("JWT_TTL_MINUTES", "not-an-int"), ("OCR_CONFIDENCE_THRESHOLD", "bad-float")],
)
def test_invalid_numeric_env_raises_runtime_error(monkeypatch, env_name, value):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    monkeypatch.setenv(env_name, value)
    with pytest.raises(RuntimeError, match=env_name):
        Config.from_env()


def test_firebase_project_id_retained_with_warning_when_app_id_missing(monkeypatch, caplog):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", "vision-ai-srmtrp")
    monkeypatch.delenv("FIREBASE_APP_ID", raising=False)
    config = Config.from_env()
    assert config.firebase == {}
    assert config.firebase_project_id == "vision-ai-srmtrp"
    assert config.firebase_auth_enabled is True
    assert "FIREBASE_APP_ID" in caplog.text
