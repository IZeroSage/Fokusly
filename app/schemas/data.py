from __future__ import annotations

from pydantic import BaseModel


class ExportRequest(BaseModel):
    format: str


class JobResponse(BaseModel):
    job_id: str
    status: str


class ExportStatusResponse(BaseModel):
    job_id: str
    status: str
    download_url: str | None


class ImportStatusResponse(BaseModel):
    job_id: str
    status: str
    imported_notes: int
    imported_tasks: int
