"""One-click desktop entrypoint: starts the AlphaScope API server and opens
the dashboard in its own native window (not a browser tab). This is what
AlphaScope.exe runs.

Paper trading only — starting this executable never places a real order.
"""
from __future__ import annotations

import os
import sys
import threading
import time
import urllib.request

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
    os.environ.setdefault("MARKET_DATA_PROVIDER", "yfinance")
    os.environ.setdefault("PAPER_TRADING_ONLY", "true")
    os.environ.setdefault("LIVE_TRADING_ENABLED", "false")


def _run_server() -> None:
    import uvicorn

    from app.main import app as fastapi_app  # noqa: E402 - env must be set first

    uvicorn.run(fastapi_app, host=HOST, port=PORT, log_level="warning")


def _wait_until_ready(timeout_seconds: float = 20.0) -> None:
    # The native window loads this URL immediately after being created; a
    # cold uvicorn start (first run, antivirus scanning the new exe, slow
    # disk) can take longer than a fixed sleep would assume, so poll /health
    # instead of guessing a delay.
    deadline = time.monotonic() + timeout_seconds
    url = f"http://{HOST}:{PORT}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return
        except Exception:
            pass
        time.sleep(0.2)


def main() -> None:
    _configure_environment()

    import webview

    threading.Thread(target=_run_server, daemon=True).start()
    _wait_until_ready()

    webview.create_window(
        "AlphaScope",
        url=f"http://{HOST}:{PORT}/",
        width=1400,
        height=900,
        min_size=(1000, 700),
    )
    webview.start()


if __name__ == "__main__":
    main()
