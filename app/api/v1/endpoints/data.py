from __future__ import annotations

import json

from fastapi import APIRouter, Depends, File, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.exceptions import AppError
from app.db.session import get_db
from app.models.jobs import ExportJob, ImportJob
from app.models.note import Note
from app.models.task import Task
from app.models.user import User, UserSettings
from app.schemas.data import ExportRequest, ExportStatusResponse, ImportStatusResponse, JobResponse
from app.services.helpers import serialize_note, serialize_settings, serialize_task, serialize_user

router = APIRouter(prefix="/data", tags=["Data"])


def _mark_ready(status: str, created_at, delay_seconds: int) -> str:
    from app.core.security import ensure_utc, now_utc

    if status != "processing":
        return status
    elapsed = (now_utc() - ensure_utc(created_at)).total_seconds()
    return "done" if elapsed >= delay_seconds else status


@router.post("/export", status_code=status.HTTP_202_ACCEPTED, response_model=JobResponse)
def create_export_job(
    payload: ExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    if payload.format != "json":
        raise AppError(
            status_code=422,
            code="VALIDATION_ERROR",
            message="Only json export format is supported",
            details={"field": "format"},
        )

    settings_row = db.get(UserSettings, current_user.id)
    notes = db.query(Note).filter(Note.user_id == current_user.id).all()
    tasks = db.query(Task).filter(Task.user_id == current_user.id).all()
    export_payload = {
        "user": serialize_user(current_user),
        "settings": serialize_settings(settings_row) if settings_row else {},
        "notes": [serialize_note(item) for item in notes],
        "tasks": [serialize_task(item) for item in tasks],
    }

    job = ExportJob(user_id=current_user.id, status="processing", export_format="json", payload_json=json.dumps(export_payload))
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"job_id": job.job_id, "status": "processing"}


@router.get("/export/{job_id}", response_model=ExportStatusResponse)
def get_export_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    job = db.get(ExportJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise AppError(status_code=404, code="NOT_FOUND", message="Export job not found")
    job.status = _mark_ready(job.status, job.created_at, settings.async_job_delay_seconds)
    db.commit()
    download_url = f"https://fokusly.app/exports/{job_id}.json" if job.status == "done" else None
    return {"job_id": job.job_id, "status": job.status, "download_url": download_url}


@router.post("/import", status_code=status.HTTP_202_ACCEPTED, response_model=JobResponse)
async def create_import_job(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    content = await file.read()
    imported_notes = 0
    imported_tasks = 0
    if content:
        try:
            parsed = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise AppError(
                status_code=400,
                code="BAD_REQUEST",
                message="Import file must be valid JSON",
                details={"field": "file"},
            )
        if isinstance(parsed, dict):
            imported_notes = len(parsed.get("notes", []))
            imported_tasks = len(parsed.get("tasks", []))

    job = ImportJob(
        user_id=current_user.id,
        status="processing",
        imported_notes=imported_notes,
        imported_tasks=imported_tasks,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"job_id": job.job_id, "status": "processing"}


@router.get("/import/{job_id}", response_model=ImportStatusResponse)
def get_import_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    job = db.get(ImportJob, job_id)
    if job is None or job.user_id != current_user.id:
        raise AppError(status_code=404, code="NOT_FOUND", message="Import job not found")
    job.status = _mark_ready(job.status, job.created_at, settings.async_job_delay_seconds)
    db.commit()
    return {
        "job_id": job.job_id,
        "status": job.status,
        "imported_notes": job.imported_notes if job.status == "done" else 0,
        "imported_tasks": job.imported_tasks if job.status == "done" else 0,
    }
