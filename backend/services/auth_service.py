"""Authentication business logic: registration, login, refresh-token rotation, logout, and
password changes. Routers stay thin and call these; all DB work and token bookkeeping lives
here. Token minting/verification itself is in core.security; this layer ties it to the User
and RefreshToken tables.

Refresh tokens are tracked by `jti` and rotated on every use: a refresh revokes the presented
token and issues a new one. Presenting an already-revoked token (reuse) revokes the whole
chain for that user as a safety response to a possible theft.
"""

import logging
import time

import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from models import RefreshToken, User
from schemas import TokenPair

logger = logging.getLogger("nutriai")


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail)


def _issue_tokens(db: Session, user: User) -> TokenPair:
    """Mint an access token and a tracked refresh token for `user`. Commits the refresh row."""
    access = create_access_token(db, user_id=user.id, role=user.role)
    refresh, jti, expires_at = create_refresh_token(db, user_id=user.id)
    db.add(
        RefreshToken(
            jti=jti,
            user_id=user.id,
            expires_at=expires_at,
            revoked=False,
            created_at=int(time.time()),
        )
    )
    db.commit()
    return TokenPair(access_token=access, refresh_token=refresh)


def register(
    db: Session, *, username: str, password: str, name: str | None, avatar_color: str | None
):
    """Create a new account. The very first account becomes the admin; the rest are users.
    Usernames are stored lowercased and must be unique (409 on collision)."""
    uname = username.strip().lower()
    existing = db.query(User).filter(User.username == uname).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    is_first = db.query(User.id).first() is None
    user = User(
        username=uname,
        name=(name or username).strip(),
        password_hash=hash_password(password),
        role="admin" if is_first else "user",
        must_change_password=False,
        avatar_color=avatar_color or "#22c55e",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    if is_first:
        logger.info("first account '%s' created as admin", uname)
    tokens = _issue_tokens(db, user)
    return user, tokens


def authenticate(db: Session, *, username: str, password: str):
    """Verify credentials and issue a token pair. A wrong username and a wrong password return
    the same 401 (no account-enumeration). Deactivated accounts can't log in."""
    uname = username.strip().lower()
    user = db.query(User).filter(User.username == uname).first()
    # Verify even when the user is missing/inactive to keep timing roughly constant.
    ok = verify_password(password, user.password_hash if user else "")
    if not user or not user.is_active or not ok:
        raise _unauthorized("Invalid credentials")
    tokens = _issue_tokens(db, user)
    return user, tokens


def refresh(db: Session, *, refresh_token: str) -> TokenPair:
    """Rotate a refresh token: validate it, revoke it, and issue a fresh pair. Reuse of an
    already-revoked token revokes every outstanding token for that user (theft response)."""
    try:
        claims = decode_token(db, refresh_token, expected_type="refresh")
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid refresh token") from None

    jti = claims.get("jti")
    user_id = claims.get("sub")
    row = db.query(RefreshToken).filter(RefreshToken.jti == jti).first()
    if row is None:
        raise _unauthorized("Invalid refresh token")
    if row.revoked:
        # The token was already used/rotated — treat as compromise and revoke the chain.
        logger.warning("refresh token reuse detected for user %s; revoking all tokens", user_id)
        db.query(RefreshToken).filter(
            RefreshToken.user_id == row.user_id, RefreshToken.revoked.is_(False)
        ).update({"revoked": True})
        db.commit()
        raise _unauthorized("Invalid refresh token")
    if row.expires_at < int(time.time()):
        raise _unauthorized("Refresh token expired")

    user = db.query(User).filter(User.id == row.user_id, User.is_active.is_(True)).first()
    if not user:
        raise _unauthorized("Invalid refresh token")

    row.revoked = True  # rotate: the old token is single-use
    db.commit()
    return _issue_tokens(db, user)


def logout(db: Session, *, refresh_token: str) -> None:
    """Revoke the presented refresh token. Best-effort and idempotent: a malformed or unknown
    token still returns cleanly (logout shouldn't fail), it just revokes nothing."""
    try:
        claims = decode_token(db, refresh_token, expected_type="refresh")
    except jwt.InvalidTokenError:
        return
    row = db.query(RefreshToken).filter(RefreshToken.jti == claims.get("jti")).first()
    if row and not row.revoked:
        row.revoked = True
        db.commit()


def change_password(db: Session, *, user: User, current_password: str, new_password: str) -> None:
    """Verify the current password, set the new one, clear must_change_password, and revoke all
    of the user's refresh tokens so other sessions are forced to re-authenticate."""
    if not verify_password(current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect"
        )
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    db.query(RefreshToken).filter(
        RefreshToken.user_id == user.id, RefreshToken.revoked.is_(False)
    ).update({"revoked": True})
    db.commit()
