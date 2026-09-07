"""Structured logging setup. Never logs API secrets."""
from __future__ import annotations

import logging
import sys

_CONFIGURED = False

_REDACT_KEYS = {"api_key", "massive_api_key", "authorization", "token", "secret"}


class _RedactingFilter(logging.Filter):
    """Best-effort redaction of secret-looking extra fields on log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__.keys()):
            if key.lower() in _REDACT_KEYS:
                record.__dict__[key] = "***REDACTED***"
        return True


def setup_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(_RedactingFilter())

    root = logging.getLogger()
    root.setLevel(level.upper())
    root.handlers.clear()
    root.addHandler(handler)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
