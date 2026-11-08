# Phase 7 Acceptance Report

Run date: 2026-11-08  
Environment: Intel Core i7-1355U, 16 GB RAM, Intel Iris Xe; Windows; local CPU inference  
AI/OCR: Ollama `qwen2.5:3b`; Tesseract 5.5.3.20260724; Sentence Transformers `all-MiniLM-L6-v2`  
Test data: reproducible synthetic fixtures only

## Status summary

| Area | Status | Result |
|---|---|---|
| Six-format live ingestion and persistence | PASS | Six of six existing synthetic fixtures passed through the local pipeline; 12 of 12 expected line items persisted. |
| Live OCR and model handoff | PASS | Tesseract ran on the scanned PDF, PNG, and JPG; OCR output reached the local Ollama extraction flow. |
| Labeled-text live Ollama evaluation | PASS | Three of three synthetic cases succeeded; 27 of 27 comparisons matched. |
| Backend regression suite | PASS | 74 tests passed, zero failed. |
| Frontend lint and production build | PASS | Both passed. |
| Browser workflow using production preview | PASS | Dashboard, upload, status, results, errors, correction, search, retry, and comparisons were exercised. |
| Vite development-server startup | FAIL | Installed Node 18.20.8 is below the Vite version's requirement; startup failed with `crypto.hash is not a function`. The built production preview was used for browser testing. |
| Real-world extraction accuracy | NOT TESTED | No representative real-world document dataset was available; all tested documents were synthetic. |
| Screenshots | NOT TESTED | No screenshots were captured. The acceptance JSON and isolated browser-test database were used as records during verification. |

## Live six-format acceptance

The original Phase 6 fixture files and manifest were reused without regeneration. Their SHA-256 hashes were unchanged. The run used an isolated temporary database and upload directory and wrote its measurements to [phase7_live/phase6_acceptance_results.json](./phase7_live/phase6_acceptance_results.json). It used actual local Ollama and Tesseract calls, not mocked model or OCR responses.

| Document | Result | Pages | Line items persisted | LLM time (s) | OCR time (s) | Total time (s) |
|---|---|---:|---:|---:|---:|---:|
| Digital PDF | PASS | 1 | 2/2 | 56.778 | Not used | 67.428 |
| Scanned PDF | PASS; `requires_review` | 2 | 2/2 | 57.964 | 0.345 | 58.620 |
| PNG invoice | PASS | 1 | 2/2 | 58.035 | 0.367 | 58.564 |
| XLSX invoice | PASS | 3 sheets | 2/2 | 0 | Not used | 0.320 |
| CSV invoice | PASS | 1 | 2/2 | 0 | Not used | 0.056 |
| JPG invoice | PASS | 1 | 2/2 | 58.698 | 0.383 | 59.250 |

The scanned PDF correctly remained `requires_review`; a passing ingestion means that parsing, extraction, persistence, and expected review status were observed, not that every field was confirmed. Page-level source metadata was retained for the two-page scanned PDF.

Detailed Phase 6/7 performance comparisons, methodology, chart, and labeled-text evaluation results are maintained in the canonical [evaluation report](./evaluation_report.md). The live six-format results and per-document timings remain in [phase7_live/phase6_acceptance_results.json](./phase7_live/phase6_acceptance_results.json).

## Browser acceptance

The API and worker used an isolated SQLite database. The successful production build was served with Vite preview because the installed Node 18.20.8 cannot start the installed Vite development server.

- Dashboard loaded and showed live document status and extracted details, line items, evidence, confidence, and validation information.
- Eight supported synthetic documents uploaded and processed. Five ended `processed`; three remained `requires_review`. A separate unsupported `.exe` upload was rejected with an error. A deliberately malformed PDF produced a persisted `failed` record with a sanitized parsing-stage error.
- The malformed PDF's retry control was enabled. Clicking it created a new job; the retried job failed after three attempts. Its history retained both failed jobs, each with three attempts. Reprocessing an already-processed document was disabled in the UI and the API returned HTTP 409.
- Keyword search for `Cedar` returned the scanned invoice. A keyword with no match showed the empty state. Semantic search ranked the scanned invoice first. Semantic search has no minimum relevance threshold, so a query with no exact match still returns nearest-neighbor results.
- A manual customer correction to `Reviewed Clinic` remained after refresh and was recorded in the isolated database. Existing review issues remained. There is no dedicated correction-history panel; the correction was confirmed from persisted data.
- Four comparisons were performed and persisted: PDF/PDF MATCH, PDF/PDF MISMATCH, PDF/XLSX MATCH, and PDF/XLSX MISMATCH. A document could not be selected against itself.
- Captured browser checks showed no JavaScript console errors.

## Regression and feature preservation

- Full backend test suite: **74 passed**. No backend code changes were made after that run.
- Frontend lint: **passed**.
- Frontend production build: **passed**.
- Existing six-format extraction retained 2/2 expected line items for each format, matching the Phase 6 result of 12/12.
- The dashboard comparison UI, field evidence display, search-mode selection, retry gating, and search API source-text omission were exercised or covered by the completed suite.
- Manual correction persisted, and document retry history was retained. No application architecture, schema, model, or external provider was changed for this acceptance phase.
- The existing Phase 6 fixture set and historical Phase 6 results were preserved.

### Files changed during Phase 7

- [backend/app/services/ai_extractor.py](../backend/app/services/ai_extractor.py)
- [backend/app/main.py](../backend/app/main.py)
- [backend/tests/test_ai_extraction.py](../backend/tests/test_ai_extraction.py)
- [backend/tests/test_document_comparison_integration.py](../backend/tests/test_document_comparison_integration.py)
- [backend/tests/evaluate.py](../backend/tests/evaluate.py)
- [frontend/src/App.tsx](../frontend/src/App.tsx)
- [frontend/src/App.css](../frontend/src/App.css)
- [README.md](../README.md)
- [reports/evaluation_report.md](./evaluation_report.md)
- [reports/phase7_acceptance_report.md](./phase7_acceptance_report.md)
- [reports/phase7_live/phase6_acceptance_results.json](./phase7_live/phase6_acceptance_results.json)
- [reports/phase7_live/evaluation_summary.json](./phase7_live/evaluation_summary.json)

## Failed cases and limitations

- **FAIL (development-server only):** Vite's development server does not run with the installed Node 18.20.8 (`crypto.hash is not a function`); frontend browser checks used the successful production build and preview server.
- **Expected processing failure:** The intentionally malformed PDF failed parsing on both processing jobs after the three configured attempts. This verified error reporting and retry history rather than a defect in supported-format acceptance.
- **PARTIAL:** Semantic nearest-neighbor search has no relevance cutoff; unrelated results can appear for queries with no exact match.
- **PARTIAL:** Manual correction is persisted, but no dedicated correction-history UI was found.
- **NOT TESTED:** Real-world accuracy, visual screenshots, model/OCR service outage behavior in the UI, and a warm-only performance benchmark.
- The application has no authentication; it should remain local and not be exposed to untrusted networks.

## Evidence files

- Test-category and environment details: [testing_report.md](./testing_report.md)
- Report index: [README.md](./README.md)
- Six-format live run: [phase7_live/phase6_acceptance_results.json](./phase7_live/phase6_acceptance_results.json)
- Labeled-text Ollama evaluation: [phase7_live/evaluation_summary.json](./phase7_live/evaluation_summary.json)
- Updated evaluation report: [evaluation_report.md](./evaluation_report.md)
- Browser workflow records were held in an isolated temporary database during testing; no screenshot artifacts were captured.
