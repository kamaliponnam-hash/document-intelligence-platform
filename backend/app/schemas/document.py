"""
Top-level request/response schemas for the document processing API.
Mirrors the "Mandatory Structured Response" shape from the assignment spec.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.extraction import ValidationResult


class DocumentType(str, Enum):
    invoice = "invoice"
    balance_sheet = "balance_sheet"
    profit_and_loss = "profit_and_loss"
    cash_flow_statement = "cash_flow_statement"


class ProcessingStatus(str, Enum):
    PASS = "PASS"
    FAILED = "FAILED"


class FileValidation(BaseModel):
    file_type: str
    is_supported: bool
    is_readable: bool
    page_count: int
    status: str  # PASS | FAILED
    reason: Optional[str] = None


class ProcessingMetadata(BaseModel):
    ocr_used: bool
    processed_at: str
    processing_time_ms: int
    llm_model: Optional[str] = None
    extraction_mode: Optional[str] = None  # "llm" | "offline_fallback"


class DocumentProcessResponse(BaseModel):
    document_name: str
    document_type: str
    processing_status: str
    overall_confidence: Optional[float] = None
    file_validation: FileValidation
    extracted_data: Dict[str, Any] = Field(default_factory=dict)
    validation: ValidationResult
    processing_metadata: ProcessingMetadata
    error: Optional[Dict[str, str]] = None


class DocumentListItem(BaseModel):
    document_name: str
    document_type: str
    processing_status: str
    overall_validation_status: Optional[str] = None
    page_count: int
    ocr_used: bool
    processed_at: str


class DocumentListResponse(BaseModel):
    total: int
    documents: List[DocumentListItem]


class HealthResponse(BaseModel):
    status: str
    app_name: str
    environment: str
    timestamp: str
