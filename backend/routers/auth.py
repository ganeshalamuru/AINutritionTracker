"""Authentication routes — thin wrappers over services.auth_service. Registration and login
are public; the rest derive the caller from the access token via core.auth dependencies."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from core.auth import get_current_user
from core.database import get_db
from models import User
from schemas import (
    AuthResponse,
    ChangePassword,
    OkResponse,
    RefreshRequest,
    TokenPair,
    UserLogin,
    UserOut,
    UserRegister,
)
from services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=AuthResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account",
)
def register(data: UserRegister, db: Session = Depends(get_db)):
    user, tokens = auth_service.register(
        db,
        username=data.username,
        password=data.password,
        name=data.name,
        avatar_color=data.avatar_color,
    )
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@router.post("/login", response_model=AuthResponse, summary="Log in with username + password")
def login(data: UserLogin, db: Session = Depends(get_db)):
    user, tokens = auth_service.authenticate(db, username=data.username, password=data.password)
    return AuthResponse(user=UserOut.model_validate(user), tokens=tokens)


@router.post("/refresh", response_model=TokenPair, summary="Rotate the refresh token")
def refresh(data: RefreshRequest, db: Session = Depends(get_db)):
    return auth_service.refresh(db, refresh_token=data.refresh_token)


@router.post("/logout", response_model=OkResponse, summary="Revoke a refresh token")
def logout(data: RefreshRequest, db: Session = Depends(get_db)):
    auth_service.logout(db, refresh_token=data.refresh_token)
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
