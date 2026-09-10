"""
Repository layer — the ONLY place that talks to the database for
processed-document records. Keeps persistence concerns out of the API and
service layers (section 9 "separate ... persistence/database access").
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import DatabaseError
from app.core.logging import get_logger
from app.models.document import ProcessedDocument

logger = get_logger(__name__)


class DocumentRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_result(
        self,
        *,
        document_name: str,
        document_type: str,
        processing_status: str,
        file_type: str,
        page_count: int,
        result_json: dict,
        overall_validation_status: Optional[str],
        ocr_used: bool,
        processing_time_ms: int,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> ProcessedDocument:
        try:
            existing = self.db.execute(
                select(ProcessedDocument).where(ProcessedDocument.document_name == document_name)
            ).scalar_one_or_none()

            payload = json.dumps(result_json, default=str)

            if existing:
                existing.document_type = document_type
                existing.processing_status = processing_status
                existing.file_type = file_type
                existing.page_count = page_count
                existing.result_json = payload
                existing.overall_validation_status = overall_validation_status
                existing.ocr_used = ocr_used
                existing.processing_time_ms = processing_time_ms
                existing.error_code = error_code
                existing.error_message = error_message
                record = existing
            else:
                record = ProcessedDocument(
                    document_name=document_name,
                    document_type=document_type,
                    processing_status=processing_status,
                    file_type=file_type,
                    page_count=page_count,
                    result_json=payload,
                    overall_validation_status=overall_validation_status,
                    ocr_used=ocr_used,
                    processing_time_ms=processing_time_ms,
                    error_code=error_code,
                    error_message=error_message,
                )
                self.db.add(record)

            self.db.commit()
            self.db.refresh(record)
            return record
        except Exception as exc:
            self.db.rollback()
            logger.exception("Failed to persist processed document result")
            raise DatabaseError("Failed to store the processing result.") from exc

    def get_by_name(self, document_name: str) -> Optional[ProcessedDocument]:
        try:
            return self.db.execute(
                select(ProcessedDocument).where(ProcessedDocument.document_name == document_name)
            ).scalar_one_or_none()
        except Exception as exc:
            logger.exception("Failed to fetch document by name")
            raise DatabaseError("Failed to retrieve the document.") from exc

    def list_all(self, limit: int = 200) -> list[ProcessedDocument]:
        try:
            stmt = (
                select(ProcessedDocument)
                .order_by(ProcessedDocument.updated_at.desc())
                .limit(limit)
            )
            return list(self.db.execute(stmt).scalars().all())
        except Exception as exc:
            logger.exception("Failed to list documents")
            raise DatabaseError("Failed to list processed documents.") from exc
