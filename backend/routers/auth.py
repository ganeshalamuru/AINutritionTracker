"""Authentication routes — thin wrappers over services.auth_service. Registration and login
are public; the rest derive the caller from the access token via core.auth dependencies.

Token delivery split: the short-lived access token is returned in the response body (the SPA
holds it in memory), while the long-lived refresh token is set as an HttpOnly cookie scoped to
/api/auth — JavaScript can't read it, so an XSS payload can't exfiltrate the renewable
credential. /refresh and /logout read the token back from that cookie, never the body."""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from core.security import REFRESH_TTL_SECONDS
from models import User
from schemas import (
    AccessTokenResponse,
    AuthResponse,
    ChangePassword,
    OkResponse,
    UserLogin,
    UserOut,
    UserRegister,
)
from services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])

# The refresh cookie. Scoped to /api/auth so the browser sends it only to refresh/logout (not on
# every API call), and `secure` is gated on production: local/LAN runs serve over plain HTTP,
# where a Secure cookie would be silently dropped and break auth. SameSite=Lax + same-origin
# serving means no separate CSRF token is needed for the simple case.
REFRESH_COOKIE = "nutriai_refresh"
REFRESH_COOKIE_PATH = "/api/auth"


def _cookie_secure() -> bool:
    return os.getenv("APP_ENV") == "production"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        max_age=REFRESH_TTL_SECONDS,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE, path=REFRESH_COOKIE_PATH, samesite="lax", httponly=True
    )


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
def register(data: UserRegister, response: Response, db: Session = Depends(get_db)):
    user, tokens = auth_service.register(
        db,
        username=data.username,
        password=data.password,
        name=data.name,
        avatar_color=data.avatar_color,
    )
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(user=UserOut.model_validate(user), access_token=tokens.access_token)


@router.post("/login", response_model=AuthResponse, summary="Log in with username + password")
def login(data: UserLogin, response: Response, db: Session = Depends(get_db)):
    user, tokens = auth_service.authenticate(db, username=data.username, password=data.password)
    _set_refresh_cookie(response, tokens.refresh_token)
    return AuthResponse(user=UserOut.model_validate(user), access_token=tokens.access_token)


@router.post("/refresh", response_model=AccessTokenResponse, summary="Rotate the refresh token")
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing refresh token"
        )
    tokens = auth_service.refresh(db, refresh_token=token)
    _set_refresh_cookie(response, tokens.refresh_token)
    return AccessTokenResponse(access_token=tokens.access_token)


@router.post("/logout", response_model=OkResponse, summary="Revoke a refresh token")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    # Best-effort revoke of whatever cookie was presented, then always clear it so the browser
    # drops the credential even if it was already unknown/expired server-side.
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        auth_service.logout(db, refresh_token=token)
    _clear_refresh_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut, summary="Current authenticated user")
def me(user: User = Depends(get_current_user)):
    return user


@router.post("/change-password", response_model=OkResponse, summary="Change own password")
def change_password(
    data: ChangePassword,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    auth_service.change_password(
        db, user=user, current_password=data.current_password, new_password=data.new_password
    )
    return {"ok": True}
