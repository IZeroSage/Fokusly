from __future__ import annotations

from uuid import uuid4

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import Select, delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, paginate
from app.core.exceptions import AppError
from app.core.security import now_utc
from app.db.session import get_db
from app.models.note import Note
from app.models.user import User
from app.schemas.common import SuccessResponse, to_model_dict
from app.schemas.note import (
    CategoriesResponse,
    CreateNoteRequest,
    NoteResponse,
    NotesListResponse,
    ShareResponse,
    UpdateNoteRequest,
)
from app.services.helpers import DEFAULT_NOTE_CATEGORIES, serialize_note

router = APIRouter(prefix="/notes", tags=["Notes"])


def _query_user_notes(user_id: str) -> Select[tuple[Note]]:
    return select(Note).where(Note.user_id == user_id)


@router.get("/categories", response_model=CategoriesResponse)
def list_note_categories(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    categories = db.execute(_query_user_notes(current_user.id)).scalars().all()
    unique = sorted({note.category for note in categories if note.category not in DEFAULT_NOTE_CATEGORIES})
    return {"items": DEFAULT_NOTE_CATEGORIES + unique}


@router.get("", response_model=NotesListResponse)
def list_notes(
    q: str | None = Query(default=None),
    category: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    notes = db.execute(_query_user_notes(current_user.id)).scalars().all()
    if q:
        qn = q.lower()
        notes = [n for n in notes if qn in n.title.lower() or qn in n.body.lower()]
    if category and category != "All":
        notes = [n for n in notes if n.category == category]
    notes.sort(key=lambda item: item.created_at, reverse=True)
    serialized = [serialize_note(note) for note in notes]
    return paginate(serialized, page, size)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=NoteResponse)
def create_note(
    payload: CreateNoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    note = Note(
        user_id=current_user.id,
        title=payload.title.strip(),
        body=payload.body,
        category=payload.category.strip(),
        created_at=now_utc(),
        updated_at=now_utc(),
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return serialize_note(note)


@router.get("/{note_id}", response_model=NoteResponse)
def get_note(note_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    note = db.get(Note, note_id)
    if note is None or note.user_id != current_user.id:
        raise AppError(status_code=404, code="NOT_FOUND", message="Note not found")
    return serialize_note(note)


@router.patch("/{note_id}", response_model=NoteResponse)
def patch_note(
    note_id: str,
    payload: UpdateNoteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    note = db.get(Note, note_id)
    if note is None or note.user_id != current_user.id:
        raise AppError(status_code=404, code="NOT_FOUND", message="Note not found")

    updates = to_model_dict(payload, exclude_unset=True)
    if "title" in updates and updates["title"] is not None:
        note.title = updates["title"].strip()
    if "body" in updates and updates["body"] is not None:
        note.body = updates["body"]
    if "category" in updates and updates["category"] is not None:
        note.category = updates["category"].strip()
    note.updated_at = now_utc()
    db.commit()
    db.refresh(note)
    return serialize_note(note)


@router.delete("/{note_id}", response_model=SuccessResponse)
def delete_note(note_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    note = db.get(Note, note_id)
    if note is None or note.user_id != current_user.id:
        raise AppError(status_code=404, code="NOT_FOUND", message="Note not found")
    db.execute(delete(Note).where(Note.id == note_id))
    db.commit()
    return {"success": True}


@router.post("/{note_id}/share", response_model=ShareResponse)
def share_note(note_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)) -> dict:
    note = db.get(Note, note_id)
    if note is None or note.user_id != current_user.id:
        raise AppError(status_code=404, code="NOT_FOUND", message="Note not found")
    return {"share_url": f"https://fokusly.app/share/{note_id}?token={uuid4()}"}
