from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel

from app.auth.session import COOKIE_MAX_AGE_SECONDS, COOKIE_NAME, make_session_cookie
from app.config import get_settings

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    password: str


@router.post("/login")
async def login(payload: LoginRequest, response: Response) -> dict:
    settings = get_settings()
    if settings.access_password is None:
        return {"ok": True}  # no password configured (e.g. the desktop build) -- nothing to check
    if payload.password != settings.access_password:
        raise HTTPException(status_code=401, detail="Şifre hatalı.")
    response.set_cookie(
        COOKIE_NAME,
        make_session_cookie(settings.access_password),
        max_age=COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
        secure=settings.environment == "production",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}
