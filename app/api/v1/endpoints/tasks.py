from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, paginate
from app.core.exceptions import AppError
from app.core.security import ensure_utc, now_utc
from app.db.session import get_db
from app.models.note import Note
from app.models.task import Task
from app.models.user import User
from app.schemas.common import SuccessResponse, to_model_dict
from app.schemas.task import CreateTaskRequest, TaskResponse, TasksListResponse, UpdateTaskRequest
from app.services.helpers import serialize_task

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.get("", response_model=TasksListResponse)
def list_tasks(
    date_filter: date | None = Query(default=None, alias="date"),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    tasks = db.execute(select(Task).where(Task.user_id == current_user.id)).scalars().all()
    if date_filter is not None:
        tasks = [task for task in tasks if ensure_utc(task.start_at).date() == date_filter]
    else:
        if date_from is not None:
            tasks = [task for task in tasks if ensure_utc(task.start_at).date() >= date_from]
        if date_to is not None:
            tasks = [task for task in tasks if ensure_utc(task.start_at).date() <= date_to]
    tasks.sort(key=lambda item: item.start_at)
    return paginate([serialize_task(task) for task in tasks], page, size)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskResponse)
def create_task(
    payload: CreateTaskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if payload.source_note_id:
        note = db.get(Note, payload.source_note_id)
        if note is None or note.user_id != current_user.id:
            raise AppError(
                status_code=404,
                code="NOT_FOUND",
                message="Source note not found",
                details={"field": "source_note_id"},
            )

    task = Task(
        user_id=current_user.id,
        title=payload.title.strip(),
        mini_description=payload.mini_description.strip(),
        duration_minutes=payload.duration_minutes,
        start_at=ensure_utc(payload.start_at),
        category=payload.category.strip(),
        source_note_id=payload.source_note_id,
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return serialize_task(task)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != current_user.id:
        raise AppError(status_code=404, code="NOT_FOUND", message="Task not found")
    return serialize_task(task)


@router.patch("/{task_id}", response_model=TaskResponse)
def patch_task(
    task_id: str,
    payload: UpdateTaskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != current_user.id:
        raise AppError(status_code=404, code="NOT_FOUND", message="Task not found")

    updates = to_model_dict(payload, exclude_unset=True)
    if "source_note_id" in updates:
        source_note_id = updates["source_note_id"]
        if source_note_id is not None:
            note = db.get(Note, source_note_id)
            if note is None or note.user_id != current_user.id:
                raise AppError(
                    status_code=404,
                    code="NOT_FOUND",
                    message="Source note not found",
                    details={"field": "source_note_id"},
                )
        task.source_note_id = source_note_id
    if "title" in updates and updates["title"] is not None:
        task.title = updates["title"].strip()
    if "mini_description" in updates and updates["mini_description"] is not None:
        task.mini_description = updates["mini_description"].strip()
    if "duration_minutes" in updates and updates["duration_minutes"] is not None:
        task.duration_minutes = updates["duration_minutes"]
    if "start_at" in updates and updates["start_at"] is not None:
        task.start_at = ensure_utc(updates["start_at"])
    if "category" in updates and updates["category"] is not None:
        task.category = updates["category"].strip()
    task.updated_at = now_utc()
    db.commit()
    db.refresh(task)
    return serialize_task(task)


@router.delete("/{task_id}", response_model=SuccessResponse)
def delete_task(task_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    task = db.get(Task, task_id)
    if task is None or task.user_id != current_user.id:
        raise AppError(status_code=404, code="NOT_FOUND", message="Task not found")
    db.execute(delete(Task).where(Task.id == task_id))
    db.commit()
    return {"success": True}
