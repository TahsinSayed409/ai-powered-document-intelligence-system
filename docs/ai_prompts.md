# AI extraction and disclosure

## Invoice extraction

The processing worker sends extracted document text to the local Ollama chat endpoint using `OLLAMA_MODEL` (default `qwen2.5:3b`). Ollama receives the existing Pydantic `InvoiceExtraction` JSON Schema as its `format` value. Requests use the local `OLLAMA_BASE_URL`, CPU inference, configurable context/timeouts, a single concurrent request by default, and bounded retries for timeouts, connection failures, HTTP 408/429, and server errors. A missing model, unavailable service, malformed response, or schema violation fails the processing attempt with an actionable error. No invoice data is sent to an external AI provider. There is no heuristic LLM fallback for unstructured documents; deterministic extraction is limited to sufficiently structured spreadsheet tables and labeled metadata.

The system prompt is:

```text
Extract only source-grounded invoice facts and return the required JSON schema. Never invent missing information.
```

The user prompt (kept in `backend/app/services/ai_extractor.py`) is:

```text
Extract invoice fields and line items from the source text.
Use null for every missing or ambiguous value; never infer or invent information.
When a clear invoice label and adjacent value are present, extract that value:
invoice_number follows labels such as "Invoice No", "Invoice Number", "Invoice #",
or "INV"; invoice_date follows "Invoice Date" or "Date". Do not mistake a line-item
number for the invoice number.
Dates in YYYY-MM-DD, MM/DD/YYYY, and DD/MM/YYYY formats are valid source dates.
When the ordering is unambiguous, preserve the date or normalize it to ISO format.
Do not calculate subtotal from line items; require an explicit subtotal/net amount
label, and do not copy the grand total or a line-item total into subtotal.
For each top-level field, return exactly one assessment with status found, missing,
or uncertain, confidence from 0 to 1, and an exact supporting source quote as
evidence. Missing values must have status missing and null evidence. Ambiguous
values must have status uncertain and be listed in uncertain_fields. Return line
item evidence as an exact quote too. Numeric values must be JSON numbers. Dates
and currency may be normalized only when the source supports it.
Assess each of these fields exactly once: invoice_number, invoice_date,
supplier_name, customer_name, subtotal, tax, total, currency.
```

The request also supplies the Pydantic `InvoiceExtraction` JSON Schema as Ollama's
`format` value. For PDFs and images, the worker grounds model output against the
extracted source text. For spreadsheets with recognized line-item headers and
sufficient labeled invoice metadata, deterministic table extraction bypasses the
LLM; otherwise the LLM extracts the remaining invoice fields and structured
line-item rows replace model line items when detected.

Unknown properties, invalid types, missing schema properties, duplicate/omitted field assessments, and inconsistent missing/found states are rejected. Each non-null field must also have evidence that occurs in the extracted text and supports the returned value. Unsupported values become `null` and are marked uncertain. Line items retain their source quote and confidence; unsupported values are nulled.

Confidence and provenance are model-reported, not calibrated probabilities. They should be treated as review signals, not guarantees. OCR errors can contaminate the source text and evidence checks do not prove that the source itself is correct.

## Semantic embeddings

The system uses the local CPU Sentence Transformers model `sentence-transformers/all-MiniLM-L6-v2` (384 dimensions by default). Model files are stored under `MODEL_CACHE_DIR` (default `.cache\models` in the project on E:), and the loaded model is reused for document and query embedding. Text is split into chunks before embedding. Vectors are stored as JSON in `search_index.embedding`; each processed document records its embedding model name and dimension in `extracted_data`. A query is embedded with the same model and ranked by cosine similarity, using the best chunk score for each document. Semantic search refuses documents with missing or stale embedding metadata. Run `python scripts/reindex_embeddings.py` from `backend\` after changing the embedding model/dimension; this rebuilds vectors from stored SQL text chunks without rerunning OCR or invoice extraction. JSON storage and the in-process scan are intended for a small local evaluation, not a high-scale vector database.

Keyword filtering is separate and searches indexed text and invoice metadata without an embedding request.

## Validation and decisions

Financial arithmetic and duplicate checks are deterministic application logic, not LLM decisions. Missing/uncertain values, arithmetic mismatches, and duplicate candidates are stored as reviewable validation issues.

## Evaluation

`backend/tests/fixtures/invoices.json` contains labeled synthetic invoice text. The evaluation runner uses the configured local Ollama model and reports processing latency and success/failure. Accuracy is only computed for successful extractions; it is `null` when none succeed. Synthetic fixtures do not establish real-world invoice accuracy. The supplied text fixtures are not an OCR accuracy evaluation.

## AI-assisted development disclosure

AI-assisted coding support was used to develop and refine parts of this repository. No external document data or user secrets are embedded in the code. Invoice text is processed by the configured local Ollama service; initial model downloads are the only component that may require internet access.
