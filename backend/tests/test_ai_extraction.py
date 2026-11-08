import json

import httpx
import pytest

from app.config import settings
from app.services.ai_extractor import (
    InvoiceExtractionError,
    extract_invoice_data,
)

SOURCE = (
    "Invoice No: INV-9\n"
    "Date: 2026-04-04\n"
    "Supplier: A & B Ltd\n"
    "Customer: X Ltd\n"
    "Subtotal: 15.00\n"
    "Tax: 1.50\n"
    "Total: 16.50\n"
    "Currency: USD\n"
    "Paper | Qty 1 | Unit 15.00 | Total 15.00"
)


def _provider_result(supplier: str = "A & B Ltd", supplier_evidence: str = "Supplier: A & B Ltd"):
    return {
        "invoice_number": "INV-9",
        "invoice_date": "2026-04-04",
        "supplier_name": supplier,
        "customer_name": "X Ltd",
        "subtotal": 15.0,
        "tax": 1.5,
        "total": 16.5,
        "currency": "USD",
        "line_items": [{
            "description": "Paper",
            "quantity": 1.0,
            "unit_price": 15.0,
            "tax": None,
            "line_total": 15.0,
            "evidence": "Paper | Qty 1 | Unit 15.00 | Total 15.00",
            "confidence": 0.94,
        }],
        "uncertain_fields": [],
        "field_assessments": [
            {"field": "invoice_number", "status": "found", "confidence": 0.99, "evidence": "Invoice No: INV-9"},
            {"field": "invoice_date", "status": "found", "confidence": 0.99, "evidence": "Date: 2026-04-04"},
            {"field": "supplier_name", "status": "found", "confidence": 0.93, "evidence": supplier_evidence},
            {"field": "customer_name", "status": "found", "confidence": 0.94, "evidence": "Customer: X Ltd"},
            {"field": "subtotal", "status": "found", "confidence": 0.98, "evidence": "Subtotal: 15.00"},
            {"field": "tax", "status": "found", "confidence": 0.98, "evidence": "Tax: 1.50"},
            {"field": "total", "status": "found", "confidence": 0.99, "evidence": "Total: 16.50"},
            {"field": "currency", "status": "found", "confidence": 0.96, "evidence": "Currency: USD"},
        ],
    }


class _FakeResponse:
    def __init__(self, value):
        self.value = value
        self.status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"message": {"content": json.dumps(self.value)}}


class _FakeHTTPErrorResponse:
    def __init__(self, status_code: int, message: str):
        self.response = httpx.Response(
            status_code,
            request=httpx.Request("POST", "http://localhost:11434/api/chat"),
            json={"error": message},
        )
        self.status_code = status_code

    @property
    def text(self):
        return self.response.text

    def raise_for_status(self):
        self.response.raise_for_status()


def _mock_provider(monkeypatch, provider_result):
    observed = {}

    def post(url, **kwargs):
        observed["url"] = url
        observed["payload"] = kwargs["json"]
        return _FakeResponse(provider_result)

    monkeypatch.setattr("app.services.ai_extractor.httpx.post", post)
    return observed


def test_llm_extraction_uses_strict_schema_and_preserves_provenance(monkeypatch):
    observed = _mock_provider(monkeypatch, _provider_result())

    result = extract_invoice_data(SOURCE, "invoice.pdf")

    assert result["invoice_number"] == "INV-9"
    assert result["line_items"][0]["description"] == "Paper"
    assert result["field_assessments"][0]["evidence"] == "Invoice No: INV-9"
    assert next(
        item for item in result["field_assessments"]
        if item["field"] == "subtotal"
    )["evidence"] == "Subtotal: 15.00"
    assert result["confidence"] > 0.9
    assert result["source_file"] == "invoice.pdf"
    assert observed["url"] == "http://localhost:11434/api/chat"
    assert observed["payload"]["model"] == "qwen2.5:3b"
    assert observed["payload"]["options"]["num_gpu"] == 0
    assert observed["payload"]["options"]["num_ctx"] == 4096
    assert observed["payload"]["format"]["additionalProperties"] is False
    assert observed["payload"]["format"]["properties"]["field_assessments"]["minItems"] == 8
    assert observed["payload"]["format"]["properties"]["field_assessments"]["maxItems"] == 8


def test_unsupported_field_value_is_null_and_marked_uncertain(monkeypatch):
    provider_result = _provider_result(
        supplier="Invented Supplier",
        supplier_evidence="Invented Supplier",
    )
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(SOURCE, "invoice.pdf")

    assert result["supplier_name"] is None
    assert "supplier_name" in result["uncertain_fields"]
    assessment = next(
        item for item in result["field_assessments"] if item["field"] == "supplier_name"
    )
    assert assessment["status"] == "uncertain"
    assert assessment["evidence"] is None
    assert assessment["confidence"] == 0.93


def test_uncertain_field_with_fabricated_evidence_is_cleared(monkeypatch):
    provider_result = _provider_result(
        supplier=None,
        supplier_evidence="Supplier: Invented Supplier",
    )
    supplier_assessment = next(
        item
        for item in provider_result["field_assessments"]
        if item["field"] == "supplier_name"
    )
    supplier_assessment.update(status="uncertain", confidence=1.0)
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(SOURCE, "invoice.pdf")

    assessment = next(
        item for item in result["field_assessments"]
        if item["field"] == "supplier_name"
    )
    assert result["supplier_name"] is None
    assert assessment["status"] == "uncertain"
    assert assessment["evidence"] is None
    assert assessment["confidence"] == 1.0


def test_accept_scan_subtotal_fabrication_regression(monkeypatch):
    source = "\n".join([
        "INVOICE",
        "Invoice Number: ACCEPT-SCAN-002",
        "Invoice Date: 2026-10-25",
        "Supplier: Cedar Office Supply Ltd",
        "Bill To:",
        "Currency: USD",
        "Item | Description | Qty | Unit Price | Line Total",
        "A-17 | Paper ream | 2 | 12.50 | 25.00",
        "B-04 | Pens | 1 | 5.00 | 5.00",
        "Tax: 3.00",
        "Grand Total: 33.00",
        "Remittance note: Include ACCEPT-SCAN-002 with payment. Page two.",
    ])
    provider_result = _provider_result()
    provider_result["invoice_number"] = "ACCEPT-SCAN-002"
    provider_result["invoice_date"] = "2026-10-25"
    provider_result["supplier_name"] = None
    provider_result["customer_name"] = None
    provider_result["subtotal"] = None
    assessments = {
        item["field"]: item
        for item in provider_result["field_assessments"]
    }
    assessments["invoice_number"]["evidence"] = (
        "Invoice Number: ACCEPT-SCAN-002"
    )
    assessments["invoice_date"]["evidence"] = "Invoice Date: 2026-10-25"
    assessments["supplier_name"].update(
        status="missing",
        confidence=0.0,
        evidence=None,
    )
    assessments["customer_name"].update(
        status="missing",
        confidence=0.0,
        evidence=None,
    )
    assessments["subtotal"].update(
        status="uncertain",
        confidence=1.0,
        evidence="Subtotal: 30.00",
    )
    assessments["tax"]["evidence"] = "Tax: 3.00"
    assessments["total"]["evidence"] = "Grand Total: 33.00"
    provider_result["line_items"] = [{
        "description": "Paper ream",
        "quantity": 2.0,
        "unit_price": 12.5,
        "tax": None,
        "line_total": 25.0,
        "evidence": "A-17 | Paper ream | 2 | 12.50 | 25.00",
        "confidence": 0.95,
    }]
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(source, "scanned_invoice.pdf")

    subtotal = next(
        item for item in result["field_assessments"]
        if item["field"] == "subtotal"
    )
    assert result["subtotal"] is None
    assert subtotal["status"] == "uncertain"
    assert subtotal["evidence"] is None
    assert subtotal["confidence"] == 1.0
    assert "subtotal" in result["uncertain_fields"]
    assert "Subtotal: 30.00" not in json.dumps(result)


def test_missing_field_with_fabricated_quote_stays_missing(monkeypatch):
    provider_result = _provider_result()
    provider_result["supplier_name"] = None
    supplier_assessment = next(
        item
        for item in provider_result["field_assessments"]
        if item["field"] == "supplier_name"
    )
    supplier_assessment.update(
        status="missing",
        confidence=0.0,
        evidence="Supplier: Invented Supplier",
    )
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(SOURCE, "invoice.pdf")

    assessment = next(
        item for item in result["field_assessments"]
        if item["field"] == "supplier_name"
    )
    assert result["supplier_name"] is None
    assert assessment["status"] == "missing"
    assert assessment["evidence"] is None


def test_unverifiable_line_item_evidence_is_cleared(monkeypatch):
    provider_result = _provider_result()
    provider_result["line_items"][0]["evidence"] = "Invented row | 9 | 999.00"
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(SOURCE, "invoice.pdf")

    assert result["line_items"] == []


def test_subtotal_is_not_inferred_from_a_line_item_total(monkeypatch):
    provider_result = _provider_result()
    provider_result["subtotal"] = 15.0
    subtotal_assessment = next(
        item
        for item in provider_result["field_assessments"]
        if item["field"] == "subtotal"
    )
    subtotal_assessment["evidence"] = "Paper | Qty 1 | Unit 15.00 | Total 15.00"
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(SOURCE, "invoice.pdf")

    assert result["subtotal"] is None
    assert "subtotal" in result["uncertain_fields"]
    subtotal_assessment = next(
        item for item in result["field_assessments"]
        if item["field"] == "subtotal"
    )
    assert subtotal_assessment["evidence"] is None


def test_invoice_total_rejects_line_total_evidence_and_preserves_line_item(monkeypatch):
    source = "Item A | Quantity: 1 | Unit Price: 30.00 | Line Total: 30.00"
    provider_result = _provider_result()
    provider_result["total"] = 30.0
    provider_result["line_items"] = [{
        "description": "Item A",
        "quantity": 1.0,
        "unit_price": 30.0,
        "tax": None,
        "line_total": 30.0,
        "evidence": source,
        "confidence": 0.95,
    }]
    total_assessment = next(
        item for item in provider_result["field_assessments"]
        if item["field"] == "total"
    )
    total_assessment["evidence"] = "Line Total: 30.00"
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(source, "invoice.pdf")

    assert result["total"] is None
    assert "total" in result["uncertain_fields"]
    total_assessment = next(
        item for item in result["field_assessments"]
        if item["field"] == "total"
    )
    assert total_assessment["status"] == "uncertain"
    assert total_assessment["evidence"] is None
    assert len(result["line_items"]) == 1
    assert result["line_items"][0]["description"] == "Item A"
    assert result["line_items"][0]["line_total"] == 30.0


@pytest.mark.parametrize(
    "label",
    [
        "Grand Total",
        "Invoice Total",
        "Total Due",
        "Amount Due",
        "Balance Due",
        "Amount Payable",
    ],
)
def test_invoice_total_accepts_explicit_invoice_total_labels(monkeypatch, label):
    source = f"Subtotal: 30.00\nTax: 0.00\n{label}: 30.00"
    provider_result = _provider_result()
    provider_result["total"] = 30.0
    provider_result["line_items"] = []
    total_assessment = next(
        item for item in provider_result["field_assessments"]
        if item["field"] == "total"
    )
    total_assessment["evidence"] = f"{label}: 30.00"
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(source, "invoice.pdf")

    assert result["total"] == 30.0
    assert "total" not in result["uncertain_fields"]
    total_assessment = next(
        item for item in result["field_assessments"]
        if item["field"] == "total"
    )
    assert total_assessment["status"] == "found"
    assert total_assessment["evidence"] == f"{label}: 30.00"


def test_unambiguous_numeric_date_is_normalized_from_source_evidence(monkeypatch):
    source = SOURCE.replace("Date: 2026-04-04", "Date: 02/20/2026")
    provider_result = _provider_result()
    provider_result["invoice_date"] = None
    date_assessment = next(
        item
        for item in provider_result["field_assessments"]
        if item["field"] == "invoice_date"
    )
    date_assessment.update(status="uncertain", evidence="Date: 02/20/2026")
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(source, "invoice.pdf")

    assert result["invoice_date"] == "2026-02-20"
    assert "invoice_date" not in result["uncertain_fields"]


def test_ambiguous_numeric_date_remains_uncertain(monkeypatch):
    source = SOURCE.replace("Date: 2026-04-04", "Date: 02/03/2026")
    provider_result = _provider_result()
    provider_result["invoice_date"] = "2026-02-03"
    date_assessment = next(
        item
        for item in provider_result["field_assessments"]
        if item["field"] == "invoice_date"
    )
    date_assessment["evidence"] = "Date: 02/03/2026"
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(source, "invoice.pdf")

    assert result["invoice_date"] is None
    assert "invoice_date" in result["uncertain_fields"]
    assessment = next(
        item for item in result["field_assessments"]
        if item["field"] == "invoice_date"
    )
    assert assessment["status"] == "uncertain"
    assert assessment["evidence"] == "Date: 02/03/2026"


def test_iso_date_evidence_matches_ocr_whitespace_differences(monkeypatch):
    source = SOURCE.replace("Date: 2026-04-04", "Date : 2026 - 04 - 04")
    _mock_provider(monkeypatch, _provider_result())

    result = extract_invoice_data(source, "scan.pdf")

    assert result["invoice_date"] == "2026-04-04"
    assert "invoice_date" not in result["uncertain_fields"]
    assessment = next(
        item for item in result["field_assessments"]
        if item["field"] == "invoice_date"
    )
    assert assessment["evidence"] == "Date: 2026-04-04"


def test_date_evidence_accepts_safe_ocr_character_substitutions(monkeypatch):
    provider_result = _provider_result()
    date_assessment = next(
        item
        for item in provider_result["field_assessments"]
        if item["field"] == "invoice_date"
    )
    date_assessment["evidence"] = "Date: 2O26-O4-O4"
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(SOURCE, "scan.pdf")

    assert result["invoice_date"] == "2026-04-04"
    assert "invoice_date" not in result["uncertain_fields"]
    assessment = next(
        item for item in result["field_assessments"]
        if item["field"] == "invoice_date"
    )
    assert assessment["evidence"] == "Date: 2O26-O4-O4"


def test_missing_date_stays_null(monkeypatch):
    provider_result = _provider_result()
    provider_result["invoice_date"] = None
    date_assessment = next(
        item
        for item in provider_result["field_assessments"]
        if item["field"] == "invoice_date"
    )
    date_assessment.update(status="missing", evidence=None)
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(SOURCE, "invoice.pdf")

    assert result["invoice_date"] is None
    assert "invoice_date" not in result["uncertain_fields"]


def test_incorrect_date_evidence_is_not_trusted(monkeypatch):
    source = SOURCE.replace("Date: 2026-04-04", "Date: 2026-04-05")
    provider_result = _provider_result()
    provider_result["invoice_date"] = "2026-04-04"
    _mock_provider(monkeypatch, provider_result)

    result = extract_invoice_data(source, "invoice.pdf")

    assert result["invoice_date"] is None
    assert "invoice_date" in result["uncertain_fields"]


def test_llm_extraction_rejects_non_local_provider(monkeypatch):
    monkeypatch.setattr(settings, "ai_provider", "openai")

    with pytest.raises(InvoiceExtractionError, match="AI_PROVIDER=ollama"):
        extract_invoice_data(SOURCE, "invoice.pdf")


def test_invalid_structured_output_fails_instead_of_using_heuristics(monkeypatch):
    invalid_result = _provider_result()
    invalid_result["unknown_field"] = "not allowed"
    _mock_provider(monkeypatch, invalid_result)

    with pytest.raises(InvoiceExtractionError, match="invalid invoice JSON"):
        extract_invoice_data(SOURCE, "invoice.pdf")


def test_missing_field_assessments_fail_schema_validation(monkeypatch):
    invalid_result = _provider_result()
    invalid_result["field_assessments"] = []
    _mock_provider(monkeypatch, invalid_result)

    with pytest.raises(InvoiceExtractionError, match="invalid invoice JSON"):
        extract_invoice_data(SOURCE, "invoice.pdf")


def test_large_text_is_chunked_and_overlapping_line_items_are_deduplicated(monkeypatch):
    source = (SOURCE + "\n") * 160
    calls = []

    def post(url, **kwargs):
        calls.append(kwargs["json"])
        return _FakeResponse(_provider_result())

    monkeypatch.setattr("app.services.ai_extractor.httpx.post", post)

    result = extract_invoice_data(source, "large.pdf")

    assert len(calls) > 1
    assert result["chunks_processed"] == len(calls)
    assert result["invoice_number"] == "INV-9"
    assert len(result["line_items"]) == 1


def test_empty_source_is_rejected_without_a_provider_request(monkeypatch):
    def unexpected_request(*_args, **_kwargs):
        raise AssertionError("Empty source text must not be sent to Ollama.")

    monkeypatch.setattr("app.services.ai_extractor.httpx.post", unexpected_request)

    with pytest.raises(InvoiceExtractionError, match="non-empty source text"):
        extract_invoice_data("  \n", "empty.pdf")


def test_transient_ollama_error_is_retried(monkeypatch):
    results = iter([
        _FakeHTTPErrorResponse(503, "temporarily unavailable"),
        _FakeResponse(_provider_result()),
    ])
    calls = []

    def post(*_args, **_kwargs):
        calls.append(True)
        return next(results)

    monkeypatch.setattr("app.services.ai_extractor.httpx.post", post)
    monkeypatch.setattr("app.services.ai_extractor.time.sleep", lambda _seconds: None)

    result = extract_invoice_data(SOURCE, "invoice.pdf")

    assert result["invoice_number"] == "INV-9"
    assert len(calls) == 2


def test_ollama_model_not_found_is_actionable(monkeypatch):
    monkeypatch.setattr(
        "app.services.ai_extractor.httpx.post",
        lambda *_args, **_kwargs: _FakeHTTPErrorResponse(404, "model not found"),
    )

    with pytest.raises(InvoiceExtractionError, match="ollama pull qwen2.5:3b"):
        extract_invoice_data(SOURCE, "invoice.pdf")


def test_ollama_connection_failure_is_actionable(monkeypatch):
    monkeypatch.setattr(settings, "ollama_retries", 0)

    def unavailable(*_args, **_kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("app.services.ai_extractor.httpx.post", unavailable)

    with pytest.raises(InvoiceExtractionError, match="ollama serve"):
        extract_invoice_data(SOURCE, "invoice.pdf")


def test_ollama_timeout_is_actionable(monkeypatch):
    monkeypatch.setattr(settings, "ollama_retries", 0)

    def timeout(*_args, **_kwargs):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr("app.services.ai_extractor.httpx.post", timeout)

    with pytest.raises(InvoiceExtractionError, match="OLLAMA_TIMEOUT_SECONDS"):
        extract_invoice_data(SOURCE, "invoice.pdf")


def test_malformed_ollama_json_is_rejected(monkeypatch):
    class MalformedResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "{not valid json"}}

    monkeypatch.setattr(
        "app.services.ai_extractor.httpx.post",
        lambda *_args, **_kwargs: MalformedResponse(),
    )

    with pytest.raises(InvoiceExtractionError, match="invalid invoice JSON"):
        extract_invoice_data(SOURCE, "invoice.pdf")
