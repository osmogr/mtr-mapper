from fastapi import APIRouter, Request, Response

from app.config import get_settings
from app.schemas.auth import LoginRequest, SessionStatus
from app.services.auth import (
    SESSION_COOKIE_NAME,
    check_password,
    create_session_token,
    verify_session_token,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=SessionStatus)
async def login(payload: LoginRequest, response: Response) -> SessionStatus:
    settings = get_settings()
    if not check_password(payload.password):
        return SessionStatus(authenticated=False)
    token = create_session_token()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.admin_session_ttl_seconds,
        httponly=True,
        samesite="lax",
    )
    return SessionStatus(authenticated=True)


@router.post("/logout", response_model=SessionStatus)
async def logout(response: Response) -> SessionStatus:
    response.delete_cookie(SESSION_COOKIE_NAME)
    return SessionStatus(authenticated=False)


@router.get("/session", response_model=SessionStatus)
async def session_status(request: Request) -> SessionStatus:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    return SessionStatus(authenticated=verify_session_token(token))
