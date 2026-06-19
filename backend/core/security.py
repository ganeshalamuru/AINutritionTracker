"""Password hashing (bcrypt) + JWT access/refresh token minting (PyJWT).

This is pure crypto/token plumbing — no DB access, no request handling. The refresh
token carries a `jti` (token id) so it can be tracked and revoked server-side via the
`refresh_tokens` table (see services.auth_service); the access token is short-lived and
stateless (never stored). The signing secret comes from the JWT_SECRET env var; when
unset, a random secret is generated once and persisted in app_config so sessions survive
container restarts (see get_jwt_secret) — a warning is logged because a per-deploy env
secret is preferred for a real deployment.
"""

import logging
import secrets
import time
import uuid

import bcrypt
import jwt
from sqlalchemy.orm import Session

from core.config import get_value, set_value

logger = logging.getLogger("nutriai")

ALGORITHM = "HS256"
# Short-lived access token; the client silently refreshes it. Refresh tokens are long-lived
# but revocable (rotated on every use, see auth_service.refresh).
ACCESS_TTL_SECONDS = 15 * 60
REFRESH_TTL_SECONDS = 30 * 24 * 60 * 60

_secret_cache: str | None = None


def get_jwt_secret(db: Session) -> str:
    """The HS256 signing secret. Prefers the JWT_SECRET env var; otherwise reads (or
    generates once and persists) a random secret in app_config so tokens stay valid across
    restarts. Cached in-process after first read. Env is preferred for a real deployment so
    the secret is rotatable without a DB write — we log a warning when we fall back."""
    global _secret_cache
    if _secret_cache:
        return _secret_cache
    import os

    env_secret = os.getenv("JWT_SECRET")
    if env_secret:
        _secret_cache = env_secret
        return _secret_cache
    stored = get_value(db, "jwt_secret")
    if not stored:
        stored = secrets.token_urlsafe(48)
        set_value(db, "jwt_secret", stored)
        db.commit()
        logger.warning(
            "JWT_SECRET env var not set; generated and persisted a random secret in app_config. "
            "Set JWT_SECRET for a production deployment."
        )
    _secret_cache = stored
    return _secret_cache


# --- Passwords ---


def hash_password(password: str) -> str:
    """bcrypt hash, returned as a utf-8 string for storage in a TEXT column."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time bcrypt verify. Returns False on any malformed stored hash rather
    than raising, so a corrupt row can't 500 the login path."""
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError, TypeError:
        return False


# --- Tokens ---


def create_access_token(db: Session, *, user_id: int, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + ACCESS_TTL_SECONDS,
    }
    return jwt.encode(payload, get_jwt_secret(db), algorithm=ALGORITHM)


def create_refresh_token(db: Session, *, user_id: int) -> tuple[str, str, int]:
    """Mint a refresh token. Returns (token, jti, expires_at_epoch); the caller persists
    the jti so the token can be revoked/rotated."""
    now = int(time.time())
    jti = uuid.uuid4().hex
    expires_at = now + REFRESH_TTL_SECONDS
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(payload, get_jwt_secret(db), algorithm=ALGORITHM)
    return token, jti, expires_at


def decode_token(db: Session, token: str, *, expected_type: str) -> dict:
    """Decode and validate a token's signature, expiry, and `type`. Raises
    jwt.InvalidTokenError (incl. ExpiredSignatureError) on any problem; callers map that
    to a 401."""
    claims = jwt.decode(token, get_jwt_secret(db), algorithms=[ALGORITHM])
    if claims.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected {expected_type} token")
    return claims
