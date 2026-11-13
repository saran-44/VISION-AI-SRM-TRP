"""Regressions for the free single-service deployment path (Render).

The free path serves the Flask API and the frontend from one container with no
Secret Manager, no mounted secret file and no reverse-proxy IAM. These checks
pin the two things that differ from the Cloud Run path: the image (no torch, a
$PORT-aware entrypoint) and the trusted-proxy behaviour used for login
throttling and the audit log.
"""
from __future__ import annotations

from pathlib import Path

from backend.app import create_app
from backend.tests.conftest import (
    HEAD_ADMIN_EMAIL,
    HEAD_ADMIN_PASSWORD,
    build_config,
)

ROOT = Path(__file__).resolve().parents[2]


def test_free_image_honours_port_and_omits_the_vision_stack():
    dockerfile = (ROOT / "deploy" / "render" / "Dockerfile").read_text()
    entrypoint = (ROOT / "deploy" / "render" / "entrypoint.sh").read_text()

    # 512 MB cannot hold CPU torch, so the free image must not install it.
    assert "requirements-vision.txt" not in dockerfile
    assert "requirements.txt" in dockerfile
    assert 'CMD ["/app/entrypoint.sh"]' in dockerfile
    # The platform injects $PORT; binding a hard-coded port would fail health checks.
    assert "${PORT:-10000}" in entrypoint
    assert "backend.app:create_app()" in entrypoint
    # The CA arrives base64-encoded because free plans have no mounted secrets.
    assert "PGSSLROOTCERT_B64" in entrypoint
    assert 'export PGSSLROOTCERT="$CERT_DIR/supabase-ca.crt"' in entrypoint


def test_render_blueprint_is_one_free_service_with_prompted_secrets():
    blueprint = (ROOT / "render.yaml").read_text()

    assert "plan: free" in blueprint
    assert "runtime: docker" in blueprint
    assert "deploy/render/Dockerfile" in blueprint
    assert "healthCheckPath: /api/health" in blueprint
    # One service only: the frontend is served by Flask, so no second static site.
    assert blueprint.count("type: web") == 1

    for key in ("DATABASE_URL", "JWT_SECRET", "DEVICE_API_KEYS", "FIREBASE_API_KEY", "PGSSLROOTCERT_B64"):
        assert f"- key: {key}\n        sync: false" in blueprint, key

    # Never a private connection string in Git.
    assert "postgresql://" not in blueprint and "postgres://" not in blueprint


def test_trusted_proxy_headers_record_the_real_client_address(app, db, users):
    proxied = create_app(build_config(trust_proxy_headers=True), database_engine=db.engine)
    proxied.config.update(TESTING=True)
    client = proxied.test_client()

    response = login_with_ip(client, "203.0.113.9")
    assert response.status_code == 200

    entries = [entry for entry in db.audit_logs.find({"action": "login"})]
    assert entries
    assert entries[-1]["ip"] == "203.0.113.9"
    # The scheme is forwarded too, so HSTS and Secure cookies work behind TLS.
    assert response.headers.get("Set-Cookie", "").count("__session") == 1


def test_untrusted_proxy_headers_are_ignored(app, db, users):
    client = app.test_client()

    response = login_with_ip(client, "203.0.113.9")
    assert response.status_code == 200

    entries = [entry for entry in db.audit_logs.find({"action": "login"})]
    assert entries
    # Without the opt-in the spoofable header must not reach the audit log.
    assert entries[-1]["ip"] != "203.0.113.9"


def login_with_ip(client, forwarded_for: str):
    return client.post(
        "/api/auth/login",
        json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD},
        headers={"X-Forwarded-For": forwarded_for, "X-Forwarded-Proto": "https"},
    )
