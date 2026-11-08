import json
import io
import re

import pymupdf
from openpyxl import Workbook
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.db import Base, SessionLocal
from app.main import app
from app.models import (
    Document,
    InvoiceLineItem,
    ManualCorrection,
    ProcessingJob,
    SearchIndex,
)
from app.services.document_processor import process_document
from app.worker import claim_next_job
from fastapi.testclient import TestClient

client = TestClient(app)
INVOICE = {
    "invoice_number": "E2E-CROSS-9001",
    "invoice_date": "2026-05-01",
    "supplier_name": "Integration Supplier Ltd",
    "customer_name": "Integration Customer",
    "subtotal": 100.0,
    "tax": 10.0,
    "total": 110.0,
    "currency": "USD",
}


class _FakeResponse:
    def __init__(self, value):
        self.value = value

    def raise_for_status(self):
        return None

    def json(self):
        if "data" in self.value:
            return self.value
        return {"message": {"content": json.dumps(self.value)}}


def _line_for_field(text: str, field: str, value) -> str:
    candidates = text.splitlines()
    value_text = str(value).casefold()
    field_label = field.replace("_", " ").casefold()
    for line in candidates:
        normalized = line.casefold()
        if re.search(rf"\b{re.escape(field_label)}\b", normalized) or value_text in normalized:
            return line
    raise AssertionError(f"No source evidence for {field} in {text!r}")


def _fake_provider_post(url, **kwargs):
    prompt = kwargs["json"]["messages"][1]["content"]
    source_text = prompt.split("SOURCE DOCUMENT:\n", 1)[1]
    fields = [
        "invoice_number",
        "invoice_date",
        "supplier_name",
        "customer_name",
        "subtotal",
        "tax",
        "total",
        "currency",
    ]
    response = dict(INVOICE)
    response["line_items"] = [{
        "description": "Widget",
        "quantity": 1.0,
        "unit_price": 100.0,
        "tax": None,
        "line_total": 100.0,
        "evidence": _line_for_field(source_text, "Widget", "Widget"),
        "confidence": 0.98,
    }]
    response["uncertain_fields"] = []
    response["field_assessments"] = [{
        "field": field,
        "status": "found",
        "confidence": 0.98,
        "evidence": _line_for_field(source_text, field, INVOICE[field]),
    } for field in fields]
    return _FakeResponse(response)


def _create_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    source = "\n".join([
        "Invoice No: E2E-CROSS-9001",
        "Invoice Date: 2026-05-01",
        "Supplier: Integration Supplier Ltd",
        "Customer: Integration Customer",
        "Subtotal: 100.00",
        "Tax: 10.00",
        "Total: 110.00",
        "Currency: USD",
        "Widget | Qty 1 | Unit 100.00 | Total 100.00",
    ])
    page.insert_text((72, 72), source)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def _create_xlsx() -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Invoice"
    sheet.append(["Field", "Value"])
    for field, value in INVOICE.items():
        sheet.append([field, value])
    sheet.append([])
    sheet.append(["Description", "Quantity", "Unit Price", "Line Total"])
    sheet.append(["Widget", 1, 100, 100])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_real_pdf_and_xlsx_ingestion_compare_end_to_end(monkeypatch):
    monkeypatch.setattr("app.services.ai_extractor.httpx.post", _fake_provider_post)
    monkeypatch.setattr(
        "app.services.embeddings.embed_texts",
        lambda texts: [[1.0, 0.1] + [0.0] * 382 for _ in texts],
    )

    upload = client.post(
        "/api/documents/upload",
        files=[
            ("files", ("invoice.pdf", _create_pdf(), "application/pdf")),
            (
                "files",
                ("invoice.xlsx", _create_xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            ),
        ],
    )
    assert upload.status_code == 200
    uploaded = upload.json()["documents"]
    assert len(uploaded) == 2

    db: Session = SessionLocal()
    try:
        for item in uploaded:
            job = db.query(ProcessingJob).filter(ProcessingJob.id == item["job_id"]).one()
            document = db.query(Document).filter(Document.id == item["id"]).one()
            job.status = "running"
            job.retries = 1
            document.status = "processing"
        db.commit()
    finally:
        db.close()

    for item in uploaded:
        process_document(item["id"], item["job_id"])

    details = [client.get(f"/api/documents/{item['id']}").json() for item in uploaded]
    assert all(detail["extracted_data"]["invoice_number"] == INVOICE["invoice_number"] for detail in details)
    assert all(detail["status"] in {"processed", "requires_review"} for detail in details)
    assert all(len(detail["line_items"]) == 1 for detail in details)

    db = SessionLocal()
    try:
        assert db.query(SearchIndex).filter(
            SearchIndex.document_id.in_([item["id"] for item in uploaded]),
            SearchIndex.embedding.isnot(None),
        ).count() == 2
        assert db.query(InvoiceLineItem).filter(
            InvoiceLineItem.document_id.in_([item["id"] for item in uploaded])
        ).count() == 2
    finally:
        db.close()

    comparison = client.post(
        "/api/compare",
        json={
            "left_document_id": uploaded[0]["id"],
            "right_document_id": uploaded[1]["id"],
        },
    )
    assert comparison.status_code == 200
    assert comparison.json()["comparison"]["status"] == "MATCH"
    assert comparison.json()["duplicate"]["classification"] == "duplicate"


def test_temporary_database_api_worker_search_and_correction(
    monkeypatch,
    tmp_path,
):
    database_path = tmp_path / "integration.db"
    test_engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    test_session_local = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=test_engine,
    )
    Base.metadata.create_all(bind=test_engine)
    monkeypatch.setattr("app.db.SessionLocal", test_session_local)
    monkeypatch.setattr("app.worker.SessionLocal", test_session_local)
    monkeypatch.setattr("app.services.document_processor.SessionLocal", test_session_local)
    monkeypatch.setattr(settings, "upload_dir", str(tmp_path / "uploads"))
    monkeypatch.setattr("app.services.ai_extractor.httpx.post", _fake_provider_post)
    vector = [1.0, 0.1] + [0.0] * 382
    monkeypatch.setattr(
        "app.services.document_processor.embed_document_text",
        lambda text: [(text, vector)],
    )
    monkeypatch.setattr(
        "app.services.search.embed_texts",
        lambda texts: [vector for _ in texts],
    )

    upload = client.post(
        "/api/documents/upload",
        files=[("files", ("worker-e2e.pdf", _create_pdf(), "application/pdf"))],
    )
    assert upload.status_code == 200
    uploaded = upload.json()["documents"][0]

    claimed = claim_next_job()
    assert claimed == (uploaded["job_id"], uploaded["id"])
    process_document(uploaded["id"], claimed[0])

    details_response = client.get(f"/api/documents/{uploaded['id']}")
    assert details_response.status_code == 200
    details = details_response.json()
    assert details["status"] == "processed", details["validation_result"]
    assert details["extracted_data"]["invoice_number"] == INVOICE["invoice_number"]
    assert details["line_items"][0]["description"] == "Widget"

    search_response = client.get(
        "/api/search",
        params={"query": "matching invoice", "mode": "semantic"},
    )
    assert search_response.status_code == 200
    assert search_response.json()["results"][0]["id"] == uploaded["id"]
    assert "raw_text" not in search_response.json()["results"][0]

    corrected_number = "CORRECTED-E2E-CROSS-9001"
    correction = client.post(
        f"/api/documents/{uploaded['id']}/corrections",
        json={"field_name": "invoice_number", "value": corrected_number},
    )
    assert correction.status_code == 200
    assert correction.json()["value"] == corrected_number

    corrected_details = client.get(f"/api/documents/{uploaded['id']}")
    assert corrected_details.json()["extracted_data"]["invoice_number"] == corrected_number
    history = client.get(f"/api/documents/{uploaded['id']}/history")
    assert history.json()["jobs"][0]["status"] == "completed"

    db: Session = test_session_local()
    try:
        assert db.query(ManualCorrection).filter(
            ManualCorrection.document_id == uploaded["id"],
            ManualCorrection.new_value == corrected_number,
        ).count() == 1
        assert db.query(SearchIndex).filter(
            SearchIndex.document_id == uploaded["id"],
            SearchIndex.embedding.isnot(None),
        ).count() == 1
    finally:
        db.close()
        test_engine.dispose()
