"""Run live Phase 6 file-ingestion, OCR, extraction, and persistence checks."""

from __future__ import annotations

import json
import os
import statistics
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psutil

BACKEND_DIR = Path(__file__).parents[1]
PROJECT_DIR = BACKEND_DIR.parent
REPORT_DIR = PROJECT_DIR / "reports"
FIXTURE_DIR = BACKEND_DIR / "tests" / "fixtures" / "acceptance_documents"
sys.path.insert(0, str(BACKEND_DIR))


class ProcessMemorySampler:
    def __init__(self) -> None:
        self.process = psutil.Process()
        self.peak_rss_bytes = 0
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self.stop_event.is_set():
            try:
                total = self.process.memory_info().rss
                for child in self.process.children(recursive=True):
                    try:
                        total += child.memory_info().rss
                    except psutil.Error:
                        continue
                self.peak_rss_bytes = max(self.peak_rss_bytes, total)
            except psutil.Error:
                pass
            self.stop_event.wait(0.05)

    def __enter__(self) -> ProcessMemorySampler:
        self.thread.start()
        return self

    def __exit__(self, *_: object) -> None:
        self.stop_event.set()
        self.thread.join()


def _average(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 3) if values else None


def main() -> int:
    from generate_acceptance_fixtures import generate_fixtures

    generate_fixtures(FIXTURE_DIR)
    manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
    fixture_by_name = {
        item["filename"]: item for item in manifest["documents"]
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="phase5-",
        dir=REPORT_DIR,
    ) as temporary_directory:
        runtime_dir = Path(temporary_directory)
        os.environ["DATABASE_URL"] = f"sqlite:///{(runtime_dir / 'acceptance.db').as_posix()}"
        os.environ["UPLOAD_DIR"] = str(runtime_dir / "uploads")

        from fastapi.testclient import TestClient

        from app.config import settings
        from app.db import Base, SessionLocal, engine
        from app.main import app
        from app.models import Document, InvoiceLineItem, ProcessingJob, SearchIndex
        from app.services import ai_extractor, document_processor
        from app.worker import claim_next_job

        Base.metadata.create_all(bind=engine)
        settings.tesseract_path = r"E:\Tesseract-OCR\tesseract.exe"
        settings.tesseract_language = "eng"
        tesseract_version = str(document_processor.pytesseract.get_tesseract_version())

        current_metrics: dict[str, Any] | None = None
        original_extract = document_processor.extract_document_text
        original_invoice_extract = document_processor.extract_invoice_data
        original_llm = ai_extractor.llm_extract_invoice
        original_ocr = document_processor.pytesseract.image_to_data
        original_embed = document_processor.embed_document_text

        def capture_document_text(file_path: str, file_type: str) -> dict[str, Any]:
            assert current_metrics is not None
            result = original_extract(file_path, file_type)
            current_metrics["source_text"] = result["raw_text"]
            current_metrics["pages"] = result["pages"]
            return result

        def capture_invoice_extraction(*args: Any, **kwargs: Any) -> dict[str, Any]:
            assert current_metrics is not None
            started = time.perf_counter()
            try:
                result = original_invoice_extract(*args, **kwargs)
                current_metrics["extraction_method"] = result.get("source_type")
                current_metrics["extraction_llm_calls"] = result.get("llm_calls", 0)
                current_metrics["structured_table_header_count"] = result.get(
                    "table_header_count",
                    0,
                )
                return result
            finally:
                current_metrics["extraction_seconds"] = (
                    time.perf_counter() - started
                )

        def capture_llm(raw_text: str) -> dict[str, Any]:
            assert current_metrics is not None
            started = time.perf_counter()
            try:
                return original_llm(raw_text)
            finally:
                current_metrics["llm_seconds"].append(time.perf_counter() - started)
                current_metrics["llm_received_invoice_marker"] |= (
                    current_metrics["expected_invoice_number"].casefold()
                    in raw_text.casefold()
                )

        def capture_ocr(*args: Any, **kwargs: Any) -> Any:
            assert current_metrics is not None
            started = time.perf_counter()
            try:
                return original_ocr(*args, **kwargs)
            finally:
                current_metrics["ocr_calls"] += 1
                current_metrics["ocr_seconds"].append(time.perf_counter() - started)

        def capture_embedding(text: str) -> list[tuple[str, list[float]]]:
            assert current_metrics is not None
            started = time.perf_counter()
            try:
                return original_embed(text)
            finally:
                current_metrics["embedding_seconds"].append(time.perf_counter() - started)

        document_processor.extract_document_text = capture_document_text
        document_processor.extract_invoice_data = capture_invoice_extraction
        ai_extractor.llm_extract_invoice = capture_llm
        document_processor.pytesseract.image_to_data = capture_ocr
        document_processor.embed_document_text = capture_embedding

        results: list[dict[str, Any]] = []
        with TestClient(app) as client:
            for fixture_path in generate_fixtures(FIXTURE_DIR):
                metadata = fixture_by_name[fixture_path.name]
                current_metrics = {
                    "expected_invoice_number": metadata["expected_invoice_number"],
                    "source_text": "",
                    "pages": [],
                    "ocr_calls": 0,
                    "ocr_seconds": [],
                    "llm_seconds": [],
                    "extraction_seconds": 0.0,
                    "extraction_method": None,
                    "extraction_llm_calls": None,
                    "structured_table_header_count": 0,
                    "embedding_seconds": [],
                    "llm_received_invoice_marker": False,
                }

                with fixture_path.open("rb") as handle:
                    uploaded = client.post(
                        "/api/documents/upload",
                        files=[(
                            "files",
                            (fixture_path.name, handle, "application/octet-stream"),
                        )],
                    )
                upload_ok = uploaded.status_code == 200 and len(
                    uploaded.json().get("documents", [])
                ) == 1
                if not upload_ok:
                    results.append({
                        "filename": fixture_path.name,
                        "format": metadata["format"],
                        "status": "FAIL",
                        "error": uploaded.text[:500],
                    })
                    continue

                upload_document = uploaded.json()["documents"][0]
                job_id = upload_document["job_id"]
                document_id = upload_document["id"]
                claimed = claim_next_job()
                claimed_expected_job = claimed == (job_id, document_id)
                started = time.perf_counter()
                with ProcessMemorySampler() as sampler:
                    if claimed_expected_job:
                        document_processor.process_document(document_id, job_id)
                processing_seconds = time.perf_counter() - started

                details_response = client.get(f"/api/documents/{document_id}")
                details = details_response.json() if details_response.status_code == 200 else {}
                extracted = details.get("extracted_data") or {}
                db = SessionLocal()
                try:
                    stored_document = db.query(Document).filter(
                        Document.id == document_id
                    ).one_or_none()
                    stored_job = db.query(ProcessingJob).filter(
                        ProcessingJob.id == job_id
                    ).one_or_none()
                    line_item_count = db.query(InvoiceLineItem).filter(
                        InvoiceLineItem.document_id == document_id
                    ).count()
                    embedding_count = db.query(SearchIndex).filter(
                        SearchIndex.document_id == document_id,
                        SearchIndex.embedding.isnot(None),
                    ).count()
                    persisted = (
                        stored_document is not None
                        and stored_document.extracted_data is not None
                        and stored_job is not None
                        and stored_job.status == "completed"
                    )
                    document_status = stored_document.status if stored_document else None
                finally:
                    db.close()

                assessments = {
                    item.get("field"): item
                    for item in extracted.get("field_assessments", [])
                }
                missing_fields = {}
                for field in metadata.get("expected_missing_fields", []):
                    assessment = assessments.get(field, {})
                    missing_fields[field] = (
                        extracted.get(field) is None
                        and assessment.get("status") in {"missing", "uncertain"}
                    )
                invoice_number_matches = (
                    extracted.get("invoice_number")
                    == metadata["expected_invoice_number"]
                )
                line_item_count_matches = (
                    line_item_count == metadata["expected_line_item_count"]
                )
                page_count_matches = len(current_metrics["pages"]) == metadata["expected_pages"]
                scanned_pdf_page_content_preserved = (
                    "page_two_marker" not in metadata
                    or metadata["page_two_marker"].casefold()
                    in current_metrics["source_text"].casefold()
                )
                ocr_expected = metadata["expected_ocr"]
                ocr_invoked = current_metrics["ocr_calls"] > 0
                ocr_reached_llm = (
                    not ocr_expected
                    or current_metrics["llm_received_invoice_marker"]
                )
                passed = all([
                    claimed_expected_job,
                    details_response.status_code == 200,
                    persisted,
                    invoice_number_matches,
                    page_count_matches,
                    line_item_count_matches,
                    scanned_pdf_page_content_preserved,
                    ocr_invoked if ocr_expected else not ocr_invoked,
                    ocr_reached_llm,
                    all(missing_fields.values()),
                    embedding_count > 0,
                ])
                results.append({
                    "filename": fixture_path.name,
                    "format": metadata["format"],
                    "status": "PASS" if passed else "FAIL",
                    "document_id": document_id,
                    "job_id": job_id,
                    "job_claimed_by_worker": claimed_expected_job,
                    "document_status": document_status,
                    "invoice_number": extracted.get("invoice_number"),
                    "expected_invoice_number": metadata["expected_invoice_number"],
                    "invoice_number_matches": invoice_number_matches,
                    "page_count": len(current_metrics["pages"]),
                    "expected_page_count": metadata["expected_pages"],
                    "page_metadata": current_metrics["pages"],
                    "ocr": {
                        "expected": ocr_expected,
                        "tesseract_calls": current_metrics["ocr_calls"],
                        "seconds": round(sum(current_metrics["ocr_seconds"]), 3),
                        "tesseract_version": (
                            tesseract_version if ocr_invoked else None
                        ),
                        "text": (
                            current_metrics["source_text"]
                            if ocr_invoked
                            else None
                        ),
                        "text_reached_ollama": ocr_reached_llm,
                    },
                    "llm_seconds": round(sum(current_metrics["llm_seconds"]), 3),
                    "llm_calls": len(current_metrics["llm_seconds"]),
                    "invoice_extraction_seconds": round(
                        current_metrics["extraction_seconds"],
                        3,
                    ),
                    "extraction_method": current_metrics["extraction_method"],
                    "extraction_llm_calls": current_metrics["extraction_llm_calls"],
                    "structured_table_header_count": current_metrics[
                        "structured_table_header_count"
                    ],
                    "embedding_seconds": round(
                        sum(current_metrics["embedding_seconds"]),
                        3,
                    ),
                    "total_processing_seconds": round(processing_seconds, 3),
                    "peak_rss_python_and_children_mb": round(
                        sampler.peak_rss_bytes / (1024 * 1024),
                        1,
                    ),
                    "persisted_extraction": persisted,
                    "persisted_line_items": line_item_count,
                    "line_items_extracted": line_item_count > 0,
                    "expected_line_item_count": metadata["expected_line_item_count"],
                    "line_item_count_matches": line_item_count_matches,
                    "persisted_embedding_chunks": embedding_count,
                    "missing_field_checks": missing_fields,
                    "validation_issues": (
                        (details.get("validation_result") or {}).get("issues", [])
                    ),
                    "extracted_data": extracted,
                })

        engine.dispose()
        reports = [item for item in results if item["status"] in {"PASS", "FAIL"}]
        llm_values = [item["llm_seconds"] for item in reports if item.get("llm_calls")]
        ocr_values = [
            item["ocr"]["seconds"]
            for item in reports
            if item.get("ocr", {}).get("tesseract_calls")
        ]
        embedding_values = [
            item["embedding_seconds"]
            for item in reports
            if item.get("embedding_seconds") is not None
        ]
        processing_values = [
            item["total_processing_seconds"]
            for item in reports
            if item.get("total_processing_seconds") is not None
        ]
        extraction_values = [
            item["invoice_extraction_seconds"]
            for item in reports
            if item.get("invoice_extraction_seconds") is not None
        ]
        summary = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "dataset": "reproducible synthetic document fixtures",
            "model": settings.ollama_model,
            "provider": settings.ai_provider,
            "embedding_model": settings.embedding_model_name,
            "embedding_device": "CPU",
            "tesseract_path": settings.tesseract_path,
            "tesseract_version": tesseract_version,
            "host_hardware": "Intel Core i7-1355U, 16 GB RAM, Intel Iris Xe",
            "system_memory_total_gb": round(psutil.virtual_memory().total / (1024 ** 3), 2),
            "document_count": len(results),
            "passed_documents": sum(item["status"] == "PASS" for item in results),
            "failed_documents": sum(item["status"] == "FAIL" for item in results),
            "average_llm_extraction_seconds": _average(llm_values),
            "average_invoice_extraction_seconds": _average(extraction_values),
            "average_ocr_seconds_per_ocr_document": _average(ocr_values),
            "average_embedding_generation_seconds": _average(embedding_values),
            "average_total_processing_seconds": _average(processing_values),
            "peak_process_plus_child_rss_mb": max(
                (item.get("peak_rss_python_and_children_mb", 0) for item in reports),
                default=None,
            ),
            "memory_measurement": (
                "Approximate peak resident memory of the acceptance Python process and "
                "its child processes; sampled every 50 ms, system-wide free memory was "
                "not attributed to this workload."
            ),
            "results": results,
        }
        report_path = REPORT_DIR / "phase6_acceptance_results.json"
        report_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps({
            "report": str(report_path),
            "passed_documents": summary["passed_documents"],
            "failed_documents": summary["failed_documents"],
            "average_llm_extraction_seconds": summary["average_llm_extraction_seconds"],
            "average_invoice_extraction_seconds": summary["average_invoice_extraction_seconds"],
            "average_ocr_seconds_per_ocr_document": summary["average_ocr_seconds_per_ocr_document"],
            "average_embedding_generation_seconds": summary["average_embedding_generation_seconds"],
            "average_total_processing_seconds": summary["average_total_processing_seconds"],
            "peak_process_plus_child_rss_mb": summary["peak_process_plus_child_rss_mb"],
        }, indent=2))
        return 0 if summary["failed_documents"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
