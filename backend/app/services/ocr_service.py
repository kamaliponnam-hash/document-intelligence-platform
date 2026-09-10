"""
OCR / text extraction service.

Strategy:
  * Native PDF pages (text layer present) -> extracted directly with
    pdfplumber (fast, accurate, no OCR errors).
  * Scanned/image-only PDF pages -> rasterized with pdf2image (Poppler) and
    OCR'd with Tesseract.
  * JPG / PNG -> OCR'd directly with Tesseract.

This hybrid approach keeps native financial statements fast & accurate
while still supporting scanned documents, satisfying section 3 ("support
both native PDFs and scanned/image-based formats").

Uses only free/open-source, local tooling (Tesseract + Poppler) so the
pipeline works without any paid OCR API.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from PIL import Image

from app.core.config import Settings
from app.core.exceptions import OCRProcessingError
from app.core.logging import get_logger
from app.utils.file_utils import get_extension

logger = get_logger(__name__)


@dataclass
class PageText:
    page_number: int
    text: str
    used_ocr: bool


@dataclass
class ExtractionText:
    pages: list[PageText] = field(default_factory=list)
    ocr_used: bool = False

    @property
    def full_text(self) -> str:
        parts = []
        for p in self.pages:
            parts.append(f"\n--- PAGE {p.page_number} ---\n{p.text}")
        return "\n".join(parts)


class OCRService:
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD

    def extract_text(self, file_path: str, original_filename: str) -> ExtractionText:
        ext = get_extension(original_filename)
        try:
            if ext == ".pdf":
                return self._extract_from_pdf(file_path)
            return self._extract_from_image(file_path)
        except OCRProcessingError:
            raise
        except Exception as exc:
            logger.exception("OCR/text extraction failed for %s", original_filename)
            raise OCRProcessingError(
                "Failed to extract text from the document during OCR/parsing."
            ) from exc

    def _extract_from_pdf(self, file_path: str) -> ExtractionText:
        result = ExtractionText()
        pages_needing_ocr: list[int] = []

        with pdfplumber.open(file_path) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                text = (page.extract_text() or "").strip()
                # Also try to capture simple tables as pipe-separated text,
                # which helps the LLM see tabular structure.
                table_text = self._extract_tables_as_text(page)
                combined = (text + "\n" + table_text).strip()

                if len(text) >= self.settings.NATIVE_TEXT_MIN_CHARS:
                    result.pages.append(PageText(idx, combined, used_ocr=False))
                else:
                    # Placeholder; will be filled in by OCR below
                    result.pages.append(PageText(idx, "", used_ocr=False))
                    pages_needing_ocr.append(idx)

        if pages_needing_ocr:
            logger.info(
                "Falling back to OCR for %d page(s) with no native text layer",
                len(pages_needing_ocr),
            )
            images = convert_from_path(file_path, dpi=self.settings.OCR_DPI)
            for page_num in pages_needing_ocr:
                if page_num - 1 >= len(images):
                    continue
                ocr_text = pytesseract.image_to_string(
                    images[page_num - 1], lang=self.settings.TESSERACT_LANG
                )
                result.pages[page_num - 1] = PageText(page_num, ocr_text.strip(), used_ocr=True)
                result.ocr_used = True

        return result

    @staticmethod
    def _extract_tables_as_text(page) -> str:
        try:
            tables = page.extract_tables()
        except Exception:
            return ""
        lines = []
        for table in tables:
            for row in table:
                cells = [c.strip() if c else "" for c in row]
                lines.append(" | ".join(cells))
        return "\n".join(lines)

    def _extract_from_image(self, file_path: str) -> ExtractionText:
        with Image.open(file_path) as img:
            text = pytesseract.image_to_string(img, lang=self.settings.TESSERACT_LANG)
        return ExtractionText(
            pages=[PageText(1, text.strip(), used_ocr=True)],
            ocr_used=True,
        )
