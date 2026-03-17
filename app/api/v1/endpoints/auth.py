from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import AppError
from app.core.security import decode_token, encode_token, hash_password, now_utc, validate_email, validate_password
from app.db.session import get_db
from app.models.user import PasswordResetToken, RefreshSession, User, UserSettings
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RefreshRequest,
    SignupRequest,
    TokenPairResponse,
)
from app.schemas.common import SuccessResponse
from app.schemas.user import AuthResponse
from app.services.helpers import derive_avatar_initial, derive_display_name, serialize_user

router = APIRouter(prefix="/auth", tags=["Auth"])


def issue_token_pair(db: Session, user_id: str) -> tuple[str, str]:
    now_ts = int(now_utc().timestamp())
    access_payload = {
        "sub": user_id,
        "type": "access",
        "exp": now_ts + settings.access_token_ttl_minutes * 60,
    }
    refresh_jti = str(uuid4())
    refresh_payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": refresh_jti,
        "exp": now_ts + settings.refresh_token_ttl_days * 24 * 60 * 60,
    }
    db.add(RefreshSession(jti=refresh_jti, user_id=user_id, revoked=False, exp_ts=refresh_payload["exp"]))
    return encode_token(access_payload), encode_token(refresh_payload)


@router.post("/signup", status_code=status.HTTP_201_CREATED, response_model=AuthResponse)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> dict:
    email = validate_email(payload.email)
    validate_password(payload.password)
    if payload.password != payload.password_repeat:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Passwords do not match",
            details={"field": "password_repeat"},
        )

    existing = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if existing is not None:
        raise AppError(
            status_code=409,
            code="CONFLICT",
            message="User with this email already exists",
            details={"field": "email"},
        )

    display_name = derive_display_name(email)
    user = User(
        email=email,
        display_name=display_name,
        avatar_initial=derive_avatar_initial(display_name),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.flush()

    db.add(
        UserSettings(
            user_id=user.id,
            language="en",
            theme="light",
            smart_planning=True,
            ai_suggestions=True,
            timezone="Europe/Moscow",
        )
    )
    access_token, refresh_token = issue_token_pair(db, user.id)
    db.commit()
    db.refresh(user)
    return {"access_token": access_token, "refresh_token": refresh_token, "user": serialize_user(user)}


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> dict:
    email = validate_email(payload.email)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None or user.password_hash != hash_password(payload.password):
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid credentials")

    access_token, refresh_token = issue_token_pair(db, user.id)
    db.commit()
    return {"access_token": access_token, "refresh_token": refresh_token, "user": serialize_user(user)}


@router.post("/refresh", response_model=TokenPairResponse)
def refresh_tokens(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict:
    token_payload = decode_token(payload.refresh_token)
    if token_payload.get("type") != "refresh":
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token type")
    jti = token_payload.get("jti")
    user_id = token_payload.get("sub")
    if not isinstance(jti, str) or not isinstance(user_id, str):
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid refresh token")

    session = db.get(RefreshSession, jti)
    if session is None or session.revoked or session.user_id != user_id:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Refresh token revoked")

    session.revoked = True
    access_token, refresh_token = issue_token_pair(db, user_id)
    db.commit()
    return {"access_token": access_token, "refresh_token": refresh_token}


@router.post("/logout", response_model=SuccessResponse)
def logout(payload: LogoutRequest, db: Session = Depends(get_db)) -> dict:
    try:
        token_payload = decode_token(payload.refresh_token)
        jti = token_payload.get("jti")
        if isinstance(jti, str):
            session = db.get(RefreshSession, jti)
            if session is not None:
                session.revoked = True
                db.commit()
    except AppError:
        pass
    return {"success": True}


@router.post("/password/reset/request", response_model=PasswordResetRequestResponse)
def request_password_reset(payload: PasswordResetRequest, db: Session = Depends(get_db)) -> dict:
    email = validate_email(payload.email)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is not None:
        token = str(uuid4())
        db.add(
            PasswordResetToken(
                token=token,
                user_id=user.id,
                used=False,
                exp_ts=int(now_utc().timestamp()) + settings.reset_token_ttl_minutes * 60,
            )
        )
        db.commit()
    return {"success": True, "message": "Reset email sent"}


@router.post("/password/reset/confirm", response_model=SuccessResponse)
def confirm_password_reset(payload: PasswordResetConfirmRequest, db: Session = Depends(get_db)) -> dict:
    validate_password(payload.new_password, "new_password")
    if payload.new_password != payload.new_password_repeat:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Passwords do not match",
            details={"field": "new_password_repeat"},
        )

    reset_token = db.get(PasswordResetToken, payload.token)
    if reset_token is None or reset_token.used:
        raise AppError(status_code=400, code="BAD_REQUEST", message="Invalid reset token")
    if int(now_utc().timestamp()) >= reset_token.exp_ts:
        raise AppError(status_code=400, code="BAD_REQUEST", message="Reset token expired")

    user = db.get(User, reset_token.user_id)
    if user is None:
        raise AppError(status_code=404, code="NOT_FOUND", message="User not found")

    user.password_hash = hash_password(payload.new_password)
    reset_token.used = True
    db.execute(update(RefreshSession).where(RefreshSession.user_id == user.id).values(revoked=True))
    db.commit()
    return {"success": True}
