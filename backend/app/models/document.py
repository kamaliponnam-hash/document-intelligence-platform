"""
ORM model for a processed document record.

A single row represents the LATEST processing result for a given
document_name (per the assignment: retaining prior versions is optional,
so re-processing the same file name overwrites/updates the row).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProcessedDocument(Base):
    __tablename__ = "processed_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)

    # Business key used for GET-by-name lookups. Unique so re-processing the
    # same file name updates the existing row (latest-result semantics).
    document_name: Mapped[str] = mapped_column(String(512), unique=True, index=True)

    document_type: Mapped[str] = mapped_column(String(64), index=True)
    processing_status: Mapped[str] = mapped_column(String(16), index=True)  # PASS / FAILED

    file_type: Mapped[str] = mapped_column(String(64))
    page_count: Mapped[int] = mapped_column(Integer, default=0)

    # Full structured JSON response, stored as text (works identically on
    # SQLite/Postgres/MySQL without needing native JSON column support).
    result_json: Mapped[str] = mapped_column(Text)

    overall_validation_status: Mapped[str] = mapped_column(String(16), nullable=True)
    ocr_used: Mapped[bool] = mapped_column(default=False)
    processing_time_ms: Mapped[int] = mapped_column(Integer, default=0)

    error_code: Mapped[str] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
