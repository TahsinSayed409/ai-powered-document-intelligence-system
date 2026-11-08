# Assignment requirements status

The original assignment and compliance override are audited in detail in [reports/implementation_audit.md](./reports/implementation_audit.md). This checklist reflects verified current status, not the earlier baseline.

## Functional requirements

- [x] PDF text extraction, including a generated 1,000-page digital PDF regression case.
- [x] Native Tesseract 5.5.3 at `E:\Tesseract-OCR\tesseract.exe` and English data verified with a generated invoice scan; a real user scan was not available.
- [x] JPG/JPEG, PNG, TIFF, XLSX, legacy XLS, and CSV parser paths; multi-sheet Excel is covered.
- [x] Deterministic CSV/XLSX line-item extraction, multiple worksheet support, PDF table rows, missing-value preservation, and page/sheet provenance are covered by regression tests and the six-format live synthetic acceptance run.
- [x] OCR date evidence tolerates normalized whitespace and safe OCR digit substitutions while leaving ambiguous or unsupported dates uncertain.
- [x] Live local Ollama `qwen2.5:3b` structured extraction and three-invoice synthetic evaluation completed; the latest run measured 100% field-level and invoice-level accuracy.
- [x] Phase 6 unmocked six-format acceptance completed; all 12 expected line items persisted, and CSV/XLSX used zero Ollama calls when structured data sufficed. This is synthetic coverage, not a real-world accuracy claim.
- [x] Financial validation, duplicate detection, and persisted validation findings.
- [ ] Production-grade background worker verification (live API/worker processing is verified against an isolated SQLite database; PostgreSQL concurrency is not verified).
- [x] Structured PDF/PDF and PDF/XLSX comparison workflows, tested with mocked local AI responses.
- [x] Local Sentence Transformers model loaded on CPU; 384-dimensional vectors and meaningful cosine ranking verified. Intended-scale performance is not measured.
- [ ] Clean-machine acceptance remains unverified; browser upload, status, results, errors, correction, search, and retry were exercised. Comparison was tested via its API because the dashboard has no comparison control.

## Deliverables

- [ ] Git repository and recorded walkthrough are still missing from this workspace.
- [ ] README setup is documented but requires clean Windows validation with supported Node and live external dependencies.
- [x] Mermaid/PNG architecture and database diagrams are present.
- [x] FastAPI backend, OpenAPI JSON, and connected React frontend are present; frontend lint/build pass.
- [x] Automated suite: 61 backend tests pass; frontend lint/build pass.
- [x] Evaluation script and synthetic labeled fixtures are present; latest 3-document synthetic run reports 100% field-level accuracy, 100% invoice-level accuracy, and 100% missing-field handling. This is not a real-world accuracy claim.
- [x] AI prompt and AI-assisted development disclosure are documented.

The app defaults to SQLite for local development and supports PostgreSQL configuration. Ollama/Qwen, Sentence Transformers, and the configured Tesseract installation are local. PostgreSQL concurrency, representative real-invoice accuracy, clean-machine setup, and dashboard-level comparison remain unverified; the Phase 5 browser acceptance covered the other listed UI workflows.
