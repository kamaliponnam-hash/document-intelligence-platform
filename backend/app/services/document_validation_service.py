"""
Document (input) validation service.

This is the "input-control layer" required by section 4.1 of the spec:
runs BEFORE any OCR/AI extraction and checks file type, integrity,
readability and page count. It never attempts document-type classification.
"""
from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass

import pdfplumber
from PIL import Image, UnidentifiedImageError

from app.core.config import Settings
from app.core.exceptions import (
    CorruptedFileError,
    EmptyFileError,
    PageLimitExceededError,
    UnsupportedFileTypeError,
)
from app.core.logging import get_logger
from app.utils.file_utils import get_extension

logger = get_logger(__name__)

_EXT_TO_MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


@dataclass
class FileValidationResult:
    file_type: str
    is_supported: bool
    is_readable: bool
    page_count: int
    status: str  # PASS | FAILED
    reason: str | None = None


class DocumentValidationService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def validate(self, file_path: str, original_filename: str, declared_content_type: str | None) -> FileValidationResult:
        ext = get_extension(original_filename)

        # 1. Extension / content-type support check
        if ext not in self.settings.SUPPORTED_EXTENSIONS:
            logger.warning("Rejected upload with unsupported extension: %s", ext)
            raise UnsupportedFileTypeError(
                "Only PDF / JPG / PNG documents are supported.",
            )

        resolved_type = _EXT_TO_MIME.get(ext) or mimetypes.guess_type(original_filename)[0] or "application/octet-stream"

        # 2. Empty file check
        size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        if size == 0:
            logger.warning("Rejected empty upload: %s", original_filename)
            raise EmptyFileError("The uploaded file is empty.")

        max_bytes = self.settings.MAX_FILE_SIZE_MB * 1024 * 1024
        if size > max_bytes:
            logger.warning("Rejected oversized upload: %s (%d bytes)", original_filename, size)
            raise CorruptedFileError(
                f"File exceeds the maximum allowed size of {self.settings.MAX_FILE_SIZE_MB} MB."
            )

        # 3. Readability + page count check
        if ext == ".pdf":
            page_count = self._validate_pdf(file_path)
        else:
            page_count = self._validate_image(file_path)

        # 4. Page limit check
        if page_count > self.settings.MAX_PAGE_COUNT:
            logger.warning(
                "Rejected upload exceeding page limit: %s has %d pages (max %d)",
                original_filename,
                page_count,
                self.settings.MAX_PAGE_COUNT,
            )
            raise PageLimitExceededError(
                f"Document has {page_count} pages; only up to "
                f"{self.settings.MAX_PAGE_COUNT} pages are supported."
            )

        return FileValidationResult(
            file_type=resolved_type,
            is_supported=True,
            is_readable=True,
            page_count=page_count,
            status="PASS",
        )

    @staticmethod
    def _validate_pdf(file_path: str) -> int:
        try:
            with pdfplumber.open(file_path) as pdf:
                page_count = len(pdf.pages)
                if page_count == 0:
                    raise CorruptedFileError("PDF has no readable pages.")
                return page_count
        except CorruptedFileError:
            raise
        except Exception as exc:  # pdfplumber/pdfminer raise various errors on corrupt PDFs
            logger.exception("Failed to open PDF as valid/readable: %s", exc)
            raise CorruptedFileError("The PDF file is corrupted or unreadable.") from exc

    @staticmethod
    def _validate_image(file_path: str) -> int:
        try:
            with Image.open(file_path) as img:
                img.verify()
            # Re-open after verify() (verify() invalidates the file handle)
            with Image.open(file_path) as img2:
                img2.load()
            return 1
        except (UnidentifiedImageError, OSError) as exc:
            logger.exception("Failed to open image as valid/readable: %s", exc)
            raise CorruptedFileError("The image file is corrupted or unreadable.") from exc
