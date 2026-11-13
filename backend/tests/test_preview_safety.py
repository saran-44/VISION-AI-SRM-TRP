from __future__ import annotations

import sys

import pytest

from scripts import run_preview


FAKE_EXTERNAL_URI = "mongodb+srv://demo-user:demo-password@cluster.example.invalid/"


def _no_database_call(*_args, **_kwargs):
    pytest.fail("The preview must reject this URI before contacting MongoDB")


@pytest.mark.parametrize("extra_args", [[], ["--no-seed"]])
@pytest.mark.parametrize("allow_demo_seed", ["true", "false"])
def test_preview_refuses_an_external_uri_before_connecting(
    monkeypatch, capsys, extra_args, allow_demo_seed
):
    monkeypatch.setenv("MONGO_URI", FAKE_EXTERNAL_URI)
    monkeypatch.setenv("ALLOW_DEMO_SEED", allow_demo_seed)
    monkeypatch.delenv("ALLOW_REAL_PREVIEW_DB", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_preview.py", *extra_args])
    monkeypatch.setattr(run_preview, "create_mongo_client", _no_database_call)
    monkeypatch.setattr(run_preview, "get_database", _no_database_call)

    assert run_preview.main() == 2
    error = capsys.readouterr().err
    assert "Refusing to connect" in error
    assert "mongomock://transport_preview" in error
    assert "demo-password" not in error


def test_preview_refuses_external_seeding_before_connecting(monkeypatch, capsys):
    monkeypatch.setenv("MONGO_URI", FAKE_EXTERNAL_URI)
    monkeypatch.setenv("ALLOW_REAL_PREVIEW_DB", "true")
    monkeypatch.setenv("ALLOW_DEMO_SEED", "false")
    monkeypatch.setattr(sys, "argv", ["run_preview.py"])
    monkeypatch.setattr(run_preview, "create_mongo_client", _no_database_call)
    monkeypatch.setattr(run_preview, "get_database", _no_database_call)

    assert run_preview.main() == 2
    assert "Refusing to seed" in capsys.readouterr().err


def test_preview_explicit_external_opt_in_does_not_print_uri(monkeypatch, capsys):
    monkeypatch.setenv("MONGO_URI", FAKE_EXTERNAL_URI)
    monkeypatch.setenv("ALLOW_REAL_PREVIEW_DB", "true")
    monkeypatch.setenv("PREVIEW_PASSWORD", "demo-only-password")
    monkeypatch.setattr(sys, "argv", ["run_preview.py", "--no-seed", "--port", "5057"])
    client, config, db = object(), object(), object()
    calls = []

    class FakeApp:
        def run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(run_preview, "build_config", lambda uri, secret: config)
    monkeypatch.setattr(run_preview, "create_mongo_client", lambda uri: client)
    monkeypatch.setattr(run_preview, "get_database", lambda cfg, c: db)
    monkeypatch.setattr(run_preview, "seed_demo_data", _no_database_call)
    monkeypatch.setattr(run_preview, "create_app", lambda cfg, mongo_client: FakeApp())

    assert run_preview.main() == 0
    assert calls[0]["port"] == 5057
    output = capsys.readouterr().out
    assert "external MongoDB (URI hidden)" in output
    assert "demo-user" not in output
    assert "demo-password@" not in output
