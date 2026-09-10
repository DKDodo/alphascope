from __future__ import annotations

import time

from app.auth.session import COOKIE_MAX_AGE_SECONDS, is_valid_session_cookie, make_session_cookie


def test_valid_cookie_is_accepted():
    cookie = make_session_cookie("hunter2")
    assert is_valid_session_cookie("hunter2", cookie) is True


def test_wrong_password_rejects_a_cookie_issued_under_a_different_one():
    cookie = make_session_cookie("hunter2")
    assert is_valid_session_cookie("a-different-password", cookie) is False


def test_missing_cookie_is_rejected():
    assert is_valid_session_cookie("hunter2", None) is False
    assert is_valid_session_cookie("hunter2", "") is False


def test_malformed_cookie_is_rejected():
    assert is_valid_session_cookie("hunter2", "not-a-valid-cookie-at-all") is False
    assert is_valid_session_cookie("hunter2", "notanumber.deadbeef") is False


def test_tampered_signature_is_rejected():
    cookie = make_session_cookie("hunter2")
    issued_at, _, _signature = cookie.partition(".")
    tampered = f"{issued_at}.0000000000000000000000000000000000000000000000000000000000000000"
    assert is_valid_session_cookie("hunter2", tampered) is False


def test_expired_cookie_is_rejected():
    # Forge a cookie as if it were issued just past the expiry window --
    # can't wait 30 real days in a test, so backdate the timestamp and
    # re-sign it exactly the way make_session_cookie() would have.
    from app.auth.session import _signature

    stale_issued_at = int(time.time()) - COOKIE_MAX_AGE_SECONDS - 1
    stale_cookie = f"{stale_issued_at}.{_signature('hunter2', stale_issued_at)}"
    assert is_valid_session_cookie("hunter2", stale_cookie) is False


def test_cookie_just_inside_the_expiry_window_is_still_accepted():
    from app.auth.session import _signature

    fresh_issued_at = int(time.time()) - COOKIE_MAX_AGE_SECONDS + 5
    fresh_cookie = f"{fresh_issued_at}.{_signature('hunter2', fresh_issued_at)}"
    assert is_valid_session_cookie("hunter2", fresh_cookie) is True
