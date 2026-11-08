from __future__ import annotations

from datetime import timedelta
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re
import shutil

import pandas as pd
import pytesseract
import pymupdf as fitz
from PIL import Image, ImageOps, ImageSequence
from pytesseract import TesseractError, TesseractNotFoundError
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import (
    Document,
    InvoiceLineItem,
    ProcessingJob,
    SearchIndex,
    ValidationIssue,
    utcnow,
)
from app.services.ai_extractor import (
    InvoiceSchemaError,
    _evidence_matches_source,
    extract_invoice_data,
)
from app.services.embeddings import embed_document_text
from app.services.validation import validate_invoice

MAX_JOB_ATTEMPTS = 3


class OCRUnavailableError(RuntimeError):
    pass


@lru_cache(maxsize=4)
def _verify_tesseract(executable: str, language: str) -> None:
    pytesseract.pytesseract.tesseract_cmd = executable
    try:
        pytesseract.get_tesseract_version()
        languages = pytesseract.get_languages(config="")
    except (TesseractError, TesseractNotFoundError, OSError) as exc:
        raise OCRUnavailableError(
            f"Tesseract at '{executable}' could not be started. Install Tesseract "
            "or verify the executable path and installation."
        ) from exc
    if language not in languages:
        raise OCRUnavailableError(
            f"Tesseract language data '{language}' is missing. "
            "Install the requested language data or configure TESSERACT_LANGUAGE."
        )


def _configure_tesseract() -> None:
    executable = settings.tesseract_path or shutil.which("tesseract")
    if not executable:
        raise OCRUnavailableError(
            "Tesseract OCR is unavailable. Install Tesseract or set TESSERACT_PATH."
        )
    if settings.tesseract_path and not Path(executable).is_file():
        raise OCRUnavailableError(
            f"TESSERACT_PATH does not point to a file: {settings.tesseract_path}"
        )
    _verify_tesseract(str(executable), settings.tesseract_language)


def _ocr_image(image: Image.Image) -> tuple[str, float | None]:
    _configure_tesseract()
    processed = ImageOps.autocontrast(image.convert("L"))
    if min(processed.size) < 1000 and max(processed.size) < 6000:
        processed = processed.resize(
            (processed.width * 2, processed.height * 2),
            Image.Resampling.LANCZOS,
        )
    try:
        result = pytesseract.image_to_data(
            processed,
            output_type=pytesseract.Output.DICT,
            config="--psm 6",
            lang=settings.tesseract_language,
            timeout=settings.ocr_timeout_seconds,
        )
    except TesseractNotFoundError as exc:
        raise OCRUnavailableError(
            "Tesseract OCR is unavailable. Install Tesseract or set TESSERACT_PATH."
        ) from exc
    except TesseractError as exc:
        raise OCRUnavailableError(
            f"Tesseract OCR failed for this image: {exc}"
        ) from exc
    except RuntimeError as exc:
        raise OCRUnavailableError(
            f"Tesseract OCR failed or timed out after "
            f"{settings.ocr_timeout_seconds} seconds: {exc}"
        ) from exc

    words: list[str] = []
    confidences: list[float] = []
    for word, confidence in zip(result["text"], result["conf"]):
        word = word.strip()
        try:
            score = float(confidence)
        except (TypeError, ValueError):
            continue
        if word and score >= 0:
            words.append(word)
            confidences.append(score / 100)
    average_confidence = sum(confidences) / len(confidences) if confidences else None
    return " ".join(words), average_confidence


def extract_pdf_text(file_path: str) -> dict:
    pages = []
    text_parts = []
    tables = []
    with fitz.open(file_path) as document:
        for page_number, page in enumerate(document, start=1):
            text = page.get_text("text") or ""
            image_count = len(page.get_images())
            word_count = len(text.split())
            ocr_confidence = None
            ocr_performed = False
            if image_count and word_count < 10:
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                rendered = Image.open(BytesIO(pixmap.tobytes("png")))
                text, ocr_confidence = _ocr_image(ImageOps.grayscale(rendered))
                word_count = len(text.split())
                ocr_performed = True
            text = text.replace("\x00", " ")
            delimited_rows = [
                [cell.strip() or None for cell in line.split("|")]
                for line in text.splitlines()
                if "|" in line
            ]
            if delimited_rows:
                tables.append({
                    "source": "pdf",
                    "page": page_number,
                    "rows": delimited_rows,
                })
            elif re.search(
                r"\b(?:description|quantity|qty|unit\s+price|line\s+total)\b",
                text,
                flags=re.IGNORECASE,
            ):
                for table in page.find_tables(strategy="text").tables:
                    rows = table.extract()
                    if rows:
                        tables.append({
                            "source": "pdf",
                            "page": page_number,
                            "rows": rows,
                        })
            pages.append({
                "page": page_number,
                "has_images": image_count > 0,
                "word_count": word_count,
                "ocr_confidence": ocr_confidence,
                "ocr_performed": ocr_performed,
            })
            text_parts.append(text)
    return {
        "pages": pages,
        "raw_text": "\n".join(text_parts),
        "source_type": "pdf",
        "tables": tables,
        "page_texts": [
            {"page": page_number, "text": text}
            for page_number, text in enumerate(text_parts, start=1)
        ],
    }


def extract_image_text(file_path: str) -> dict:
    pages = []
    text_parts = []
    with Image.open(file_path) as image:
        for page_number, frame in enumerate(ImageSequence.Iterator(image), start=1):
            processed = ImageOps.exif_transpose(frame.copy()).convert("L")
            text, confidence = _ocr_image(processed)
            text = text.replace("\x00", " ")
            pages.append({
                "page": page_number,
                "ocr_confidence": confidence,
                "ocr_performed": True,
            })
            text_parts.append(text)
    return {
        "pages": pages,
        "raw_text": "\n".join(text_parts),
        "source_type": "image",
        "page_texts": [
            {"page": page_number, "text": text}
            for page_number, text in enumerate(text_parts, start=1)
        ],
    }


def extract_spreadsheet_text(file_path: str) -> dict:
    file_extension = Path(file_path).suffix.lower()
    if file_extension == ".csv":
        frame = pd.read_csv(
            file_path,
            header=None,
            dtype=str,
            encoding="utf-8-sig",
            encoding_errors="replace",
        )
        sheets = [{"sheet_name": "csv", "rows": frame.values.tolist()}]
    else:
        engine = "xlrd" if file_extension == ".xls" else "openpyxl"
        workbook = pd.read_excel(
            file_path,
            sheet_name=None,
            header=None,
            dtype=object,
            engine=engine,
        )
        sheets = [
            {"sheet_name": sheet_name, "rows": frame.values.tolist()}
            for sheet_name, frame in workbook.items()
        ]

    text_parts = []
    tables = []
    page_texts = []
    for sheet_number, sheet in enumerate(sheets, start=1):
        sheet_text_parts = [f"Sheet: {sheet['sheet_name']}"]
        rows = [
            [None if pd.isna(value) else value for value in row]
            for row in sheet["rows"]
        ]
        sheet["rows"] = rows
        tables.append({
            "source": "spreadsheet",
            "sheet_name": sheet["sheet_name"],
            "rows": rows,
        })
        for row in rows:
            sheet_text_parts.append(" | ".join(
                str(value) for value in row
                if value is not None and str(value).strip()
            ))
        sheet_text = "\n".join(sheet_text_parts)
        text_parts.append(sheet_text)
        page_texts.append({
            "page": sheet_number,
            "sheet_name": sheet["sheet_name"],
            "text": sheet_text,
        })
    return {
        "pages": sheets,
        "raw_text": "\n".join(text_parts),
        "source_type": "spreadsheet",
        "tables": tables,
        "page_texts": page_texts,
    }


def extract_document_text(file_path: str, file_type: str) -> dict:
    if file_type == "pdf":
        return extract_pdf_text(file_path)
    if file_type in {"jpg", "jpeg", "png", "tif", "tiff"}:
        return extract_image_text(file_path)
    if file_type in {"xlsx", "xls", "csv"}:
        return extract_spreadsheet_text(file_path)
    raise ValueError(f"Unsupported document type: {file_type}")


def _attach_evidence_pages(
    invoice_data: dict,
    page_texts: list[dict],
) -> None:
    def unique_source(evidence: str, field: str | None = None) -> dict | None:
        matches = [
            source_page
            for source_page in page_texts
            if _evidence_matches_source(evidence, source_page["text"], field)
        ]
        return matches[0] if len(matches) == 1 else None

    for assessment in invoice_data.get("field_assessments", []):
        evidence = assessment.get("evidence")
        if not evidence:
            continue
        source_page = unique_source(evidence, assessment.get("field"))
        if source_page:
            assessment["source_page"] = source_page["page"]
            if source_page.get("sheet_name"):
                assessment["source_sheet"] = source_page["sheet_name"]

    for item in invoice_data.get("line_items", []):
        evidence = item.get("evidence")
        if not evidence:
            continue
        source_page = unique_source(evidence)
        if source_page:
            item["source_page"] = source_page["page"]
            if source_page.get("sheet_name"):
                item["source_sheet"] = source_page["sheet_name"]


def _record_failure(
    db: Session,
    document: Document,
    job: ProcessingJob,
    exc: Exception,
    stage: str = "document_parsing",
) -> None:
    db.rollback()
    now = utcnow()
    if isinstance(exc, OCRUnavailableError):
        stage = "ocr"
        message = (
            "OCR execution failed; verify the configured local Tesseract executable "
            "and language data."
        )
    elif isinstance(exc, InvoiceSchemaError):
        stage = "schema_validation"
        message = "Extracted values failed schema or source-evidence validation."
    elif isinstance(exc, ValueError) and "Unsupported document type" in str(exc):
        stage = "document_parsing"
        message = "The uploaded file type is not supported."
    else:
        if stage == "ai_extraction":
            message = (
                "Local Ollama extraction failed; verify the local model service and "
                "retry."
            )
        elif stage == "source_normalization":
            message = "Source data could not be normalized into invoice fields."
        elif stage == "embedding_generation":
            message = "Local search embedding generation failed."
        elif stage == "validation":
            message = "Financial validation could not be completed."
        elif stage == "database_persistence":
            message = "Extracted results could not be saved to the database."
        else:
            stage = "document_parsing"
            message = (
                f"Document parsing failed ({type(exc).__name__}); verify that the "
                "file is readable and supported."
            )
    diagnostic = f"{message} [stage={stage}; error={type(exc).__name__}]"
    job.error_message = diagnostic
    job.finished_at = now
    if job.retries < MAX_JOB_ATTEMPTS:
        job.status = "queued"
        job.finished_at = now + timedelta(seconds=min(2 ** job.retries, 60))
        document.status = "queued"
    else:
        job.status = "failed"
        document.status = "failed"
        document.validation_status = "INVALID"
    document.error_message = diagnostic
    issue_field = f"processing.{stage}"
    db.query(ValidationIssue).filter(
        ValidationIssue.document_id == document.id,
        ValidationIssue.field == issue_field,
    ).delete()
    db.add(ValidationIssue(
        document_id=document.id,
        severity="error",
        field=issue_field,
        message=message,
    ))
    db.commit()


def process_document(document_id: int, job_id: int) -> None:
    db = SessionLocal()
    stage = "document_parsing"
    try:
        document = db.query(Document).filter(Document.id == document_id).first()
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        if document is None or job is None or job.document_id != document_id:
            return

        try:
            extracted = extract_document_text(document.storage_path, document.file_type)
            stage = "source_normalization"
            tables = extracted.get("tables", [])
            stage = "ai_extraction"
            invoice_data = extract_invoice_data(
                extracted["raw_text"],
                document.filename,
                structured_tables=tables,
                source_type=extracted.get("source_type"),
            )
            _attach_evidence_pages(invoice_data, extracted.get("page_texts", []))
            stage = "embedding_generation"
            embeddings = embed_document_text(extracted["raw_text"])
            invoice_data["embedding_model"] = settings.embedding_model_name
            invoice_data["embedding_dimension"] = settings.embedding_dimension
            diagnostics = [{
                "stage": "document_parsing",
                "status": "passed",
                "message": (
                    f"Parsed {len(extracted.get('pages', []))} source page(s) "
                    f"from {extracted.get('source_type', 'unknown')} input."
                ),
            }]
            ocr_page_count = sum(
                bool(page.get("ocr_performed"))
                for page in extracted.get("pages", [])
            )
            diagnostics.append({
                "stage": "ocr",
                "status": "passed" if ocr_page_count else "not_used",
                "message": (
                    f"Native OCR ran on {ocr_page_count} page(s)."
                    if ocr_page_count
                    else "Native OCR was not needed for this document."
                ),
            })
            normalized_line_items = invoice_data.get("line_items", [])
            table_header_count = invoice_data.get("table_header_count", 0)
            diagnostics.append({
                "stage": "source_normalization",
                "status": "passed",
                "message": (
                    f"Detected {table_header_count} structured table header(s) and "
                    f"normalized {len(normalized_line_items)} line item(s)."
                ),
            })
            llm_calls = invoice_data.get("llm_calls", 0)
            diagnostics.append({
                "stage": "ai_extraction",
                "status": "passed" if llm_calls else "skipped",
                "message": (
                    f"Local Ollama extraction used {llm_calls} call(s)."
                    if llm_calls
                    else "Ollama was skipped because structured spreadsheet data was sufficient."
                ),
            })
            diagnostics.append({
                "stage": "schema_validation",
                "status": "passed",
                "message": "Extraction schema and source-evidence checks completed.",
            })
            missing_fields = [
                field for field in (
                    "invoice_number",
                    "invoice_date",
                    "supplier_name",
                    "customer_name",
                    "subtotal",
                    "tax",
                    "total",
                )
                if invoice_data.get(field) is None
            ]
            if missing_fields:
                diagnostics.append({
                    "stage": "ai_extraction",
                    "status": "warning",
                    "message": (
                        f"{len(missing_fields)} important invoice field(s) remain missing "
                        "or uncertain; see validation issues."
                    ),
                })
            if not normalized_line_items:
                diagnostics.append({
                    "stage": (
                        "source_normalization"
                        if extracted.get("source_type") == "spreadsheet"
                        else "ai_extraction"
                    ),
                    "status": "warning",
                    "message": "No line items were extracted from the source.",
                })
            invoice_data["processing_diagnostics"] = diagnostics
            stage = "validation"
            duplicate_filters = []
            if invoice_data.get("invoice_number"):
                duplicate_filters.append(
                    func.lower(Document.invoice_number)
                    == invoice_data["invoice_number"].strip().casefold()
                )
            if invoice_data.get("supplier_name") and invoice_data.get("invoice_date"):
                duplicate_filters.append(and_(
                    func.lower(Document.supplier_name)
                    == invoice_data["supplier_name"].strip().casefold(),
                    func.lower(Document.invoice_date)
                    == invoice_data["invoice_date"].strip().casefold(),
                ))
            if invoice_data.get("supplier_name") and invoice_data.get("total") is not None:
                total = float(invoice_data["total"])
                duplicate_filters.append(and_(
                    func.lower(Document.supplier_name)
                    == invoice_data["supplier_name"].strip().casefold(),
                    Document.total.between(total - 0.02, total + 0.02),
                ))
            existing_invoices = []
            if duplicate_filters:
                candidates = db.query(Document).filter(
                    Document.id != document.id,
                    Document.status.in_(["processed", "requires_review"]),
                    or_(*duplicate_filters),
                ).all()
                existing_invoices = [
                    candidate.extracted_data
                    for candidate in candidates
                    if candidate.extracted_data
                ]
            validation = validate_invoice(invoice_data, existing_invoices)

            stage = "database_persistence"
            db.query(SearchIndex).filter(SearchIndex.document_id == document.id).delete()
            db.query(InvoiceLineItem).filter(
                InvoiceLineItem.document_id == document.id
            ).delete()
            db.query(ValidationIssue).filter(
                ValidationIssue.document_id == document.id
            ).delete()
            db.add_all(
                SearchIndex(document_id=document.id, text=chunk, embedding=vector)
                for chunk, vector in embeddings
            )
            db.add_all(
                InvoiceLineItem(
                    document_id=document.id,
                    ordinal=ordinal,
                    description=item.get("description"),
                    quantity=item.get("quantity"),
                    unit_price=item.get("unit_price"),
                    tax=item.get("tax"),
                    line_total=item.get("line_total"),
                    evidence=item.get("evidence"),
                    confidence=item.get("confidence"),
                )
                for ordinal, item in enumerate(invoice_data.get("line_items", []), start=1)
            )
            db.add_all(
                ValidationIssue(
                    document_id=document.id,
                    severity=issue["severity"],
                    field=issue["field"],
                    message=issue["message"],
                )
                for issue in validation["issues"]
            )
            document.extracted_data = invoice_data
            document.validation_result = validation
            document.status = "processed" if validation["status"] == "VALID" else "requires_review"
            document.validation_status = validation["status"]
            document.error_message = None
            document.invoice_number = invoice_data.get("invoice_number")
            document.invoice_date = invoice_data.get("invoice_date")
            document.supplier_name = invoice_data.get("supplier_name")
            document.customer_name = invoice_data.get("customer_name")
            document.subtotal = invoice_data.get("subtotal")
            document.tax = invoice_data.get("tax")
            document.total = invoice_data.get("total")
            document.currency = invoice_data.get("currency")
            document.updated_at = utcnow()
            job.status = "completed"
            job.progress = 100
            job.error_message = None
            job.finished_at = utcnow()
            invoice_data["processing_diagnostics"].append({
                "stage": "database_persistence",
                "status": "passed",
                "message": (
                    f"Persisted {len(normalized_line_items)} line item(s), "
                    f"{len(embeddings)} embedding chunk(s), and "
                    f"{len(validation['issues'])} validation issue(s)."
                ),
            })
            document.extracted_data = invoice_data
            db.commit()
        except Exception as exc:
            _record_failure(db, document, job, exc, stage)
    finally:
        db.close()
