from __future__ import annotations

from typing import Any

from app.core.security import to_iso_utc
from app.models.note import Note
from app.models.task import Task
from app.models.user import User, UserSettings

DEFAULT_NOTE_CATEGORIES = ["All", "Work", "University", "Home", "TO DO"]


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


def serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "display_name": user.display_name,
        "email": user.email,
        "avatar_initial": user.avatar_initial,
    }


def serialize_settings(settings: UserSettings) -> dict[str, Any]:
    return {
        "language": settings.language,
        "theme": settings.theme,
        "smart_planning": settings.smart_planning,
        "ai_suggestions": settings.ai_suggestions,
    }


def serialize_note(note: Note) -> dict[str, Any]:
    return {
        "id": note.id,
        "title": note.title,
        "body": note.body,
        "category": note.category,
        "created_at": to_iso_utc(note.created_at),
        "updated_at": to_iso_utc(note.updated_at) if note.updated_at else None,
    }


def serialize_task(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "mini_description": task.mini_description,
        "duration_minutes": task.duration_minutes,
        "start_at": to_iso_utc(task.start_at),
        "category": task.category,
    }


def day_load_label(total_minutes: int) -> str:
    if total_minutes < 180:
        return "light day"
    if total_minutes < 420:
        return "medium day"
    return "hard day"
