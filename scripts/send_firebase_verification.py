"""Send a Firebase password user's verification email without exposing tokens.

This is an onboarding helper, not a portal login. A successful Firebase sign-in
and verified email do not grant portal access: an active MongoDB access entry
is still required. See docs/DEPLOY_WINDOWS.md for hidden-prompt usage.
"""
from __future__ import annotations

import argparse
import os
import sys

import requests

IDENTITY_TOOLKIT = "https://identitytoolkit.googleapis.com/v1"


class VerificationError(Exception):
    """A deliberately sanitized onboarding error."""


def _post(endpoint: str, api_key: str, payload: dict):
    try:
        return requests.post(
            f"{IDENTITY_TOOLKIT}/{endpoint}",
            params={"key": api_key},
            json=payload,
            timeout=20,
        )
    except requests.RequestException:
        raise VerificationError(
            "Could not contact Firebase. Check the internet connection and try again."
        ) from None


def _sign_in(email: str, password: str, api_key: str) -> str:
    signed_in = _post(
        "accounts:signInWithPassword", api_key,
        {"email": email, "password": password, "returnSecureToken": True},
    )
    if not signed_in.ok:
        raise VerificationError(
            f"Firebase sign-in failed (HTTP {signed_in.status_code}). Check the "
            "account, password, provider and API-key restrictions."
        )
    try:
        token = signed_in.json().get("idToken")
    except (ValueError, AttributeError):
        token = None
    if not isinstance(token, str) or not token:
        raise VerificationError("Firebase sign-in did not return an ID token.")
    return token


def send_verification(email: str, password: str, api_key: str) -> None:
    """Authenticate the password user, then ask Firebase to send a link.

    Passwords and tokens remain in memory, are sent only to Firebase over TLS,
    and are never printed or stored by this script. Do not enable HTTP debug
    logging or pass credentials on the command line.
    """
    token = _sign_in(email, password, api_key)
    sent = _post("accounts:sendOobCode", api_key, {"requestType": "VERIFY_EMAIL", "idToken": token})
    if not sent.ok:
        raise VerificationError(
            f"Firebase could not send the verification email (HTTP {sent.status_code}). "
            "Check the email template, API-key restrictions and sending quota."
        )


def email_is_verified(email: str, password: str, api_key: str) -> bool:
    """Check the signed-in Firebase identity after its owner opens the link."""
    token = _sign_in(email, password, api_key)
    result = _post("accounts:lookup", api_key, {"idToken": token})
    if not result.ok:
        raise VerificationError(f"Firebase account lookup failed (HTTP {result.status_code}).")
    try:
        users = result.json().get("users", [])
        user = users[0]
        if user.get("email", "").strip().lower() != email.strip().lower():
            raise VerificationError("Firebase returned an unexpected account.")
        return user.get("emailVerified") is True
    except (ValueError, AttributeError, IndexError, TypeError):
        raise VerificationError("Firebase returned an invalid account lookup response.") from None


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a Firebase email-verification link.")
    parser.add_argument("email", help="Email of the existing Firebase password user")
    parser.add_argument("--check", action="store_true", help="Check email verification instead of sending a link")
    args = parser.parse_args()
    api_key = os.environ.get("FIREBASE_WEB_API_KEY", "").strip()
    password = os.environ.get("FIREBASE_USER_PASSWORD", "")
    if not api_key or not password:
        print("FIREBASE_WEB_API_KEY and FIREBASE_USER_PASSWORD must be set privately.", file=sys.stderr)
        return 2
    try:
        if args.check:
            if not email_is_verified(args.email.strip(), password, api_key):
                print("Firebase reports that this email is not yet verified.", file=sys.stderr)
                return 1
            print("Firebase reports that this email is verified. Portal access still requires an active access entry.")
        else:
            send_verification(args.email.strip(), password, api_key)
            print("Verification email requested. Open the link in the account's mailbox, then sign in again.")
    except VerificationError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
