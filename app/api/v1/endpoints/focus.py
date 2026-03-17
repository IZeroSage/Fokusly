from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import ensure_utc, now_utc
from app.db.session import get_db
from app.models.task import Task
from app.models.user import User
from app.schemas.focus import FocusSummaryResponse

router = APIRouter(prefix="/focus", tags=["Focus"])


@router.get("/summary", response_model=FocusSummaryResponse)
def focus_summary(
    period: str = Query(default="week"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if period not in {"week", "month"}:
        period = "week"

    now_value = now_utc()
    start = now_value - timedelta(days=7 if period == "week" else 30)

    tasks = db.execute(select(Task).where(Task.user_id == current_user.id)).scalars().all()
    period_tasks = [task for task in tasks if start <= ensure_utc(task.start_at) <= now_value]
    focus_minutes = sum(task.duration_minutes for task in period_tasks)
    tasks_done = len(period_tasks)

    if period_tasks:
        histogram: dict[int, int] = {}
        for task in period_tasks:
            hour = ensure_utc(task.start_at).hour
            histogram[hour] = histogram.get(hour, 0) + 1
        best_hour = max(histogram, key=histogram.get)
        best_hours = f"{best_hour:02d}:00-{(best_hour + 3) % 24:02d}:00"
    else:
        best_hours = "09:00-12:00"

    completion_rate = 0.0 if tasks_done == 0 else 1.0
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
