from dataclasses import replace

import pytest
from sqlalchemy.exc import OperationalError

from backend import manage_access


def test_database_errors_are_sanitized(monkeypatch, config):
    monkeypatch.setenv("DATABASE_URL", "postgresql://demo-user:demo-password@host.invalid/db")
    monkeypatch.setattr(manage_access, "_load_dotenv", lambda: None)
    monkeypatch.setattr(manage_access.Config, "from_env", classmethod(lambda cls: config))
    def fail(_config):
        raise OperationalError("connection", {}, Exception("demo-password"))
    monkeypatch.setattr(manage_access, "get_database", fail)
    with pytest.raises(SystemExit) as raised:
        manage_access._database()
    assert "PostgreSQL" in str(raised.value)
    assert "demo-password" not in str(raised.value)
    assert raised.value.__suppress_context__


def test_missing_url_is_reported_without_connecting(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(manage_access, "_load_dotenv", lambda: None)
    with pytest.raises(SystemExit, match="DATABASE_URL is not set"):
        manage_access._database()


def test_cli_uses_shared_database(monkeypatch, config, db, capsys):
    monkeypatch.setenv("DATABASE_URL", config.database_url)
    monkeypatch.setattr(manage_access, "_load_dotenv", lambda: None)
    monkeypatch.setattr(manage_access.Config, "from_env", classmethod(lambda cls: config))
    monkeypatch.setattr(manage_access, "get_database", lambda _: db)
    assert manage_access.main(["add", "person@example.invalid", "--role", "head_admin"]) == 0
    assert manage_access.main(["list"]) == 0
    assert "person@example.invalid" in capsys.readouterr().out
    assert db.users.find_one({"email": "person@example.invalid"})["role"] == "head_admin"


def test_cli_write_errors_do_not_expose_driver_details(monkeypatch, capsys):
    monkeypatch.setattr(manage_access, "_database", lambda: object())
    def fail(*args, **kwargs):
        raise OperationalError("secret SQL", {}, Exception("demo-password"))
    monkeypatch.setattr(manage_access, "add_access_entry", fail)
    assert manage_access.main(["add", "person@example.invalid"]) == 1
    captured = capsys.readouterr()
    assert "PostgreSQL request failed" in captured.err
    assert "demo-password" not in captured.err and "secret SQL" not in captured.err


def test_schema_version_failures_are_reported_verbatim(monkeypatch, config):
    """The schema-mismatch message carries the only useful diagnosis; hiding it
    behind a generic driver warning costs hours."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://demo-user:demo-password@host.invalid/db")
    monkeypatch.setattr(manage_access, "_load_dotenv", lambda: None)
    monkeypatch.setattr(manage_access.Config, "from_env", classmethod(lambda cls: config))

    def fail(_config):
        raise RuntimeError(
            "Database schema version is missing or incompatible; apply the documented migration "
            "(database=postgres, role=transport_portal_app.demo, expected=[1], found=[])"
        )

    monkeypatch.setattr(manage_access, "get_database", fail)
    with pytest.raises(SystemExit) as raised:
        manage_access._database()

    message = str(raised.value)
    assert "found=[]" in message
    assert "role=transport_portal_app.demo" in message
    assert "demo-password" not in message
