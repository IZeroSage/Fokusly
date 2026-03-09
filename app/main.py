from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, File, Query, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field


app = FastAPI(title="Fokusly API", version="1.0.0")
auth_scheme = HTTPBearer(auto_error=False)

SECRET_KEY = os.getenv("FOKUSLY_SECRET_KEY", "dev-secret-key-change-me")
ACCESS_TOKEN_TTL_MINUTES = 30
REFRESH_TOKEN_TTL_DAYS = 30
RESET_TOKEN_TTL_MINUTES = 30
ASYNC_JOB_DELAY_SECONDS = 1

DEFAULT_NOTE_CATEGORIES = ["All", "Work", "University", "Home", "TO DO"]


class AppError(Exception):
    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def to_iso_utc(value: datetime) -> str:
    normalized = value.astimezone(timezone.utc)
    return normalized.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def validate_email(email: str) -> str:
    email_normalized = email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email_normalized):
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Email is invalid",
            details={"field": "email"},
        )
    return email_normalized


def validate_password(password: str, field_name: str = "password") -> None:
    if len(password) < 8:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Password must be at least 8 characters",
            details={"field": field_name},
        )


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode(value + padding)


def sign_payload(payload: str) -> str:
    signature = hmac.new(SECRET_KEY.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256)
    return b64url_encode(signature.digest())


def encode_token(payload: dict[str, Any]) -> str:
    encoded_payload = b64url_encode(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    signature = sign_payload(encoded_payload)
    return f"{encoded_payload}.{signature}"


def decode_token(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 2:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token")
    encoded_payload, signature = parts
    expected_signature = sign_payload(encoded_payload)
    if not hmac.compare_digest(signature, expected_signature):
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token signature")
    try:
        payload = json.loads(b64url_decode(encoded_payload))
    except (json.JSONDecodeError, ValueError):
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token payload")

    exp = payload.get("exp")
    if not isinstance(exp, int) or int(now_utc().timestamp()) >= exp:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Token expired")
    return payload


def build_user_public(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": user["id"],
        "display_name": user["display_name"],
        "email": user["email"],
        "avatar_initial": user["avatar_initial"],
    }


def derive_display_name(email: str) -> str:
    local = email.split("@", 1)[0].strip()
    if not local:
        return "User"
    return local[0].upper() + local[1:]


def derive_avatar_initial(display_name: str) -> str:
    clean = display_name.strip()
    if not clean:
        return "U"
    return clean[0].upper()


def paginate(items: list[dict[str, Any]], page: int, size: int) -> dict[str, Any]:
    total = len(items)
    start = (page - 1) * size
    end = start + size
    return {"items": items[start:end], "page": page, "size": size, "total": total}


def to_model_dict(model: Any, *, exclude_unset: bool = False) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump(exclude_unset=exclude_unset)
    return model.dict(exclude_unset=exclude_unset)


def day_load_label(total_minutes: int) -> str:
    if total_minutes < 180:
        return "light day"
    if total_minutes < 420:
        return "medium day"
    return "hard day"


def issue_token_pair(user_id: str) -> tuple[str, str]:
    now_ts = int(now_utc().timestamp())
    access_payload = {
        "sub": user_id,
        "type": "access",
        "exp": now_ts + ACCESS_TOKEN_TTL_MINUTES * 60,
    }
    refresh_jti = str(uuid.uuid4())
    refresh_payload = {
        "sub": user_id,
        "type": "refresh",
        "jti": refresh_jti,
        "exp": now_ts + REFRESH_TOKEN_TTL_DAYS * 24 * 60 * 60,
    }
    access_token = encode_token(access_payload)
    refresh_token = encode_token(refresh_payload)
    STORE["refresh_sessions"][refresh_jti] = {
        "user_id": user_id,
        "revoked": False,
        "exp": refresh_payload["exp"],
    }
    return access_token, refresh_token


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
) -> dict[str, Any]:
    if credentials is None:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Missing bearer token")
    payload = decode_token(credentials.credentials)
    if payload.get("type") != "access":
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token type")
    user_id = payload.get("sub")
    user = STORE["users"].get(user_id)
    if user is None:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="User not found")
    return user


def filter_user_notes(user_id: str) -> list[dict[str, Any]]:
    return [note for note in STORE["notes"].values() if note["user_id"] == user_id]


def filter_user_tasks(user_id: str) -> list[dict[str, Any]]:
    return [task for task in STORE["tasks"].values() if task["user_id"] == user_id]


def serialize_note(note: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": note["id"],
        "title": note["title"],
        "body": note["body"],
        "category": note["category"],
        "created_at": to_iso_utc(note["created_at"]),
    }


def serialize_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": task["id"],
        "title": task["title"],
        "mini_description": task["mini_description"],
        "duration_minutes": task["duration_minutes"],
        "start_at": to_iso_utc(task["start_at"]),
        "category": task["category"],
    }


def mark_job_if_ready(job: dict[str, Any]) -> None:
    if job["status"] != "processing":
        return
    if (now_utc() - job["created_at"]).total_seconds() >= ASYNC_JOB_DELAY_SECONDS:
        job["status"] = "done"


class SignupRequest(BaseModel):
    email: str
    password: str
    password_repeat: str


class LoginRequest(BaseModel):
    email: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class PasswordResetRequest(BaseModel):
    email: str


class PasswordResetConfirmRequest(BaseModel):
    token: str
    new_password: str
    new_password_repeat: str


class UpdateProfileRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
    new_password_repeat: str


class UserSettingsPayload(BaseModel):
    language: str
    theme: Literal["light", "dark"]
    smart_planning: bool
    ai_suggestions: bool


class CreateNoteRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    category: str = Field(min_length=1, max_length=60)


class UpdateNoteRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    category: str | None = Field(default=None, min_length=1, max_length=60)


class CreateTaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    mini_description: str = Field(default="", max_length=400)
    duration_minutes: int = Field(ge=1, le=24 * 60)
    start_at: datetime
    category: str = Field(min_length=1, max_length=60)
    source_note_id: str | None = None


class UpdateTaskRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    mini_description: str | None = Field(default=None, max_length=400)
    duration_minutes: int | None = Field(default=None, ge=1, le=24 * 60)
    start_at: datetime | None = None
    category: str | None = Field(default=None, min_length=1, max_length=60)
    source_note_id: str | None = None


class SendAIMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class GenerateScheduleRequest(BaseModel):
    date: date
    mode: Literal["balanced", "deep_focus", "light"] = "balanced"


class ExportRequest(BaseModel):
    format: Literal["json"]


STORE: dict[str, Any] = {
    "users": {},
    "users_by_email": {},
    "settings": {},
    "notes": {},
    "tasks": {},
    "ai_messages": {},
    "refresh_sessions": {},
    "password_reset_tokens": {},
    "export_jobs": {},
    "import_jobs": {},
}


@app.exception_handler(AppError)
async def handle_app_error(_, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


@app.exception_handler(RequestValidationError)
async def handle_validation_error(_, exc: RequestValidationError) -> JSONResponse:
    details = {"fields": exc.errors()}
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Validation failed",
                "details": details,
            }
        },
    )


@app.get("/api/v1/health")
def healthcheck() -> dict[str, Any]:
    return {"status": "ok"}


@app.post("/api/v1/auth/signup", status_code=201)
def signup(payload: SignupRequest) -> dict[str, Any]:
    email = validate_email(payload.email)
    validate_password(payload.password)
    if payload.password != payload.password_repeat:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Passwords do not match",
            details={"field": "password_repeat"},
        )
    if email in STORE["users_by_email"]:
        raise AppError(
            status_code=409,
            code="CONFLICT",
            message="User with this email already exists",
            details={"field": "email"},
        )

    user_id = str(uuid.uuid4())
    display_name = derive_display_name(email)
    user = {
        "id": user_id,
        "email": email,
        "display_name": display_name,
        "avatar_initial": derive_avatar_initial(display_name),
        "password_hash": hash_password(payload.password),
        "created_at": now_utc(),
    }
    STORE["users"][user_id] = user
    STORE["users_by_email"][email] = user_id
    STORE["settings"][user_id] = {
        "language": "en",
        "theme": "light",
        "smart_planning": True,
        "ai_suggestions": True,
    }
    STORE["ai_messages"][user_id] = []

    access_token, refresh_token = issue_token_pair(user_id)
    return {"access_token": access_token, "refresh_token": refresh_token, "user": build_user_public(user)}


@app.post("/api/v1/auth/login")
def login(payload: LoginRequest) -> dict[str, Any]:
    email = validate_email(payload.email)
    user_id = STORE["users_by_email"].get(email)
    if user_id is None:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid credentials")
    user = STORE["users"][user_id]
    if user["password_hash"] != hash_password(payload.password):
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid credentials")
    access_token, refresh_token = issue_token_pair(user_id)
    return {"access_token": access_token, "refresh_token": refresh_token, "user": build_user_public(user)}


@app.post("/api/v1/auth/refresh")
def refresh_tokens(payload: RefreshRequest) -> dict[str, Any]:
    token_payload = decode_token(payload.refresh_token)
    if token_payload.get("type") != "refresh":
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid token type")
    jti = token_payload.get("jti")
    user_id = token_payload.get("sub")
    if not isinstance(jti, str):
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Invalid refresh token")
    session = STORE["refresh_sessions"].get(jti)
    if session is None or session["revoked"] or session["user_id"] != user_id:
        raise AppError(status_code=401, code="UNAUTHORIZED", message="Refresh token revoked")
    session["revoked"] = True
    access_token, refresh_token = issue_token_pair(user_id)
    return {"access_token": access_token, "refresh_token": refresh_token}


@app.post("/api/v1/auth/logout")
def logout(payload: LogoutRequest) -> dict[str, Any]:
    try:
        token_payload = decode_token(payload.refresh_token)
        jti = token_payload.get("jti")
        if isinstance(jti, str) and jti in STORE["refresh_sessions"]:
            STORE["refresh_sessions"][jti]["revoked"] = True
    except AppError:
        pass
    return {"success": True}


@app.post("/api/v1/auth/password/reset/request")
def request_password_reset(payload: PasswordResetRequest) -> dict[str, Any]:
    email = validate_email(payload.email)
    user_id = STORE["users_by_email"].get(email)
    if user_id is not None:
        token = str(uuid.uuid4())
        STORE["password_reset_tokens"][token] = {
            "user_id": user_id,
            "used": False,
            "exp": int((now_utc() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES)).timestamp()),
        }
    return {"success": True, "message": "Reset email sent"}


@app.post("/api/v1/auth/password/reset/confirm")
def confirm_password_reset(payload: PasswordResetConfirmRequest) -> dict[str, Any]:
    validate_password(payload.new_password, "new_password")
    if payload.new_password != payload.new_password_repeat:
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Passwords do not match",
            details={"field": "new_password_repeat"},
        )

    token_data = STORE["password_reset_tokens"].get(payload.token)
    if token_data is None or token_data["used"]:
        raise AppError(status_code=400, code="BAD_REQUEST", message="Invalid reset token")
    if int(now_utc().timestamp()) >= token_data["exp"]:
        raise AppError(status_code=400, code="BAD_REQUEST", message="Reset token expired")

    user = STORE["users"].get(token_data["user_id"])
    if user is None:
        raise AppError(status_code=404, code="NOT_FOUND", message="User not found")

    user["password_hash"] = hash_password(payload.new_password)
    token_data["used"] = True
    for session in STORE["refresh_sessions"].values():
        if session["user_id"] == user["id"]:
            session["revoked"] = True
    return {"success": True}


@app.get("/api/v1/user/me")
def get_me(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return build_user_public(current_user)


@app.patch("/api/v1/user/me")
def patch_me(payload: UpdateProfileRequest, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    current_user["display_name"] = payload.display_name.strip()
    current_user["avatar_initial"] = derive_avatar_initial(current_user["display_name"])
    return build_user_public(current_user)


@app.post("/api/v1/user/password/change")
def change_password(
    payload: ChangePasswordRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    if current_user["password_hash"] != hash_password(payload.old_password):
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
    current_user["password_hash"] = hash_password(payload.new_password)
    return {"success": True}


@app.get("/api/v1/user/settings")
def get_settings(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return STORE["settings"][current_user["id"]]


@app.put("/api/v1/user/settings")
def put_settings(
    payload: UserSettingsPayload,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    STORE["settings"][current_user["id"]] = to_model_dict(payload)
    return STORE["settings"][current_user["id"]]


@app.delete("/api/v1/user/me")
def delete_me(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    user_id = current_user["id"]
    STORE["users"].pop(user_id, None)
    STORE["users_by_email"].pop(current_user["email"], None)
    STORE["settings"].pop(user_id, None)
    STORE["ai_messages"].pop(user_id, None)

    for note_id in [item["id"] for item in filter_user_notes(user_id)]:
        STORE["notes"].pop(note_id, None)
    for task_id in [item["id"] for item in filter_user_tasks(user_id)]:
        STORE["tasks"].pop(task_id, None)

    for key, session in list(STORE["refresh_sessions"].items()):
        if session["user_id"] == user_id:
            STORE["refresh_sessions"].pop(key, None)

    for key, reset_data in list(STORE["password_reset_tokens"].items()):
        if reset_data["user_id"] == user_id:
            STORE["password_reset_tokens"].pop(key, None)

    for key, job in list(STORE["export_jobs"].items()):
        if job["user_id"] == user_id:
            STORE["export_jobs"].pop(key, None)

    for key, job in list(STORE["import_jobs"].items()):
        if job["user_id"] == user_id:
            STORE["import_jobs"].pop(key, None)

    return {"success": True, "message": "Account deleted"}


@app.get("/api/v1/user/subscription")
def get_subscription(_: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    return {"plan": "free", "status": "active", "renews_at": None}


@app.get("/api/v1/notes/categories")
def list_note_categories(current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    user_categories = {note["category"] for note in filter_user_notes(current_user["id"])}
    items = DEFAULT_NOTE_CATEGORIES + sorted(item for item in user_categories if item not in DEFAULT_NOTE_CATEGORIES)
    return {"items": items}


@app.get("/api/v1/notes")
def list_notes(
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    notes = filter_user_notes(current_user["id"])
    if q:
        q_normalized = q.lower()
        notes = [n for n in notes if q_normalized in n["title"].lower() or q_normalized in n["body"].lower()]
    if category and category != "All":
        notes = [n for n in notes if n["category"] == category]
    notes.sort(key=lambda item: item["created_at"], reverse=True)
    serialized = [serialize_note(item) for item in notes]
    return paginate(serialized, page, size)


@app.post("/api/v1/notes", status_code=201)
def create_note(payload: CreateNoteRequest, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    note_id = str(uuid.uuid4())
    note = {
        "id": note_id,
        "user_id": current_user["id"],
        "title": payload.title.strip(),
        "body": payload.body,
        "category": payload.category.strip(),
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    STORE["notes"][note_id] = note
    return serialize_note(note)


@app.get("/api/v1/notes/{note_id}")
def get_note(note_id: str, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    note = STORE["notes"].get(note_id)
    if note is None or note["user_id"] != current_user["id"]:
        raise AppError(status_code=404, code="NOT_FOUND", message="Note not found")
    return serialize_note(note)


@app.patch("/api/v1/notes/{note_id}")
def patch_note(
    note_id: str,
    payload: UpdateNoteRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    note = STORE["notes"].get(note_id)
    if note is None or note["user_id"] != current_user["id"]:
        raise AppError(status_code=404, code="NOT_FOUND", message="Note not found")

    update_data = to_model_dict(payload, exclude_unset=True)
    for key, value in update_data.items():
        if key == "title" and value is not None:
            note["title"] = value.strip()
        elif key == "category" and value is not None:
            note["category"] = value.strip()
        elif key == "body" and value is not None:
            note["body"] = value
    note["updated_at"] = now_utc()
    return serialize_note(note)


@app.delete("/api/v1/notes/{note_id}")
def delete_note(note_id: str, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    note = STORE["notes"].get(note_id)
    if note is None or note["user_id"] != current_user["id"]:
        raise AppError(status_code=404, code="NOT_FOUND", message="Note not found")
    STORE["notes"].pop(note_id, None)
    return {"success": True}


@app.post("/api/v1/notes/{note_id}/share")
def share_note(note_id: str, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    note = STORE["notes"].get(note_id)
    if note is None or note["user_id"] != current_user["id"]:
        raise AppError(status_code=404, code="NOT_FOUND", message="Note not found")
    share_token = str(uuid.uuid4())
    return {"share_url": f"https://fokusly.app/share/{note_id}?token={share_token}"}


@app.get("/api/v1/tasks")
def list_tasks(
    date_filter: date | None = Query(default=None, alias="date"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    tasks = filter_user_tasks(current_user["id"])
    if date_filter is not None:
        tasks = [task for task in tasks if task["start_at"].date() == date_filter]
    else:
        if date_from is not None:
            tasks = [task for task in tasks if task["start_at"].date() >= date_from]
        if date_to is not None:
            tasks = [task for task in tasks if task["start_at"].date() <= date_to]

    tasks.sort(key=lambda item: item["start_at"])
    serialized = [serialize_task(item) for item in tasks]
    return paginate(serialized, page, size)


@app.post("/api/v1/tasks", status_code=201)
def create_task(payload: CreateTaskRequest, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if payload.source_note_id:
        note = STORE["notes"].get(payload.source_note_id)
        if note is None or note["user_id"] != current_user["id"]:
            raise AppError(
                status_code=404,
                code="NOT_FOUND",
                message="Source note not found",
                details={"field": "source_note_id"},
            )

    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "user_id": current_user["id"],
        "title": payload.title.strip(),
        "mini_description": payload.mini_description.strip(),
        "duration_minutes": payload.duration_minutes,
        "start_at": ensure_utc(payload.start_at),
        "category": payload.category.strip(),
        "source_note_id": payload.source_note_id,
        "created_at": now_utc(),
        "updated_at": now_utc(),
    }
    STORE["tasks"][task_id] = task
    return serialize_task(task)


@app.get("/api/v1/tasks/{task_id}")
def get_task(task_id: str, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    task = STORE["tasks"].get(task_id)
    if task is None or task["user_id"] != current_user["id"]:
        raise AppError(status_code=404, code="NOT_FOUND", message="Task not found")
    return serialize_task(task)


@app.patch("/api/v1/tasks/{task_id}")
def patch_task(
    task_id: str,
    payload: UpdateTaskRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    task = STORE["tasks"].get(task_id)
    if task is None or task["user_id"] != current_user["id"]:
        raise AppError(status_code=404, code="NOT_FOUND", message="Task not found")

    updates = to_model_dict(payload, exclude_unset=True)
    if "source_note_id" in updates:
        source_note_id = updates["source_note_id"]
        if source_note_id is not None:
            note = STORE["notes"].get(source_note_id)
            if note is None or note["user_id"] != current_user["id"]:
                raise AppError(
                    status_code=404,
                    code="NOT_FOUND",
                    message="Source note not found",
                    details={"field": "source_note_id"},
                )
        task["source_note_id"] = source_note_id
    if "title" in updates and updates["title"] is not None:
        task["title"] = updates["title"].strip()
    if "mini_description" in updates and updates["mini_description"] is not None:
        task["mini_description"] = updates["mini_description"].strip()
    if "duration_minutes" in updates and updates["duration_minutes"] is not None:
        task["duration_minutes"] = updates["duration_minutes"]
    if "start_at" in updates and updates["start_at"] is not None:
        task["start_at"] = ensure_utc(updates["start_at"])
    if "category" in updates and updates["category"] is not None:
        task["category"] = updates["category"].strip()
    task["updated_at"] = now_utc()
    return serialize_task(task)


@app.delete("/api/v1/tasks/{task_id}")
def delete_task(task_id: str, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    task = STORE["tasks"].get(task_id)
    if task is None or task["user_id"] != current_user["id"]:
        raise AppError(status_code=404, code="NOT_FOUND", message="Task not found")
    STORE["tasks"].pop(task_id, None)
    return {"success": True}


@app.get("/api/v1/schedule/day")
def day_schedule(
    day: date = Query(alias="date"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    tasks = [item for item in filter_user_tasks(current_user["id"]) if item["start_at"].date() == day]
    tasks.sort(key=lambda item: item["start_at"])
    total_minutes = sum(item["duration_minutes"] for item in tasks)
    items = [
        {
            "id": item["id"],
            "time": item["start_at"].astimezone(timezone.utc).strftime("%H:%M"),
            "title": item["title"],
            "subtitle": item["mini_description"] or "default",
            "duration_minutes": item["duration_minutes"],
            "category": item["category"],
        }
        for item in tasks
    ]
    return {
        "date": day.isoformat(),
        "tasks_count": len(tasks),
        "day_load_label": day_load_label(total_minutes),
        "items": items,
    }


@app.get("/api/v1/schedule/month")
def month_schedule(
    year: int = Query(ge=1970, le=2100),
    month: int = Query(ge=1, le=12),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    first_day = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    days_total = (next_month - first_day).days

    tasks = filter_user_tasks(current_user["id"])
    tasks_count_by_day: dict[int, int] = {idx: 0 for idx in range(1, days_total + 1)}
    for task in tasks:
        task_date = task["start_at"].date()
        if task_date.year == year and task_date.month == month:
            tasks_count_by_day[task_date.day] = tasks_count_by_day.get(task_date.day, 0) + 1

    selected_day = next((day_key for day_key, count in tasks_count_by_day.items() if count > 0), 1)
    days = [
        {"day": day_idx, "tasks_count": tasks_count_by_day.get(day_idx, 0), "is_selected": day_idx == selected_day}
        for day_idx in range(1, days_total + 1)
    ]
    return {"year": year, "month": month, "selected_day": selected_day, "days": days}


@app.get("/api/v1/schedule/year")
def year_schedule(
    year: int = Query(ge=1970, le=2100),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    tasks = filter_user_tasks(current_user["id"])
    by_month: dict[int, set[int]] = {month: set() for month in range(1, 13)}
    for task in tasks:
        task_date = task["start_at"].date()
        if task_date.year == year:
            by_month[task_date.month].add(task_date.day)
    months = [{"month": month, "active_days": sorted(by_month[month])} for month in range(1, 13)]
    return {"year": year, "months": months}


@app.get("/api/v1/ai/messages")
def list_ai_messages(
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = Query(default=None),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    messages = STORE["ai_messages"].get(current_user["id"], [])
    if before is not None:
        before_utc = ensure_utc(before)
        messages = [msg for msg in messages if msg["created_at"] < before_utc]
    sliced = messages[-limit:]
    return {
        "items": [
            {
                "id": item["id"],
                "role": item["role"],
                "text": item["text"],
                "created_at": to_iso_utc(item["created_at"]),
            }
            for item in sliced
        ]
    }


@app.post("/api/v1/ai/messages")
def send_ai_message(
    payload: SendAIMessageRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    messages = STORE["ai_messages"].setdefault(current_user["id"], [])
    user_msg = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "text": payload.message.strip(),
        "created_at": now_utc(),
    }
    messages.append(user_msg)

    reply_text = "Done. Added tasks to your schedule."
    assistant_msg = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "text": reply_text,
        "created_at": now_utc(),
    }
    messages.append(assistant_msg)
    return {"reply": assistant_msg["text"], "created_at": to_iso_utc(assistant_msg["created_at"])}


@app.post("/api/v1/ai/generate-schedule")
def generate_schedule(
    payload: GenerateScheduleRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    presets = [
        ("Morning planning", "Plan day goals", 30, "Planning"),
        ("Deep work block", "Focus session", 120, "Important"),
        ("Break and walk", "Recharge", 30, "Health"),
        ("Review and wrap-up", "Check progress", 45, "Review"),
    ]
    if payload.mode == "light":
        presets = presets[:2]
    elif payload.mode == "deep_focus":
        presets = [
            ("Morning planning", "Set priorities", 20, "Planning"),
            ("Deep work block 1", "Hard task", 150, "Important"),
            ("Deep work block 2", "Second hard task", 150, "Important"),
            ("Evening review", "Lessons learned", 30, "Review"),
        ]

    base_time = datetime.combine(payload.date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=9, minute=0)
    created_tasks = 0
    for idx, (title, mini_description, duration, category) in enumerate(presets):
        task_id = str(uuid.uuid4())
        task = {
            "id": task_id,
            "user_id": current_user["id"],
            "title": title,
            "mini_description": mini_description,
            "duration_minutes": duration,
            "start_at": base_time + timedelta(minutes=idx * 150),
            "category": category,
            "source_note_id": None,
            "created_at": now_utc(),
            "updated_at": now_utc(),
        }
        STORE["tasks"][task_id] = task
        created_tasks += 1
    return {"success": True, "created_tasks": created_tasks, "message": "Schedule generated"}


@app.get("/api/v1/focus/summary")
def focus_summary(
    period: Literal["week", "month"] = Query(default="week"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    tasks = filter_user_tasks(current_user["id"])
    now_value = now_utc()
    start = now_value - timedelta(days=7 if period == "week" else 30)
    range_tasks = [item for item in tasks if start <= item["start_at"] <= now_value]
    focus_minutes = sum(item["duration_minutes"] for item in range_tasks)
    tasks_done = len(range_tasks)
    completion_rate = 0.0 if not range_tasks else min(1.0, tasks_done / max(len(range_tasks), 1))

    if range_tasks:
        histogram: dict[int, int] = {}
        for task in range_tasks:
            hour = task["start_at"].hour
            histogram[hour] = histogram.get(hour, 0) + 1
        best_hour = max(histogram, key=histogram.get)
        best_hours = f"{best_hour:02d}:00-{(best_hour + 3) % 24:02d}:00"
    else:
        best_hours = "09:00-12:00"

    if focus_minutes >= 1200:
        stress_level = "High"
        ai_tip = "Add buffer blocks and short breaks."
    elif focus_minutes >= 600:
        stress_level = "Low"
        ai_tip = "Move hard tasks to morning"
    else:
        stress_level = "Low"
        ai_tip = "Try longer focus blocks in the morning."

    return {
        "focus_minutes": focus_minutes,
        "tasks_done": tasks_done,
        "completion_rate": round(completion_rate, 2),
        "best_hours": best_hours,
        "stress_level": stress_level,
        "ai_tip": ai_tip,
    }


@app.post("/api/v1/data/export", status_code=202)
def create_export_job(
    payload: ExportRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = current_user["id"]
    export_payload = {
        "user": build_user_public(current_user),
        "settings": STORE["settings"].get(user_id, {}),
        "notes": [serialize_note(item) for item in filter_user_notes(user_id)],
        "tasks": [serialize_task(item) for item in filter_user_tasks(user_id)],
    }
    job_id = str(uuid.uuid4())
    STORE["export_jobs"][job_id] = {
        "job_id": job_id,
        "user_id": user_id,
        "status": "processing",
        "created_at": now_utc(),
        "data": export_payload,
        "format": payload.format,
    }
    return {"job_id": job_id, "status": "processing"}


@app.get("/api/v1/data/export/{job_id}")
def get_export_job(job_id: str, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    job = STORE["export_jobs"].get(job_id)
    if job is None or job["user_id"] != current_user["id"]:
        raise AppError(status_code=404, code="NOT_FOUND", message="Export job not found")
    mark_job_if_ready(job)
    download_url = f"https://fokusly.app/exports/{job_id}.json" if job["status"] == "done" else None
    return {"job_id": job_id, "status": job["status"], "download_url": download_url}


@app.post("/api/v1/data/import", status_code=202)
async def create_import_job(
    file: UploadFile = File(...),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    content = await file.read()
    imported_notes = 0
    imported_tasks = 0
    if content:
        try:
            payload = json.loads(content.decode("utf-8"))
            imported_notes = len(payload.get("notes", [])) if isinstance(payload, dict) else 0
            imported_tasks = len(payload.get("tasks", [])) if isinstance(payload, dict) else 0
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AppError(
                status_code=400,
                code="BAD_REQUEST",
                message="Import file must be valid JSON",
                details={"field": "file"},
            )
    job_id = str(uuid.uuid4())
    STORE["import_jobs"][job_id] = {
        "job_id": job_id,
        "user_id": current_user["id"],
        "status": "processing",
        "created_at": now_utc(),
        "imported_notes": imported_notes,
        "imported_tasks": imported_tasks,
    }
    return {"job_id": job_id, "status": "processing"}


@app.get("/api/v1/data/import/{job_id}")
def get_import_job(job_id: str, current_user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    job = STORE["import_jobs"].get(job_id)
    if job is None or job["user_id"] != current_user["id"]:
        raise AppError(status_code=404, code="NOT_FOUND", message="Import job not found")
    mark_job_if_ready(job)
    return {
        "job_id": job_id,
        "status": job["status"],
        "imported_notes": job["imported_notes"] if job["status"] == "done" else 0,
        "imported_tasks": job["imported_tasks"] if job["status"] == "done" else 0,
    }
