# Phase 6.1 Evidence Provenance Audit

## Status summary

| Area | Status | Result |
|---|---|---|
| Root-cause trace | PASS | Unsupported evidence came from the Ollama response and bypassed grounding for null/uncertain fields. |
| Source-grounded assessment evidence | PASS | Unmatched evidence is cleared; unsupported field values remain null/uncertain for review. |
| Page and sheet provenance | PASS | A source page/sheet is assigned only when evidence matches exactly one source. |
| Focused regressions | PASS | 40 focused tests passed. |
| Complete backend suite | PASS | 67 tests passed on the final complete run. |
| Live scanned-PDF retest | PASS | Actual Tesseract and Ollama processing used an isolated temporary SQLite database. |
| Frontend lint/build | NOT TESTED | No frontend files or behavior changed; these checks were not required for this backend-only change. |

## Root cause

The unsupported quote originated in the model response, not in OCR, evidence fabrication fallback, persistence serialization, or page mapping. In the affected Phase 6 saved result, the subtotal assessment was null and uncertain but contained `"Subtotal: 30.00"`.

The bug was in `_ground_extraction()` in `backend/app/services/ai_extractor.py`: the null-value/uncertain-status branch returned to the next field before checking the assessment's evidence against source text. Thus, evidence on an uncertain or missing-valued field could bypass verification. `_merge_extractions()` carried that assessment through, and `process_document()` persisted it in `Document.extracted_data`; neither created nor validated the quote.

The Phase 6 acceptance JSON preserves the historical bad assessment, but did not preserve the raw model response. The Phase 6.1 live run captured the actual Ollama response directly: it returned subtotal `30.0`, status `found`, confidence `1.0`, and evidence `"Subtotal: 30.00"` even though the OCR input had no subtotal label. The source-grounding step now rejects this response before persistence.

Separately, `_attach_evidence_pages()` previously selected the first matching page/sheet. Repeated evidence could therefore be assigned an unsupported location. It now attaches provenance only when a single source matches.

## Correction implemented

- Validate every non-null field-assessment quote against the original source before null/missing/uncertain early exits.
- Require a matching subtotal/tax/total label for monetary-field evidence. A line-item sum or another monetary amount cannot verify a subtotal quote.
- Clear an unsupported quote without replacing it. Keep the existing confidence and uncertain/missing status semantics; do not promote the field.
- When a non-null field value has unsupported evidence, null the value and mark it uncertain for manual review.
- Clear unsupported line-item evidence and its unsupported values using the existing review behavior.
- Attach page/sheet provenance only when the evidence matches exactly one source. Ambiguous or repeated matches receive no invented location.

No schema, database records, extraction architecture, frontend behavior, model, or external provider was changed.

## Files modified

- `backend/app/services/ai_extractor.py`
- `backend/app/services/document_processor.py`
- `backend/tests/test_ai_extraction.py`
- `backend/tests/test_structured_tables.py`
- `reports/phase6_1_provenance_audit.md` (this report)

## Regression coverage

Six regression tests were added for fabricated uncertain evidence, the exact ACCEPT-SCAN-002 subtotal case, evidence on a missing field, unsupported line-item evidence, valid digital-PDF evidence/page mapping, and page-two/ambiguous-page attribution. Existing assertions and tests also cover exact evidence, OCR whitespace and safe character substitutions, ambiguous/unambiguous/missing dates, invalid evidence, and deterministic CSV/XLSX extraction and provenance.

The ACCEPT-SCAN-002 test exercises `extract_invoice_data()` and its actual assessment-grounding path with a controlled model response; it does not merely test a new helper.

## Test results

- Focused backend selectors (`test_ai_extraction.py`, `test_structured_tables.py`, and `test_document_processing.py`): **40 passed**.
- Complete backend suite, final run: **67 passed**, with one existing Pandas `xlrd` deprecation warning.
- One earlier complete-suite run had a single failure in the manual-correction workflow's `VALID` status assertion. The test passed when isolated, and a fresh complete run passed all 67 tests. No code change was made for this intermittent result; its cause was not established.
- Pylance syntax checks: no syntax errors in either changed backend module or test module.
- Frontend checks: **NOT TESTED**, because no frontend files changed.

## Live scanned-PDF retest

The unchanged `backend/tests/fixtures/acceptance_documents/scanned_invoice.pdf` fixture was uploaded and processed through the application with the actual local Tesseract executable and Ollama `qwen2.5:3b`. The live model call was observed directly; it was not mocked. The run used a temporary SQLite database and upload directory under `reports`, and the temporary data was removed afterward. The normal application database was not used.

Observed results:

- Tesseract was invoked for the scanned, two-page PDF. Instrumentation observed four `image_to_data` calls across processing and the subsequent OCR source verification.
- Ollama returned `subtotal=30.0`, `status=found`, `confidence=1.0`, and fabricated evidence `"Subtotal: 30.00"`. The OCR source contained no subtotal declaration and did not contain that quote.
- Persisted subtotal: `null`; persisted assessment: `uncertain`, confidence `1.0`, evidence `null`.
- The document remained `requires_review`; validation included `supplier_name`, `customer_name`, and `subtotal` review issues. Those missing values remained null.
- Both line items were persisted and mapped to page 1. Supported field-assessment evidence was retained and mapped to page 1; each saved assessment quote matched OCR text. Page 2 remained a distinct source and was not assigned to page 1 by the page mapper.
- The fabricated quote did not appear in persisted extracted data.

### ACCEPT-SCAN-002 before and after

| State | Subtotal value | Assessment status | Confidence | Evidence |
|---|---:|---|---:|---|
| Phase 6 saved acceptance result | null | uncertain | 1.0 | `"Subtotal: 30.00"` (not in OCR) |
| Phase 6.1 live Ollama response | 30.0 | found | 1.0 | `"Subtotal: 30.00"` (not in OCR) |
| Phase 6.1 persisted result | null | uncertain | 1.0 | null |

The confidence shown is the unchanged model-reported confidence, not a verification score. The result remains uncertain and is routed for manual review; the correction does not treat the failed evidence as confirmation.

## Preserved behavior and remaining limitations

**PASS:** Existing CSV/XLSX deterministic extraction and sheet/row provenance tests passed in the focused and complete backend suites. The live scan retained valid date, invoice-number, tax, total, and line-item evidence.

**PARTIAL:** Evidence is source-grounded, but model-reported confidence can remain high (including `1.0`) after its evidence is rejected. It is not increased or used to confirm the field; status/value and validation continue to require review. The schema does not distinguish model confidence from evidence-verification confidence.

**NOT TESTED:** Frontend lint/build and the broader six-format live acceptance workflow were not rerun because this is a targeted backend-only audit.

