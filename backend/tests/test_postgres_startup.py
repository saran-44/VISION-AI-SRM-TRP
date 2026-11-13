"""Startup retries connection outages without exposing database credentials."""
import pytest
from sqlalchemy.exc import OperationalError, ProgrammingError
from backend import db as db_module
from backend.tests.conftest import build_config


def test_production_startup_retries_transient_connections(monkeypatch):
    config = build_config(environment="production")
    attempts, sleeps = [], []
    expected = object()
    def get_db(*_):
        attempts.append(1)
        if len(attempts) < 3:
            raise OperationalError("hidden SQL", {}, Exception("sensitive connection detail"))
        return expected
    monkeypatch.setattr(db_module, "get_database", get_db)
    monkeypatch.setattr(db_module.time, "sleep", sleeps.append)
    assert db_module.get_database_for_startup(config) is expected
    assert sleeps == [5, 5]


def test_production_startup_retries_for_bounded_window(monkeypatch, caplog):
    config = build_config(environment="production")
    clock, attempts = [0], []
    def fail(*_):
        attempts.append(1)
        raise OperationalError("secret SQL", {}, Exception("credential-looking detail"))
    monkeypatch.setattr(db_module, "get_database", fail)
    monkeypatch.setattr(db_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(db_module.time, "sleep", lambda n: clock.__setitem__(0, clock[0] + n))
    with pytest.raises(RuntimeError, match="PostgreSQL initialization failed") as error:
        db_module.get_database_for_startup(config, object())
    assert clock[0] == db_module.STARTUP_TIMEOUT_SECONDS
    assert len(attempts) == db_module.STARTUP_TIMEOUT_SECONDS // 5
    assert "credential-looking" not in str(error.value) + caplog.text


def test_production_authentication_errors_are_not_retried(monkeypatch):
    config = build_config(environment="production")
    class PrivateError(Exception): sqlstate = "28P01"
    def fail(*_): raise OperationalError("hidden", {}, PrivateError("sensitive"))
    monkeypatch.setattr(db_module, "get_database", fail)
    monkeypatch.setattr(db_module.time, "sleep", lambda _: pytest.fail("must not retry auth errors"))
    with pytest.raises(RuntimeError, match="rejected") as error:
        db_module.get_database_for_startup(config, object())
    assert "sensitive" not in str(error.value)


def test_development_does_not_retry_connection_failures(monkeypatch):
    def fail(*_): raise OperationalError("hidden", {}, Exception("network"))
    monkeypatch.setattr(db_module, "get_database", fail)
    with pytest.raises(OperationalError):
        db_module.get_database_for_startup(build_config(), object())


def test_invalid_engine_configuration_is_sanitized_without_retry(monkeypatch):
    from sqlalchemy.exc import ArgumentError
    def fail(*_): raise ArgumentError("demo-password in connection detail")
    monkeypatch.setattr(db_module, "get_database", fail)
    monkeypatch.setattr(db_module.time, "sleep", lambda _: pytest.fail("must not retry invalid configuration"))
    with pytest.raises(RuntimeError, match="configuration is invalid") as error:
        db_module.get_database_for_startup(build_config(environment="production"))
    assert "demo-password" not in str(error.value)
