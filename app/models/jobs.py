from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.security import now_utc
from app.db.session import Base


class ExportJob(Base):
    __tablename__ = "export_jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="processing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    export_format: Mapped[str] = mapped_column(String(16), default="json")
    payload_json: Mapped[str] = mapped_column(Text)


class ImportJob(Base):
    __tablename__ = "import_jobs"

    job_id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="processing")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    imported_notes: Mapped[int] = mapped_column(Integer, default=0)
    imported_tasks: Mapped[int] = mapped_column(Integer, default=0)
