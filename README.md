# Intelligent Document Extraction, Validation & API Platform

AI Engineer Internship — Technical Case Study submission.

An end-to-end document intelligence service that accepts invoices, balance
sheets, profit & loss statements and cash flow statements (PDF / JPG / PNG,
up to 3 pages), validates the upload, extracts every meaningful field/table
using OCR + an LLM, runs financial calculation checks, persists the result,
and serves it through a REST API and a dashboard.

---

## 1. Solution Overview & Architecture

```
Frontend (HTML/CSS/JS)
        │  POST /api/v1/documents/process (multipart: file + document_type)
        ▼
Document Validation Service   — file type / empty / corrupted / page-limit
        ▼
OCR / Text Extraction Service — pdfplumber (native PDF) + Tesseract/Poppler (scanned/image)
        ▼
AI Extraction Service (Gemini or Claude LLM) — structured field & table extraction
        │  (offline regex fallback if no API key / LLM call fails)
        ▼
Financial Validation Service  — per document-type formulas → PASS/FAIL/NOT_APPLICABLE
        ▼
Document Repository (SQLAlchemy) — SQLite by default, Postgres/MySQL via env var
        ▼
Structured JSON response + persisted record
        ▼
GET /api/v1/documents , GET /api/v1/documents/{name} , GET /api/v1/health
        ▼
Dashboard renders list + result (fields, tables, validations, raw JSON)
```

See `docs/architecture.png` for the visual diagram and
`docs/solution_presentation.pptx` for the mandatory solution presentation.

A **single FastAPI service** serves both the REST API (under `/api/v1/*`)
and the server-rendered HTML/CSS/JS frontend (`/`, `/documents/{name}`) —
this means one deployment gives you both the "frontend URL" and the
"backend API URL" deliverables at the same base URL. This is a documented
assumption (see §9) made because the assignment explicitly allows serving
the frontend from the same Python framework as the API ("FastAPI, Flask...
may be used... A separate React/Node frontend stack is not required").

## 2. Technology Stack & Rationale

| Concern | Choice | Why |
|---|---|---|
| API framework | **FastAPI** | Async, automatic Swagger/OpenAPI at `/docs`, first-class Pydantic validation |
| Native PDF text | **pdfplumber** | Accurate text + table extraction for native PDFs, no OCR errors |
| OCR | **Tesseract + Poppler (pdf2image)** | Free, local, open-source — no API quota risk for the assignment window; used only when a PDF page has no text layer, or for JPG/PNG |
| AI field/table extraction | **Google Gemini** (default) or **Anthropic Claude** | Layout-agnostic — regex cannot realistically satisfy "extract ALL meaningful fields" across arbitrary invoice/statement layouts. Gemini is the default because Google AI Studio offers a genuinely free API tier (no billing setup required); Claude is supported as a drop-in alternative via `LLM_PROVIDER=anthropic` for anyone with API credits |
| Offline fallback extractor | **Regex/label matching** | Keeps the service usable and demoable without an API key, and prevents 5xx crashes if the LLM call fails |
| Persistence | **SQLAlchemy → SQLite** (default) | Zero-config, file-based, perfect for free-tier deployment; swap to Postgres/MySQL with one `DATABASE_URL` change |
| Frontend | **Server-rendered HTML/CSS + vanilla JS** | Matches the spec exactly ("HTML/CSS, JavaScript may be used"); no separate frontend build/deploy needed |

## 3. Project Structure

```
project-root/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app, routing, error handlers, frontend mount
│   │   ├── api/routes/documents.py # 4 mandatory REST endpoints
│   │   ├── core/                   # config.py, database.py, logging.py, exceptions.py
│   │   ├── models/document.py      # SQLAlchemy ORM model
│   │   ├── schemas/                # Pydantic request/response schemas
│   │   ├── services/               # validation, OCR, extraction, financial validation, orchestrator
│   │   ├── repositories/           # DB access layer
│   │   └── utils/                  # file helpers
│   ├── tests/                      # pytest suite
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── templates/                  # dashboard.html, document_result.html
│   └── static/{css,js}/
├── docs/
│   ├── architecture.png
│   └── solution_presentation.pptx
├── sample_outputs/                 # example JSON responses for all 4 doc types + error/failure cases
├── .env.example
├── .gitignore
└── README.md   (this file)
```

## 4. Local Setup & Installation

### Prerequisites
- Python 3.11+
- Tesseract OCR and Poppler (for scanned PDFs / images)
  - macOS: `brew install tesseract poppler`
  - Ubuntu/Debian: `sudo apt-get install tesseract-ocr poppler-utils`
  - Windows: install Tesseract from the UB-Mannheim build and Poppler binaries, then set `TESSERACT_CMD` / add Poppler to `PATH`

### Install & configure
```bash
cd project-root/backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example .env
# edit .env and set GEMINI_API_KEY (free — get one at https://aistudio.google.com/apikey)
# Alternatively set LLM_PROVIDER=anthropic and ANTHROPIC_API_KEY to use Claude instead.
```

### Run
```bash
# from project-root/backend, with .venv active
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

- Frontend dashboard: http://localhost:8000/
- Swagger / OpenAPI docs: http://localhost:8000/docs
- Health check: http://localhost:8000/api/v1/health

> If no API key is set for the configured `LLM_PROVIDER`, the service still runs and processes
> documents using the offline regex fallback extractor (see §7) instead of
> crashing — useful for a quick local smoke test, but full extraction
> completeness requires the LLM path.

### Run tests
```bash
cd project-root/backend
pytest -v
```
Covers: file validation (unsupported type / empty / corrupted / valid),
financial validation checks (PASS / FAIL / NOT_APPLICABLE across all 4
document types), offline extraction fallback + LLM JSON-response parsing,
and a full API integration flow (health, list, reject-unsupported-file,
reject-invalid-document-type, reject-empty-file, process→get-by-name→list,
404-on-unknown-document).

> **Note on this submission:** the code was written and manually reviewed
> line-by-line for correctness, but could not be executed inside the
> authoring sandbox (no network access to install dependencies there).
> Run `pip install -r requirements.txt && pytest -v` once locally before
> deploying to confirm your environment.

## 5. Configuration (Environment Variables)

See `.env.example` for the full list with defaults. Key ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | SQLite by default; set to a Postgres/MySQL URL for production |
| `LLM_PROVIDER` | `gemini` (default, free tier) or `anthropic` (paid) |
| `GEMINI_API_KEY` | Required for Gemini extraction; free at https://aistudio.google.com/apikey |
| `GEMINI_MODEL` | Defaults to `gemini-2.0-flash` |
| `ANTHROPIC_API_KEY` | Required only if `LLM_PROVIDER=anthropic` |
| `ANTHROPIC_MODEL` | Defaults to `claude-3-5-sonnet-20241022`; change to any current Claude model |
| `ALLOW_OFFLINE_EXTRACTION_FALLBACK` | If `true`, degrade gracefully instead of failing the request when the LLM is unavailable |
| `MAX_PAGE_COUNT` | Document page limit (default 3, per spec) |
| `VALIDATION_ABS_TOLERANCE` / `VALIDATION_REL_TOLERANCE_PERCENT` | Financial-check tolerance: `max(abs_tolerance, reported_value * rel_tolerance%)` |

No secrets are hardcoded anywhere in source; `.env` is gitignored.

## 6. Deployment (Render / Railway / Koyeb)

The backend requires system packages (Tesseract, Poppler), so **deploy using
the provided `backend/Dockerfile`** rather than a buildpack.

### Render (example)
1. Push this repository to a public GitHub repo.
2. New → Web Service → connect the repo.
3. Environment: **Docker**. Dockerfile path: `backend/Dockerfile`. Build context: repo root.
4. Add environment variables from `.env.example` (at least `GEMINI_API_KEY`; `DATABASE_URL` can be left as the default SQLite path for the assignment, or pointed at a managed Postgres instance for persistence across redeploys).
5. Deploy. Render provides one public URL — that URL serves both the frontend (`/`) and the API (`/api/v1/*`, `/docs`).

### Railway / Koyeb
Same pattern: point the platform at `backend/Dockerfile` with the repo root
as build context, set the same environment variables, and deploy.

> ⚠️ SQLite on most free-tier hosts uses an ephemeral filesystem — data can
> be lost on redeploy/restart. For evaluation persistence guarantees, point
> `DATABASE_URL` at a free-tier managed Postgres instance (e.g. Render's
> free Postgres, Neon, Supabase) instead of the default SQLite file.

### Deliverable URLs (fill in after deploying)
- Live frontend URL: `<TODO>`
- Live backend API base URL: `<TODO>` (same as frontend URL, per §1)
- Swagger/OpenAPI URL: `<TODO>/docs`
- Public GitHub repository: `<TODO>`

## 7. OCR / Extraction Approach

- **Native PDFs** (financial statements exported digitally): text and
  tables extracted directly with `pdfplumber` — fast and OCR-error-free.
- **Scanned PDFs / JPG / PNG**: rasterized at 300 DPI (`pdf2image` /
  Poppler) and OCR'd with **Tesseract** (open-source, free, local — no
  paid OCR API or quota limits during the assessment window). *(Confirmed
  necessary: the sample Balance Sheet / P&L / Cash Flow PDFs provided have
  no extractable text layer — they are scanned images.)*
- **Field/table extraction**: the page-tagged OCR/parsed text is sent to
  **Google Gemini** (default; **Anthropic Claude** supported as a drop-in
  alternative via `LLM_PROVIDER`) with a document-type-specific system prompt that
  lists the minimum required fields and instructs the model to (a) never
  invent values — return `null` if not present, (b) return plain numeric
  JSON values (parentheses parsed as negative), and (c) attach a page
  number + short verbatim evidence snippet to every field.
- **Offline fallback**: if no API key is configured for the selected provider, or the LLM call
  fails, a lightweight regex/label-matching extractor runs instead so the
  service degrades gracefully rather than returning a 5xx. This is a
  best-effort safety net, not the primary extraction strategy.
- **Confidence scoring**: intentionally **not implemented** (explicitly
  optional per spec) to avoid returning "arbitrary LLM-generated values"
  that the spec warns against; evidence (source text + page number) is
  provided instead, which the spec treats as the primary grounding
  mechanism.

## 8. Financial Validation Rules & Tolerance

Implemented in `backend/app/services/financial_validation_service.py`.
Every check returns `{name, formula, operands, calculated_value,
reported_value, variance, status}`, where `status` is `PASS`, `FAIL`, or
`NOT_APPLICABLE` (used whenever a required operand or the reported value
itself is missing — never assumed/invented).

| Document | Checks |
|---|---|
| Invoice | `subtotal + tax_amount − discount ≈ total_amount`; `cash_paid − total_amount ≈ change_returned` (only if both fields are present) |
| Balance Sheet | `total_liabilities + total_equity ≈ total_assets` |
| Profit & Loss | `revenue − cost_of_sales ≈ gross_profit`; `gross_profit − operating_expenses ≈ operating_profit`; `operating_profit − tax ≈ net_profit` |
| Cash Flow Statement | `operating_cf + investing_cf + financing_cf ≈ net_change_in_cash`; `opening_cash + net_change_in_cash ≈ closing_cash` |

**Tolerance:** a check passes if `abs(calculated − reported) ≤
max(VALIDATION_ABS_TOLERANCE, abs(reported) × VALIDATION_REL_TOLERANCE_PERCENT / 100)`
— defaults to `max(1.0, 1%)`, configurable via env vars.

## 9. Assumptions Made (spec was ambiguous in places)

1. **Single deployment for frontend + API.** The spec asks for both a
   "Live deployed frontend URL" and "Live backend API URL" as separate
   checklist items but also explicitly permits building the frontend with
   the same Python framework as the API. I serve both from one FastAPI
   app/deployment for simplicity and reliability within the time budget;
   both deliverable URLs are simply the same base URL.
2. **Validation scope = current/most-recent period.** Section 4.4 asks for
   period-by-period validation on comparative statements. Given the 1-day
   time budget, the top-level required fields (and therefore the PASS/FAIL
   checks) are extracted for the **current/most-recent reporting period**
   only. Prior-period figures are still captured for every line item in
   `extracted_data.statement_items` (`comparative_period_value`) for
   transparency, but are not independently re-validated. Documented here
   as a known limitation (§11) rather than silently skipped.
3. **Section 4.4's P&L formulas vs. Section 2's minimum P&L fields
   disagree.** Section 2 lists generic minimum fields (`revenue`,
   `cost_of_sales`, `gross_profit`, `operating_expenses`,
   `operating_profit`, `tax`, `net_profit`), while section 4.4's P&L
   validation formulas use bank/NBFC-specific terminology ("Interest
   Earned", "Provisions & Contingencies", "Minority Interest", "Brought
   Forward Profit") that doesn't map onto section 2's fields. I implemented
   validations against the **section 2 minimum field set** (the fields the
   API is actually required to return), and captured the additional
   bank-style line items only inside `statement_items` where present,
   without inventing formulas for fields the API isn't required to
   produce.
4. **`document_type` is supplied by the caller**, per spec ("Automated
   document schema-selection logic are NOT required") — no classifier is
   implemented.
5. **`GET /documents/{document_name}` matches on the sanitized original
   filename** (path separators and unsafe characters stripped); the same
   sanitization is applied consistently on both upload and lookup so
   round-tripping is reliable.
6. **Re-processing the same file name overwrites/updates the existing DB
   row** ("latest result" semantics) rather than storing full version
   history, per spec: "retaining prior versions is optional."
7. **Uploaded files are deleted from disk after processing** (only the
   extracted structured result is retained) to conserve free-tier disk
   space; this is called out in §11 as something to reconsider for audit
   requirements in production.

## 10. Example API Usage

### Health check
```bash
curl https://<your-deployed-url>/api/v1/health
```

### Process a document
```bash
curl -X POST https://<your-deployed-url>/api/v1/documents/process \
  -F "file=@sample_invoice.pdf" \
  -F "document_type=invoice"
```

### Get the latest result by document name
```bash
curl https://<your-deployed-url>/api/v1/documents/sample_invoice.pdf
```

### List processed documents (dashboard data source)
```bash
curl https://<your-deployed-url>/api/v1/documents
```

See `sample_outputs/*.json` for full example responses covering all 4
document types, a scanned/OCR'd invoice, a financial-validation FAILURE
case, and an unsupported-file-type error case.

## 11. Known Limitations & What I'd Change for Production

- **Comparative-period validation** is not independently checked (see
  Assumption 2) — would add per-period validation in production.
- **OCR accuracy** on low-quality/skewed scans is bounded by Tesseract;
  a production system would likely use a paid Document AI service (Google
  Document AI, Azure Document Intelligence) for higher accuracy at scale.
- **Synchronous processing** is fine for ≤3-page documents per the spec,
  but a production system should move to an async job queue (Celery/RQ +
  webhook or polling) for larger volumes or slower OCR.
- **No authentication/authorization** — would add API-key or OAuth-based
  auth, per-tenant data isolation, and rate limiting for production.
- **SQLite on free-tier hosts** is not durable across redeploys — would
  use a managed Postgres instance in production (already supported via
  `DATABASE_URL` with no code changes).
- **Raw uploads are deleted after processing** — production would likely
  retain them (e.g., in object storage) for audit/reprocessing, gated by a
  data-retention policy.
- **Confidence scoring** is not implemented — a calibrated, explainable
  confidence mechanism (e.g., derived from OCR quality + evidence-match
  strength rather than a raw LLM-reported number) would be a good
  production addition.

## 12. AI Tool Usage Declaration

Claude (Anthropic) was used as a coding assistant to design and implement
the backend services, frontend, tests, documentation and presentation in
this repository. At runtime, the deployed extraction engine is **Google
Gemini** (`gemini-2.0-flash`, free API tier) by default — selected for
zero-cost access during the assessment window — with Anthropic Claude
supported as an interchangeable alternative via `LLM_PROVIDER=anthropic`.
This is a disclosed, load-bearing part of the architecture (§7), not merely a
development aid. All code was reviewed for correctness and is understood
well enough to explain, modify, and debug during the technical discussion.
