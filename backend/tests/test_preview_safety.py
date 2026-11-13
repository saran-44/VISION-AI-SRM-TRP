import sys

import pytest
from scripts import run_preview

FAKE_EXTERNAL_URL = "postgresql://demo-user:demo-password@host.invalid/postgres"


def _no_database_call(*_args, **_kwargs):
    pytest.fail("The preview must reject this URL before contacting PostgreSQL")


@pytest.mark.parametrize("extra_args", [[], ["--no-seed"]])
@pytest.mark.parametrize("allow_demo_seed", ["true", "false"])
def test_preview_refuses_external_url_before_connecting(monkeypatch, capsys, extra_args, allow_demo_seed):
    monkeypatch.setenv("DATABASE_URL", FAKE_EXTERNAL_URL)
    monkeypatch.setenv("ALLOW_DEMO_SEED", allow_demo_seed)
    monkeypatch.delenv("ALLOW_REAL_PREVIEW_DB", raising=False)
    monkeypatch.setattr(sys, "argv", ["run_preview.py", *extra_args])
    monkeypatch.setattr(run_preview, "create_database_engine", _no_database_call)
    assert run_preview.main() == 2
    error = capsys.readouterr().err
    assert "Refusing to connect" in error
    assert "sqlite:///:memory:" in error
    assert "demo-password" not in error


def test_preview_refuses_external_seeding_before_connecting(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", FAKE_EXTERNAL_URL)
    monkeypatch.setenv("ALLOW_REAL_PREVIEW_DB", "true")
    monkeypatch.setenv("ALLOW_DEMO_SEED", "false")
    monkeypatch.setattr(sys, "argv", ["run_preview.py"])
    monkeypatch.setattr(run_preview, "create_database_engine", _no_database_call)
    assert run_preview.main() == 2
    assert "Refusing to seed" in capsys.readouterr().err


def test_preview_explicit_external_opt_in_does_not_print_url(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", FAKE_EXTERNAL_URL)
    monkeypatch.setenv("ALLOW_REAL_PREVIEW_DB", "true")
    monkeypatch.setattr(sys, "argv", ["run_preview.py", "--no-seed", "--port", "5057"])
    engine, config, db = object(), object(), object()
    calls = []
    class FakeApp:
        def run(self, **kwargs): calls.append(kwargs)
    monkeypatch.setattr(run_preview, "build_config", lambda url, secret: config)
    monkeypatch.setattr(run_preview, "create_database_engine", lambda url: engine)
    monkeypatch.setattr(run_preview, "get_database", lambda cfg, e: db)
    monkeypatch.setattr(run_preview, "seed_demo_data", _no_database_call)
    monkeypatch.setattr(run_preview, "create_app", lambda cfg, database_engine: FakeApp())
    assert run_preview.main() == 0
    assert calls[0]["port"] == 5057
    output = capsys.readouterr().out
    assert "external PostgreSQL (URL hidden)" in output
    assert "demo-user" not in output and "demo-password" not in output
