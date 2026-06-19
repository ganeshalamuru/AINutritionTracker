"""Account-level business logic: the signed-in user's own profile updates (calorie goal) and
admin-only user management (list, change role/active, reset password). Auth flows (login,
tokens, password change for self) live in services.auth_service.
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.security import hash_password
from models import RefreshToken, User
from schemas import AdminUserUpdate, ProfileGoalUpdate


def update_goal(db: Session, *, user: User, data: ProfileGoalUpdate) -> User:
    """Update the signed-in user's own calorie goal."""
    user.calorie_goal = data.calorie_goal
    db.commit()
    db.refresh(user)
    return user


def list_users(db: Session) -> list[User]:
    return db.query(User).order_by(User.id).all()


def _get_user(db: Session, user_id: int) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def admin_update_user(db: Session, *, actor: User, user_id: int, data: AdminUserUpdate) -> User:
    """Admin edit of another user's role / active flag. Guards against an admin locking the
    system out of admin access by demoting or deactivating the last remaining admin."""
    target = _get_user(db, user_id)

    if data.role is not None and data.role != target.role and target.role == "admin":
        _guard_last_admin(db, target)
    if data.is_active is False and target.role == "admin":
        _guard_last_admin(db, target)

    if data.role is not None:
        target.role = data.role
    if data.is_active is not None:
        target.is_active = data.is_active
        if data.is_active is False:
            # Deactivating: kill outstanding sessions.
            db.query(RefreshToken).filter(
                RefreshToken.user_id == target.id, RefreshToken.revoked.is_(False)
            ).update({"revoked": True})
    db.commit()
    db.refresh(target)
    return target


def admin_reset_password(db: Session, *, user_id: int, new_password: str) -> User:
    """Admin sets a user's password and flags must_change_password, then revokes that user's
    sessions. Used for the admin-assisted reset path (no email/SMTP)."""
    target = _get_user(db, user_id)
    target.password_hash = hash_password(new_password)
    target.must_change_password = True
    db.query(RefreshToken).filter(
        RefreshToken.user_id == target.id, RefreshToken.revoked.is_(False)
    ).update({"revoked": True})
    db.commit()
    db.refresh(target)
    return target


def _guard_last_admin(db: Session, target: User) -> None:
    other_admins = (
        db.query(User.id)
        .filter(User.role == "admin", User.is_active.is_(True), User.id != target.id)
        .first()
    )
    if other_admins is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove the last active admin",
        )
