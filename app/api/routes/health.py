from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict:
    # A single local SQLite "SELECT 1" is sub-millisecond -- not worth an
    # asyncio.to_thread dispatch (this endpoint is also polled every 0.2s by
    # desktop_launcher.py's startup readiness check, so it needs to stay cheap).
    db = getattr(request.app.state, "db", None)
    db_ok = False
    if db is not None:
        try:
            with db.session_factory() as session:
                session.execute(text("SELECT 1"))
            db_ok = True
        except Exception:  # noqa: BLE001 - any DB failure means "not ok", report it, don't crash the probe
            db_ok = False

    contexts = getattr(request.app.state, "market_contexts", {})
    return {
        "status": "ok" if db_ok else "degraded",
        "database": "ok" if db_ok else "unreachable",
        "markets_available": sorted(contexts.keys()),
    }
