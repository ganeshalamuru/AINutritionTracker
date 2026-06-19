"""FastAPI authentication/authorization dependencies — the single chokepoint that turns a
bearer token into the authenticated `User` and enforces roles.

Endpoints depend on `get_current_user` (any logged-in user) or `get_current_admin` (admins
only) instead of trusting a client-supplied user id, so ownership can't be forgotten
on one route. Decoding/secret handling lives in core.security; this layer only resolves the
token to a live, active user and maps failures to 401/403.
"""

import logging

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from core.database import get_db
from core.security import decode_token
from models import User

logger = logging.getLogger("nutriai")

# auto_error=False so a missing/blank Authorization header yields our own clean 401 (with the
# WWW-Authenticate header) rather than HTTPBearer's terser default.
_bearer = HTTPBearer(auto_error=False)

_UNAUTHENTICATED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """Resolve the access token to a live, active user. 401 on any token problem
    (missing/expired/invalid) or if the user no longer exists / is deactivated."""
    if credentials is None or not credentials.credentials:
        raise _UNAUTHENTICATED
    try:
        claims = decode_token(db, credentials.credentials, expected_type="access")
        # `sub` is stored as a string in the JWT; coerce back to int for the PK lookup so the
        # comparison doesn't rely on SQLite's loose type affinity (and works on a strict DB).
        user_id = int(claims.get("sub"))
    except jwt.InvalidTokenError, TypeError, ValueError:
        raise _UNAUTHENTICATED from None
    user = db.query(User).filter(User.id == user_id, User.is_active.is_(True)).first()
    if not user:
        raise _UNAUTHENTICATED
    return user


def get_current_admin(user: User = Depends(get_current_user)) -> User:
    """Require an admin. 403 (not 401) for an authenticated non-admin — they're known, just
    not allowed."""
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
