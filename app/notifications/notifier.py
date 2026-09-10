"""Best-effort desktop notifications for noteworthy AutoTrader events (a new
position opened, the drawdown circuit breaker paused a market) -- a toast
the user can see without the dashboard open. Windows-only (winotify wraps
the native Action Center toast API) and desktop-build-only: the web deploy
has no access to anyone's desktop, so it always gets NullNotifier -- see
main.py's _build_notifier().
"""
from __future__ import annotations

from typing import Protocol

from app.core.logging import get_logger

logger = get_logger(__name__)


class Notifier(Protocol):
    def notify(self, title: str, message: str) -> None: ...


class NullNotifier:
    """No-op -- used on the web deploy and whenever notifications are
    disabled, so AutoTraderService never has to ask "is this desktop?"
    itself; it just always has a notifier to call."""

    def notify(self, title: str, message: str) -> None:
        return None


class WindowsToastNotifier:
    """Native Windows 10/11 Action Center toast via winotify -- a desktop-
    only dependency (see requirements.txt, absent from requirements-web.txt)
    imported lazily so importing this module never fails on the web deploy,
    which never constructs this class in the first place."""

    def __init__(self, app_id: str = "AlphaScope") -> None:
        self._app_id = app_id

    def notify(self, title: str, message: str) -> None:
        try:
            from winotify import Notification

            Notification(app_id=self._app_id, title=title, msg=message).show()
        except Exception:  # noqa: BLE001 - a failed toast must never break a trading tick
            logger.warning("desktop notification failed", exc_info=True)
