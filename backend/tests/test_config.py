from __future__ import annotations

import os
from dataclasses import replace

import pytest

from backend.config import Config
from backend.tests.conftest import build_config


def test_production_requires_a_strong_jwt_secret():
    config = build_config(environment="production", jwt_secret="short")
    with pytest.raises(RuntimeError):
        config.validate()


def test_production_rejects_debug_mode():
    config = build_config(environment="production", debug=True)
    with pytest.raises(RuntimeError):
        config.validate()


def test_cors_wildcards_are_rejected(monkeypatch):
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "*")
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    with pytest.raises(ValueError):
        Config.from_env()


def test_camera_stream_requires_http_scheme(monkeypatch):
    monkeypatch.setenv("CAMERA_STREAM_URLS", '{"gate-1-entry": {"type": "hls", "url": "file:///etc/passwd"}}')
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    with pytest.raises(ValueError):
        Config.from_env()


def test_camera_stream_rejects_embedded_credentials(monkeypatch):
    monkeypatch.setenv(
        "CAMERA_STREAM_URLS",
        '{"gate-1-entry": {"type": "mjpeg", "url": "https://user:pass@example.edu/stream"}}',
    )
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    with pytest.raises(ValueError):
        Config.from_env()


def test_camera_stream_is_parsed(monkeypatch):
    monkeypatch.setenv(
        "CAMERA_STREAM_URLS",
        '{"gate-1-entry": {"type": "hls", "url": "https://example.edu/s.m3u8", "label": "Gate 1 Entry"}}',
    )
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    config = Config.from_env()
    assert config.camera_streams["gate-1-entry"]["type"] == "hls"
    assert config.camera_streams["gate-1-entry"]["label"] == "Gate 1 Entry"


def test_missing_mongo_uri_is_rejected(monkeypatch):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    with pytest.raises(RuntimeError):
        Config.from_env()


def test_missing_jwt_secret_is_rejected(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.delenv("JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        Config.from_env()


def test_production_defaults_cookie_secure_to_true(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("MONGO_URI", "mongodb://127.0.0.1:27017")
    monkeypatch.setenv("JWT_SECRET", "a-very-long-secret-value-for-testing-1234")
    monkeypatch.delenv("COOKIE_SECURE", raising=False)
    config = Config.from_env()
    assert config.cookie_secure is True
    assert config.debug is False


def test_indexes_are_created(app, db):
    assert db.users.index_information()
    assert db.buses.index_information()
    assert db.events.index_information()
    assert db.audit_logs.index_information()
