from datetime import date
import math
import re
import threading
import time
import unicodedata
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import settings
from app.schemas import InvoiceExtraction
from app.services.table_extractor import (
    extract_labeled_metadata,
    extract_table_line_items,
)


class InvoiceExtractionError(RuntimeError):
    pass


class InvoiceSchemaError(InvoiceExtractionError):
    pass


_OLLAMA_REQUEST_SEMAPHORE = threading.BoundedSemaphore(
    settings.ollama_max_parallel_requests
)


def normalize_currency(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip().upper()
    mapping = {
        "BDT": "BDT",
        "USD": "USD",
        "EUR": "EUR",
        "GBP": "GBP",
        "INR": "INR",
        "JPY": "JPY",
    }
    return mapping.get(value, value[:3] if len(value) >= 3 else value)


def parse_amount(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = re.sub(r"[^0-9.,-]", "", value)
    if not cleaned or cleaned in {".", ",", "-"}:
        return None
    cleaned = cleaned.replace(",", "")
    if cleaned.count(".") > 1:
        cleaned = cleaned.replace(".", "", cleaned.count(".") - 1)
    try:
        return float(cleaned)
    except ValueError:
        return None


def _evidence_supports_value(value: str | float | None, evidence: str | None) -> bool:
    if value is None or not evidence:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(float(value)):
            return False
        candidates = re.findall(r"[-+]?\d[\d,]*(?:\.\d+)?", evidence)
        return any(
            (parsed := parse_amount(candidate)) is not None
            and math.isclose(parsed, float(value), rel_tol=0.001, abs_tol=0.01)
            for candidate in candidates
        )

    normalized_value = _normalize_evidence_text(str(value))
    normalized_evidence = _normalize_evidence_text(evidence)
    if normalized_value in normalized_evidence:
        return True
    value_digits = re.sub(r"\D", "", normalized_value)
    evidence_digits = re.sub(r"\D", "", normalized_evidence)
    return bool(value_digits) and value_digits in evidence_digits


def _normalize_evidence_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return re.sub(r"\s*([:|,./=-])\s*", r"\1", normalized)


_DATE_TOKEN_PATTERN = (
    r"([0-9oOil|]{4}\s*[-/]\s*[0-9oOil|]{1,2}\s*[-/]\s*[0-9oOil|]{1,4}"
    r"|[0-9oOil|]{1,2}\s*[-/]\s*[0-9oOil|]{1,2}\s*[-/]\s*[0-9oOil|]{4})"
)
_MONETARY_LABEL_PATTERNS = {
    "subtotal": r"\b(?:sub[\s-]*total|net\s+amount)\b",
    "tax": r"\b(?:tax|vat|gst)\b",
    "total": r"(?<!line )\b(?:grand\s+total|invoice\s+total|total(?:\s+due)?|amount\s+due|balance\s+due|amount\s+payable)\b",
}


def _date_tokens(text: str) -> list[str]:
    return [
        match.group(1)
        for match in re.finditer(
            rf"\b(?:invoice\s+date|date)\s*[:=]?\s*{_DATE_TOKEN_PATTERN}\b",
            text,
            flags=re.IGNORECASE,
        )
    ]


def _normalize_ocr_date_token(value: str) -> str:
    return value.translate(str.maketrans({"O": "0", "o": "0", "I": "1", "i": "1", "l": "1", "|": "1"}))


def _evidence_matches_source(
    evidence: str | None,
    source: str,
    field: str | None = None,
) -> bool:
    if not evidence:
        return False
    normalized_evidence = _normalize_evidence_text(evidence)
    normalized_source = _normalize_evidence_text(source)
    if normalized_evidence in normalized_source:
        return True
    if field != "invoice_date":
        return False

    evidence_dates = _date_tokens(evidence)
    source_dates = _date_tokens(source)
    if not evidence_dates or not source_dates:
        return False
    evidence_date_values = [
        (_invoice_date_from_evidence(f"Date: {value}"), _normalize_ocr_date_token(value).replace(" ", ""))
        for value in evidence_dates
    ]
    source_date_values = [
        (_invoice_date_from_evidence(f"Date: {value}"), _normalize_ocr_date_token(value).replace(" ", ""))
        for value in source_dates
    ]
    return any(
        (
            evidence_date[0][0] is not None
            and evidence_date[0][0] == source_date[0][0]
        )
        or (
            evidence_date[0][0] is None
            and source_date[0][0] is None
            and evidence_date[1] == source_date[1]
        )
        for evidence_date in evidence_date_values
        for source_date in source_date_values
    )


def _invoice_date_from_evidence(evidence: str) -> tuple[str | None, bool]:
    label_match = re.search(
        rf"\b(?:invoice\s+date|date)\s*[:=]?\s*{_DATE_TOKEN_PATTERN}\b",
        evidence,
        flags=re.IGNORECASE,
    )
    if not label_match:
        return None, False

    raw_date = re.sub(r"\s+", "", _normalize_ocr_date_token(label_match.group(1)))
    if re.fullmatch(r"\d{4}-\d{1,2}-\d{1,2}", raw_date):
        year, month, day = map(int, raw_date.split("-"))
    elif re.fullmatch(r"\d{4}/\d{1,2}/\d{1,2}", raw_date):
        year, month, day = map(int, raw_date.split("/"))
    else:
        first, second, year = map(int, re.split(r"[/-]", raw_date))
        if first > 12 and second <= 12:
            day, month = first, second
        elif second > 12 and first <= 12:
            month, day = first, second
        else:
            return None, True

    try:
        return date(year, month, day).isoformat(), False
    except ValueError:
        return None, True


def heuristic_extract_invoice(raw_text: str, file_name: str) -> dict[str, Any]:
    text = (raw_text or "").replace("\r", " ")
    invoice_number = None
    for pattern in [
        r"invoice\s*(?:no|number|#)?\s*[:#-]?\s*([A-Z0-9/-]+)",
        r"inv\s*[:#-]?\s*([A-Z0-9/-]+)",
    ]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            invoice_number = match.group(1).strip()
            break

    invoice_date = None
    for pattern in [
        r"(?:invoice\s*date|date)\s*[:=]?\s*(\d{4}-\d{2}-\d{2})",
        r"(?:invoice\s*date|date)\s*[:=]?\s*(\d{2}/\d{2}/\d{4})",
        r"(?:invoice\s*date|date)\s*[:=]?\s*(\d{2}-\d{2}-\d{4})",
    ]:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            invoice_date = match.group(1)
            break

    supplier_name = None
    customer_name = None
    for label, target in {
        "supplier": "supplier",
        "vendor": "supplier",
        "from": "supplier",
        "bill from": "supplier",
        "customer": "customer",
        "bill to": "customer",
        "to": "customer",
    }.items():
        pattern = re.compile(rf"(?:{label})\s*[:\-]?\s*([A-Za-z0-9&.,'\-/ ]{{3,80}})", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            value = re.sub(r"\s+", " ", match.group(1)).strip(" -:|")
            if target == "supplier":
                supplier_name = value
            else:
                customer_name = value
            break

    def extract_amount(label: str) -> float | None:
        pattern = re.compile(rf"(?:{label})\s*[:=]?\s*(?:[A-Z]+\s+)?(\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?|\d+(?:\.\d{{2}})?)", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            return parse_amount(match.group(1))
        return None

    subtotal = extract_amount("subtotal")
    tax = extract_amount("tax")
    total = extract_amount("total")
    if total is None:
        total_candidate = re.search(r"grand\s*total\s*[:=]?\s*(?:[A-Z]+\s+)?(\d[\d,]*(?:\.\d{2})?)", text, flags=re.IGNORECASE)
        if total_candidate:
            total = parse_amount(total_candidate.group(1))

    currency_match = re.search(r"\b(BDT|USD|EUR|GBP|INR|JPY)\b", text, flags=re.IGNORECASE)
    currency = normalize_currency(currency_match.group(0) if currency_match else None)

    line_items = []
    for line in text.splitlines():
        if "subtotal" in line.lower() or "tax" in line.lower() or "total" in line.lower():
            continue
        if re.search(r"\d+", line) and re.search(r"[A-Za-z]", line):
            description = line.strip()
            qty_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:x|qty|quantity)?", line, flags=re.IGNORECASE)
            unit_price = None
            total_price = None
            for amount_match in re.finditer(r"(\d{1,3}(?:,\d{3})*(?:\.\d{2})?|\d+(?:\.\d{2})?)", line):
                value = parse_amount(amount_match.group(1))
                if value is not None:
                    if unit_price is None:
                        unit_price = value
                    else:
                        total_price = value
                        break
            if description and unit_price is not None:
                line_items.append({
                    "description": description,
                    "quantity": float(qty_match.group(1)) if qty_match else 1.0,
                    "unit_price": unit_price,
                    "tax": None,
                    "line_total": total_price or unit_price,
                })

    return {
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "supplier_name": supplier_name,
        "customer_name": customer_name,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "currency": currency,
        "line_items": line_items,
        "raw_text": text[:5000],
        "confidence": 0.72,
        "source_file": file_name,
    }


def llm_extract_invoice(raw_text: str) -> dict[str, Any]:
    if settings.ai_provider != "ollama":
        raise InvoiceExtractionError(
            f"Unsupported AI_PROVIDER '{settings.ai_provider}'. Use AI_PROVIDER=ollama."
        )

    prompt = """Extract invoice fields and line items from the source text.
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
"""
    payload = {
        "model": settings.ollama_model,
        "format": InvoiceExtraction.model_json_schema(),
        "messages": [
            {
                "role": "system",
                "content": (
                    "Extract only source-grounded invoice facts and return the "
                    "required JSON schema. Never invent missing information."
                ),
            },
            {"role": "user", "content": f"{prompt}\n\nSOURCE DOCUMENT:\n{raw_text}"},
        ],
        "stream": False,
        "keep_alive": settings.ollama_keep_alive,
        "options": {
            "num_ctx": settings.ollama_context_length,
            "num_gpu": 0,
            "temperature": 0.0,
            "seed": 42,
        },
    }
    base_url = settings.ollama_base_url.rstrip("/")
    url = f"{base_url}/api/chat"
    response = None
    with _OLLAMA_REQUEST_SEMAPHORE:
        for attempt in range(settings.ollama_retries + 1):
            try:
                response = httpx.post(
                    url,
                    json=payload,
                    timeout=settings.ollama_timeout_seconds,
                )
                status_code = getattr(response, "status_code", 200)
                if (
                    status_code in {408, 429} or status_code >= 500
                ) and attempt < settings.ollama_retries:
                    time.sleep(min(0.5 * (2**attempt), 2))
                    continue
                response.raise_for_status()
                break
            except httpx.TimeoutException as exc:
                if attempt >= settings.ollama_retries:
                    raise InvoiceExtractionError(
                        f"Ollama request timed out at {base_url}. Increase "
                        "OLLAMA_TIMEOUT_SECONDS or reduce document size."
                    ) from exc
                time.sleep(min(0.5 * (2**attempt), 2))
            except httpx.TransportError as exc:
                if attempt >= settings.ollama_retries:
                    raise InvoiceExtractionError(
                        f"Could not connect to Ollama at {base_url}. Start the "
                        "local service with 'ollama serve' and verify it is reachable."
                    ) from exc
                time.sleep(min(0.5 * (2**attempt), 2))
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 404:
                    raise InvoiceExtractionError(
                        f"Ollama model '{settings.ollama_model}' was not found. "
                        f"Run 'ollama pull {settings.ollama_model}' or configure "
                        "OLLAMA_MODEL with an installed model."
                    ) from exc
                raise InvoiceExtractionError(
                    f"Ollama returned HTTP {exc.response.status_code} for "
                    f"{settings.ollama_model}: {exc.response.text[:500]}"
                ) from exc

    if response is None:
        raise InvoiceExtractionError(
            "Ollama did not return a response; check local service health and retry."
        )
    try:
        response_data = response.json()
        content = response_data["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Ollama returned an empty structured response.")
        parsed = InvoiceExtraction.model_validate_json(content)
    except (httpx.DecodingError, KeyError, TypeError, ValueError, ValidationError) as exc:
        raise InvoiceSchemaError(
            f"Ollama returned invalid invoice JSON or schema data: {exc}"
        ) from exc
    return parsed.model_dump()


def _split_text(raw_text: str, max_chars: int = 24000, overlap: int = 300) -> list[str]:
    if not raw_text:
        return [""]
    chunks = []
    start = 0
    while start < len(raw_text):
        end = min(start + max_chars, len(raw_text))
        if end < len(raw_text):
            newline = raw_text.rfind("\n", start + max_chars // 2, end)
            if newline > start:
                end = newline + 1
        chunks.append(raw_text[start:end])
        if end == len(raw_text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def _ground_extraction(result: dict[str, Any], raw_text: str) -> dict[str, Any]:
    assessments = {item["field"]: item for item in result["field_assessments"]}
    expected_fields = {
        "invoice_number",
        "invoice_date",
        "supplier_name",
        "customer_name",
        "subtotal",
        "tax",
        "total",
        "currency",
    }
    if set(assessments) != expected_fields or len(result["field_assessments"]) != len(expected_fields):
        raise InvoiceSchemaError("LLM output must assess every invoice field exactly once.")

    uncertain_fields: set[str] = set()
    for field, assessment in assessments.items():
        value = result[field]
        evidence = assessment["evidence"]
        label_pattern = _MONETARY_LABEL_PATTERNS.get(field)
        label_evidence = re.sub(r"\s+", " ", evidence or "")
        evidence_is_supported = _evidence_matches_source(
            evidence,
            raw_text,
            field,
        ) and (
            label_pattern is None
            or re.search(label_pattern, label_evidence, flags=re.IGNORECASE) is not None
        )
        if evidence is not None and not evidence_is_supported:
            assessment["evidence"] = None
            evidence = None

        if (
            field == "invoice_date"
            and assessment["status"] != "missing"
            and (value is not None or assessment["status"] == "uncertain")
            and evidence_is_supported
        ):
            normalized_date, ambiguous_date = _invoice_date_from_evidence(evidence)
            if normalized_date is not None:
                result[field] = normalized_date
                assessment["status"] = "found"
                continue
            if ambiguous_date:
                result[field] = None
                assessment["status"] = "uncertain"
                uncertain_fields.add(field)
                continue
        if assessment["status"] == "missing":
            if value is not None or evidence is not None:
                raise InvoiceSchemaError(f"Missing field {field} must have null value and evidence.")
            continue
        if value is None:
            if assessment["status"] == "found":
                raise InvoiceSchemaError(f"Found field {field} cannot have a null value.")
            if assessment["status"] == "uncertain":
                uncertain_fields.add(field)
            continue
        if (
            not evidence_is_supported
            or not _evidence_supports_value(value, evidence)
        ):
            result[field] = None
            assessment["status"] = "uncertain"
            uncertain_fields.add(field)
        elif assessment["status"] == "uncertain":
            uncertain_fields.add(field)

    for item in result["line_items"]:
        evidence = item["evidence"]
        if not _evidence_matches_source(evidence, raw_text):
            item["evidence"] = None
            item["description"] = None
            item["quantity"] = None
            item["unit_price"] = None
            item["tax"] = None
            item["line_total"] = None
            item["confidence"] = 0.0
            continue
        for field in ("description", "quantity", "unit_price", "tax", "line_total"):
            value = item[field]
            if value is not None and not _evidence_supports_value(value, evidence):
                item[field] = None
                item["confidence"] = 0.0

    result["uncertain_fields"] = sorted(uncertain_fields)
    return result


def _same_value(left: str | float | None, right: str | float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=0.005)
    return re.sub(r"\s+", " ", str(left)).strip().casefold() == re.sub(
        r"\s+", " ", str(right)
    ).strip().casefold()


def _merge_extractions(results: list[dict[str, Any]], file_name: str) -> dict[str, Any]:
    fields = (
        "invoice_number",
        "invoice_date",
        "supplier_name",
        "customer_name",
        "subtotal",
        "tax",
        "total",
        "currency",
    )
    merged: dict[str, Any] = {
        field: None for field in fields
    }
    merged_assessments = []
    uncertain_fields = []

    for field in fields:
        candidates = [
            (result[field], next(item for item in result["field_assessments"] if item["field"] == field))
            for result in results
        ]
        values = [(value, assessment) for value, assessment in candidates if value is not None]
        unique_values: list[tuple[str | float, dict[str, Any]]] = []
        for value, assessment in values:
            if not any(_same_value(value, existing) for existing, _ in unique_values):
                unique_values.append((value, assessment))

        if len(unique_values) > 1:
            best_assessment = max(
                (assessment for _, assessment in unique_values),
                key=lambda item: item["confidence"],
            )
            status = "uncertain"
            value = None
            uncertain_fields.append(field)
        elif unique_values:
            value, best_assessment = max(
                unique_values,
                key=lambda candidate: candidate[1]["confidence"],
            )
            status = (
                "uncertain"
                if best_assessment["status"] == "uncertain"
                else "found"
            )
            if status == "uncertain":
                uncertain_fields.append(field)
        else:
            uncertain_assessments = [
                assessment
                for _, assessment in candidates
                if assessment["status"] == "uncertain"
            ]
            if uncertain_assessments:
                best_assessment = max(
                    uncertain_assessments,
                    key=lambda item: item["confidence"],
                )
                status = "uncertain"
                uncertain_fields.append(field)
            else:
                best_assessment = max(
                    (assessment for _, assessment in candidates),
                    key=lambda item: item["confidence"],
                )
                status = "missing"
            value = None

        merged[field] = value
        merged_assessments.append({
            "field": field,
            "status": status,
            "confidence": best_assessment["confidence"],
            "evidence": best_assessment["evidence"] if status != "missing" else None,
        })

    line_items_by_evidence: dict[str, dict[str, Any]] = {}
    for result in results:
        for item in result["line_items"]:
            if not any(item.get(field) is not None for field in (
                "description",
                "quantity",
                "unit_price",
                "tax",
                "line_total",
            )):
                continue
            evidence_key = re.sub(r"\s+", " ", item.get("evidence") or "").strip().casefold()
            if not evidence_key:
                continue
            previous = line_items_by_evidence.get(evidence_key)
            if previous is None or item["confidence"] > previous["confidence"]:
                line_items_by_evidence[evidence_key] = item

    merged["line_items"] = list(line_items_by_evidence.values())
    merged["field_assessments"] = merged_assessments
    merged["uncertain_fields"] = sorted(uncertain_fields)
    merged["confidence"] = round(
        sum(item["confidence"] for item in merged_assessments) / len(fields),
        4,
    )
    merged["source_file"] = file_name
    merged["source_type"] = "ollama_chat"
    merged["model"] = settings.ollama_model
    merged["chunks_processed"] = len(results)
    return merged


def _structured_spreadsheet_result(
    metadata: dict[str, tuple[str, str]],
    line_items: list[dict[str, Any]],
    header_count: int,
    file_name: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    assessments = []
    uncertain_fields = []
    for field in (
        "invoice_number",
        "invoice_date",
        "supplier_name",
        "customer_name",
        "subtotal",
        "tax",
        "total",
        "currency",
    ):
        entry = metadata.get(field)
        value: Any = entry[0] if entry else None
        evidence = entry[1] if entry else None
        status = "found" if entry else "missing"
        if field in {"subtotal", "tax", "total"} and entry:
            value = parse_amount(str(value))
            if value is None:
                status = "uncertain"
        elif field == "invoice_date" and entry:
            value, ambiguous = _invoice_date_from_evidence(f"Date: {value}")
            if value is None:
                status = "uncertain"
                if ambiguous or entry:
                    uncertain_fields.append(field)
        elif field == "currency" and entry:
            value = normalize_currency(str(value))
        result[field] = value
        assessments.append({
            "field": field,
            "status": status,
            "confidence": 1.0 if status == "found" else 0.0,
            "evidence": evidence,
        })
        if status == "uncertain" and field not in uncertain_fields:
            uncertain_fields.append(field)

    try:
        validated = InvoiceExtraction.model_validate({
            **result,
            "line_items": line_items,
            "field_assessments": assessments,
            "uncertain_fields": sorted(uncertain_fields),
        })
    except ValidationError as exc:
        raise InvoiceSchemaError(
            "Deterministic table extraction failed invoice schema validation."
        ) from exc

    return {
        **validated.model_dump(),
        "line_items": line_items,
        "confidence": round(
            sum(item["confidence"] for item in assessments) / len(assessments),
            4,
        ),
        "source_file": file_name,
        "source_type": "structured_table",
        "model": None,
        "chunks_processed": 0,
        "llm_calls": 0,
        "table_header_count": header_count,
        "line_item_source": "structured_table",
    }


def extract_invoice_data(
    raw_text: str,
    file_name: str,
    structured_tables: list[dict[str, Any]] | None = None,
    source_type: str | None = None,
) -> dict[str, Any]:
    if not raw_text or not raw_text.strip():
        raise InvoiceExtractionError(
            "Invoice extraction requires non-empty source text."
        )
    tables = structured_tables or []
    structured_line_items, header_count = extract_table_line_items(tables)
    if source_type == "spreadsheet" and structured_line_items and header_count:
        metadata, _ = extract_labeled_metadata(tables)
        if all(metadata.get(field) for field in (
            "invoice_number",
            "supplier_name",
            "total",
        )):
            return _structured_spreadsheet_result(
                metadata,
                structured_line_items,
                header_count,
                file_name,
            )

    results = [
        _ground_extraction(llm_extract_invoice(chunk), chunk)
        for chunk in _split_text(raw_text)
    ]
    merged = _merge_extractions(results, file_name)
    merged["llm_calls"] = len(results)
    if structured_line_items:
        merged["line_items"] = structured_line_items
        merged["line_item_source"] = "structured_table"
        merged["table_header_count"] = header_count
    else:
        merged["line_item_source"] = "ollama"
    return merged
