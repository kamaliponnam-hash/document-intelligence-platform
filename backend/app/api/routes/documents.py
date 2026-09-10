"""
REST API routes — mirrors section 5 of the assignment spec exactly:

  POST /api/v1/documents/process
  GET  /api/v1/documents/{document_name}
  GET  /api/v1/documents
  GET  /api/v1/health
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.exceptions import InvalidDocumentTypeError
from app.core.logging import get_logger
from app.schemas.document import (
    DocumentListResponse,
    DocumentProcessResponse,
    DocumentType,
    HealthResponse,
)
from app.services.document_service import DocumentService

logger = get_logger(__name__)
router = APIRouter()

_VALID_TYPES = {t.value for t in DocumentType}


@router.post(
    "/documents/process",
    response_model=DocumentProcessResponse,
    summary="Upload and process a PDF / JPG / PNG document",
)
async def process_document(
    file: UploadFile = File(..., description="The PDF / JPG / PNG document to process"),
    document_type: str = Form(..., description="invoice | balance_sheet | profit_and_loss | cash_flow_statement"),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> DocumentProcessResponse:
    if document_type not in _VALID_TYPES:
        raise InvalidDocumentTypeError(
            f"document_type must be one of: {', '.join(sorted(_VALID_TYPES))}"
        )

    file_bytes = await file.read()
    logger.info(
        "Received document for processing: name=%s type=%s size_bytes=%d",
        file.filename,
        document_type,
        len(file_bytes),
    )

    service = DocumentService(settings, db)
    result = service.process_document(
        file_bytes=file_bytes,
        original_filename=file.filename or "upload",
        document_type=document_type,
    )
    return result


@router.get(
    "/documents/{document_name}",
    response_model=DocumentProcessResponse,
    summary="Retrieve the latest structured result for a document by name",
)
def get_document(
    document_name: str,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> DocumentProcessResponse:
    service = DocumentService(settings, db)
    return service.get_by_name(document_name)


@router.get(
    "/documents",
    response_model=DocumentListResponse,
    summary="List processed documents for the dashboard",
)
def list_documents(
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> DocumentListResponse:
    service = DocumentService(settings, db)
    return service.list_documents()


@router.get("/health", response_model=HealthResponse, summary="Health check")
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app_name=settings.APP_NAME,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
