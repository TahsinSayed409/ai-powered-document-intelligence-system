# Phase 6 — Targeted extraction quality acceptance

## Result summary

The acceptance run was performed on the Intel Core i7-1355U / 16 GB / Iris Xe laptop using the installed local Ollama `qwen2.5:3b`, Tesseract 5.5.3, local Sentence Transformers model, FastAPI processing path, background-job claim, and an isolated temporary SQLite database. No provider calls were mocked. Results are in [phase6_acceptance_results.json](./phase6_acceptance_results.json); Phase 5 measurements remain in [phase5_acceptance_results.json](./phase5_acceptance_results.json).

| Area | Result | Evidence |
|---|---|---|
| Six supported synthetic formats | **PASS** — all six were ingested, processed, and persisted; all invoice numbers matched and each document persisted two line items. | Per-document results below and JSON report |
| Structured table extraction | **PASS** — digital PDF rows were preserved; CSV and XLSX each extracted two complete rows deterministically. XLSX metadata and items were read across three worksheets. | `line_item_source`, `source_page`, and `source_sheet` in JSON |
| Native OCR and date provenance | **PASS** — Tesseract ran four times (two scanned-PDF pages, PNG, JPG). OCR page text reached live Ollama; date evidence on all three OCR documents normalized to `2026-10-25` and retained page 1 provenance. | JSON `ocr`, page metadata, and field assessments |
| Spreadsheet model efficiency | **PASS** — clear CSV/XLSX tables used zero Ollama calls; total processing took 0.145 s and 0.188 s respectively, versus 81.560 s and 81.103 s in Phase 5. | Matched Phase 5/6 timings |
| Backend and frontend verification | **PASS** — 61 backend tests; frontend lint and production build. | [test_report.md](./test_report.md) |
| Real-world accuracy | **NOT TESTED** — inputs are reproducible synthetic fixtures, not permission-cleared customer invoices. | No representative real documents were available. |

## Root causes and changes

- CSV and XLSX grids were flattened into strings before extraction. Headers, metadata rows, multiple sheets, and item columns were not modeled as structured tables, so the model missed or incompletely filled rows.
- PDF table text reached the model as generic prose; there was no deterministic path to preserve all rows when they were already clearly tabular.
- Date grounding required exact quote substring matching. OCR whitespace and spacing around separators caused otherwise readable dates to be rejected.
- Processing failures were stored as raw exception messages with no stage, which could expose provider response text and did not distinguish parsing, OCR, extraction, schema, and persistence failures.

The updated path retains spreadsheet grids and worksheet names, maps common header variants, and deterministically parses clear line-item tables. It skips Ollama for complete, labeled CSV/XLSX invoices and still uses Ollama for PDF/OCR field interpretation when needed. Digital PDF pipe tables are passed with all rows; deterministic row parsing protects their line items from model omission. Arithmetic mismatches in line totals remain errors; subtotal/total reconciliation differences are review warnings to allow discounts, rounding, and additional charges. Diagnostic messages identify the processing stage without recording source contents or provider response bodies. Evidence now normalizes whitespace and date formatting, safely handles common OCR `O`/`0` and `I`/`1` substitutions in date tokens, and adds a source page/sheet to matched evidence without persisting the full page text.

## Per-document results

| Input | Phase 5 → Phase 6 persisted line items | Phase 6 Ollama (s) | OCR calls (s) | Total processing (s) | Result / review notes |
|---|---:|---:|---:|---:|---|
| `digital_invoice.pdf` | 0 → 2 | 84.359 | 0 (0) | 102.687 | PASS; two items and evidence on page 1 |
| `scanned_invoice.pdf` | 1 → 2 | 85.070 | 2 (0.605) | 86.179 | PASS; date accepted; supplier uncertain, customer missing, subtotal uncertain; review required |
| `image_invoice.png` | 1 → 2 | 83.085 | 1 (0.465) | 83.800 | PASS; two items; date accepted |
| `spreadsheet_invoice.xlsx` | 1 → 2 | 0 | 0 (0) | 0.188 | PASS; three worksheets; metadata and items mapped; zero Ollama calls |
| `table_invoice.csv` | 0 → 2 | 0 | 0 (0) | 0.145 | PASS; zero Ollama calls |
| `image_invoice.jpg` | 1 → 2 | 59.835 | 1 (0.490) | 60.496 | PASS; two items; date accepted |

**Line-item comparison:** all six formats persisted two line items (12 total). The three Phase 5 gaps/incompletions—digital PDF `0 → 2`, CSV `0 → 2`, XLSX `1 → 2`—were corrected; the scanned PDF, PNG, and JPG each improved from one to two. Structured rows preserve missing cells as null; deterministic tests cover absent quantity and unit price, incorrect arithmetic, discounts/tax rows, and repeated headers.

## Date, diagnostics, and performance

Seven deterministic regression cases passed: clear ISO date, unambiguous numeric date, ambiguous numeric date remains uncertain, OCR whitespace differences, safe OCR character substitutions, missing date remains null, and an incorrect evidence quote remains uncertain. In the live run, all six dates were supported by page/sheet evidence; the scanned PDF, PNG, and JPG OCR dates were accepted and mapped to page 1. The intentionally missing scan customer/subtotal remained missing or uncertain and generated review findings.

Successful extraction diagnostics are persisted as stage/status/message entries for document parsing, OCR, source normalization, AI extraction, schema validation, and database persistence. Failed jobs receive a stage-specific validation issue and safe error message; document text and raw provider output are not included.

| Measurement | Phase 5 baseline | Phase 6 measured |
|---|---:|---:|
| Average total processing, six documents | 66.646 s | 55.583 s |
| Average Ollama time | 64.068 s across six | 78.087 s across the four documents that used Ollama |
| Average invoice extraction, six documents | Not separately reported | 52.061 s |
| Average OCR per OCR document | 0.403 s | 0.520 s |
| Average embedding generation | 2.261 s | 3.101 s |
| Approximate peak Python-plus-child RSS | 762.8 MiB | 759.8 MiB |

The per-call Ollama average is not directly comparable because Phase 6 intentionally skipped two structured spreadsheets; on the four matching model-backed inputs, inference took longer than Phase 5 while processing the added second item row. End-to-end average was lower because both spreadsheet model calls (about 80 s each in Phase 5) were eliminated. Embedding measurements include a cold model initialization and should not be interpreted as a steady-state guarantee.

## Status

- **PASS:** 6/6 synthetic file workflows, 12 persisted line items, OCR invocation/page preservation, OCR date evidence, CSV/XLSX deterministic extraction, 61 backend tests, frontend lint/build, and the Phase 5 browser-tested upload/status/results/error/retry/correction/search workflow.
- **PARTIAL:** the scanned PDF's supplier and subtotal remain uncertain and its customer field is missing; the document correctly requires review. Ollama was slower on the four model-backed inputs, offset by removing spreadsheet inference.
- **FAIL:** none of the six supported Phase 6 inputs failed processing.
- **NOT TESTED:** customer-document accuracy, clean-machine setup, PostgreSQL concurrency, and repeating the browser workflow during Phase 6. Semantic search and manual correction are covered by the passing automated backend suite; the prior Phase 5 browser run verified correction and search. Comparison still has no dashboard control.

The test dataset is synthetic and does not establish real-world invoice accuracy.

## Historical Phase 5 browser and acceptance record

The original browser workflow and Phase 5 measurements are retained below for reference. Phase 6 did not repeat the browser UI workflow.

### Phase 5 — Real document and browser acceptance

#### Scope and isolation

The workspace did not contain ingestible representative invoice files, only labeled text fixtures. Six small, reproducible synthetic inputs were generated with [generate_acceptance_fixtures.py](../backend/scripts/generate_acceptance_fixtures.py) and saved under [acceptance_documents/](../backend/tests/fixtures/acceptance_documents). They cover a digital PDF, a two-page image-only scanned PDF, PNG, JPG, XLSX, and CSV.

The live file-processing run used [run_acceptance_tests.py](../backend/scripts/run_acceptance_tests.py), a temporary SQLite database and uploads directory under `reports\`; it called the existing upload, worker-claim, document-processing, local Ollama, Tesseract, embedding, and persistence code without mocking those providers. The temporary database was disposed after the run. The separate browser run used its own isolated SQLite database at `reports\phase5-browser\acceptance.db`; it did not use or alter the user's normal database.

#### Results at a glance

| Area | Result | Evidence |
|---|---|---|
| Ingest and process supported synthetic files | **PASS** — 6/6 uploads were claimed, processed, and persisted; all six expected invoice numbers matched and all six persisted embedding chunks were present. | [phase5_acceptance_results.json](./phase5_acceptance_results.json) |
| Native OCR | **PASS** — Tesseract 5.5.3 was invoked four times across the scanned PDF (two pages), PNG, and JPG. OCR text, page metadata, and confidence were produced. | JSON report's per-document `ocr` and `page_metadata` values |
| OCR-to-model and missing-field behavior | **PASS / PARTIAL** — invoice-number OCR text was verified in the live Ollama input. The scan's expected missing customer and subtotal remained null and were flagged. Three readable OCR dates were conservatively left uncertain because the evidence quote did not exactly match the flattened OCR text. | JSON report's `ocr.text_reached_ollama`, extraction assessments, and validation issues |
| Browser dashboard, upload, polling, results, errors, correction, search, retry | **PASS** — exercised in the integrated browser against the running API and worker. | Browser screenshots were captured in-session; backend request/worker logs and isolated DB provide supporting evidence. |
| Comparison | **PASS (API)** — PDF/XLSX comparison returned HTTP 200 and a `MISMATCH` result in the browser context. **PARTIAL (UI)** — the dashboard has no comparison control; the endpoint was invoked directly from the browser page. | API response recorded below; no comparison UI was claimed. |
| Performance and memory | **PASS** — timed on this host for all six documents; these measurements are local synthetic-run observations, not service guarantees. | [phase5_acceptance_results.json](./phase5_acceptance_results.json) |
| Real customer invoices / representative OCR quality | **NOT TESTED** — only reproducible synthetic invoices were available. | No real document fixture was present. |

#### Document-by-document processing

| Input | Processing result | Invoice number | Pages | OCR calls | LLM (s) | OCR (s) | Embeddings (s) | Total (s) | Persisted line items |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `digital_invoice.pdf` | PASS; `processed` | `ACCEPT-PDF-001` | 1 | 0 | 53.153 | 0 | 13.181 | 66.366 | 0 |
| `scanned_invoice.pdf` | PASS; `requires_review` as expected for incomplete/uncertain values | `ACCEPT-SCAN-002` | 2 | 2 | 56.198 | 0.425 | 0.067 | 57.003 | 1 |
| `image_invoice.png` | PASS; `requires_review` for uncertain date | `ACCEPT-PNG-003` | 1 | 1 | 58.200 | 0.394 | 0.050 | 58.771 | 1 |
| `spreadsheet_invoice.xlsx` | PASS; `processed` | `ACCEPT-XLSX-004` | 1 | 0 | 80.937 | 0 | 0.106 | 81.103 | 1 |
| `table_invoice.csv` | PASS; `processed` | `ACCEPT-CSV-005` | 1 | 0 | 81.391 | 0 | 0.129 | 81.560 | 0 |
| `image_invoice.jpg` | PASS; `requires_review` for uncertain date | `ACCEPT-JPG-006` | 1 | 1 | 54.530 | 0.391 | 0.033 | 55.074 | 1 |

All six document extractions and embedding rows were persisted in the isolated database. Digital PDF and CSV line items were not extracted; the XLSX line item had incomplete description/quantity/unit-price fields. These are extraction-quality gaps, not file-ingestion failures.

The two-page scanned PDF retained page 1 and page 2 separately, with OCR confidence approximately `0.950` and `0.948`. Page 2's “Remittance note … Page two” text was present in extracted OCR output. Tesseract reported version `5.5.3.20260724` at `E:\Tesseract-OCR\tesseract.exe`. The scan deliberately omitted both customer and subtotal: the extractor kept them null, marked them missing/uncertain, and persisted validation notes. The scanned PDF date was also marked uncertain; PNG and JPG dates were likewise sent to review rather than accepted from non-matching evidence.

#### Browser workflow

The initial Vite dev-server run on the installed Node 18.20.8 failed because the installed Vite release requires Node `20.19+` or `22.12+`. The production build still ran on Node 18, but the development server did not. To proceed without changing the project's dependencies or the system Node install, Node `22.15.0` was run from the E: npm cache.

The first dashboard render exposed a missing Vite `/api` proxy: the UI received frontend HTML for its API request and showed a JSON parse error. Added the local dev proxy in [vite.config.ts](../frontend/vite.config.ts), restarted Vite, and repeated the browser workflow. The dashboard then loaded from the API successfully. This was the only application change made during acceptance.

Actions performed in the browser:

1. Loaded the dashboard and uploaded a digital PDF, XLSX, and deliberately unreadable PDF in one batch.
2. Observed queue states progress from queued/processing to processed or failed; the two valid files showed invoice results and persisted totals.
3. Selected the unreadable PDF; the details pane displayed the parser error. Retried it through “Retry processing”; the worker attempted it three times and returned it to failed with the error visible.
4. Corrected the XLSX invoice number through the form; the dashboard displayed the corrected value and saved confirmation.
5. Searched for the corrected invoice number; the matching row appeared.
6. Called the PDF/XLSX comparison endpoint from the browser page; it returned HTTP 200, status `MISMATCH`, and `possible_duplicate`. The dashboard itself does not currently expose a comparison button, so this is not reported as UI comparison acceptance.

The browser run used actual local Ollama, worker, API, and SQLite services. The invalid PDF failure was intentional and verified error/retry behavior; it is not counted among the six supported-format processing results.

#### Performance and resource measurements

Host: Intel Core i7-1355U, 16 GB RAM, Intel Iris Xe; available system memory reported approximately 15.64 GiB. Ollama used `qwen2.5:3b` on CPU; embeddings used `sentence-transformers/all-MiniLM-L6-v2` on CPU.

| Measurement | Result |
|---|---:|
| Average live Ollama extraction | 64.068 s per document |
| Average native OCR | 0.403 s per OCR document |
| Average embedding generation | 2.261 s per document |
| Average total processing | 66.646 s per document |
| Peak sampled Python process plus child-process RSS | approximately 762.8 MiB |

Memory was sampled every 50 ms and includes the Python worker/test process plus observed child processes (including Tesseract when present). It is an approximate resident-memory peak, not total system memory attributable with perfect precision. The first embedding call included model initialization; timings vary by cold/warm cache and machine load. Individual timings and page-level OCR data are in the JSON results.

#### Failed and partial cases

- No supported synthetic file failed upload, processing, extraction persistence, or invoice-number matching.
- The intentionally malformed PDF failed as expected; its readable parser error appeared in the dashboard and retry exhausted three attempts.
- Two of six documents had no persisted line items (digital PDF and CSV); one spreadsheet line-item record had incomplete fields.
- Scanned PDF, PNG, and JPG invoice dates were marked uncertain despite visible OCR dates because the evidence did not match the flattened OCR text exactly. The customer and subtotal intentionally omitted from the scan were correctly left null. This conservative result triggered review rather than an unsupported value.
- No visual browser control for comparison exists; only the comparison endpoint was exercised through the browser page.
- Three documents had `requires_review` status due to uncertain extraction fields. They were persisted rather than silently treated as clean.

#### Final status

- **PASS:** synthetic ingestion across digital PDF, scanned PDF, PNG, JPG, XLSX, and CSV; Tesseract execution and page-level OCR; Ollama receipt of OCR text; persistence; browser dashboard/upload/status/results/error/correction/search/retry; PDF/XLSX comparison API; measured performance.
- **PARTIAL:** field-level quality for OCR dates and line items; comparison is not exposed as a dashboard action.
- **FAIL:** none of the six supported synthetic ingestion cases. The intentionally unreadable PDF correctly failed and surfaced the failure.
- **NOT TESTED:** real customer invoices, clean-machine setup, production PostgreSQL concurrency, and dashboard-level comparison UI.

The full backend suite, frontend lint, and production build are rerun after the Vite proxy change and recorded in [test_report.md](./test_report.md).
