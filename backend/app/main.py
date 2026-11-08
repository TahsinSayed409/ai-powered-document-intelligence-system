from contextlib import asynccontextmanager
import re
import uuid
import math
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.config import settings
from app.db import Base, SessionLocal, engine, get_db
from app.models import (
    ComparisonResult,
    Document,
    InvoiceLineItem,
    ManualCorrection,
    ProcessingJob,
    SearchIndex,
    ValidationIssue,
)
from app.schemas import CompareRequest, CorrectionRequest
from app.services.embeddings import EmbeddingError
from app.services.search import keyword_search, semantic_search
from app.services.validation import compare_documents, detect_duplicate, validate_invoice

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url, "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def _document_payload(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "filename": document.filename,
        "file_type": document.file_type,
        "status": document.status,
        "validation_status": document.validation_status,
        "invoice_number": document.invoice_number,
        "invoice_date": document.invoice_date,
        "supplier_name": document.supplier_name,
        "customer_name": document.customer_name,
        "subtotal": document.subtotal,
        "tax": document.tax,
        "total": document.total,
        "currency": document.currency,
        "error_message": document.error_message,
    }


def _line_item_payload(item: InvoiceLineItem) -> dict[str, Any]:
    return {
        "ordinal": item.ordinal,
        "description": item.description,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "tax": item.tax,
        "line_total": item.line_total,
        "evidence": item.evidence,
        "confidence": item.confidence,
    }


def _new_job(db: Session, document: Document) -> ProcessingJob:
    job = ProcessingJob(
        document_id=document.id,
        job_name="extract_and_validate",
        status="queued",
        progress=0,
        retries=0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _safe_filename(filename: str) -> str:
    safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", filename).strip(" .")
    if "." in safe_name:
        stem, extension = safe_name.rsplit(".", 1)
        safe_name = f"{stem[:190]}.{extension[:9]}"
    else:
        safe_name = safe_name[:200]
    return safe_name or "upload"


@app.get(f"{settings.api_prefix}/health")
def read_health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(f"{settings.api_prefix}/documents/upload")
async def upload_documents(
    files: list[UploadFile] = File(...),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if len(files) > 100:
        raise HTTPException(status_code=413, detail="A batch can contain at most 100 files.")
    uploaded_docs: list[dict[str, Any]] = []
    failed_files: list[dict[str, str]] = []
    allowed_extensions = {extension.lower() for extension in settings.allowed_extensions}
    max_bytes = settings.max_upload_size_mb * 1024 * 1024

    for uploaded_file in files:
        raw_name = (uploaded_file.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not raw_name:
            failed_files.append({"filename": "", "error": "A filename is required."})
            continue
        original_name = _safe_filename(raw_name)
        if "." not in original_name:
            failed_files.append({"filename": original_name, "error": "The file has no extension."})
            continue
        extension = original_name.rsplit(".", 1)[-1].lower()
        if extension not in allowed_extensions:
            failed_files.append({
                "filename": original_name,
                "error": f"Unsupported file type: {extension}",
            })
            continue

        stored_name = f"{uuid.uuid4().hex}_{original_name}"
        destination = Path(settings.upload_dir) / stored_name
        total_size = 0
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                while True:
                    chunk = await uploaded_file.read(1024 * 1024)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > max_bytes:
                        raise ValueError(
                            f"File exceeds the {settings.max_upload_size_mb} MB upload limit."
                        )
                    handle.write(chunk)
            if total_size == 0:
                raise ValueError("The uploaded file is empty.")
        except (OSError, ValueError) as exc:
            if destination.exists():
                destination.unlink()
            failed_files.append({"filename": original_name, "error": str(exc)})
            continue

        document = Document(
            filename=original_name,
            file_type=extension,
            storage_path=str(destination),
            status="queued",
            file_size=total_size,
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        job = _new_job(db, document)
        uploaded_docs.append({
            **_document_payload(document),
            "job_id": job.id,
        })

    return {
        "documents": uploaded_docs,
        "failures": failed_files,
        "partial_success": bool(uploaded_docs) and bool(failed_files),
    }


@app.get(f"{settings.api_prefix}/documents")
def list_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    documents = db.query(Document).order_by(Document.created_at.desc()).offset(skip).limit(limit).all()
    return {"items": [_document_payload(document) for document in documents], "count": len(documents)}


@app.get(f"{settings.api_prefix}/documents/{{document_id}}")
def get_document(document_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    line_items = db.query(InvoiceLineItem).filter(
        InvoiceLineItem.document_id == document_id
    ).order_by(InvoiceLineItem.ordinal).all()
    return {
        **_document_payload(document),
        "extracted_data": document.extracted_data,
        "line_items": [_line_item_payload(item) for item in line_items],
        "validation_result": document.validation_result,
    }


@app.get(f"{settings.api_prefix}/documents/{{document_id}}/results")
def get_document_results(document_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    line_items = db.query(InvoiceLineItem).filter(
        InvoiceLineItem.document_id == document_id
    ).order_by(InvoiceLineItem.ordinal).all()
    issues = db.query(ValidationIssue).filter(
        ValidationIssue.document_id == document_id
    ).order_by(ValidationIssue.id).all()
    return {
        "document_id": document.id,
        "status": document.status,
        "extracted_data": document.extracted_data,
        "line_items": [_line_item_payload(item) for item in line_items],
        "validation_result": document.validation_result,
        "validation_errors": [{
            "severity": issue.severity,
            "field": issue.field,
            "message": issue.message,
        } for issue in issues],
    }


@app.get(f"{settings.api_prefix}/documents/{{document_id}}/validation-errors")
def get_validation_errors(document_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not db.query(Document.id).filter(Document.id == document_id).first():
        raise HTTPException(status_code=404, detail="Document not found")
    issues = db.query(ValidationIssue).filter(
        ValidationIssue.document_id == document_id
    ).order_by(ValidationIssue.id).all()
    return {"document_id": document_id, "errors": [{
        "severity": issue.severity,
        "field": issue.field,
        "message": issue.message,
    } for issue in issues]}


@app.get(f"{settings.api_prefix}/documents/{{document_id}}/status")
def get_status(document_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    job = db.query(ProcessingJob).filter(
        ProcessingJob.document_id == document_id
    ).order_by(ProcessingJob.id.desc()).first()
    return {
        "id": document.id,
        "status": document.status,
        "validation_status": document.validation_status,
        "job_id": job.id if job else None,
        "job_status": job.status if job else None,
        "retries": job.retries if job else 0,
        "error_message": job.error_message or document.error_message if job else document.error_message,
    }


@app.get(f"{settings.api_prefix}/documents/{{document_id}}/history")
def get_processing_history(document_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not db.query(Document.id).filter(Document.id == document_id).first():
        raise HTTPException(status_code=404, detail="Document not found")
    jobs = db.query(ProcessingJob).filter(
        ProcessingJob.document_id == document_id
    ).order_by(ProcessingJob.id.desc()).all()
    return {
        "document_id": document_id,
        "jobs": [{
            "id": job.id,
            "job_name": job.job_name,
            "status": job.status,
            "progress": job.progress,
            "attempts": job.retries,
            "started_at": job.started_at.isoformat() if job.started_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
            "error_message": job.error_message,
        } for job in jobs],
    }


@app.post(f"{settings.api_prefix}/documents/{{document_id}}/reprocess")
def reprocess_document(document_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    latest_job = db.query(ProcessingJob).filter(
        ProcessingJob.document_id == document_id
    ).order_by(ProcessingJob.id.desc()).first()
    if document.status != "failed" and (latest_job is None or latest_job.status != "failed"):
        raise HTTPException(status_code=409, detail="Only failed documents can be reprocessed.")
    document.status = "queued"
    document.error_message = None
    job = _new_job(db, document)
    return {"id": document.id, "job_id": job.id, "status": "queued"}


@app.post(f"{settings.api_prefix}/documents/{{document_id}}/corrections")
def apply_correction(
    document_id: int,
    payload: CorrectionRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    document = db.query(Document).filter(Document.id == document_id).first()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.status not in {"processed", "requires_review"} or not document.extracted_data:
        raise HTTPException(status_code=409, detail="A processed document is required for corrections.")
    allowed_fields = {
        "invoice_number",
        "invoice_date",
        "supplier_name",
        "customer_name",
        "subtotal",
        "tax",
        "total",
        "currency",
    }
    if payload.field_name not in allowed_fields:
        raise HTTPException(status_code=422, detail="Unsupported correction field.")
    numeric_fields = {"subtotal", "tax", "total"}
    if payload.value is not None:
        if payload.field_name in numeric_fields:
            if isinstance(payload.value, bool) or not isinstance(payload.value, (int, float)):
                raise HTTPException(status_code=422, detail="This field requires a numeric value or null.")
            if not math.isfinite(float(payload.value)):
                raise HTTPException(status_code=422, detail="This field requires a finite numeric value.")
        if payload.field_name not in numeric_fields and not isinstance(payload.value, str):
            raise HTTPException(status_code=422, detail="This field requires a string value or null.")

    previous_value = getattr(document, payload.field_name)
    correction = ManualCorrection(
        document_id=document.id,
        field_name=payload.field_name,
        old_value=str(previous_value) if previous_value is not None else None,
        new_value=str(payload.value) if payload.value is not None else None,
    )
    db.add(correction)
    setattr(document, payload.field_name, payload.value)
    updated_data = dict(document.extracted_data)
    updated_data[payload.field_name] = payload.value
    document.extracted_data = updated_data
    other_documents = db.query(Document).filter(
        Document.id != document.id,
        Document.status.in_(["processed", "requires_review"]),
    ).all()
    existing_invoices = [
        candidate.extracted_data
        for candidate in other_documents
        if candidate.extracted_data
    ]
    validation = validate_invoice(document.extracted_data or {}, existing_invoices)
    db.query(ValidationIssue).filter(
        ValidationIssue.document_id == document.id
    ).delete()
    db.add_all(
        ValidationIssue(
            document_id=document.id,
            severity=issue["severity"],
            field=issue["field"],
            message=issue["message"],
        )
        for issue in validation["issues"]
    )
    document.validation_result = validation
    document.validation_status = validation["status"]
    document.status = "processed" if validation["status"] == "VALID" else "requires_review"
    db.commit()
    return {"status": "saved", "field": payload.field_name, "value": payload.value}


@app.get(f"{settings.api_prefix}/search")
def search_documents(
    query: str = Query(..., min_length=1, max_length=500),
    mode: str = Query("keyword", pattern="^(keyword|semantic)$"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    documents = db.query(Document).all()
    text_indexes = db.query(SearchIndex).filter(
        SearchIndex.document_id.in_([document.id for document in documents])
    ).all() if documents else []
    text_by_document: dict[int, list[str]] = {}
    for index in text_indexes:
        text_by_document.setdefault(index.document_id, []).append(index.text)
    payload = [{
        **_document_payload(document),
        "extracted_data": document.extracted_data,
        "raw_text": "\n".join(text_by_document.get(document.id, [])),
    } for document in documents]
    if mode == "keyword":
        results = keyword_search(payload, query)
    else:
        try:
            results = semantic_search(payload, query, db=db)
        except EmbeddingError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
    safe_results = [
        {key: value for key, value in result.items() if key != "raw_text"}
        for result in results[:20]
    ]
    return {"query": query, "mode": mode, "results": safe_results}


@app.post(f"{settings.api_prefix}/compare")
def compare_documents_endpoint(
    payload: CompareRequest,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    left = db.query(Document).filter(Document.id == payload.left_document_id).first()
    right = db.query(Document).filter(Document.id == payload.right_document_id).first()
    if not left or not right:
        raise HTTPException(status_code=404, detail="One or both documents not found")
    if not left.extracted_data or not right.extracted_data:
        raise HTTPException(status_code=409, detail="Both documents must finish processing before comparison.")

    left_data = left.extracted_data
    right_data = right.extracted_data
    comparison = compare_documents(left_data, right_data)
    duplicate = detect_duplicate(left_data, right_data)
    result_data = {
        "left_file_type": left.file_type,
        "right_file_type": right.file_type,
        "comparison": comparison,
        "duplicate": duplicate,
    }
    result = ComparisonResult(
        left_document_id=left.id,
        right_document_id=right.id,
        comparison_data=result_data,
    )
    db.add(result)
    db.commit()
    return result_data


@app.get(f"{settings.api_prefix}/jobs")
def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    jobs = db.query(ProcessingJob).order_by(
        ProcessingJob.id.desc()
    ).offset(skip).limit(limit).all()
    return {"jobs": [{
        "id": job.id,
        "document_id": job.document_id,
        "job_name": job.job_name,
        "status": job.status,
        "progress": job.progress,
        "attempts": job.retries,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error_message": job.error_message,
    } for job in jobs]}
