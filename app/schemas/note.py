from __future__ import annotations

from pydantic import BaseModel, Field


class NoteResponse(BaseModel):
    id: str
    title: str
    body: str
    category: str
    created_at: str


class NotesListResponse(BaseModel):
    items: list[NoteResponse]
    page: int
    size: int
    total: int


class CreateNoteRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=4000)
    category: str = Field(min_length=1, max_length=60)


class UpdateNoteRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=4000)
    category: str | None = Field(default=None, min_length=1, max_length=60)


class ShareResponse(BaseModel):
    share_url: str


class CategoriesResponse(BaseModel):
    items: list[str]
