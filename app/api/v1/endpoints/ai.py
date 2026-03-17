from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import ensure_utc, now_utc, to_iso_utc
from app.db.session import get_db
from app.models.ai_message import AIMessage
from app.models.task import Task
from app.models.user import User
from app.schemas.ai import AIHistoryResponse, SendAIMessageRequest, SendAIMessageResponse
from app.schemas.task import GenerateScheduleRequest, GenerateScheduleResponse

router = APIRouter(prefix="/ai", tags=["AI"])


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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    user_msg = AIMessage(user_id=current_user.id, role="user", text=payload.message.strip(), created_at=now_utc())
    db.add(user_msg)

    assistant_text = "Done. Added tasks to your schedule."
    assistant_msg = AIMessage(user_id=current_user.id, role="assistant", text=assistant_text, created_at=now_utc())
    db.add(assistant_msg)
    db.commit()
    return {"reply": assistant_msg.text, "created_at": to_iso_utc(assistant_msg.created_at)}


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
