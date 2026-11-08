# Historical Phase 6 Test Report — Superseded

> This file records an earlier 61-test run and is retained as historical evidence. For the current Phase 7 verified results, use [testing_report.md](./testing_report.md). Do not interpret the results below as the latest run.

## Backend test run

Command run from `backend\`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Result: **61 passed, 0 failed** in 6.36 seconds.

Non-fatal warnings:

- `pytest-asyncio` reports that the default fixture event-loop scope is not configured.
- Pandas reports that the `xlrd` engine is deprecated for legacy `.xls` reading.

## Coverage exercised

The backend tests include:

- PDF, JPG/JPEG, PNG, multipage TIFF, XLSX (including multiple sheets), legacy XLS, and CSV parsing.
- A generated 1,000-page digital PDF extraction case.
- Mocked OCR preprocessing/fallback behavior and explicit missing-Tesseract behavior.
- Strict Ollama response schema, evidence/provenance checks, missing/uncertain handling, numeric-date grounding, and subtotal evidence checks.
- Deterministic multi-row PDF/CSV/XLSX table extraction, multi-worksheet metadata, header variants, repeated-header/discount filtering, missing quantity/unit-price preservation, incorrect line-total detection, and source page/sheet provenance.
- Seven date regression cases covering clear ISO, unambiguous and ambiguous numeric dates, OCR whitespace and character differences, missing values, and incorrect evidence.
- Stage-specific persisted processing diagnostics that avoid recording document text or raw provider output.
- Financial validation, duplicate detection, and persisted validation issues.
- Distinct keyword and mocked embedding/cosine semantic search behavior.
- Multi-file upload with per-file failures, processing status, results, manual correction, history, and failed-job reprocessing.
- Worker queue claiming, retries, failures, and stale-job recovery behavior.
- PDF/PDF and PDF/XLSX ingestion-to-comparison workflows with mocked AI/embedding provider responses.
- A temporary SQLite API/worker integration covering PDF upload, queued-job claiming, persisted extraction/indexing, semantic search, and persisted manual correction. External model/embedding calls are mocked in this deterministic integration test.

The native Tesseract and local Ollama installations were used unmocked in the six-format Phase 6 acceptance workflow; all six synthetic files processed and all 12 expected line items persisted. CSV/XLSX extracted without Ollama calls. These host measurements are reported separately from mocked automated tests in [acceptance_test_report.md](./acceptance_test_report.md) and [phase6_acceptance_results.json](./phase6_acceptance_results.json).

## Frontend validation

Commands run from `frontend\`:

```powershell
npm run lint
npm run build
```

Both completed successfully under temporary Node.js 22.15.0 from the E: npm cache; no system Node installation or project dependency was changed. The system Node.js 18.20.8 cannot start the installed Vite dev server. The Phase 5 browser workflow is documented in [acceptance_test_report.md](./acceptance_test_report.md); it was not repeated for Phase 6.

## Live synthetic evaluation

The labeled synthetic evaluator is [backend/tests/evaluate.py](../backend/tests/evaluate.py). Its latest successful local run is documented in [evaluation_report.md](./evaluation_report.md) and [evaluation_summary.json](../backend/reports/evaluation_summary.json): 3/3 documents succeeded, with 100% field-level and invoice-level accuracy. This small synthetic text-only result does not establish real-world accuracy or evaluate OCR.
