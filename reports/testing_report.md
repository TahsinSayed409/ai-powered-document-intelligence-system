# Testing Report

## Status and provenance

This is the current evidence summary for the Phase 7 application state. The latest recorded full backend suite is **74 passed, 0 failed**; frontend lint and production build passed. No application source files were changed in the documentation finalization phase. The preceding [test_report.md](./test_report.md) describes an older Phase 6 run and is retained as historical evidence.

The full browser acceptance and live document measurements are in [phase7_acceptance_report.md](./phase7_acceptance_report.md). Machine-readable live results are [phase7_live/phase6_acceptance_results.json](./phase7_live/phase6_acceptance_results.json) and [phase7_live/evaluation_summary.json](./phase7_live/evaluation_summary.json).

## Test environment

| Component | Recorded environment |
|---|---|
| OS | Windows 11 Pro, build 22631 (host OS inventory reported Windows Pro). |
| CPU | Intel Core i7-1355U. |
| RAM | 16 GB installed; approximately 15.64 GiB visible to the process. |
| GPU | Intel Iris Xe integrated graphics; extraction/embeddings configured for CPU. |
| Python | Python 3.14.0. |
| Node.js | System Node 18.20.8; temporary portable Node 22.15.0 used for frontend lint/build. |
| LLM | Local Ollama, `qwen2.5:3b`, 4096-token configured context. |
| OCR | Tesseract 5.5.3.20260724, English language data. |
| Embeddings | `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions, CPU. |
| Test database | Isolated SQLite databases for integration/browser/live acceptance; normal application database was not used for those workflows. |

## Automated test results

Latest recorded commands and results:

```powershell
# From backend\
.\.venv\Scripts\python.exe -m pytest -q
# 74 passed, 0 failed

# From frontend\ using portable Node 22.15.0
npm run lint
# passed
npm run build
# passed
```

The installed Vite 7 release requires Node 20.19+ or 22.12+. The system Node 18.20.8 failed to start Vite development mode with `crypto.hash is not a function`. The system installation was left unchanged. A temporary portable Node 22.15.0 was used for frontend lint/build. Browser testing used the built production preview; the preview ran under the available environment with a Node-version warning. No browser screenshots were captured.

### Test categories

| Category | What is exercised / method | Result and boundary |
|---|---|---|
| PDF parsing | Synthetic digital PDF text and table parsing; PyMuPDF page handling, including a generated 1,000-page case. Automated tests are deterministic. | **PASS** in the backend suite. The 1,000-page case exercises PDF page parsing/iteration only; it is not an end-to-end OCR/LLM test or a scanned-document time/memory benchmark. |
| Multipage PDF | Page-level extraction, sparse/image page OCR fallback, and source-page evidence mapping. | **PASS** in tests; the live two-page scanned PDF acceptance passed and retained page metadata. |
| OCR | OCR preprocessing and missing-executable/error paths are unit-tested with mocked OCR. | **PASS** for unit behavior; real Tesseract was invoked in Phase 7 on the scanned PDF (two calls), PNG, and JPG. OCR for arbitrary real-world scans is **NOT TESTED**. |
| Image processing | Pillow orientation/preprocessing and image/TIFF frame parsing are covered with generated inputs. | **PASS** in tests. Real local OCR was exercised for one PNG and one JPG; TIFF was not in the live six-format set. |
| Excel parsing | XLSX/XLS parser paths, header variants, multiple worksheets, metadata/table separation, and line-item provenance. | **PASS** in tests. The live XLSX had three sheets and persisted 2/2 expected line items. Live legacy XLS acceptance was **NOT TESTED**. |
| CSV parsing | CSV rows, header detection, metadata and line-item extraction, and empty/header handling. | **PASS** in tests. The live CSV persisted 2/2 expected line items. |
| AI extraction | Schema, field extraction, uncertainty, missing values, merge behavior, and error handling use deterministic mocked Ollama responses in unit/integration tests. | **PASS** in tests. The three-case labeled evaluator separately used the actual local Ollama model and succeeded 3/3. |
| Evidence grounding | Exact/normalized quotes, safe OCR substitutions, date support, fabricated evidence rejection, correct page/sheet provenance, and ACCEPT-SCAN-002 regression. Controlled model responses are used for repeatable tests. | **PASS** in tests; Phase 6.1 also ran the scanned PDF with actual Ollama/Tesseract and confirmed unsupported subtotal evidence was cleared before persistence. |
| Financial validation | Missing/uncertain fields, quantity × unit-price discrepancies, subtotal/total reconciliation, rounding tolerance, and duplicate-candidate outcomes. | **PASS** in tests. No representative customer invoice corpus was used. |
| Duplicate detection | Deterministic duplicate scoring and validation review state are tested against synthetic records. | **PASS** in tests. Real duplicate rates/false-positive rates are **NOT TESTED**. |
| Database persistence | Isolated SQLite API/worker integration persists extracted JSON, line items, search chunks, issues, and corrections. | **PASS** in tests/live acceptance. PostgreSQL execution was **NOT TESTED** in Phase 7. |
| Background processing | Job claiming, state transitions, completion/failure, and stale-job recovery are covered by worker tests. | **PASS** in tests. The live browser workflow observed queued-to-processing/completed states. |
| Retry/failure handling | Worker attempt cap, parser/model failures, stale recovery, history, and failed-document reprocess are tested. | **PASS** in tests. A malformed PDF failed after three attempts; a second job was created and also reached three attempts. A successful-document retry returned HTTP 409. |
| API endpoints | Upload, listing, details/results, validation, status/history/jobs, correction, search, comparison, and expected not-found/conflict/validation responses are covered across API and workflow tests. | **PASS** in the 74-test suite. |
| Search | Keyword matching and semantic ranking/cosine behavior are tested; embedding providers are mocked in deterministic tests. | **PASS** in tests. Browser acceptance returned the scanned invoice first for a semantic `Cedar` query. The UI/API have no minimum semantic relevance threshold. |
| Manual corrections | Validation/type checks, correction persistence, and revalidation are tested. | **PASS** in tests and browser acceptance; a customer correction remained after refresh. A correction-history UI is not present. |
| PDF/PDF comparison | Comparison field/line-item behavior and API persistence are tested with controlled fixture extraction. | **PASS** in tests and live browser flow: one matching and one mismatching comparison were stored. |
| PDF/Excel comparison | API comparison for PDF and XLSX, including matching/mismatching values, is covered by integration tests. | **PASS** in tests and live browser flow: one matching and one mismatching comparison were stored. |
| Frontend lint/build | ESLint and TypeScript/Vite production build. | **PASS** using temporary portable Node 22.15.0. |
| Browser workflow | Production-preview UI: dashboard, upload, status, results, errors, correction, keyword/semantic search, retry, and comparisons. | **PASS** in Phase 7. The unsupported `.exe` was rejected; the malformed PDF showed a sanitized parsing error. No screenshots were captured. |

### Browser acceptance summary

The production-preview browser workflow verified upload, processing/results, error handling, correction persistence, keyword/semantic search, retry/history, and PDF/PDF plus PDF/XLSX comparisons. It used synthetic documents and an isolated SQLite database. The scenario-level results and failure cases are in the [Phase 7 acceptance report](./phase7_acceptance_report.md). Screenshots were not captured.

## Limitations and untested areas

- **Real-world extraction accuracy: NOT TESTED.** The labeled evaluation contains only three synthetic invoices; no permission-cleared customer dataset was available.
- **General OCR accuracy: NOT TESTED.** Unit tests mock OCR; the live run covers only one synthetic scanned PDF, one PNG, and one JPG.
- **PostgreSQL: NOT TESTED** in the Phase 7 acceptance workflow; all live persistence checks used isolated SQLite.
- **Node 18 Vite development server: FAIL.** Use a compatible Node runtime. Production build and preview acceptance passed separately.
- **Production security, multi-user access control, load/scalability, disaster recovery, and network deployment: NOT TESTED.**
- **Visual screenshot evidence: NOT TESTED.** Browser interactions were performed, but no screenshots were captured.
- **Warm-only performance comparison: NOT TESTED.** The embedding timing includes model initialization; the reported six-document set is small and not a controlled benchmark.
- Semantic nearest-neighbor search has no relevance cutoff; correction history is persisted but has no user-facing history panel.

For interpretation of accuracy and performance metrics, read [evaluation_report.md](./evaluation_report.md). The measured figures do not establish production throughput or real-world accuracy.
