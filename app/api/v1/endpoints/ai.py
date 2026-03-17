from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.exceptions import AppError
from app.core.security import ensure_utc, now_utc, to_iso_utc
from app.db.session import get_db
from app.models.ai_message import AIMessage
from app.models.ai_request import AIRequestLog
from app.models.task import Task
from app.models.user import User, UserSettings
from app.schemas.ai import AIHistoryResponse, SendAIMessageRequest, SendAIMessageResponse
from app.schemas.task import GenerateScheduleRequest, GenerateScheduleResponse
from app.services.ai_chat import AIAction, DeepSeekCommand, ai_metrics, call_deepseek, parse_user_datetime

router = APIRouter(prefix="/ai", tags=["AI"])
logger = logging.getLogger(__name__)


def _user_timezone(db: Session, user_id: str) -> str:
    settings = db.get(UserSettings, user_id)
    timezone_name = settings.timezone if settings and settings.timezone else "Europe/Moscow"
    try:
        ZoneInfo(timezone_name)
    except Exception:
        timezone_name = "Europe/Moscow"
    return timezone_name


def _load_recent_tasks(db: Session, user_id: str, limit: int = 100) -> list[Task]:
    tasks = db.execute(select(Task).where(Task.user_id == user_id).order_by(Task.start_at.desc())).scalars().all()
    return tasks[:limit]


def _dedupe_key(header_value: str | None, request_value: str | None) -> str | None:
    candidate = (header_value or request_value or "").strip()
    return candidate if candidate else None


def _apply_ai_operations(
    db: Session,
    user: User,
    timezone_name: str,
    command: DeepSeekCommand,
) -> tuple[list[AIAction], list[str]]:
    actions: list[AIAction] = []
    notes: list[str] = []
    zone = ZoneInfo(timezone_name)
    allowed_ops = {"create_task", "update_task", "delete_task"}

    for operation in command.operations:
        if operation.op not in allowed_ops:
            raise AppError(status_code=422, code="VALIDATION_ERROR", message="Unsupported AI operation")

        if operation.op == "create_task":
            if not operation.title or not operation.date or not operation.time:
                notes.append("Не хватает данных для создания задачи: нужны title/date/time.")
                continue
            start_at_local = parse_user_datetime(operation.date, operation.time, timezone_name)
            duration = operation.duration_minutes if operation.duration_minutes is not None else 60
            if duration < 1 or duration > 24 * 60:
                raise AppError(status_code=422, code="VALIDATION_ERROR", message="Invalid duration_minutes in AI command")
            task = Task(
                user_id=user.id,
                title=operation.title.strip(),
                mini_description=(operation.mini_description or "").strip(),
                duration_minutes=duration,
                start_at=ensure_utc(start_at_local),
                category=(operation.category or "General").strip() or "General",
                source_note_id=None,
                created_at=now_utc(),
                updated_at=now_utc(),
            )
            db.add(task)
            db.flush()
            actions.append(AIAction(type="create_task", task_id=task.id))
            notes.append(f'Создана задача "{task.title}".')
            continue

        if operation.op == "update_task":
            changed_fields = [
                operation.title,
                operation.mini_description,
                operation.duration_minutes,
                operation.date,
                operation.time,
                operation.category,
            ]
            if not operation.task_id or all(value is None for value in changed_fields):
                notes.append("Недостаточно данных для обновления задачи.")
                continue

            task = (
                db.execute(select(Task).where(Task.id == operation.task_id, Task.user_id == user.id))
                .scalars()
                .first()
            )
            if task is None:
                notes.append(f"Задача {operation.task_id} не найдена.")
                continue

            if operation.title is not None:
                task.title = operation.title.strip()
            if operation.mini_description is not None:
                task.mini_description = operation.mini_description.strip()
            if operation.duration_minutes is not None:
                if operation.duration_minutes < 1 or operation.duration_minutes > 24 * 60:
                    raise AppError(
                        status_code=422,
                        code="VALIDATION_ERROR",
                        message="Invalid duration_minutes in AI command",
                    )
                task.duration_minutes = operation.duration_minutes
            if operation.category is not None:
                task.category = operation.category.strip()
            if operation.date is not None or operation.time is not None:
                local_existing = ensure_utc(task.start_at).astimezone(zone)
                next_date = operation.date or local_existing.date().isoformat()
                next_time = operation.time or local_existing.strftime("%H:%M")
                task.start_at = ensure_utc(parse_user_datetime(next_date, next_time, timezone_name))
            task.updated_at = now_utc()
            actions.append(AIAction(type="update_task", task_id=task.id))
            notes.append(f'Обновлена задача "{task.title}".')
            continue

        if not operation.task_id:
            notes.append("Не указан task_id для удаления.")
            continue
        task = db.execute(select(Task).where(Task.id == operation.task_id, Task.user_id == user.id)).scalars().first()
        if task is None:
            notes.append(f"Задача {operation.task_id} не найдена.")
            continue
        deleted_title = task.title
        db.delete(task)
        actions.append(AIAction(type="delete_task", task_id=operation.task_id))
        notes.append(f'Удалена задача "{deleted_title}".')

    return actions, notes


@router.get("/messages", response_model=AIHistoryResponse)
def list_ai_messages(
    limit: int = Query(default=50, ge=1, le=200),
    before: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    messages = db.execute(
        select(AIMessage)
        .where(AIMessage.user_id == current_user.id)
        .order_by(AIMessage.created_at.asc())
    ).scalars().all()
    if before is not None:
        before_utc = ensure_utc(before)
        messages = [msg for msg in messages if ensure_utc(msg.created_at) < before_utc]
    selected = messages[-limit:]
    return {
        "items": [
            {"id": msg.id, "role": msg.role, "text": msg.text, "created_at": to_iso_utc(msg.created_at)}
            for msg in selected
        ]
    }


@router.post("/messages", response_model=SendAIMessageResponse)
def send_ai_message(
    payload: SendAIMessageRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    started = time.perf_counter()
    text = payload.message.strip()
    dedupe = _dedupe_key(idempotency_key, payload.request_id)
    if dedupe:
        existing = (
            db.execute(select(AIRequestLog).where(AIRequestLog.user_id == current_user.id, AIRequestLog.dedupe_key == dedupe))
            .scalars()
            .first()
        )
        if existing is not None:
            logger.info("ai_chat_deduped user_id=%s dedupe_key=%s", current_user.id, dedupe)
            return {
                "reply": existing.reply_text,
                "actions": json.loads(existing.actions_json),
                "created_at": to_iso_utc(existing.created_at),
            }

    timezone_name = _user_timezone(db, current_user.id)
    recent_tasks = _load_recent_tasks(db, current_user.id)
    logger.info("ai_chat_request user_id=%s message=%s timezone=%s", current_user.id, text, timezone_name)

    user_msg = AIMessage(user_id=current_user.id, role="user", text=text, created_at=now_utc())
    db.add(user_msg)
    db.commit()

    command = call_deepseek(text, timezone_name, recent_tasks)
    logger.info("ai_chat_model_response user_id=%s payload=%s", current_user.id, command.model_dump_json())

    if command.need_clarification:
        reply_text = (command.clarification_question or command.summary or "Уточни, пожалуйста, детали задачи.").strip()
        assistant_msg = AIMessage(user_id=current_user.id, role="assistant", text=reply_text, created_at=now_utc())
        db.add(assistant_msg)
        if dedupe:
            db.add(
                AIRequestLog(
                    user_id=current_user.id,
                    dedupe_key=dedupe,
                    request_text=text,
                    reply_text=reply_text,
                    actions_json="[]",
                    created_at=assistant_msg.created_at,
                )
            )
        db.commit()
        duration = time.perf_counter() - started
        logger.info("ai_chat_done user_id=%s actions=0 duration_seconds=%.3f", current_user.id, duration)
        logger.info("ai_metrics snapshot=%s", ai_metrics.snapshot())
        return {"reply": reply_text, "actions": [], "created_at": to_iso_utc(assistant_msg.created_at)}

    try:
        actions, notes = _apply_ai_operations(db, current_user, timezone_name, command)
        action_dicts = [item.as_dict() for item in actions]
        reply_text = command.summary.strip() if command.summary.strip() else "Готово."
        if notes:
            reply_text = f"{reply_text} " + " ".join(notes)

        assistant_msg = AIMessage(user_id=current_user.id, role="assistant", text=reply_text, created_at=now_utc())
        db.add(assistant_msg)
        if dedupe:
            db.add(
                AIRequestLog(
                    user_id=current_user.id,
                    dedupe_key=dedupe,
                    request_text=text,
                    reply_text=reply_text,
                    actions_json=json.dumps(action_dicts, ensure_ascii=False),
                    created_at=assistant_msg.created_at,
                )
            )
        db.commit()
    except AppError:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("ai_chat_execution_error user_id=%s", current_user.id)
        raise AppError(status_code=500, code="INTERNAL_ERROR", message="AI service temporary unavailable") from exc

    duration = time.perf_counter() - started
    logger.info(
        "ai_chat_done user_id=%s operations=%s duration_seconds=%.3f",
        current_user.id,
        [action.type for action in actions],
        duration,
    )
    logger.info("ai_metrics snapshot=%s", ai_metrics.snapshot())
    return {"reply": assistant_msg.text, "actions": action_dicts, "created_at": to_iso_utc(assistant_msg.created_at)}


@router.post("/generate-schedule", response_model=GenerateScheduleResponse)
def generate_schedule(
    payload: GenerateScheduleRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    mode = payload.mode
    presets = [
        ("Morning planning", "Plan day goals", 30, "Planning"),
        ("Deep work block", "Focus session", 120, "Important"),
        ("Break and walk", "Recharge", 30, "Health"),
        ("Review and wrap-up", "Check progress", 45, "Review"),
    ]
    if mode == "light":
        presets = presets[:2]
    elif mode == "deep_focus":
        presets = [
            ("Morning planning", "Set priorities", 20, "Planning"),
            ("Deep work block 1", "Hard task", 150, "Important"),
            ("Deep work block 2", "Second hard task", 150, "Important"),
            ("Evening review", "Lessons learned", 30, "Review"),
        ]

    base_time = datetime.combine(payload.date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=9, minute=0)
    created_tasks = 0
    for idx, (title, mini_description, duration, category) in enumerate(presets):
        db.add(
            Task(
                user_id=current_user.id,
                title=title,
                mini_description=mini_description,
                duration_minutes=duration,
                start_at=base_time + timedelta(minutes=idx * 150),
                category=category,
                source_note_id=None,
                created_at=now_utc(),
                updated_at=now_utc(),
            )
        )
        created_tasks += 1
    db.commit()
    return {"success": True, "created_tasks": created_tasks, "message": "Schedule generated"}
