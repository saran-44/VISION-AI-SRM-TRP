"""Production startup tolerates transient Direct VPC/NAT connectivity delays."""
from __future__ import annotations

import pytest
from pymongo.errors import ConfigurationError, OperationFailure, ServerSelectionTimeoutError

from backend import db as db_module
from backend.tests.conftest import build_config


def test_production_startup_retries_transient_connection_failures(monkeypatch):
    config = build_config(environment="production")
    client, expected_db = object(), object()
    calls = []
    sleeps = []

    monkeypatch.setattr(db_module, "create_mongo_client", lambda _uri: client)

    def get_database(_config, actual_client):
        assert actual_client is client
        calls.append(1)
        if len(calls) < 3:
            raise ServerSelectionTimeoutError("sensitive connection detail")
        return expected_db

    monkeypatch.setattr(db_module, "get_database", get_database)
    monkeypatch.setattr(db_module.time, "sleep", sleeps.append)
    assert db_module.get_database_for_startup(config) is expected_db
    assert len(calls) == 3
    assert sleeps == [5, 5]


def test_production_startup_retries_srv_configuration_failures(monkeypatch):
    config = build_config(environment="production")
    expected_db = object()
    calls = []

    def make_client(_uri):
        calls.append(1)
        if len(calls) == 1:
            raise ConfigurationError("temporary SRV DNS failure")
        return object()

    monkeypatch.setattr(db_module, "create_mongo_client", make_client)
    monkeypatch.setattr(db_module, "get_database", lambda *_: expected_db)
    monkeypatch.setattr(db_module.time, "sleep", lambda _: None)
    assert db_module.get_database_for_startup(config) is expected_db
    assert len(calls) == 2


def test_production_startup_stops_after_a_bounded_number_of_failures(monkeypatch, caplog):
    config = build_config(environment="production")
    calls = []

    def fail(*_args):
        calls.append(1)
        raise ServerSelectionTimeoutError("credential-looking sensitive detail")

    clock = [0.0]
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(db_module, "get_database", fail)
    monkeypatch.setattr(db_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(db_module.time, "sleep", sleep)
    with pytest.raises(RuntimeError, match="MongoDB initialization failed") as error:
        db_module.get_database_for_startup(config, object())
    # Even immediately-failing SRV lookups are retried for the full window,
    # rather than exhausting a fixed attempt count before VPC egress is ready.
    assert clock[0] == db_module.MONGO_STARTUP_TIMEOUT_SECONDS
    # A sleep that reaches the deadline must not start a 25th attempt.
    assert len(calls) == db_module.MONGO_STARTUP_TIMEOUT_SECONDS // 5
    assert all(0 < seconds <= 5 for seconds in sleeps)
    assert "credential-looking" not in str(error.value)
    assert "credential-looking" not in caplog.text


def test_final_operation_timeout_is_limited_by_remaining_window(monkeypatch):
    from contextlib import nullcontext

    config = build_config(environment="production")
    clock = [0.0]
    timeouts = []
    attempts = []

    def fail(*_args):
        attempts.append(clock[0])
        clock[0] = 112 if len(attempts) == 1 else clock[0] + 2
        raise ServerSelectionTimeoutError("private detail")

    def sleep(seconds):
        clock[0] += seconds

    def timeout(seconds):
        timeouts.append(seconds)
        return nullcontext()

    monkeypatch.setattr(db_module, "get_database", fail)
    monkeypatch.setattr(db_module, "mongo_timeout", timeout)
    monkeypatch.setattr(db_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(db_module.time, "sleep", sleep)
    with pytest.raises(RuntimeError, match="MongoDB initialization failed"):
        db_module.get_database_for_startup(config, object())
    assert attempts == [0, 117]
    assert timeouts == [20, 3]
    assert clock[0] == 120


def test_mongo_authentication_error_is_not_retried(monkeypatch):
    config = build_config(environment="production")
    calls = []

    def fail(*_args):
        calls.append(1)
        raise OperationFailure("not authorized", code=13)

    monkeypatch.setattr(db_module, "get_database", fail)
    monkeypatch.setattr(db_module.time, "sleep", lambda _: pytest.fail("must not retry auth errors"))
    with pytest.raises(RuntimeError, match="MongoDB rejected database initialization") as error:
        db_module.get_database_for_startup(config, object())
    assert "not authorized" not in str(error.value)
    assert len(calls) == 1


def test_development_does_not_retry_connection_failures(monkeypatch):
    config = build_config(environment="development")
    calls = []

    def fail(*_args):
        calls.append(1)
        raise ServerSelectionTimeoutError("network unavailable")

    monkeypatch.setattr(db_module, "get_database", fail)
    monkeypatch.setattr(db_module.time, "sleep", lambda _: pytest.fail("must not retry in development"))
    with pytest.raises(ServerSelectionTimeoutError):
        db_module.get_database_for_startup(config, object())
    assert len(calls) == 1
