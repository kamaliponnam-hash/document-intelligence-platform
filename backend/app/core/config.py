"""
Application configuration.

All tunables are read from environment variables (see .env.example at the
project root). Nothing sensitive is hardcoded here — this satisfies the
"no secrets committed to source" requirement.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List

from dotenv import load_dotenv

# Load variables from backend/.env into the process environment. Must run
# before the Settings class body executes, since its class attributes read
# os.getenv(...) at import time. Safe to call even if no .env file exists
# (e.g. in production where real env vars are injected by the platform).
load_dotenv()


def _get_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # --- General ---
    APP_NAME: str = os.getenv("APP_NAME", "Document Intelligence Platform")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # --- CORS ---
    CORS_ORIGINS: List[str] = [
        o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()
    ]

    # --- Storage / Database ---
    # Default: local SQLite file. Can be swapped for Postgres/MySQL by
    # setting DATABASE_URL, e.g. postgresql+psycopg2://user:pass@host/db
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///./storage/document_intelligence.db"
    )
    UPLOAD_DIR: str = os.getenv("UPLOAD_DIR", "./storage/uploads")

    # --- Upload / document constraints ---
    MAX_PAGE_COUNT: int = int(os.getenv("MAX_PAGE_COUNT", "3"))
    MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "15"))
    SUPPORTED_CONTENT_TYPES: List[str] = [
        "application/pdf",
        "image/jpeg",
        "image/png",
    ]
    SUPPORTED_EXTENSIONS: List[str] = [".pdf", ".jpg", ".jpeg", ".png"]

    # --- OCR ---
    # Minimum number of characters pdfplumber must find on a PDF page
    # before we treat it as "native text" rather than falling back to OCR.
    NATIVE_TEXT_MIN_CHARS: int = int(os.getenv("NATIVE_TEXT_MIN_CHARS", "20"))
    OCR_DPI: int = int(os.getenv("OCR_DPI", "300"))
    TESSERACT_LANG: str = os.getenv("TESSERACT_LANG", "eng")
    # Optional explicit path to the tesseract binary (useful on some hosts)
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "")

    # --- LLM extraction ---
    # Supported providers: "gemini" (Google AI Studio, free tier available)
    # or "anthropic" (Claude, requires paid credits). Default is Gemini so
    # the project runs on a no-cost API key out of the box.
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "gemini")

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")

    LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "4096"))
    LLM_TIMEOUT_SECONDS: int = int(os.getenv("LLM_TIMEOUT_SECONDS", "60"))
    # If true and no API key / LLM call fails, use the lightweight offline
    # regex-based extractor instead of failing the whole request. Useful for
    # local development and CI without an API key. Default off in production.
    ALLOW_OFFLINE_EXTRACTION_FALLBACK: bool = _get_bool(
        "ALLOW_OFFLINE_EXTRACTION_FALLBACK", True
    )

    # --- Financial validation tolerance ---
    # A check passes if |calculated - reported| <= max(ABS_TOLERANCE,
    # REL_TOLERANCE_PERCENT% of |reported|)
    VALIDATION_ABS_TOLERANCE: float = float(os.getenv("VALIDATION_ABS_TOLERANCE", "1.0"))
    VALIDATION_REL_TOLERANCE_PERCENT: float = float(
        os.getenv("VALIDATION_REL_TOLERANCE_PERCENT", "1.0")
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
