from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.security import ensure_utc
from app.db.session import get_db
from app.models.task import Task
from app.models.user import User
from app.schemas.task import DayScheduleResponse, MonthScheduleResponse, YearScheduleResponse
from app.services.helpers import day_load_label

router = APIRouter(prefix="/schedule", tags=["Schedule"])


@router.get("/day", response_model=DayScheduleResponse)
def day_schedule(
    day: date = Query(alias="date"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    tasks = db.execute(select(Task).where(Task.user_id == current_user.id)).scalars().all()
    day_tasks = [task for task in tasks if ensure_utc(task.start_at).date() == day]
    day_tasks.sort(key=lambda item: item.start_at)
    total_minutes = sum(item.duration_minutes for item in day_tasks)
    items = [
        {
            "id": item.id,
            "time": ensure_utc(item.start_at).strftime("%H:%M"),
            "title": item.title,
            "subtitle": item.mini_description or "default",
            "duration_minutes": item.duration_minutes,
            "category": item.category,
        }
        for item in day_tasks
    ]
    return {
        "date": day.isoformat(),
        "tasks_count": len(day_tasks),
        "day_load_label": day_load_label(total_minutes),
        "items": items,
    }


@router.get("/month", response_model=MonthScheduleResponse)
def month_schedule(
    year: int = Query(ge=1970, le=2100),
    month: int = Query(ge=1, le=12),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    first_day = date(year, month, 1)
    next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    days_total = (next_month - first_day).days

    tasks = db.execute(select(Task).where(Task.user_id == current_user.id)).scalars().all()
    counts = {day: 0 for day in range(1, days_total + 1)}
    for task in tasks:
        task_date = ensure_utc(task.start_at).date()
        if task_date.year == year and task_date.month == month:
            counts[task_date.day] = counts.get(task_date.day, 0) + 1

    selected_day = next((day_idx for day_idx, count in counts.items() if count > 0), 1)
    days = [
        {"day": day_idx, "tasks_count": counts.get(day_idx, 0), "is_selected": day_idx == selected_day}
        for day_idx in range(1, days_total + 1)
    ]
    return {"year": year, "month": month, "selected_day": selected_day, "days": days}


@router.get("/year", response_model=YearScheduleResponse)
def year_schedule(
    year: int = Query(ge=1970, le=2100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    tasks = db.execute(select(Task).where(Task.user_id == current_user.id)).scalars().all()
    by_month: dict[int, set[int]] = {idx: set() for idx in range(1, 13)}
    for task in tasks:
        task_date = ensure_utc(task.start_at).date()
        if task_date.year == year:
            by_month[task_date.month].add(task_date.day)
    months = [{"month": month, "active_days": sorted(list(days))} for month, days in by_month.items()]
    return {"year": year, "months": months}
