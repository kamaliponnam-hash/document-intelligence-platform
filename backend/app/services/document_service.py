"""
Document processing orchestrator.

Wires together: file validation -> OCR/text extraction -> AI field
extraction -> financial validation -> persistence, and assembles the
mandatory structured JSON response. This is the single place that
implements the pipeline described in section 1 of the spec.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError, DocumentNotFoundError
from app.core.logging import get_logger
from app.repositories.document_repository import DocumentRepository
from app.schemas.document import (
    DocumentListItem,
    DocumentListResponse,
    DocumentProcessResponse,
    FileValidation,
    ProcessingMetadata,
)
from app.schemas.extraction import ValidationResult
from app.services.document_validation_service import DocumentValidationService
from app.services.extraction_service import REQUIRED_FIELDS, ExtractionService
from app.services.financial_validation_service import FinancialValidationService
from app.services.ocr_service import OCRService
from app.utils.file_utils import sanitize_filename, unique_storage_path

logger = get_logger(__name__)


class DocumentService:
    def __init__(self, settings: Settings, db: Session):
        self.settings = settings
        self.db = db
        self.validation_service = DocumentValidationService(settings)
        self.ocr_service = OCRService(settings)
        self.extraction_service = ExtractionService(settings)
        self.financial_validation_service = FinancialValidationService(settings)
        self.repository = DocumentRepository(db)

    # ------------------------------------------------------------------
    def process_document(self, *, file_bytes: bytes, original_filename: str, document_type: str) -> DocumentProcessResponse:
        start = time.monotonic()
        document_name = sanitize_filename(original_filename)
        storage_path = unique_storage_path(self.settings.UPLOAD_DIR, original_filename)

        with open(storage_path, "wb") as f:
            f.write(file_bytes)

        try:
            file_validation = self.validation_service.validate(
                storage_path, original_filename, None
            )
        except AppError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning("File validation failed for %s: %s", document_name, exc.message)
            response = self._build_failure_response(
                document_name, document_type, exc, elapsed_ms, file_type_hint=original_filename
            )
            self._persist(response, ocr_used=False, elapsed_ms=elapsed_ms, error_code=exc.code, error_message=exc.message)
            return response
        finally:
            pass

        try:
            ocr_result = self.ocr_service.extract_text(storage_path, original_filename)
            outcome = self.extraction_service.extract(document_type, ocr_result, document_name)
            fields = outcome.data.get("fields", {})

            extracted_data = self._assemble_extracted_data(document_type, outcome.data)
            validation = self.financial_validation_service.validate(document_type, fields)

            missing_required = [
                name for name in REQUIRED_FIELDS.get(document_type, [])
                if fields.get(name, {}).get("value") is None
            ]
            processing_status = "PASS" if validation.overall_status != "FAIL" else "FAILED"

            elapsed_ms = int((time.monotonic() - start) * 1000)
            response = DocumentProcessResponse(
                document_name=document_name,
                document_type=document_type,
                processing_status=processing_status,
                overall_confidence=None,
                file_validation=FileValidation(
                    file_type=file_validation.file_type,
                    is_supported=file_validation.is_supported,
                    is_readable=file_validation.is_readable,
                    page_count=file_validation.page_count,
                    status=file_validation.status,
                ),
                extracted_data=extracted_data,
                validation=validation,
                processing_metadata=ProcessingMetadata(
                    ocr_used=ocr_result.ocr_used,
                    processed_at=datetime.now(timezone.utc).isoformat(),
                    processing_time_ms=elapsed_ms,
                    llm_model=outcome.model,
                    extraction_mode=outcome.mode,
                ),
                error=None,
            )
            if missing_required:
                response.validation.issues.append(
                    f"Missing required fields: {', '.join(missing_required)}"
                )

            self._persist(
                response,
                ocr_used=ocr_result.ocr_used,
                elapsed_ms=elapsed_ms,
                error_code=None,
                error_message=None,
            )
            return response

        except AppError as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.warning("Processing failed for %s: %s", document_name, exc.message)
            response = self._build_failure_response(
                document_name,
                document_type,
                exc,
                elapsed_ms,
                file_type_hint=original_filename,
                file_validation=file_validation,
            )
            self._persist(response, ocr_used=False, elapsed_ms=elapsed_ms, error_code=exc.code, error_message=exc.message)
            return response
        except Exception as exc:  # unexpected error -> fail gracefully, no stack trace to client
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.exception("Unexpected error while processing %s", document_name)
            fallback_error = AppError("An unexpected error occurred while processing the document.", code="PROCESSING_FAILED", http_status=500)
            response = self._build_failure_response(
                document_name,
                document_type,
                fallback_error,
                elapsed_ms,
                file_type_hint=original_filename,
                file_validation=file_validation,
            )
            self._persist(response, ocr_used=False, elapsed_ms=elapsed_ms, error_code=fallback_error.code, error_message=fallback_error.message)
            return response
        finally:
            # Clean up the stored upload to save disk on free-tier hosts;
            # comment out if you want to retain raw uploads for audit.
            try:
                if os.path.exists(storage_path):
                    os.remove(storage_path)
            except OSError:
                logger.warning("Failed to remove temp upload %s", storage_path)

    # ------------------------------------------------------------------
    def _assemble_extracted_data(self, document_type: str, raw: dict[str, Any]) -> dict[str, Any]:
        fields = raw.get("fields", {})
        extracted: dict[str, Any] = {}
        for name, entry in fields.items():
            if not isinstance(entry, dict):
                extracted[name] = {"value": entry}
                continue
            evidence = None
            if entry.get("evidence_text") or entry.get("page_number") is not None:
                evidence = {
                    "source_text": entry.get("evidence_text"),
                    "page_number": entry.get("page_number"),
                }
            extracted[name] = {
                "value": entry.get("value"),
                "page_number": entry.get("page_number"),
            }
            if evidence:
                extracted[name]["evidence"] = evidence

        header = raw.get("header") or {}
        if header:
            extracted["header"] = header

        if document_type == "invoice":
            extracted["line_items"] = raw.get("line_items") or []
        else:
            extracted["statement_items"] = raw.get("statement_items") or []

        return extracted

    def _build_failure_response(
        self,
        document_name: str,
        document_type: str,
        exc: AppError,
        elapsed_ms: int,
        file_type_hint: str,
        file_validation: Optional[Any] = None,
    ) -> DocumentProcessResponse:
        if file_validation is not None:
            fv = FileValidation(
                file_type=file_validation.file_type,
                is_supported=file_validation.is_supported,
                is_readable=file_validation.is_readable,
                page_count=file_validation.page_count,
                status="FAILED",
                reason=exc.message,
            )
        else:
            fv = FileValidation(
                file_type="unknown",
                is_supported=False,
                is_readable=False,
                page_count=0,
                status="FAILED",
                reason=exc.message,
            )

        return DocumentProcessResponse(
            document_name=document_name,
            document_type=document_type,
            processing_status="FAILED",
            overall_confidence=None,
            file_validation=fv,
            extracted_data={},
            validation=ValidationResult(checks=[], overall_status="NOT_APPLICABLE", issues=[exc.message]),
            processing_metadata=ProcessingMetadata(
                ocr_used=False,
                processed_at=datetime.now(timezone.utc).isoformat(),
                processing_time_ms=elapsed_ms,
            ),
            error={"code": exc.code, "message": exc.message},
        )

    def _persist(self, response: DocumentProcessResponse, *, ocr_used: bool, elapsed_ms: int, error_code: Optional[str], error_message: Optional[str]) -> None:
        self.repository.upsert_result(
            document_name=response.document_name,
            document_type=response.document_type,
            processing_status=response.processing_status,
            file_type=response.file_validation.file_type,
            page_count=response.file_validation.page_count,
            result_json=response.model_dump(),
            overall_validation_status=response.validation.overall_status,
            ocr_used=ocr_used,
            processing_time_ms=elapsed_ms,
            error_code=error_code,
            error_message=error_message,
        )

    # ------------------------------------------------------------------
    def get_by_name(self, document_name: str) -> DocumentProcessResponse:
        record = self.repository.get_by_name(sanitize_filename(document_name))
        if not record:
            raise DocumentNotFoundError(f"No processed result found for document '{document_name}'.")
        return DocumentProcessResponse(**json.loads(record.result_json))

    def list_documents(self) -> DocumentListResponse:
        records = self.repository.list_all()
        items = [
            DocumentListItem(
                document_name=r.document_name,
                document_type=r.document_type,
                processing_status=r.processing_status,
                overall_validation_status=r.overall_validation_status,
                page_count=r.page_count,
                ocr_used=r.ocr_used,
                processed_at=r.updated_at.isoformat(),
            )
            for r in records
        ]
        return DocumentListResponse(total=len(items), documents=items)
