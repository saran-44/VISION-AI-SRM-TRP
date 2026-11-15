"""The live dashboard stream and the limits of a single free container.

`/api/stream` used to be `while True`. Each connection therefore held one
gunicorn thread for as long as the browser tab stayed open, and a closed tab was
not noticed until the next write — on the Render free plan (one worker, four
threads at the time) four idle admin dashboards were enough to stop the portal
answering anything at all. These tests pin the three properties that fix it:
the response ends on its own, it keeps the connection alive while it is open,
and it reconnects without hammering `compute_stats()`.

The last two tests are about the rest of the free plan: an ephemeral disk (so
the error log must also reach the platform's log stream) and the fact that the
vision stack is not installed there.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.tests.conftest import login_head_admin

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture()
def short_stream(monkeypatch):
    monkeypatch.setenv("API_SSE_SECONDS", "2")
    monkeypatch.setenv("API_SSE_REFRESH_SECONDS", "1")
    monkeypatch.setenv("API_SSE_HEARTBEAT_SECONDS", "1")
    monkeypatch.setenv("API_STATS_CACHE_SECONDS", "60")


def _drain(response, *, limit_seconds: float = 20.0) -> str:
    """Consume the event stream, failing loudly instead of hanging forever."""
    chunks: list[str] = []
    deadline = time.monotonic() + limit_seconds
    for chunk in response.response:
        chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        if time.monotonic() > deadline:
            pytest.fail("the stream did not end on its own; it is unbounded again")
    return "".join(chunks)


def test_the_stream_ends_so_the_thread_comes_back(client, users, short_stream):
    login_head_admin(client, users)
    response = client.get("/api/stream")

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    body = _drain(response)

    # Ends by itself, with an explicit end event ...
    assert body.rstrip().endswith("event: end\ndata: {}")
    # ... and tells EventSource to reconnect straight away, so the operator sees
    # a continuous feed rather than a 2-second hole.
    assert body.startswith("retry: ")


def test_the_stream_sends_ticks_and_keep_alives(client, users, short_stream):
    login_head_admin(client, users)
    body = _drain(client.get("/api/stream"))

    assert '"type": "tick"' in body
    assert "recent_events" in body and "inside_buses" in body
    # A proxy that sees only silence will buffer or drop the connection.
    assert ": keep-alive" in body


def test_concurrent_streams_share_one_stats_calculation(client, users, short_stream, monkeypatch):
    """`compute_stats()` is a full read of every table; N tabs must not mean N reads."""
    import backend.app as app_module

    calls = {"n": 0}
    real = app_module.compute_stats

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(app_module, "compute_stats", counting)

    login_head_admin(client, users)
    # Two connections, back to back. They cannot be interleaved here because
    # Flask's test client shares one request-context stack per thread (a browser
    # uses a separate connection per tab), but the second one starts well inside
    # API_STATS_CACHE_SECONDS, which is the condition the cache has to satisfy.
    _drain(client.get("/api/stream"))
    _drain(client.get("/api/stream"))

    assert calls["n"] == 1


def test_the_stream_needs_a_session(client):
    assert client.get("/api/stream").status_code == 401


def test_a_free_instance_gets_eight_threads(monkeypatch):
    """The ceiling that made four dashboards fatal is raised, and stays raised."""
    entrypoint = (ROOT / "deploy" / "render" / "entrypoint.sh").read_text()
    blueprint = (ROOT / "render.yaml").read_text()

    assert '--threads "${GUNICORN_THREADS:-8}"' in entrypoint
    assert '--workers "${WEB_CONCURRENCY:-1}"' in entrypoint
    # Recycles a worker that has been up for days; the free plan never restarts.
    assert "--max-requests 800" in entrypoint
    assert 'key: GUNICORN_THREADS\n        value: "8"' in blueprint
    # The stream's lifetime is a documented setting, not an accident of code.
    assert "API_SSE_SECONDS" in blueprint


def test_error_blocks_also_reach_the_platform_log_stream(caplog):
    """Render keeps no disk, so the log stream is the only survivor."""
    from backend import diagnostics

    with caplog.at_level("WARNING", logger="backend.diagnostics"):
        diagnostics.log_error("render", "database went away", detail="pool timeout")

    messages = [record.getMessage() for record in caplog.records]
    assert any("database went away" in message and "ref=" in message for message in messages)


def test_a_render_scan_points_at_the_gate_executable_by_its_real_name(client, users, monkeypatch):
    """The 503 on a cloud instance must name the file the build actually produces."""
    import backend.app as app_module
    from backend.vision import VisionUnavailable

    login_head_admin(client, users)
    monkeypatch.setattr(
        app_module,
        "decode_image",
        lambda payload: (_ for _ in ()).throw(VisionUnavailable("no torch here")),
    )

    import io

    response = client.post(
        "/api/detection/scan",
        data={"image": (io.BytesIO(b"\xff\xd8\xff\xdb"), "frame.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 503
    payload = response.get_json()
    hint = payload["error"] + payload["auto_scan"]["agent"]
    assert "VisionAI.exe" in hint
    assert "GateAgent" not in hint


def test_the_live_counters_do_not_read_the_whole_table(app, db, config, monkeypatch):
    """`/api/stats` runs on every stream tick; it must not scan all history."""
    from dataclasses import replace
    from datetime import datetime, timedelta

    from backend.services import compute_stats

    seen: list[dict] = []
    real_find = db.events.find

    def recording_find(filter=None, projection=None, *args, **kwargs):  # noqa: A002
        seen.append(filter or {})
        return real_find(filter, projection, *args, **kwargs)

    monkeypatch.setattr(db.events, "find", recording_find)

    def ages_of_windows(cfg) -> list[timedelta]:
        seen.clear()
        compute_stats(db, cfg)
        found = [item["timestamp"]["$gte"] for item in seen if "timestamp" in item]
        assert found, f"no bounded query was made: {seen}"
        return [datetime.utcnow() - value for value in found]

    # The widest query reaches back exactly the lookback window; the others are
    # "today". Nothing reads the events table without a bound.
    default_ages = ages_of_windows(config)
    assert any(timedelta(days=44) < age < timedelta(days=46) for age in default_ages), default_ages

    # The window is configurable, so a deployment that keeps a bus parked for a
    # term can widen it without a code change.
    widened = ages_of_windows(replace(config, stats_lookback_days=90))
    assert any(age > timedelta(days=89) for age in widened), widened
