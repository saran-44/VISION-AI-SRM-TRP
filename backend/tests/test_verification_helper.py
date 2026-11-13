"""The onboarding helper sends verification without logging credentials."""
from __future__ import annotations

import requests
import pytest

from scripts import send_firebase_verification as helper


class Response:
    def __init__(self, ok=True, status=200, body=None):
        self.ok = ok
        self.status_code = status
        self.body = body if body is not None else {}

    def json(self):
        return self.body


def test_sends_verification_only_after_firebase_password_signin(monkeypatch, capsys):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return Response(body={"idToken": "private-token", "refreshToken": "private-refresh"})
        return Response()

    monkeypatch.setattr(helper.requests, "post", post)
    helper.send_verification("admin@example.invalid", "private-password", "test-key")
    assert len(calls) == 2
    assert calls[0][0].endswith("/accounts:signInWithPassword")
    assert calls[0][1]["json"] == {
        "email": "admin@example.invalid", "password": "private-password", "returnSecureToken": True
    }
    assert calls[1][0].endswith("/accounts:sendOobCode")
    assert calls[1][1]["json"] == {"requestType": "VERIFY_EMAIL", "idToken": "private-token"}
    assert capsys.readouterr().out == ""


def test_failed_signin_does_not_send_verification_or_expose_response(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return Response(ok=False, status=400, body={"error": "private-password"})

    monkeypatch.setattr(helper.requests, "post", post)
    with pytest.raises(helper.VerificationError, match="sign-in failed") as error:
        helper.send_verification("admin@example.invalid", "private-password", "test-key")
    assert len(calls) == 1
    assert "private-password" not in str(error.value)


@pytest.mark.parametrize("verified", [True, False])
def test_check_uses_firebase_account_lookup(monkeypatch, verified):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        if len(calls) == 1:
            return Response(body={"idToken": "private-token"})
        return Response(body={"users": [{"email": "admin@example.invalid", "emailVerified": verified}]})

    monkeypatch.setattr(helper.requests, "post", post)
    assert helper.email_is_verified("admin@example.invalid", "private-password", "test-key") is verified
    assert calls[1][0].endswith("/accounts:lookup")
    assert calls[1][1]["json"] == {"idToken": "private-token"}


def test_lookup_refuses_a_different_account(monkeypatch):
    responses = iter([
        Response(body={"idToken": "private-token"}),
        Response(body={"users": [{"email": "other@example.invalid", "emailVerified": True}]}),
    ])
    monkeypatch.setattr(helper.requests, "post", lambda *_args, **_kwargs: next(responses))
    with pytest.raises(helper.VerificationError, match="unexpected account"):
        helper.email_is_verified("admin@example.invalid", "private-password", "test-key")


def test_network_failure_is_sanitized(monkeypatch):
    def post(*_args, **_kwargs):
        raise requests.ConnectionError("private-password and private-token")

    monkeypatch.setattr(helper.requests, "post", post)
    with pytest.raises(helper.VerificationError, match="Could not contact Firebase") as error:
        helper.send_verification("admin@example.invalid", "private-password", "test-key")
    assert "private-password" not in str(error.value)
    assert error.value.__suppress_context__


def test_missing_credentials_fail_without_network(monkeypatch, capsys):
    monkeypatch.delenv("FIREBASE_WEB_API_KEY", raising=False)
    monkeypatch.delenv("FIREBASE_USER_PASSWORD", raising=False)
    monkeypatch.setattr("sys.argv", ["send_firebase_verification.py", "admin@example.invalid"])
    assert helper.main() == 2
    assert "set privately" in capsys.readouterr().err
