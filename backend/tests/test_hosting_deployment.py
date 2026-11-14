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


INSTABOX_ORIGIN = "https://8080-agq5ufybv2apmker5klcd7t7zi.instabox.tech"


def test_hosting_redirects_every_path_to_the_instabox_backend():
    """Hosting redirects visitors to the full-vision InstaBox backend.

    A rewrite to ``run.serviceId`` needs Blaze billing, so the deployed config
    redirects instead: one capture rule keeps the path and query string, and a
    catch-all covers anything the capture misses. Every visitor still reaches
    the Flask app, which owns authentication, roles and the page templates.
    """
    config = json.loads((ROOT / "firebase.json").read_text())
    hosting = config["hosting"]
    assert hosting["public"] == "deploy/firebase/public"
    assert "rewrites" not in hosting, "Spark plan cannot rewrite to Cloud Run"
    redirects = hosting["redirects"]
    assert redirects, "hosting must send visitors to the InstaBox deployment"
    assert all(rule["type"] == 302 for rule in redirects), "keep it temporary"
    assert all(rule["destination"].startswith(INSTABOX_ORIGIN) for rule in redirects)
    # First rule keeps the path and query string; last rule is the catch-all.
    assert redirects[0] == {
        "source": "/:path*",
        "destination": f"{INSTABOX_ORIGIN}/:path*",
        "type": 302,
    }
    assert redirects[-1] == {"source": "**", "destination": INSTABOX_ORIGIN, "type": 302}


def test_hosting_public_directory_has_a_fallback_page():
    """Hosting refuses a deploy without a public directory with content.

    The redirects shadow this page, so it is only a safety net, but it must
    exist and must point at the live deployment.
    """
    public = ROOT / "firebase.json"
    hosting = json.loads(public.read_text())["hosting"]
    index = ROOT / hosting["public"] / "index.html"
    assert index.is_file()
    html = index.read_text()
    assert INSTABOX_ORIGIN in html
    assert "http-equiv=\"refresh\"" in html


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
