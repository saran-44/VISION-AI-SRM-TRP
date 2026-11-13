"""Regressions for the Firebase Hosting -> Cloud Run boundary.

Firebase Hosting serves uploaded files before applying rewrites, and forwards
only the ``__session`` cookie to dynamic backends.  These tests exercise the
same cookie boundary locally; a live Hosting deployment is still required to
verify the real platform integration.
"""
from __future__ import annotations

import json
from http.cookies import SimpleCookie
from pathlib import Path

from backend.tests.conftest import HEAD_ADMIN_EMAIL, HEAD_ADMIN_PASSWORD


ROOT = Path(__file__).resolve().parents[2]


def test_hosting_routes_dynamic_paths_to_cloud_run_without_uploading_pages():
    config = json.loads((ROOT / "firebase.json").read_text())
    hosting = config["hosting"]
    assert hosting["public"] == "frontend"
    assert "**/pages/**" in hosting["ignore"]
    assert hosting["rewrites"] == [
        {
            "source": "**",
            "run": {"serviceId": "srm-trp-transport", "region": "asia-south1"},
        }
    ]


def test_cookie_survives_the_hosting_forwarding_boundary(app, users):
    # Simulate Hosting: the browser may receive other cookies, but only
    # __session is forwarded to Cloud Run. Flask's cookie jar is disabled so
    # this test sends exactly the header that Hosting would forward.
    client = app.test_client(use_cookies=False)
    login = client.post(
        "/api/auth/login",
        json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD},
    )
    assert login.status_code == 200
    header = login.headers.get("Set-Cookie", "")
    cookies = SimpleCookie()
    cookies.load(header)
    assert "__session" in cookies
    assert "HttpOnly" in header and "SameSite=Lax" in header
    forwarded = {"Cookie": f"__session={cookies['__session'].value}"}

    assert client.get("/api/auth/me", headers=forwarded).status_code == 200
    dashboard = client.get("/dashboard", headers=forwarded)
    assert dashboard.status_code == 200
    assert b"Live Dashboard" in dashboard.data
    # Dynamic pages carry the backend headers, not only the Hosting headers.
    assert dashboard.headers["Permissions-Policy"] == (
        "camera=(self), microphone=(), geolocation=()"
    )
    assert "no-store" in dashboard.headers["Cache-Control"]
    assert client.get("/manage", headers=forwarded).status_code in (301, 302)

    logout = client.post("/api/auth/logout", headers=forwarded)
    assert logout.status_code == 200
    assert "__session=" in logout.headers.get("Set-Cookie", "")
    assert client.get("/api/auth/me").status_code == 401


def test_old_cookie_name_does_not_authorise_requests(app, users):
    client = app.test_client(use_cookies=False)
    login = client.post(
        "/api/auth/login",
        json={"email": HEAD_ADMIN_EMAIL, "password": HEAD_ADMIN_PASSWORD},
    )
    cookies = SimpleCookie()
    cookies.load(login.headers.get("Set-Cookie", ""))
    assert "__session" in cookies
    response = client.get(
        "/api/auth/me",
        headers={"Cookie": f"transport_token={cookies['__session'].value}"},
    )
    assert response.status_code == 401
