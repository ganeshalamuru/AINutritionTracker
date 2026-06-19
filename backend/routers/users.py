"""User account routes — the signed-in user's own settings (calorie goal) plus admin-only
user management. Thin wrappers over services.user_service; authz is enforced by the
core.auth dependencies (get_current_user / get_current_admin), never by client-supplied ids.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from core.auth import get_current_admin, get_current_user
from core.database import get_db
from models import User
from schemas import AdminPasswordReset, AdminUserUpdate, GoalUpdate, UserOut
from services import user_service

router = APIRouter(prefix="/users", tags=["users"])


@router.patch("/me", response_model=UserOut, summary="Update own calorie goal")
def update_me(
    data: GoalUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return user_service.update_goal(db, user=user, data=data)


# --- Admin-only user management (admin-assisted password reset, role/active changes) ---


@router.get(
    "",
    response_model=list[UserOut],
    summary="List all users (admin)",
    dependencies=[Depends(get_current_admin)],
)
def list_users(db: Session = Depends(get_db)):
    return user_service.list_users(db)


@router.patch(
    "/{user_id}",
    response_model=UserOut,
    summary="Change a user's role / active flag (admin)",
)
def admin_update_user(
    user_id: int,
    data: AdminUserUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    return user_service.admin_update_user(db, actor=admin, user_id=user_id, data=data)


@router.post(
    "/{user_id}/reset-password",
    response_model=UserOut,
    summary="Reset a user's password (admin)",
    dependencies=[Depends(get_current_admin)],
)
def admin_reset_password(
    user_id: int,
    data: AdminPasswordReset,
    db: Session = Depends(get_db),
):
    return user_service.admin_reset_password(db, user_id=user_id, new_password=data.new_password)
