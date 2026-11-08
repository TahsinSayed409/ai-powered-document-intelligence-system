# AI-Powered Document Intelligence System

A local-first document processing application for extracting, validating, searching, correcting, and comparing invoice information. It combines a FastAPI backend and a React dashboard with local Ollama inference, Tesseract OCR, and CPU Sentence Transformers embeddings. The application stores files on disk and structured records in SQLite by default; PostgreSQL is also supported by the configured SQLAlchemy driver.

> **Deployment warning:** The application has no authentication or authorization. Keep it on a trusted local machine/network. Do not expose it to untrusted networks.

## Contents

- [Project overview](#project-overview)
- [Features and support boundaries](#features)
- [Supported file formats](#supported-file-formats)
- [Technology stack](#technology-stack)
- [Architecture and processing flow](#architecture-and-processing-flow)
- [AI extraction and evidence](#ai-extraction-and-source-evidence)
- [Validation and review](#validation-and-manual-review)
- [Database design](#database-design)
- [REST API](#rest-api)
- [Frontend guide](#frontend-guide)
- [Windows installation](#windows-installation)
- [Configuration reference](#configuration-reference)
- [Run the application](#run-the-application)
- [Testing and evaluation](#testing-and-evaluation)
- [Security and limitations](#security-and-limitations)
- [Troubleshooting](#troubleshooting)
- [Project structure](#project-structure)
- [Future improvements](#future-improvements)

## Project overview

Organizations receive invoices as digital PDFs, scans, images, and spreadsheets. Manual entry of invoice identifiers and amounts is slow and can introduce transcription and arithmetic errors. This application automates the first-pass extraction and reconciliation work: it reads supported files, extracts invoice fields and line items, checks source evidence and financial consistency, and makes processed documents searchable and comparable.

The intended users are local reviewers and evaluators who need to upload invoices, monitor processing, inspect extracted values and source evidence, resolve validation findings, and compare a PDF invoice with another PDF or an Excel invoice. The system is a review aid; its output is not guaranteed to be correct and should not replace human review where the document is incomplete or ambiguous.

The original assignment is [Ai Engineer Task 1.3.pdf](./Ai%20Engineer%20Task%201.3.pdf). The implementation and evidence-backed testing status are described in [reports/testing_report.md](./reports/testing_report.md), [reports/evaluation_report.md](./reports/evaluation_report.md), and [reports/phase7_acceptance_report.md](./reports/phase7_acceptance_report.md). The [reports index](./reports/README.md) distinguishes current Phase 7 evidence from historical reports.

| Assignment task | Documentation / implementation entry point |
|---|---|
| Document processing and supported formats | [Supported file formats](#supported-file-formats), [architecture](#architecture-and-processing-flow) |
| Invoice extraction and source evidence | [AI extraction and evidence](#ai-extraction-and-source-evidence), [prompt details](./docs/ai_prompts.md) |
| Validation and review | [Validation and manual review](#validation-and-manual-review) |
| Backend REST API | [REST API](#rest-api) |
| Database and search | [Database design](#database-design), [search API](#rest-api) |
| Frontend | [Frontend guide](#frontend-guide) |
| Automated testing and evaluation | [Testing report](./reports/testing_report.md), [evaluation report](./reports/evaluation_report.md) |

## Features

Implemented behavior:

- Multiple-file uploads with per-file acceptance or rejection.
- Digital PDF text extraction and page-aware processing; scanned/sparse PDF pages can be rasterized and OCR'd.
- OCR for JPG/JPEG, PNG, and multipage TIFF frames.
- CSV, XLSX, and legacy XLS reading, including multiple workbook sheets.
- Structured invoice extraction for invoice number/date, supplier/customer, subtotal, tax, total, currency, and line items.
- Deterministic table/header mapping for structured spreadsheet rows and recognized PDF table rows.
- Strict JSON-schema validation, missing/uncertain states, source-evidence checks, and page/sheet provenance where a unique source can be identified.
- Financial consistency checks and heuristic duplicate/possible-duplicate review flags.
- Database-backed background jobs, status and history endpoints, up to three processing attempts per job, and reprocessing of failed documents.
- Keyword search over invoice metadata and indexed source text; semantic search over local text embeddings.
- Manual correction of supported invoice header fields with a stored correction record and validation refresh.
- PDF/PDF and PDF/XLSX comparison through the dashboard. The API accepts two processed documents and compares their extracted data.
- Local-only Ollama extraction and local CPU embeddings; no paid AI provider, Redis, or vector database.

Limits to keep in mind:

- A successful parse/extraction can still result in `requires_review`; this is not a confirmed invoice.
- The dashboard supports the PDF/PDF and PDF/XLSX comparison workflow. Comparison is data-based and does not visually align or compare the original page images.
- Manual corrections apply to invoice header fields; there is no line-item editing workflow or correction-history panel. Field evidence/assessment describes the original extraction; a correction does not create new source evidence.
- Semantic search ranks nearest documents without a minimum-relevance cutoff.
- The acceptance/evaluation corpus is synthetic, not a representative real-world invoice dataset.

## Supported file formats

| Format | Processing method | Important notes |
|---|---|---|
| PDF | PyMuPDF extracts text page by page and detects candidate table rows. | Multipage PDFs retain page-level text. A page containing images and fewer than 10 native text words is rasterized and sent to OCR. |
| JPG/JPEG | Pillow decodes/orients the image; Tesseract extracts text. | One image is processed as one source page. |
| PNG | Pillow decodes the image; Tesseract extracts text. | OCR quality depends on scan/image quality. |
| TIFF | Pillow iterates the TIFF frames; each frame is OCR'd. | Multipage TIFF frames are processed as separate source pages. |
| XLSX | pandas reads every worksheet with openpyxl. | Rows are parsed as structured tables; evidence retains source-row text and a uniquely identified sheet, but there is no dedicated row-number column. |
| XLS | pandas reads every worksheet with xlrd. | Legacy Excel support depends on xlrd and the source workbook being readable. |
| CSV | pandas reads rows as text. | UTF-8 with BOM is supported; undecodable bytes are replaced. The source is represented as a single `csv` sheet. |

The upload layer checks the filename extension against `ALLOWED_EXTENSIONS`, rejects empty files, and enforces a size limit. It does not validate file contents by MIME sniffing or antivirus scanning. Parser errors (including corrupt files) are recorded as processing failures and retried according to the job policy.

## Technology stack

| Technology | Use in this project | Component / notes |
|---|---|---|
| Python 3.14.0 | Backend runtime used for the recorded validation. | `backend/`; package bounds are in [backend/requirements.txt](./backend/requirements.txt). No explicit `Requires-Python` minimum is declared. |
| FastAPI + Uvicorn | HTTP API, request validation, CORS, and local API server. | `backend/app/main.py`; API prefix defaults to `/api`. |
| Pydantic / pydantic-settings | Strict extraction/request schemas and environment configuration. | `backend/app/schemas.py`, `backend/app/config.py`. |
| SQLAlchemy | Database access and SQL-backed queue. | SQLite default; PostgreSQL driver is included. |
| SQLite | Default local relational database. | Default URL is `sqlite:///./document_intelligence.db`, relative to the backend process working directory. |
| PostgreSQL 16 | Supported alternate relational database. | `psycopg[binary]` and `docker-compose.yml` are provided; Phase 7 acceptance used SQLite, not PostgreSQL. |
| Ollama + Qwen 2.5 3B | Local structured invoice extraction. | HTTP request to Ollama `/api/chat`, default model `qwen2.5:3b`; CPU inference. |
| Sentence Transformers | Local semantic-search embeddings. | `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions by default, CPU; vectors are JSON in SQL, not a vector database. |
| Tesseract OCR + pytesseract | OCR for images and qualifying scanned PDF pages. | Local executable and language data; the acceptance host used Tesseract 5.5.3 with English. |
| PyMuPDF (`pymupdf`) | PDF page text, image inspection, rasterization, and table detection. | Runs in the document processing service. |
| Pillow | Image decoding, EXIF orientation, preprocessing, and TIFF frame iteration. | Used before Tesseract. |
| pandas, openpyxl, xlrd | CSV and workbook parsing. | Reads CSV, XLSX, and XLS; workbook sheets are processed independently. |
| React 19, TypeScript 5.9, Vite 7 | Dashboard user interface and build tooling. | `frontend/`; Vite's installed major requires Node.js 20.19+ or 22.12+. |
| pytest | Backend unit and integration test runner. | Tests include mocked provider/API cases and isolated SQLite integrations. |

Redis, MongoDB, a vector database, external/cloud AI services, and paid APIs are **not** part of the current application.

## Architecture and processing flow

The editable Mermaid sources and PNG exports are in [`docs/`](./docs/):

- [Architecture diagram (Mermaid)](./docs/architecture_diagram.mmd) · [PNG](./docs/architecture_diagram.png)
- [Database schema (Mermaid)](./docs/database_schema.mmd) · [PNG](./docs/database_schema.png)

The architecture is deliberately local-first:

1. **Upload (synchronous API request):** The dashboard sends one or more files as multipart data. FastAPI checks file count, extension, size, and non-empty content, sanitizes the display filename, writes each accepted file into `UPLOAD_DIR` under a generated storage name, and creates a `documents` row plus a queued `processing_jobs` row. Per-file failures are returned alongside successful uploads.
2. **Queue (database-backed):** The independent worker polls `processing_jobs`. It claims queued work by updating its status and attempt count in SQL. There is no separate broker. Stale running jobs can be recovered after one hour.
3. **Parse (background):** The worker uses separate parsers: PyMuPDF extracts PDF text and tables by page and only sparse image-containing PDF pages are rendered for Tesseract; Pillow decodes images and iterates TIFF frames for OCR; pandas and workbook engines read CSV/XLS/XLSX tables and sheets. All paths retain page or sheet provenance when available.
4. **Normalize and extract (background):** Structured tables are analyzed for header rows, metadata, and line items. Sufficiently complete spreadsheets can use deterministic mapping without an LLM call. Other sources use locally hosted Ollama structured extraction; detected table line items are preserved alongside model-extracted invoice fields.
5. **Ground and validate (background):** Pydantic validates the extraction shape. Evidence quotes are checked against source text using conservative normalization; unique matching page/sheet text can be attached as provenance. Financial rules and duplicate heuristics produce validation issues and a `VALID`, `WARNING`, `INVALID`, or `REQUIRES_REVIEW` result.
6. **Index and persist (background):** Source text is chunked and embedded locally. The worker stores invoice JSON, normalized line items, validation issues, search chunks/vectors, document status, and job completion in SQL. Files remain in the configured upload directory.
7. **Review and search (API requests):** The dashboard polls status and requests result/detail data. Keyword search reads metadata and indexed text. Semantic search embeds the query and ranks stored chunks by cosine similarity. Corrections update the selected invoice field, record a `manual_corrections` row, and rerun validation.
8. **Compare (synchronous API request):** The comparison endpoint compares extracted invoice fields and line items and stores a `comparison_results` row. The UI offers PDF/PDF and PDF/XLSX pair selection.

`progress` is persisted as a job field, but the worker currently reports it as 0 while processing and 100 at completion; there is no granular stage-by-stage progress percentage. Processing can take tens of seconds for model-backed documents, so upload acceptance and extraction completion are separate events.
Automated tests include a generated 1,000-page PDF parsing/iteration case; it does not send every page through OCR, Ollama, or embeddings and is not an end-to-end time/memory benchmark for a large scanned document.

The API creates tables using SQLAlchemy `create_all`; no versioned schema-migration workflow is included. See [docs/architecture_diagram.mmd](./docs/architecture_diagram.mmd) for the component/data flow and [docs/database_schema.mmd](./docs/database_schema.mmd) for the tables and foreign keys.

## AI extraction and source evidence

The default model is local Ollama `qwen2.5:3b`, called through `OLLAMA_BASE_URL` at `/api/chat`. The request uses the Pydantic `InvoiceExtraction` JSON Schema as Ollama's structured-output format, CPU inference, deterministic temperature/seed settings, a configured context length, and bounded connection/timeout/server-error retries.

The requested invoice fields are:

- Invoice number and date.
- Supplier and customer.
- Subtotal, tax, total, and currency.
- Line items with description, quantity, unit price, tax, and line total.

The extraction schema requires one assessment per top-level field: `found`, `missing`, or `uncertain`, along with model-reported confidence and a source quote. Missing or ambiguous data should remain null; subtotal is not calculated from line items. Structured spreadsheet fields can be mapped without the model when recognized headers and enough labeled metadata are present. For longer text, extraction is split into overlapping chunks and merged; conflicting values remain uncertain.

Evidence is verified against the extracted source before a field is treated as supported. Safe Unicode, whitespace, and selected OCR normalization are used; date evidence is normalized only when the source supports an unambiguous date. Monetary fields additionally require an appropriate label, so a line-item “Line Total” alone does not establish the invoice total. Unsupported quotes are cleared; unsupported values are nulled and routed to uncertainty/review rather than receiving invented replacement evidence. Page or sheet metadata is attached only when exactly one source text matches. Evidence verification confirms correspondence to extracted text, not the truth or visual correctness of that text.

Confidence is model-reported and is not a calibrated probability or evidence-verification score. A rejected quote does not itself increase confidence or confirm a value. The exact prompt and extraction behavior are documented in [docs/ai_prompts.md](./docs/ai_prompts.md); implementation lives in [backend/app/services/ai_extractor.py](./backend/app/services/ai_extractor.py).

## Validation and manual review

The deterministic validator currently checks:

- Required invoice fields: invoice number/date, supplier/customer, subtotal, tax, and total. Currency is extracted but is not in the required-field list.
- Quantity × unit price versus line total when all values are present. Differences outside the configured absolute/relative tolerance create an error and an invalid result.
- Sum of complete line totals versus subtotal. Mismatches create a warning, allowing review of rounding, discounts, or other adjustments.
- Total versus subtotal plus tax (tax defaults to zero for this check when absent). A mismatch is a warning, not automatic rejection, because invoices can have rounding or other charges.
- Negative quantities and unusually short supplier names.
- Duplicate candidates are prefiltered by matching invoice number, matching supplier/date, or matching supplier and total within 0.02. The score then checks matching invoice number, supplier, date, and amount; a score of at least 3 is `duplicate`, 2 is `possible_duplicate`, and lower scores are `distinct`. Duplicate/possible-duplicate matches require manual review.
- Fields marked uncertain or missing, which create review/warning issues.

The validator does not reject a document solely for a missing field or arithmetic warning. A document can successfully finish processing with status `requires_review`; the result is available for human inspection. A `failed` document means a processing stage failed (for example file parsing, OCR, schema/evidence validation, embedding generation, or persistence) after its allowed attempts; this is distinct from extraction that completed but needs review.

## Database design

The SQLAlchemy models are in [backend/app/models.py](./backend/app/models.py). The ER diagram is [docs/database_schema.mmd](./docs/database_schema.mmd).

| Table | Primary key / foreign keys | Purpose and important columns |
|---|---|---|
| `documents` | `id` PK | Original file metadata/path, processing and validation statuses, error, invoice header fields, `extracted_data` JSON, `validation_result` JSON, and a nullable `comparison_result` JSON column. The latter is defined by the model but current comparison requests write to `comparison_results`. |
| `processing_jobs` | `id` PK; `document_id` FK → `documents.id` | Persisted queue and per-job retry/history: job name, status, progress, attempt counter (`retries`), timestamps, and error. Retrying creates a new job row. |
| `invoice_line_items` | `id` PK; `document_id` FK → `documents.id` | Normalized line-item values, evidence, confidence, and ordinal. `(document_id, ordinal)` is unique. |
| `validation_issues` | `id` PK; `document_id` FK → `documents.id` | Persisted warning/error, field, message, and timestamp. |
| `manual_corrections` | `id` PK; `document_id` FK → `documents.id` | Old/new values, corrected field, and timestamp. |
| `search_index` | `id` PK; `document_id` FK → `documents.id` | Text chunks plus nullable JSON embedding vectors. Embeddings include model/dimension metadata in the extracted document JSON. |
| `comparison_results` | `id` PK; `left_document_id` and `right_document_id` FKs → `documents.id` | Persisted comparison response JSON and timestamp. |

Invoice header extraction is stored in the `documents` columns and in `documents.extracted_data` JSON. Field assessments and page/sheet provenance live in that JSON; line-item relational columns do not have page/sheet columns. Source text chunks are stored in `search_index.text`; original file bytes remain on disk. Processing history is represented by multiple `processing_jobs` rows, not a separate history table. Foreign keys are defined, but SQLAlchemy `relationship()` properties and cascading-delete behavior are not configured. `documents.comparison_result` is a nullable legacy JSON column that current code does not read or write; comparison requests persist `comparison_results` rows. The JSON column could duplicate that information if populated, but current comparison requests do not populate it.

SQLite is the default and is suitable for local/single-worker use. PostgreSQL is supported through SQLAlchemy and `psycopg`; a PostgreSQL 16 Compose service is provided, but the recorded acceptance run used SQLite. Startup calls `Base.metadata.create_all`; it creates missing tables but does not migrate changed columns or preserve compatibility for arbitrary schema changes. Back up the DB and files before upgrades.

## REST API

The API prefix defaults to `/api`. The interactive FastAPI documentation is available at `http://127.0.0.1:8000/docs`; the checked-in OpenAPI snapshot is [docs/openapi.json](./docs/openapi.json). The snapshot can be regenerated from `backend/` with `python scripts/export_openapi.py`.

| Method and path | Purpose / inputs | Success response (important fields) | Common errors |
|---|---|---|---|
| `GET /api/health` | Service health. | `{"status":"ok"}` | — |
| `POST /api/documents/upload` | Multipart field `files`, one or more files; max 100 files per request and 250 MB per file by default. | `documents` with IDs/job IDs, `failures` per rejected file, and `partial_success`. | `413` if batch count exceeds 100; `422` for malformed request. Per-file extension/size/empty errors are returned in `failures`. |
| `GET /api/documents?skip=0&limit=20` | Paginated document list; `skip >= 0`, `1 <= limit <= 100`. | `items`, `count` for this page. | `422` for invalid query values. |
| `GET /api/documents/{document_id}` | Document details. | Document metadata/header fields, `extracted_data`, `line_items`, `validation_result`. | `404` if absent. |
| `GET /api/documents/{document_id}/results` | Structured result and issue list. | `document_id`, status, extraction JSON, line items, validation result, `validation_errors`. | `404` if absent. |
| `GET /api/documents/{document_id}/validation-errors` | Current persisted validation issues. | `document_id`, `errors`. | `404` if absent. |
| `GET /api/documents/{document_id}/status` | Latest document/job status. | Document status, validation status, latest job ID/status, attempts, error message. | `404` if absent. |
| `GET /api/documents/{document_id}/history` | Jobs for one document, newest first. | `jobs` with status, progress, attempts, timestamps, and error. | `404` if document absent. |
| `GET /api/jobs?skip=0&limit=100` | Paginated jobs across documents; max limit 500. | `jobs` with document ID, name/status/progress/attempts/timestamps/error. | `422` for invalid query values. |
| `POST /api/documents/{document_id}/reprocess` | Retry a failed document; no request body. Creates a new job row. | Document ID, new `job_id`, queued status. | `404` absent; `409` unless latest document/job is failed. |
| `POST /api/documents/{document_id}/corrections` | JSON `{ "field_name": "customer_name", "value": "Example Clinic" }`; supports invoice header fields only; `value: null` clears. | `status`, field, saved value. | `404` absent; `409` unless extraction is complete; `422` unsupported field/type or non-finite numeric input. |
| `GET /api/search?query=...&mode=keyword` | `query` length 1–500; `mode` is `keyword` or `semantic`. | Query, mode, up to 20 results (raw source text is omitted from response). | `422` invalid query/mode; `503` embedding unavailable or index mismatch for semantic mode. |
| `POST /api/compare` | JSON `{ "left_document_id": 1, "right_document_id": 2 }`; both documents must have extracted data. | File types, field/line-item comparison buckets and status, duplicate classification. Result is persisted. | `404` if either absent; `409` if either lacks completed extraction; `422` invalid body. |

Most endpoint-level missing-record and conflict responses use `404` and `409` respectively. FastAPI request validation returns `422`. Upload-level file failures are intentionally represented per file so successful files in a batch can still be queued.

PowerShell examples:

```powershell
# Upload one or more documents. Repeat -F files=... for additional files.
curl.exe -X POST "http://127.0.0.1:8000/api/documents/upload" `
  -F "files=@E:\Invoices\invoice.pdf" `
  -F "files=@E:\Invoices\invoice.xlsx"

# Poll one document's processing status and retrieve the result.
curl.exe "http://127.0.0.1:8000/api/documents/1/status"
curl.exe "http://127.0.0.1:8000/api/documents/1/results"

# Keyword search.
curl.exe --get "http://127.0.0.1:8000/api/search" `
  --data-urlencode "query=Northwind" `
  --data-urlencode "mode=keyword"

# Correct a header field.
curl.exe -X POST "http://127.0.0.1:8000/api/documents/1/corrections" `
  -H "Content-Type: application/json" `
  -d '{"field_name":"customer_name","value":"Example Clinic"}'

# Compare two processed document IDs.
curl.exe -X POST "http://127.0.0.1:8000/api/compare" `
  -H "Content-Type: application/json" `
  -d '{"left_document_id":1,"right_document_id":2}'
```

## Frontend guide

The React dashboard is a single-page application. It contains:

- Summary cards and a document queue with filename, invoice number, supplier, total, and status.
- Multi-file upload with per-file error reporting.
- A keyword/semantic search mode selector and query field.
- A selected-document detail panel with extracted header fields, line items, evidence/confidence assessments, source-page labels where available, and validation notes.
- A correction form for supported invoice header fields.
- A failed-document-only retry action.
- A comparison panel for processed PDF/PDF and PDF/XLSX pairs, showing match/mismatch/partial result details.

The frontend calls `/api/...` relative paths. Vite's development proxy forwards them to `http://127.0.0.1:8000`; CORS is configured for the local frontend origins. Document and job status are refreshed by the UI. The app does not stream intermediate OCR/LLM stage progress.

## Windows installation

The instructions are clone-location independent. Open PowerShell at the repository root (or first change to your clone's root), then define `$ProjectRoot = (Get-Location).Path` in each terminal. Choose a drive with enough free space for dependencies, the embedding cache, uploads, and database; no particular drive letter is required. Do not overwrite an existing personal `.env`.

### Prerequisites

- Windows PowerShell.
- Python 3.14 is the recorded test runtime; package metadata does not declare a minimum Python version. For a fresh setup, use Python 3.14 and the Windows Python Launcher.
- Node.js compatible with installed Vite 7: **20.19+ or 22.12+**. The system Node 18.20.8 cannot start the Vite development server.
- npm (included with the portable Node distribution).
- Ollama and `qwen2.5:3b` for local AI extraction.
- Tesseract 5.x with English (`eng`) language data for OCR.
- Internet access for missing installers, Python/npm dependencies, and first-use model downloads. Document processing itself uses local services.

Install Python 3.14 from the [official Python for Windows downloads](https://www.python.org/downloads/windows/) if needed, then verify `py -3.14 --version`.

### Use a compatible portable Node.js without replacing system Node

The machine's system Node does not need to be changed. One option is to download the official Node.js 22.15.0 Windows ZIP into the project's ignored `.cache` directory and temporarily prepend it to `PATH`:

```powershell
$ProjectRoot = (Get-Location).Path
$tools = Join-Path $ProjectRoot '.cache\tools'
$downloads = Join-Path $ProjectRoot '.cache\downloads'
New-Item -ItemType Directory -Force $tools, $downloads | Out-Null
$zip = Join-Path $downloads 'node-v22.15.0-win-x64.zip'
Invoke-WebRequest 'https://nodejs.org/dist/v22.15.0/node-v22.15.0-win-x64.zip' -OutFile $zip
Expand-Archive -LiteralPath $zip -DestinationPath $tools -Force
$nodeHome = Join-Path $tools 'node-v22.15.0-win-x64'
$env:PATH = "$nodeHome;$env:PATH"
node --version
npm --version
```

Expected Node output is `v22.15.0`. This is a portable runtime under the project cache, not a system-wide installation. If a compatible runtime is already available, use it instead. Keep `$env:PATH` changes scoped to the terminal used for frontend commands.

### Install and verify Ollama and Tesseract

Install Ollama from the [official Windows download](https://ollama.com/download/windows) if it is not already installed. Check whether the required model is present before downloading it:

```powershell
ollama list
# Only if qwen2.5:3b is missing:
ollama pull qwen2.5:3b
```

Run `ollama pull qwen2.5:3b` only when `ollama list` does not already show the model. Ollama model storage is managed by the Ollama service; the application does not move or redownload existing model files. If you choose a custom Ollama model directory, configure `OLLAMA_MODELS` for the Ollama service before starting it, and do not point it at a new empty directory if you intend to reuse an existing model store.

Install a trusted Windows Tesseract 5.x distribution with English language data; see the [Tesseract installation guide](https://tesseract-ocr.github.io/tessdoc/Installation.html). Tesseract is not installed by `pip`. The checked-in `.env.example` contains a placeholder path that must be replaced with the actual absolute `tesseract.exe` path on each machine. Verify the executable and language data using that path:

```powershell
$tesseract = Read-Host 'Enter the full path to tesseract.exe'
& $tesseract --version
& $tesseract --list-langs
```

Confirm `eng` is listed, then set the same executable path in `.env`.

### Configure the Python backend

From the project root:

```powershell
$ProjectRoot = (Get-Location).Path
if (-not (Test-Path '.env')) { Copy-Item '.env.example' '.env' }
notepad .env

$env:PIP_CACHE_DIR = Join-Path $ProjectRoot '.cache\pip'
Set-Location (Join-Path $ProjectRoot 'backend')
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Replace the placeholder `TESSERACT_PATH` in `.env` with the actual absolute executable path before processing. The settings module reads `.env` from the repository root. SQLite tables are created automatically when the API starts (`Base.metadata.create_all`); no separate migration or database initialization command is provided. The default SQLite file and `UPLOAD_DIR=uploads` are relative to the backend working directory, so run both API and worker from `backend\` using the same `.env` and database URL.

Sentence Transformers downloads `sentence-transformers/all-MiniLM-L6-v2` on first embedding use and caches it under `MODEL_CACHE_DIR` (default: `<repository-root>\.cache\models`). If using a different drive, set `MODEL_CACHE_DIR` in `.env` to that machine's absolute cache directory. This cache is separate from Ollama model storage.

### Install frontend dependencies

Open PowerShell at the repository root, define `$ProjectRoot`, and make the compatible Node runtime available in that terminal's `PATH` if using the portable option above:

```powershell
$ProjectRoot = (Get-Location).Path
$nodeHome = Join-Path $ProjectRoot '.cache\tools\node-v22.15.0-win-x64'
$env:PATH = "$nodeHome;$env:PATH"
$env:npm_config_cache = Join-Path $ProjectRoot '.cache\npm'
Set-Location (Join-Path $ProjectRoot 'frontend')
npm ci
```

`npm ci` uses the committed lock file and installs under `frontend\node_modules`.

### Optional PostgreSQL

SQLite is the default and requires no separate service. PostgreSQL 16 and Docker Compose are optional alternatives, not prerequisites. To try the Compose service, set a private `POSTGRES_PASSWORD` in the root `.env`, then set `DATABASE_URL` to the matching `postgresql+psycopg://...` URL. PostgreSQL was not live-tested in Phase 7.

```powershell
docker compose up -d postgres
```

The Compose file publishes port 5432 and uses a persistent Docker volume. Its development fallback credentials are not appropriate for a networked or production deployment.

## Configuration reference

The backend settings are declared in [backend/app/config.py](./backend/app/config.py), loaded from the project-root `.env`, and overridable with environment variables. Paths such as `UPLOAD_DIR` are interpreted relative to the process working directory unless absolute.

| Variable | Purpose | Default | Required / used by |
|---|---|---|---|
| `APP_NAME` | FastAPI application title. | `AI-Powered Document Intelligence System` | Optional; API. |
| `DEBUG` | Boolean setting declared in configuration. | `false` | Optional; currently not used to change runtime behavior. |
| `DATABASE_URL` | SQLAlchemy connection string. | `sqlite:///./document_intelligence.db` | Optional; API and worker. |
| `SECRET_KEY` | Legacy/development setting. | `dev-secret-key-change-me` | Optional; currently unused; the app has no authentication/session signing. |
| `API_PREFIX` | API route prefix. | `/api` | Optional; backend API. |
| `UPLOAD_DIR` | Original-file storage directory. | `uploads` | Optional; API and worker. |
| `MAX_UPLOAD_SIZE_MB` | Maximum size per uploaded file. | `250` | Optional; upload API. |
| `FRONTEND_URL` | Additional CORS-allowed frontend origin. | `http://localhost:5173` | Optional; API CORS. `http://127.0.0.1:5173` is also allowed. |
| `AI_PROVIDER` | Extraction provider. | `ollama` | Optional; only `ollama` is accepted. |
| `OLLAMA_BASE_URL` | Local Ollama HTTP service base URL. | `http://localhost:11434` | Optional; extraction worker. |
| `OLLAMA_MODEL` | Installed model tag. | `qwen2.5:3b` | Optional; extraction worker. |
| `OLLAMA_CONTEXT_LENGTH` | Model context size. | `4096` | Optional; extraction worker. Minimum 512. |
| `OLLAMA_TIMEOUT_SECONDS` | HTTP timeout per model request. | `180` | Optional; extraction worker. |
| `OLLAMA_MAX_PARALLEL_REQUESTS` | Local request concurrency limit. | `1` | Optional; extraction worker. |
| `OLLAMA_RETRIES` | Additional transport/server retries. | `2` | Optional; extraction worker. Range 0–5; job attempts are separately limited to 3. |
| `OLLAMA_KEEP_ALIVE` | Ollama model keep-alive value. | `10m` | Optional; extraction worker. |
| `EMBEDDING_MODEL_NAME` | Sentence Transformers model ID. | `sentence-transformers/all-MiniLM-L6-v2` | Optional; worker and semantic search. |
| `EMBEDDING_DIMENSION` | Expected vector dimension. | `384` | Optional; worker/search. |
| `MODEL_CACHE_DIR` | Local Transformer model cache. | `<project-root>\.cache\models` | Optional; embedding service. |
| `TESSERACT_PATH` | Tesseract executable. | Original evaluation-host fallback: `E:\Tesseract-OCR\tesseract.exe`; not portable. | Set the actual absolute `tesseract.exe` path in `.env` on a fresh machine; required for OCR. |
| `TESSERACT_LANGUAGE` | Tesseract language code. | `eng` | Optional; OCR service. |
| `OCR_TIMEOUT_SECONDS` | OCR timeout per image/page. | `120` | Optional; OCR service. |
| `ALLOWED_EXTENSIONS` | Comma-separated or JSON list of extensions. | `pdf,png,jpg,jpeg,tif,tiff,xlsx,xls,csv` | Optional; upload API. |

The example `.env.example` also contains `APP_ENV` and `BACKEND_URL`, which are not consumed by backend settings (the Vite proxy target is currently configured in `frontend/vite.config.ts`). `POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` are consumed by `docker-compose.yml`, not by FastAPI settings. Do not put real credentials in documentation or commit a personal `.env`.

## Run the application

Run each service in its own PowerShell terminal. Use the same `.env` and database URL for the API and worker.

### Terminal 1 — Ollama

Ollama may already be running in the Windows background. If not:

```powershell
ollama serve
```

Verify `http://localhost:11434/api/tags` responds and contains the configured model.

Each terminal command below assumes PowerShell starts at the repository root; define `$ProjectRoot` there before changing directories. In the frontend terminal, also make the compatible Node runtime available in `PATH`.

### Terminal 2 — FastAPI backend

```powershell
$ProjectRoot = (Get-Location).Path
Set-Location (Join-Path $ProjectRoot 'backend')
$env:PYTHONPATH = '.'
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Check `http://127.0.0.1:8000/api/health` for `{"status":"ok"}`. Interactive API docs are at `http://127.0.0.1:8000/docs`.

### Terminal 3 — background worker

```powershell
$ProjectRoot = (Get-Location).Path
Set-Location (Join-Path $ProjectRoot 'backend')
$env:PYTHONPATH = '.'
.\.venv\Scripts\python.exe -m app.worker
```

Without a running worker, uploads are accepted and remain queued. The worker retries processing up to three attempts for a given job. Reprocessing an exhausted failed document creates another job row.

### Terminal 4 — frontend development server

Use the compatible portable Node terminal:

```powershell
$ProjectRoot = (Get-Location).Path
$nodeHome = Join-Path $ProjectRoot '.cache\tools\node-v22.15.0-win-x64'
$env:PATH = "$nodeHome;$env:PATH"
Set-Location (Join-Path $ProjectRoot 'frontend')
npm run dev -- --host 127.0.0.1 --port 5173
```

Open `http://127.0.0.1:5173`. The Vite development server does not run with the system Node 18.20.8; use Node 20.19+ or 22.12+.

### Production build and preview

With compatible Node in `PATH`:

```powershell
$ProjectRoot = (Get-Location).Path
Set-Location (Join-Path $ProjectRoot 'frontend')
npm run lint
npm run build
npm run preview -- --host 127.0.0.1 --port 5173
```

Production preview serves the generated `dist` build and was used for the Phase 7 browser acceptance workflow. The preview route does not make the unsupported Node 18 development server compatible.

## Testing and evaluation

From a PowerShell terminal opened at the repository root:

```powershell
$ProjectRoot = (Get-Location).Path
Set-Location (Join-Path $ProjectRoot 'backend')
.\.venv\Scripts\python.exe -m pytest -q
```

From a PowerShell terminal opened at the repository root, using compatible Node:

```powershell
npm run lint
npm run build
```

The evaluator calls the configured local Ollama pipeline with the three labeled synthetic cases:

```powershell
$ProjectRoot = (Get-Location).Path
Set-Location (Join-Path $ProjectRoot 'backend')
$env:PYTHONPATH = '.'
.\.venv\Scripts\python.exe tests\evaluate.py
```

It writes `backend\reports\evaluation_summary.json`; preserve or copy its output before rerunning if you need to keep an earlier run.

The live six-format harness is `backend\scripts\run_acceptance_tests.py`. It invokes real local OCR/Ollama/embeddings and writes acceptance results. **It regenerates fixture files in `backend\tests\fixtures\acceptance_documents`; run only when it is safe to replace those generated fixtures.** Its normal report path is under `reports`; use an isolated copy or a redirected report directory when preserving historical results. It is not a unit test and takes several minutes on CPU.

The current verified evidence is summarized in:

- [reports/testing_report.md](./reports/testing_report.md) — automated test categories, test run, browser workflow, and caveats.
- [reports/evaluation_report.md](./reports/evaluation_report.md) — synthetic labeled evaluation and six-format performance results.
- [reports/phase7_acceptance_report.md](./reports/phase7_acceptance_report.md) — browser and live-acceptance details.
- [reports/phase6_1_provenance_audit.md](./reports/phase6_1_provenance_audit.md) — source evidence regression audit.

Mocked OCR or LLM unit tests verify code paths and error handling; they are not evidence of live service operation. Live host measurements are identified separately in the reports.

## Evaluation and performance

Phase 7 ran two distinct evaluations; their denominators must not be combined:

1. **Live six-format processing acceptance:** Six synthetic PDF, scanned PDF, PNG, XLSX, CSV, and JPG inputs were run through the local pipeline with an isolated SQLite database and upload directory. **6/6 documents passed the harness and 12/12 expected line items persisted.** The scanned PDF correctly completed as `requires_review`.
2. **Labeled extraction evaluation:** Three synthetic invoice texts were sent through the configured local Ollama extraction path. **27/27 comparison units** matched: 24 scalar-field comparisons (8 fields × 3 documents) plus 3 ordered, all-or-nothing line-item-list comparisons. All 3 invoices matched all evaluated fields. OCR is excluded. This does not measure customer-document or real-world accuracy.

Measured Phase 7 mean total processing time was 40.706 seconds/document, versus 55.583 seconds/document in Phase 6 (approximately 26.8% lower in these non-controlled synthetic runs). Phase 7 mean LLM duration was 57.869 seconds across four model-backed acceptance documents; mean OCR was 0.365 seconds per OCR document; mean embeddings were 1.800 seconds/document; sampled peak Python-plus-child RSS was approximately 750.9 MiB. The separate labeled evaluator averaged 54.047966 seconds/document. These figures are specific to the host, local model, and small synthetic run; they are not throughput or scalability guarantees.

See [reports/evaluation_report.md](./reports/evaluation_report.md) for per-document Phase 6/7 measurements and the exact evaluator methodology.

## Security and limitations

- The application has **no authentication/authorization**. Bind to loopback for local use and do not expose the API/UI to untrusted networks.
- Upload checks extension, safe display filename, per-file byte limit, batch count, and empty content. It does not inspect file magic/MIME or run antivirus scanning.
- Original documents are stored locally; indexed source text and vectors are persisted in the configured database. Ollama inference is local. Initial package/model downloads may contact their respective repositories.
- Processing diagnostics are stage-specific and avoid storing source text in failure messages. The API returns extracted data/evidence to users of the unauthenticated service; protect the local machine/database accordingly.
- Model confidence is not calibrated; OCR errors and unusual invoice layouts can produce missing or incorrect values. Evidence matching anchors a quote to extracted text, not the image's ground truth.
- Search vectors are JSON and scanned in process; there is no vector index or large-corpus benchmark. Semantic results have no relevance threshold.
- SQLite is intended for local/single-worker use. PostgreSQL is configured but was not part of the Phase 7 acceptance run. No schema migration tool is provided.
- Large PDFs can be slow because extraction, OCR, model calls, and embedding work run on local CPU. The model context and overlapping text chunks may still require review for unusually large or complex documents.
- No production-scale load, multi-user access-control, customer-data accuracy, or disaster-recovery test has been completed.
- Browser acceptance did not capture screenshots. A recorded walkthrough is also not included.

## Troubleshooting

| Symptom | Checks and action |
|---|---|
| Backend fails during import/startup | Activate/use `backend\.venv`; run `pip install -r requirements.txt`; start from `backend\` with `PYTHONPATH=.`; verify `.env` syntax and `DATABASE_URL`. |
| Frontend shows `crypto.hash is not a function` | The system Node 18.20.8 is too old for this Vite version. Use the portable Node 22.15.0 or another version meeting Node 20.19+/22.12+, then restart the terminal/server. |
| Frontend API requests fail | Confirm the API responds at `/api/health` on port 8000. Vite proxies `/api` to `http://127.0.0.1:8000`; check port, proxy configuration, and `FRONTEND_URL` if changing origins. |
| Ollama connection error | Start the local service (`ollama serve` if needed), confirm `/api/tags`, and check `OLLAMA_BASE_URL`. |
| Ollama says model not found | Run `ollama list`; pull `qwen2.5:3b` only if absent, or set `OLLAMA_MODEL` to an installed supported tag. |
| Tesseract not found / language missing | Verify `TESSERACT_PATH` points to `tesseract.exe`; run `--version` and `--list-langs`; set `TESSERACT_LANGUAGE` to an installed language (default `eng`). |
| OCR times out or is poor | Check source image legibility/resolution and `OCR_TIMEOUT_SECONDS`. OCR is sensitive to skew, blur, low contrast, and language configuration. |
| Document stays queued | Start `app.worker` using the same project `.env` and database as the API. Check the latest job through `/api/documents/{id}/status` and `/history`. |
| Document fails after retries | Inspect the sanitized status/history error and validation issue `processing.<stage>`. Correct the source/configuration before using reprocess; each job gets up to three attempts. |
| Upload is rejected | Confirm extension is allowed, file is non-empty, below `MAX_UPLOAD_SIZE_MB`, and the batch has at most 100 files. The parser can reject corrupt files after upload. |
| SQLite data appears missing | Start API and worker from `backend\`; relative `sqlite:///./document_intelligence.db` resolves from the working directory. Confirm both processes use the same `DATABASE_URL`. |
| Semantic search returns unrelated documents | The current implementation returns ranked nearest neighbors without a relevance cutoff. Try keyword search or refine the query. |
| Embedding model download fails | Verify internet access for initial model download, writable `MODEL_CACHE_DIR`, and disk space on the configured drive. This model is separate from the Ollama model store. |

## Project structure

```text
Care Guide Project/
├── README.md
├── .env.example
├── Ai Engineer Task 1.3.pdf
├── docker-compose.yml
├── backend/
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py                 # FastAPI routes
│   │   ├── worker.py               # SQL queue worker
│   │   ├── models.py               # SQLAlchemy tables
│   │   ├── schemas.py              # Pydantic schemas
│   │   └── services/               # Parsing, OCR, extraction, validation, search
│   ├── scripts/                    # Live acceptance, fixture, OpenAPI, reindex tools
│   └── tests/                      # Unit/integration tests and synthetic fixtures
├── frontend/
│   ├── package.json
│   └── src/                        # React/TypeScript dashboard
├── docs/
│   ├── architecture_diagram.mmd
│   ├── architecture_diagram.png
│   ├── database_schema.mmd
│   ├── database_schema.png
│   ├── ai_prompts.md
│   └── openapi.json
└── reports/
    ├── README.md                   # Report index and historical/current distinction
    ├── testing_report.md
    ├── evaluation_report.md
    ├── phase7_acceptance_report.md
    ├── performance_comparison.png
    ├── performance_comparison.svg # Editable performance chart source
    └── phase7_live/                # Phase 7 machine-readable measurements
```

Generated caches, virtual environments, databases, uploads, and build output are intentionally omitted from the tree.

## Future improvements

Potential follow-up work, separate from the current assignment scope:

- Add authentication, authorization, CSRF/CORS hardening, content-signature validation, malware scanning, rate limits, and deployment secrets management before any shared/network deployment.
- Introduce versioned database migrations and tested backup/restore procedures.
- Add representative, permission-cleared real invoices and a larger labeled OCR dataset; evaluate field-level error types and calibration.
- Add a semantic relevance threshold and a scalable vector/index strategy only if corpus size and measured needs justify it.
- Provide line-item correction, audit-history UI, richer source-page previews, and real-time processing-stage progress.
- Run controlled repeated benchmarks and load tests across cold/warm model state, document sizes, and hardware.
- Add PostgreSQL concurrency and deployment integration tests before relying on multi-worker operation.
