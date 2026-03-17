from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.exceptions import AppError
from app.core.security import hash_password, validate_password
from app.db.session import get_db
from app.models.ai_message import AIMessage
from app.models.ai_request import AIRequestLog
from app.models.jobs import ExportJob, ImportJob
from app.models.note import Note
from app.models.task import Task
from app.models.user import PasswordResetToken, RefreshSession, User, UserSettings
from app.schemas.common import SuccessMessageResponse, SuccessResponse
from app.schemas.common import to_model_dict
from app.schemas.user import ChangePasswordRequest, SubscriptionResponse, UpdateProfileRequest, UserPublic, UserSettingsPayload
from app.services.helpers import derive_avatar_initial, serialize_settings, serialize_user

router = APIRouter(prefix="/user", tags=["User"])


def _require_settings(db: Session, user_id: str) -> UserSettings:
    settings = db.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(
            user_id=user_id,
            language="en",
            theme="light",
            smart_planning=True,
            ai_suggestions=True,
            timezone="Europe/Moscow",
        )
        db.add(settings)
        db.flush()
    return settings


@router.get("/me", response_model=UserPublic)
def get_me(current_user: User = Depends(get_current_user)) -> dict:
    return serialize_user(current_user)


@router.patch("/me", response_model=UserPublic)
def patch_me(
    payload: UpdateProfileRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    current_user.display_name = payload.display_name.strip()
    current_user.avatar_initial = derive_avatar_initial(current_user.display_name)
    db.commit()
    db.refresh(current_user)
    return serialize_user(current_user)


@router.post("/password/change", response_model=SuccessResponse)
def change_password(
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if current_user.password_hash != hash_password(payload.old_password):
        raise AppError(
            status_code=401,
            code="UNAUTHORIZED",
            message="Old password is incorrect",
            details={"field": "old_password"},
        )
    validate_password(payload.new_password, "new_password")
    if payload.new_password != payload.new_password_repeat:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Passwords do not match",
            details={"field": "new_password_repeat"},
        )
    current_user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"success": True}


@router.get("/settings", response_model=UserSettingsPayload)
def get_settings(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    settings = _require_settings(db, current_user.id)
    db.commit()
    return serialize_settings(settings)


@router.put("/settings", response_model=UserSettingsPayload)
def put_settings(
    payload: UserSettingsPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    settings = _require_settings(db, current_user.id)
    data = to_model_dict(payload)
    settings.language = data["language"]
    settings.theme = data["theme"]
    settings.smart_planning = data["smart_planning"]
    settings.ai_suggestions = data["ai_suggestions"]
    settings.timezone = data["timezone"].strip() or "Europe/Moscow"
    db.commit()
    return serialize_settings(settings)


@router.delete("/me", response_model=SuccessMessageResponse)
def delete_me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    user_id = current_user.id
    db.execute(delete(Note).where(Note.user_id == user_id))
    db.execute(delete(Task).where(Task.user_id == user_id))
    db.execute(delete(AIMessage).where(AIMessage.user_id == user_id))
    db.execute(delete(AIRequestLog).where(AIRequestLog.user_id == user_id))
    db.execute(delete(RefreshSession).where(RefreshSession.user_id == user_id))
    db.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user_id))
    db.execute(delete(ExportJob).where(ExportJob.user_id == user_id))
    db.execute(delete(ImportJob).where(ImportJob.user_id == user_id))
    db.execute(delete(UserSettings).where(UserSettings.user_id == user_id))
    db.execute(delete(User).where(User.id == user_id))
    db.commit()
    return {"success": True, "message": "Account deleted"}


@router.get("/subscription", response_model=SubscriptionResponse)
def get_subscription(_: User = Depends(get_current_user)) -> dict:
    return {"plan": "free", "status": "active", "renews_at": None}
