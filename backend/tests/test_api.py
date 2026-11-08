from fastapi.testclient import TestClient

from app.main import app
from app.services.search import keyword_search
from app.services.validation import detect_duplicate, validate_invoice

client = TestClient(app)


def test_validation_engine():
    extracted = {
        "invoice_number": "INV-204",
        "invoice_date": "2026-02-15",
        "supplier_name": "Northwind Ltd.",
        "customer_name": "Bravo Retail",
        "subtotal": 400,
        "tax": 40,
        "total": 440,
        "line_items": [{"description": "Widget", "line_total": 200}, {"description": "Gadget", "line_total": 200}],
    }
    result = validate_invoice(extracted)
    assert result["status"] in {"VALID", "WARNING"}
    assert result["issues"] == [] or result["issues"][0]["severity"] in {"warning", "info"}


def test_duplicate_detection():
    first = {"invoice_number": "INV-204", "supplier_name": "Northwind Ltd.", "invoice_date": "2026-02-15", "total": 440}
    second = {"invoice_number": "INV-204", "supplier_name": "Northwind Ltd.", "invoice_date": "2026-02-15", "total": 444}
    result = detect_duplicate(first, second)
    assert result["classification"] in {"duplicate", "possible_duplicate"}


def test_search_keyword():
    docs = [{"filename": "INV-1001.pdf", "invoice_number": "INV-1001", "supplier_name": "Acme Co", "total": 1500.0}, {"filename": "shared.xlsx", "invoice_number": "INV-2002", "supplier_name": "Beta Co", "total": 2500.0}]
    result = keyword_search(docs, "acme")
    assert len(result) == 1 and result[0]["filename"] == "INV-1001.pdf"


def test_upload_and_read_document():
    response = client.post(
        "/api/documents/upload",
        files={"files": ("sample.pdf", b"%PDF-1.4\n...small pdf placeholder...", "application/pdf")},
    )
    assert response.status_code == 200, response.text
    document = response.json()["documents"][0]
    assert document["filename"] == "sample.pdf"
    detail = client.get(f"/api/documents/{document['id']}")
    assert detail.status_code == 200, detail.text
