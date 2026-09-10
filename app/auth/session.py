"""A single shared-password session for the web deploy.

AlphaScope has no concept of separate users -- one owner accesses their own
portfolio/simulations from several devices (see settings.access_password's
docstring in config.py). A full accounts system would add real complexity
(a users table, password hashing/reset, per-user data scoping across every
existing table) for a need that doesn't exist here; a single shared password
gated by a signed, expiring cookie is the right-sized fix for "don't let
random visitors with the URL see or trade in this portfolio."

Stateless by design (no server-side session table): the cookie carries its
own issued-at timestamp and an HMAC signature over it, both checked on
every request. Changing ACCESS_PASSWORD invalidates every previously issued
cookie at once -- the revocation mechanism, in place of per-session storage.
"""
from __future__ import annotations

import hashlib
import hmac
import time

COOKIE_NAME = "alphascope_session"
COOKIE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30 days


def _signature(password: str, issued_at: int) -> str:
    return hmac.new(password.encode(), str(issued_at).encode(), hashlib.sha256).hexdigest()


def make_session_cookie(password: str) -> str:
    issued_at = int(time.time())
    return f"{issued_at}.{_signature(password, issued_at)}"


def is_valid_session_cookie(password: str, cookie_value: str | None) -> bool:
    if not cookie_value or "." not in cookie_value:
        return False
    issued_at_str, signature = cookie_value.split(".", 1)
    try:
        issued_at = int(issued_at_str)
    except ValueError:
        return False
    if time.time() - issued_at > COOKIE_MAX_AGE_SECONDS:
        return False
    return hmac.compare_digest(signature, _signature(password, issued_at))
