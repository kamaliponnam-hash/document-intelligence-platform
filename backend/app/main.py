"""
Application entrypoint.

Serves:
  * REST API under /api/v1/*  (documents.py router)
  * Swagger/OpenAPI docs at /docs (FastAPI default) — satisfies the
    "Swagger/OpenAPI documentation must be available" requirement.
  * The mandatory HTML/CSS/JS frontend (dashboard + result view) at "/",
    served directly by this same FastAPI app via Jinja2Templates so a
    single deployed service satisfies both the "frontend URL" and
    "backend API URL" deliverables (documented assumption — see README).
"""
from __future__ import annotations

import json
import os
from markupsafe import Markup
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.api.routes import documents as documents_routes
from app.core.config import get_settings
from app.core.database import init_db
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger

configure_logging()
logger = get_logger(__name__)
settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description="Intelligent Document Extraction, Validation & API Platform",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents_routes.router, prefix="/api/v1", tags=["documents"])

# ---------------------------------------------------------------------
# Frontend (server-rendered HTML/CSS/JS, backed by the same API)
# ---------------------------------------------------------------------
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PROJECT_ROOT = os.path.dirname(_BACKEND_DIR)
_FRONTEND_DIR = os.path.join(_PROJECT_ROOT, "frontend")

templates = Jinja2Templates(directory=os.path.join(_FRONTEND_DIR, "templates"))
# Starlette's Jinja2Templates does not register Flask's `tojson` filter by
# default; the document_result.html template needs it to safely pass the
# document name into an inline <script> block.
templates.env.filters["tojson"] = lambda v: Markup(json.dumps(v))
app.mount("/static", StaticFiles(directory=os.path.join(_FRONTEND_DIR, "static")), name="static")


@app.on_event("startup")
def on_startup() -> None:
    logger.info("Starting %s in %s environment", settings.APP_NAME, settings.ENVIRONMENT)
    init_db()
    os.makedirs(settings.UPLOAD_DIR, exist_ok=True)
    active_key = settings.GEMINI_API_KEY if settings.LLM_PROVIDER == "gemini" else settings.ANTHROPIC_API_KEY
    if not active_key:
        logger.warning(
            "No API key configured for LLM_PROVIDER='%s' — extraction will use "
            "the offline heuristic fallback. Set GEMINI_API_KEY (or ANTHROPIC_API_KEY "
            "if using LLM_PROVIDER=anthropic) in your environment for full AI extraction.",
            settings.LLM_PROVIDER,
        )
    else:
        logger.info("LLM extraction configured: provider=%s", settings.LLM_PROVIDER)


# ---------------------------------------------------------------------
# Controlled error handling (no stack traces / secrets leaked to clients)
# ---------------------------------------------------------------------
@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"error": {"code": exc.code, "message": exc.message}},
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": "HTTP_ERROR", "message": str(exc.detail)}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
    )


# ---------------------------------------------------------------------
# Frontend routes
# ---------------------------------------------------------------------
@app.get("/", include_in_schema=False)
def dashboard_page(request: Request):
    return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/documents/{document_name}", include_in_schema=False)
def document_result_page(request: Request, document_name: str):
    return templates.TemplateResponse(
        "document_result.html", {"request": request, "document_name": document_name}
    )
