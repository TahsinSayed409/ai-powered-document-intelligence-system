# Engineering Compliance Audit

## Executive assessment

The original assignment PDF, [Ai Engineer Task 1.3.pdf](../Ai%20Engineer%20Task%201.3.pdf), and the subsequent compliance override are treated as the source of truth. This audit inspects the current implementation and its tests; it does not treat the earlier baseline report as evidence of current behavior.

The repository has progressed beyond the original baseline: supported document parsers, local Ollama extraction, a persisted database-backed worker queue, validation, comparison, keyword and embedding search, REST endpoints, and a connected frontend are present. The backend suite has **49 passing tests**, including an isolated API/worker integration; the frontend lint and production build both exit successfully.

It is **not yet fully acceptance-ready**. Native Tesseract was smoke-tested on a generated invoice image, and local Ollama/Qwen was evaluated on three synthetic invoice texts; representative real scans and real-world accuracy remain unverified. PostgreSQL operation, production-scale job concurrency, and an actual user walkthrough have also not been demonstrated. A Git repository is not present in the workspace.

This report distinguishes a real implementation from its live operational verification. A mocked test can verify a boundary or workflow, but is not evidence that the external provider or native executable works on this host.

## Audit scope and evidence

The audit covers the seven assignment workstreams and the nine deliverables, including the additional mandatory requirements in the compliance override: all listed formats, multipage PDFs, LLM extraction, asynchronous processing, semantic search, persistence, complete APIs, evaluation, diagrams, and documentation.

Evidence inspected:

- Current backend source, models, worker, processing and extraction services, and frontend source.
- The PDF, image, spreadsheet, AI, validation, search, worker, API, and comparison tests.
- README, AI prompt documentation, architecture and database diagrams, exported OpenAPI JSON, evaluation reports, and prior audit/report claims.
- Test commands run during this audit, recorded below.
- Existing local evaluation output and the test behavior itself.

Status definitions:

- **COMPLETE** — implemented and verified for the stated scope; limitations are explicitly noted.
- **PARTIAL** — some required behavior exists, but an integration, coverage, or operational acceptance gate remains.
- **MISSING** — required implementation or deliverable is absent.
- **MOCKED** — the behavior is represented only by a mock/placeholder, not a real implementation.

## Requirement-by-requirement findings

| Requirement description | Current implementation | Relevant source files | Verification performed | Status | Specific improvements required |
|---|---|---|---|---|---|
| PDF text extraction and large multipage PDFs | PyMuPDF extracts text page by page and records page-level metadata. The test suite creates and processes a 1,000-page digital PDF. This verifies the page loop, not a 1,000-page scanned-PDF or peak-memory/throughput target. | [document_processor.py](../backend/app/services/document_processor.py), [test_document_processing.py](../backend/tests/test_document_processing.py) | Full backend test run passed, including the generated 1,000-page PDF case. No memory or latency benchmark was run. | PARTIAL | Benchmark representative large PDFs (including image-heavy/scanned input), record memory and elapsed time, and add explicit resource limits or streaming improvements if the benchmark requires them. |
| Scanned PDF and image OCR | OCR is implemented with Tesseract, image preprocessing, confidence aggregation, multipage TIFF handling, and sparse/image-only PDF page fallback. The configured host executable is `E:\Tesseract-OCR\tesseract.exe` with English data. | [document_processor.py](../backend/app/services/document_processor.py), [test_document_processing.py](../backend/tests/test_document_processing.py), [.env.example](../.env.example) | Mocked OCR paths pass; native Tesseract was smoke-tested on a generated invoice image. A representative user scan was not available. | PARTIAL | Run OCR on permission-cleared representative scanned invoices and record extraction quality, confidence, and error handling. |
| JPG/JPEG, PNG, TIFF, including multipage TIFF | The image parser accepts JPG/JPEG, PNG, TIF/TIFF and iterates image frames. | [document_processor.py](../backend/app/services/document_processor.py), [test_document_processing.py](../backend/tests/test_document_processing.py) | Format cases pass in the full backend suite; OCR engine calls are mocked. | PARTIAL | Retain format regression tests and run at least one native OCR smoke test for each relevant image class on the deployment host. |
| XLSX, legacy XLS, CSV, and multiple sheets | Pandas reads CSV, every XLSX sheet, and XLS through `xlrd`; sheet names/rows are preserved in extracted text. | [document_processor.py](../backend/app/services/document_processor.py), [requirements.txt](../backend/requirements.txt), [test_document_processing.py](../backend/tests/test_document_processing.py) | XLSX multi-sheet, legacy XLS, and CSV processing tests pass. | COMPLETE | Keep representative fixtures in the regression suite. Track the observed `xlrd` deprecation warning and migrate engines only with compatibility tests. |
| Corrupt/unsupported inputs and partial batch success | Upload validates names, allowed extensions, size, and empty files. Parser failures are recorded in job/document state; one invalid file does not discard other successful uploads. | [main.py](../backend/app/main.py), [document_processor.py](../backend/app/services/document_processor.py), [test_api_workflows.py](../backend/tests/test_api_workflows.py), [test_document_processing.py](../backend/tests/test_document_processing.py) | Batch partial-success, file parsing failures, and retry/failure behavior are covered by passing tests. | COMPLETE | Add operational monitoring/alerting and, before exposing the service publicly, malware scanning and stronger upload isolation. |
| AI-powered extraction of invoice number/date, supplier/customer, subtotal, tax, total, currency, and line items | The processing path calls local Ollama structured extraction with `qwen2.5:3b`; missing values are represented as null and source evidence is validated. | [ai_extractor.py](../backend/app/services/ai_extractor.py), [schemas.py](../backend/app/schemas.py), [document_processor.py](../backend/app/services/document_processor.py) | Three live local-model calls completed in the synthetic evaluation; the generated numeric date was normalized from source evidence and the unlabelled subtotal was rejected. | PARTIAL | Expand and evaluate against representative permission-cleared invoices before making general accuracy or production-readiness claims. |
| Strict structured output; missing versus uncertain; provenance/confidence; no fabrication | The extraction contract distinguishes found/missing/uncertain, uses null for missing or unsupported values, includes evidence/confidence, validates structured output, and checks quoted evidence against source text. Unambiguous labeled numeric dates are normalized deterministically; ambiguous dates remain uncertain. Confidence is model-reported, not calibrated. | [ai_extractor.py](../backend/app/services/ai_extractor.py), [schemas.py](../backend/app/schemas.py), [docs/ai_prompts.md](../docs/ai_prompts.md), [test_ai_extraction.py](../backend/tests/test_ai_extraction.py) | Mocked tests cover schema, ambiguous date, and source-evidence rejection paths; the live synthetic evaluation confirms the numeric-date and subtotal-grounding cases. | PARTIAL | Characterize evidence behavior on difficult invoices and calibrate or clearly qualify confidence before using it as a probability. |
| Investigated prior 66.67% field accuracy / 0% invoice accuracy | Those earlier figures are stale and are not the current measured result. The current evaluator uses the local Qwen extraction entry point on three synthetic fixtures. | [evaluate.py](../backend/tests/evaluate.py), [invoices.json](../backend/tests/fixtures/invoices.json), [evaluation_summary.json](../backend/reports/evaluation_summary.json), [evaluation_report.md](./evaluation_report.md) | Latest run: 3/3 successful, 100% field-level and invoice-level accuracy, and 100% missing-field handling. Average processing time was 52.108772 seconds/document. | PARTIAL | Keep the result labeled synthetic; add representative labeled cases and report real-world results separately. |
| Financial validation and duplicate detection | Deterministic validation checks required values and financial arithmetic; duplicate candidates are scored from invoice identity and financial fields. Findings persist as validation results/issues and affect review status. | [validation.py](../backend/app/services/validation.py), [document_processor.py](../backend/app/services/document_processor.py), [test_validation_workflows.py](../backend/tests/test_validation_workflows.py) | Validation, duplicate, and review workflows pass automated tests. | COMPLETE | Expand ground-truth edge cases for currencies, rounding/tax conventions, and duplicate false-positive/false-negative rates. |
| Asynchronous processing, status, retries, failures, history, independent jobs, partial batches | A persisted SQL job queue is processed by a separate worker; attempts and errors are stored, failures retry up to three times, stale jobs are recovered, and upload outcomes are independent per file. Redis/Celery is intentionally not used. | [worker.py](../backend/app/worker.py), [models.py](../backend/app/models.py), [document_processor.py](../backend/app/services/document_processor.py), [test_worker.py](../backend/tests/test_worker.py), [test_api_workflows.py](../backend/tests/test_api_workflows.py) | Queue claims, retry behavior, failure tracking, and API reprocessing/history are tested. PostgreSQL multi-worker contention and crash recovery were not stress-tested. | PARTIAL | Run concurrent-worker and process-crash tests on PostgreSQL; document supported deployment topology and verify queue behavior under contention. |
| PDF-to-PDF and PDF-to-Excel cross-document comparison | Documents are parsed by their format-specific ingestion paths, extracted data is compared by the API, discrepancy/duplicate results are persisted, and PDF/PDF plus PDF/XLSX end-to-end workflows have tests. This is structured invoice comparison, not visual or bytewise PDF comparison. | [main.py](../backend/app/main.py), [validation.py](../backend/app/services/validation.py), [models.py](../backend/app/models.py), [test_document_comparison_integration.py](../backend/tests/test_document_comparison_integration.py), [test_comparison.py](../backend/tests/test_comparison.py) | End-to-end PDF/PDF and PDF/XLSX tests pass with mocked LLM/embedding provider responses. | COMPLETE | Add live-provider comparison demonstrations and more field-mapping/line-item discrepancy cases; state clearly that comparison operates on extracted structured content. |
| Relational persistence of metadata, extracted text, invoice results/line items, validation errors, history, corrections, comparisons | SQLAlchemy models persist documents, structured extraction, line items, validation issues, processing jobs, corrections, comparison results, and text/vector chunks. Tables are initialized with `create_all`; no migration history is present. | [models.py](../backend/app/models.py), [db.py](../backend/app/db.py), [document_processor.py](../backend/app/services/document_processor.py), [architecture_diagram.mmd](../docs/architecture_diagram.mmd), [database_schema.mmd](../docs/database_schema.mmd) | Model/source inspection and API/processing persistence tests. PostgreSQL deployment and schema migration were not verified. | PARTIAL | Add versioned migrations, test clean install and upgrades on SQLite/PostgreSQL, and verify referential integrity and retention behavior. |
| Distinct keyword and semantic search | Keyword filtering is deterministic over stored text/metadata. Semantic search uses local CPU Sentence Transformers vectors, persists vectors as JSON, embeds queries locally, and ranks with cosine similarity in-process. This suits a small local corpus, not a large production vector workload. | [search.py](../backend/app/services/search.py), [embeddings.py](../backend/app/services/embeddings.py), [models.py](../backend/app/models.py), [test_search.py](../backend/tests/test_search.py), [docs/ai_prompts.md](../docs/ai_prompts.md) | Local model loading and cosine ranking were smoke-tested; the temporary-database API/worker integration verifies persisted semantic search with deterministic test vectors. | PARTIAL | Benchmark corpus size and latency; use an indexed vector store if the intended corpus requires it. |
| Functional REST API: upload, status, results, search, corrections, reprocess, compare, history | Routes implement multi-file upload, document list/detail/results/status/history, validation errors, corrections, failed-job reprocessing, keyword/semantic search, comparisons, and job listing. | [main.py](../backend/app/main.py), [schemas.py](../backend/app/schemas.py), [openapi.json](../docs/openapi.json), [test_api_workflows.py](../backend/tests/test_api_workflows.py), [test_document_comparison_integration.py](../backend/tests/test_document_comparison_integration.py) | An isolated temporary-SQLite API/worker test covers PDF upload, job claim, persisted extraction, semantic search, and persisted correction; model and embedding calls are mocked there. | PARTIAL | Run a browser workflow against a configured API/worker, add remaining authorization/error-boundary tests, and add authentication before any untrusted network exposure. |
| Frontend/API integration | React dashboard connects to document APIs for listing/detail, upload, polling, search, correction, and reprocessing. Vite proxies local `/api` requests to the configured backend port. The dashboard does not expose comparison controls. | [App.tsx](../frontend/src/App.tsx), [App.css](../frontend/src/App.css), [vite.config.ts](../frontend/vite.config.ts), [main.py](../backend/app/main.py) | Browser workflow exercised dashboard load, upload, status polling, results, parser error display, retry, correction, and search against live local API/worker services. PDF/XLSX comparison returned HTTP 200 when called from the browser page. Lint/build passed under temporary Node 22.15.0. | PARTIAL | Add a dashboard comparison interaction and repeat acceptance on a clean machine/browser. |
| Reproducible labeled evaluation and required measurements | Three synthetic labeled fixtures and a script calculate field/invoice accuracy for successful extractions, elapsed time, and success/failure rates. Failures are not converted into fake accuracy values. | [evaluate.py](../backend/tests/evaluate.py), [invoices.json](../backend/tests/fixtures/invoices.json), [evaluation_report.md](./evaluation_report.md), [evaluation_summary.json](../backend/reports/evaluation_summary.json) | Latest local run: 3/3 successful, 100% field-level/invoice-level accuracy, average 52.108772 seconds/document. Dataset is synthetic and too small to support real-world claims. | PARTIAL | Expand the labeled dataset, document exclusions/denominators, and report real-world results separately from synthetic results. |
| README setup, environment, database, worker, API, troubleshooting, usage | README includes Windows PowerShell setup, `.env`, SQLite/PostgreSQL notes, worker/API/frontend startup, API routes, usage, testing, evaluation, and live acceptance steps. Redis is correctly described as unused by the SQL-queue design. | [README.md](../README.md), [.env.example](../.env.example), [docker-compose.yml](../docker-compose.yml) | Documentation inspected against current source. The browser test used temporary Node 22.15.0 from the E: npm cache; no clean-machine setup was performed. | PARTIAL | Validate the instructions in a clean Windows environment and keep secrets out of documentation and source control. |
| Architecture and database diagrams match implementation | Mermaid architecture and schema sources and PNG renderings exist. The database diagram's entities/fields align with current SQLAlchemy models; architecture reflects SQL worker, OCR/LLM/embedding path, and search/comparison flows. | [architecture_diagram.mmd](../docs/architecture_diagram.mmd), [architecture_diagram.png](../docs/architecture_diagram.png), [database_schema.mmd](../docs/database_schema.mmd), [database_schema.png](../docs/database_schema.png), [models.py](../backend/app/models.py), [worker.py](../backend/app/worker.py) | Compared diagram entities/flows to inspected model and worker source; PNG and Mermaid source files are present. | COMPLETE | Regenerate both PNGs whenever source diagrams change; consider showing the line-item uniqueness constraint and explicitly labeling in-process vector scan as a small-corpus design. |
| OpenAPI JSON, AI prompt documentation, and AI-assisted development disclosure | Exported OpenAPI JSON, prompt/schema/embedding documentation, and AI-assisted development disclosure exist. | [openapi.json](../docs/openapi.json), [export_openapi.py](../backend/scripts/export_openapi.py), [ai_prompts.md](../docs/ai_prompts.md), [README.md](../README.md) | Files exist; API schema export script and prompt docs inspected. | COMPLETE | Regenerate OpenAPI after route/schema changes and ensure the prompt disclosure stays synchronized with the implementation. |
| Recorded walkthrough | No video or recording artifact is present in the repository. | N/A | Inspected deliverable files and README disclosure. | MISSING | Record a walkthrough of the configured working application and include the recording at the agreed delivery location. |
| Git repository containing source | The workspace is not currently a Git repository; no repository history/remote is available here. | Workspace root | Environment reports that the workspace root is not a Git repository. | MISSING | Create/publish the requested source repository through the expected delivery process, without committing secrets, databases, uploads, or generated local environments. |

## Verification results

### Backend

Command run from `backend\`:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest -q
```

Result at the Phase 6 verification: **61 passed, 0 failed**. Two non-fatal warnings remain: pytest-asyncio fixture-loop default configuration and `xlrd` engine deprecation.

Coverage includes supported formats, multi-sheet workbooks, the generated 1,000-page digital PDF, mocked OCR behavior, strict extraction validation, financial validation, search ranking, batch upload, API correction/history/reprocessing, worker retry behavior, PDF/PDF plus PDF/XLSX comparison, and a temporary-database API/worker/search/correction integration. The live Ollama evaluation and native Tesseract smoke check are recorded separately.

### Frontend

Commands run from `frontend\`:

```powershell
npm run lint
npm run build
```

Both completed successfully under temporary Node.js 22.15.0 from the E: npm cache. The system Node.js 18.20.8 could not start the Vite dev server. The compatible runtime was used without changing the system installation or project dependency manifests; browser results are documented in [acceptance_test_report.md](./acceptance_test_report.md).

### Evaluation and the earlier accuracy figures

The previous reported **66.67% field-level / 0% invoice-level** result is not the current measured result. The latest local Qwen evaluation completed **3/3** synthetic invoices with **100% field-level accuracy**, **100% invoice-level accuracy**, **100% missing-field handling**, and an average of **52.108772 seconds/document**. This small synthetic text-only result does not establish real-world accuracy or evaluate OCR.

Next evaluation gate: add representative, permission-cleared invoices and scanned documents before making real-world accuracy claims.

## Assignment deliverable checklist

| # | Deliverable | Current evidence | Status | Remaining work |
|---|---|---|---|---|
| 1 | Git repository with source code | Source files exist in workspace; workspace is not a Git repository. | MISSING | Create/publish the repository and confirm only intended source/artifacts are included. |
| 2 | Complete README and setup instructions | Windows PowerShell setup, environment, database, worker, API, usage, and troubleshooting are documented. | PARTIAL | Validate clean setup using supported Node and live external dependencies. |
| 3 | Architecture diagram and database schema | Mermaid source and PNG for each; current models/flows are represented. | COMPLETE | Keep in sync with future changes. |
| 4 | Working backend API and frontend | Isolated live API/worker browser workflow completed for upload/status/results/error/correction/search/retry; comparison API called from browser. No dashboard compare control. | PARTIAL | Add dashboard comparison interaction; authentication is not implemented. |
| 5 | PDF, image, Excel, and CSV pipelines | Six synthetic inputs live-processed, with native OCR verified for scanned PDF, PNG, and JPG. OCR extraction quality was partial for dates/line items. | PARTIAL | Test representative user scans and larger documents; improve OCR date and line-item extraction quality. |
| 6 | Automated tests and actual test results | 61 backend tests pass; frontend lint/build pass; Phase 5 browser workflow verified. | COMPLETE | Add dashboard comparison and clean-machine acceptance. |
| 7 | Evaluation report with measured metrics | Reproducible local synthetic evaluation reports 100% on 3 documents with per-document results and limitations. | PARTIAL | Expand labeled data; do not generalize the synthetic score. |
| 8 | Recorded walkthrough | No recording exists. | MISSING | Record the configured app workflow. |
| 9 | AI prompts and AI-assisted development disclosure | Prompt/schema and disclosure documentation exist. | COMPLETE | Keep documentation synchronized. |

## Prioritized implementation roadmap

### Critical acceptance gates

1. **Operational OCR:** run permission-cleared representative scanned invoice images and PDFs through the configured Tesseract path; verify language data, confidence, failures, and large multipage behavior.
2. **Evaluation generalization:** expand the labeled dataset beyond three synthetic documents and report results separately for synthetic text, OCR text, and representative real invoices.
3. **Clean setup and end-to-end acceptance:** validate README instructions with supported Python/Node, database, worker, OCR, and provider configuration; exercise upload through UI, processing, results, correction, search, comparison, and history.
4. **Delivery artifacts:** create/publish the Git repository through the expected process and record the required walkthrough.

### Important hardening

1. Stress-test worker atomic claims, retries, stale-job recovery, and partial success with multiple PostgreSQL workers; add schema migrations and upgrade tests.
2. Verify live embedding calls and measure search latency at intended corpus sizes; use a vector database/index if needed.
3. Add browser/API error-path coverage and authentication before any public or shared-network deployment.
4. Regenerate diagrams and OpenAPI output after future model/route changes.

### Optional production improvements

- Add structured observability, alerting, retention policies, malware scanning, rate limits, authentication/authorization, and deployment automation according to the eventual threat model and operating environment.
- Replace in-process cosine scans and JSON vectors with a dedicated indexed vector store if the document corpus outgrows the current small-corpus design.

## Final status

The earlier baseline audit is obsolete. The current source has substantial real functionality, 49 passing backend tests, live synthetic document acceptance, and a browser workflow against an isolated API/worker database. Full acceptance still requires representative OCR/invoice validation, dashboard-level comparison, clean-machine validation, PostgreSQL concurrency verification, and the walkthrough/repository deliverables. These gaps should be closed and verified incrementally; they do not justify rebuilding the working modules.
