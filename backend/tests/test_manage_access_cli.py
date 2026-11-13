from __future__ import annotations

from dataclasses import replace

import mongomock
import pytest
from pymongo.errors import ConfigurationError, OperationFailure, ServerSelectionTimeoutError

from backend import manage_access


FAKE_URI = "mongodb+srv://demo-user:demo-password@cluster.example.invalid/"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ConfigurationError(f"DNS lookup failed for {FAKE_URI}"), "configuration or DNS"),
        (ServerSelectionTimeoutError(f"connection failed for {FAKE_URI}"), "Could not establish"),
        (OperationFailure(f"authentication failed for {FAKE_URI}", code=18), "authentication failed"),
        (OperationFailure(f"bad auth for {FAKE_URI}", code=8000), "authentication failed"),
        (OperationFailure(f"permission denied for {FAKE_URI}", code=13), "denied database access"),
        (OperationFailure(f"index error for {FAKE_URI}", code=11000), "database initialization"),
    ],
)
@pytest.mark.parametrize("failure_stage", ["client", "database"])
def test_database_errors_are_useful_and_do_not_expose_uri(
    monkeypatch, config, error, expected, failure_stage
):
    monkeypatch.setenv("MONGO_URI", FAKE_URI)
    monkeypatch.setattr(manage_access, "_load_dotenv", lambda: None)
    monkeypatch.setattr(manage_access.Config, "from_env", classmethod(lambda cls: config))
    client = object()

    def create_client(uri):
        assert uri == FAKE_URI
        if failure_stage == "client":
            raise error
        return client

    def get_database(received_config, received_client):
        assert received_config is config
        assert received_client is client
        raise error

    monkeypatch.setattr(manage_access, "create_mongo_client", create_client)
    monkeypatch.setattr(manage_access, "get_database", get_database)

    with pytest.raises(SystemExit) as raised:
        manage_access._database()

    message = str(raised.value)
    assert expected in message
    assert "demo-user" not in message
    assert "demo-password" not in message
    assert FAKE_URI not in message
    assert raised.value.__suppress_context__
    if isinstance(error, ServerSelectionTimeoutError):
        assert "does not verify" in message


def test_malformed_markdown_uri_has_a_safe_error(monkeypatch):
    monkeypatch.setenv(
        "MONGO_URI",
        "mongodb+srv://demo-user:[demo-password@cluster.example.invalid](mailto:bad)",
    )
    monkeypatch.setattr(manage_access, "_load_dotenv", lambda: None)

    with pytest.raises(SystemExit) as raised:
        manage_access._database()

    assert "malformed" in str(raised.value)
    assert "demo-password" not in str(raised.value)
    assert raised.value.__suppress_context__


def test_missing_uri_is_reported_without_contacting_a_database(monkeypatch):
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.setattr(manage_access, "_load_dotenv", lambda: None)

    with pytest.raises(SystemExit, match="MONGO_URI is not set"):
        manage_access._database()


def test_cli_uses_the_configured_database_and_persists_with_a_shared_client(
    monkeypatch, config, capsys
):
    uri = "mongomock://transport"
    config = replace(config, mongo_uri=uri, mongo_db_name="selected_database")
    client = mongomock.MongoClient()
    monkeypatch.setenv("MONGO_URI", uri)
    monkeypatch.setattr(manage_access, "_load_dotenv", lambda: None)
    monkeypatch.setattr(manage_access.Config, "from_env", classmethod(lambda cls: config))
    monkeypatch.setattr(manage_access, "create_mongo_client", lambda received_uri: client)

    assert manage_access.main(["add", "person@example.invalid", "--role", "head_admin"]) == 0
    assert manage_access.main(["list"]) == 0
    assert "person@example.invalid" in capsys.readouterr().out
    assert client.selected_database.users.find_one({"email": "person@example.invalid"})["role"] == "head_admin"
    assert client.transport_db.users.count_documents({}) == 0
