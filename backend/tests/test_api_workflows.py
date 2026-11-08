import uuid

import pytest

from app.db import SessionLocal
from app.main import app
from app.models import Document, ProcessingJob
from fastapi.testclient import TestClient

client = TestClient(app)


def test_batch_upload_returns_partial_success_and_persists_job_history():
    response = client.post(
        "/api/documents/upload",
        files=[
            ("files", ("batch.csv", b"Invoice,Total\nB-1,12.00\n", "text/csv")),
            ("files", ("unsupported.exe", b"not allowed", "application/octet-stream")),
        ],
    )

    assert response.status_code == 200
    result = response.json()
    assert result["partial_success"] is True
    assert len(result["documents"]) == 1
    assert result["failures"][0]["filename"] == "unsupported.exe"

    document_id = result["documents"][0]["id"]
    history = client.get(f"/api/documents/{document_id}/history")
    assert history.status_code == 200
    assert history.json()["jobs"][0]["status"] == "queued"
    assert history.json()["jobs"][0]["attempts"] == 0


def test_failed_document_reprocess_and_manual_correction_are_persisted():
    unique_id = uuid.uuid4().hex
    amount = float(int(unique_id[:8], 16) + 1)
    db = SessionLocal()
    try:
        failed_document = Document(
            filename="failed.csv",
            file_type="csv",
            storage_path="missing.csv",
            status="failed",
            error_message="Previous processing failed",
        )
        corrected_document = Document(
            filename="corrected.csv",
            file_type="csv",
            storage_path="corrected.csv",
            status="processed",
            extracted_data={
                "invoice_number": f"ORIGINAL-{unique_id}",
                "invoice_date": "2026-01-01",
                "supplier_name": f"Supplier-{unique_id}",
                "customer_name": f"Customer-{unique_id}",
                "subtotal": amount,
                "tax": 0.0,
                "total": amount,
                "currency": "USD",
                "line_items": [],
            },
        )
        db.add_all([failed_document, corrected_document])
        db.commit()
        db.refresh(failed_document)
        db.refresh(corrected_document)
        db.add(ProcessingJob(
            document_id=failed_document.id,
            job_name="extract_and_validate",
            status="failed",
            retries=3,
            error_message="Previous processing failed",
        ))
        db.commit()
        failed_id = failed_document.id
        corrected_id = corrected_document.id
    finally:
        db.close()

    reprocess = client.post(f"/api/documents/{failed_id}/reprocess")
    assert reprocess.status_code == 200
    assert reprocess.json()["status"] == "queued"

    correction = client.post(
        f"/api/documents/{corrected_id}/corrections",
        json={"field_name": "invoice_number", "value": f"CORRECTED-{unique_id}"},
    )
    assert correction.status_code == 200
    assert correction.json()["value"] == f"CORRECTED-{unique_id}"

    invalid_correction = client.post(
        f"/api/documents/{corrected_id}/corrections",
        json={"field_name": "storage_path", "value": "other.csv"},
    )
    assert invalid_correction.status_code == 422

    details = client.get(f"/api/documents/{corrected_id}")
    assert details.json()["extracted_data"]["invoice_number"] == f"CORRECTED-{unique_id}"
    assert details.json()["validation_status"] == "VALID"

    history = client.get(f"/api/documents/{failed_id}/history")
    assert history.status_code == 200
    assert len(history.json()["jobs"]) == 2
    assert history.json()["jobs"][0]["status"] == "queued"


@pytest.mark.parametrize("right_file_type", ["pdf", "xlsx"])
def test_compare_endpoint_compares_processed_pdf_with_pdf_or_spreadsheet(right_file_type):
    extracted = {
        "invoice_number": "CROSS-1",
        "invoice_date": "2026-02-01",
        "supplier_name": "Northwind Ltd",
        "customer_name": "Contoso",
        "subtotal": 100.0,
        "tax": 10.0,
        "total": 110.0,
        "currency": "USD",
        "line_items": [{
            "description": "Widget",
            "quantity": 2.0,
            "unit_price": 50.0,
            "line_total": 100.0,
        }],
    }
    db = SessionLocal()
    try:
        left = Document(
            filename="left.pdf",
            file_type="pdf",
            storage_path="left.pdf",
            status="processed",
            extracted_data=extracted,
        )
        right = Document(
            filename=f"right.{right_file_type}",
            file_type=right_file_type,
            storage_path=f"right.{right_file_type}",
            status="processed",
            extracted_data={**extracted, "total": 111.0},
        )
        db.add_all([left, right])
        db.commit()
        db.refresh(left)
        db.refresh(right)
        left_id, right_id = left.id, right.id
    finally:
        db.close()

    response = client.post(
        "/api/compare",
        json={"left_document_id": left_id, "right_document_id": right_id},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["left_file_type"] == "pdf"
    assert result["right_file_type"] == right_file_type
    assert result["comparison"]["status"] == "MISMATCH"
    assert result["duplicate"]["classification"] in {"duplicate", "possible_duplicate"}
