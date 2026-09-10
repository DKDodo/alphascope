from __future__ import annotations

import sys
import types

from app.notifications.notifier import NullNotifier, WindowsToastNotifier


def test_null_notifier_does_nothing():
    NullNotifier().notify("title", "message")  # must not raise


def test_windows_toast_notifier_calls_winotify(monkeypatch):
    calls: list[dict] = []

    class _FakeNotification:
        def __init__(self, app_id, title, msg):
            calls.append({"app_id": app_id, "title": title, "msg": msg})

        def show(self):
            calls[-1]["shown"] = True

    fake_module = types.ModuleType("winotify")
    fake_module.Notification = _FakeNotification
    monkeypatch.setitem(sys.modules, "winotify", fake_module)

    WindowsToastNotifier(app_id="AlphaScope").notify("Başlık", "Mesaj")

    assert calls == [{"app_id": "AlphaScope", "title": "Başlık", "msg": "Mesaj", "shown": True}]


def test_windows_toast_notifier_swallows_failures(monkeypatch):
    # A failed toast (winotify missing, PowerShell blocked by policy, no
    # Action Center on this Windows edition, etc.) must never break a
    # trading tick -- notify() logs and returns, doesn't raise.
    fake_module = types.ModuleType("winotify")

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated winotify failure")

    fake_module.Notification = _boom
    monkeypatch.setitem(sys.modules, "winotify", fake_module)

    WindowsToastNotifier().notify("title", "message")  # must not raise
