"""
Application exception hierarchy.

Every exception carries a machine-readable `code` and a human-readable
`message` so the API layer can turn it into the mandatory error response
shape:

    {"error": {"code": "...", "message": "..."}}

without ever leaking stack traces or internal details to the client.
"""
from __future__ import annotations


class AppError(Exception):
    """Base class for all controlled application errors."""

    code: str = "INTERNAL_ERROR"
    http_status: int = 500

    def __init__(self, message: str, code: str | None = None, http_status: int | None = None):
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        if http_status:
            self.http_status = http_status


class UnsupportedFileTypeError(AppError):
    code = "UNSUPPORTED_FILE_TYPE"
    http_status = 415


class EmptyFileError(AppError):
    code = "EMPTY_FILE"
    http_status = 400


class CorruptedFileError(AppError):
    code = "CORRUPTED_FILE"
    http_status = 400


class PageLimitExceededError(AppError):
    code = "PAGE_LIMIT_EXCEEDED"
    http_status = 400


class InvalidDocumentTypeError(AppError):
    code = "INVALID_DOCUMENT_TYPE"
    http_status = 400


class DocumentNotFoundError(AppError):
    code = "DOCUMENT_NOT_FOUND"
    http_status = 404


class OCRProcessingError(AppError):
    code = "OCR_PROCESSING_FAILED"
    http_status = 502


class ExtractionServiceError(AppError):
    code = "EXTRACTION_FAILED"
    http_status = 502


class DatabaseError(AppError):
    code = "DATABASE_ERROR"
    http_status = 500
