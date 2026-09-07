"""One-click desktop entrypoint: starts the AlphaScope API server and opens
the dashboard in the default browser. This is what AlphaScope.exe runs.

Paper trading only — starting this executable never places a real order.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import webbrowser

HOST = "127.0.0.1"
PORT = 8000


def _writable_app_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "AlphaScope")
    os.makedirs(path, exist_ok=True)
    return path


def _configure_environment() -> None:
    # A frozen PyInstaller exe may live under Program Files or Desktop, which
    # isn't guaranteed writable — run from a per-user app data folder instead.
    if getattr(sys, "frozen", False):
        app_dir = _writable_app_dir()
        os.chdir(app_dir)
        os.environ.setdefault(
            "DATABASE_URL", f"sqlite:///{os.path.join(app_dir, 'alphascope.db')}"
        )

    os.environ.setdefault("ALPHASCOPE_ENV", "development")
    os.environ.setdefault("MARKET_DATA_PROVIDER", "mock")
    os.environ.setdefault("PAPER_TRADING_ONLY", "true")
    os.environ.setdefault("LIVE_TRADING_ENABLED", "false")


def _open_browser_when_ready() -> None:
    time.sleep(1.5)
    webbrowser.open(f"http://{HOST}:{PORT}/")


def main() -> None:
    _configure_environment()

    import uvicorn

    from app.main import app as fastapi_app  # noqa: E402 - env must be set first

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    uvicorn.run(fastapi_app, host=HOST, port=PORT, log_level="info")


if __name__ == "__main__":
    main()
