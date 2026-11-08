import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings
from app.services.ai_extractor import InvoiceExtractionError, extract_invoice_data

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "invoices.json"
OUTPUT_PATH = Path(__file__).parents[1] / "reports" / "evaluation_summary.json"
EVALUATED_FIELDS = [
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
    "line_items",
]
SCALAR_FIELDS = [field for field in EVALUATED_FIELDS if field != "line_items"]


def _normalized_date(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    for date_format in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%d/%m/%Y",
        "%m-%d-%Y",
        "%d-%m-%Y",
    ):
        try:
            return datetime.strptime(value.strip(), date_format).date().isoformat()
        except ValueError:
            continue
    return None


def values_match(actual, expected, field: str | None = None) -> bool:
    if actual is None or expected is None:
        return actual is None and expected is None
    if field == "invoice_date":
        return _normalized_date(actual) == _normalized_date(expected)
    if isinstance(expected, (int, float)):
        return (
            isinstance(actual, (int, float))
            and math.isclose(float(actual), float(expected), abs_tol=0.01, rel_tol=0.001)
        )
    if isinstance(expected, list):
        if not isinstance(actual, list) or len(actual) != len(expected):
            return False
        line_item_fields = ("description", "quantity", "unit_price", "tax", "line_total")
        return all(
            all(values_match(actual_item.get(field), expected_item.get(field)) for field in line_item_fields)
            for actual_item, expected_item in zip(actual, expected)
        )
    return str(actual).strip().casefold() == str(expected).strip().casefold()


def main() -> None:
    cases = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    document_results = []
    successful_documents = 0
    matching_fields = 0
    evaluated_fields = 0
    exact_invoices = 0
    field_match_counts = {field: 0 for field in EVALUATED_FIELDS}
    exact_invoice_numbers = 0
    missing_fields = 0
    correctly_missing_fields = 0

    for case in cases:
        started = time.perf_counter()
        try:
            extracted = extract_invoice_data(case["text"], case["id"])
        except InvoiceExtractionError as exc:
            elapsed = time.perf_counter() - started
            document_results.append({
                "document": case["id"],
                "success": False,
                "processing_time_seconds": round(elapsed, 6),
                "error": str(exc),
            })
            continue

        elapsed = time.perf_counter() - started
        successful_documents += 1
        field_matches = {
            field: values_match(
                extracted.get(field),
                case["expected"].get(field),
                field=field,
            )
            for field in EVALUATED_FIELDS
        }
        matching_fields += sum(field_matches.values())
        evaluated_fields += len(EVALUATED_FIELDS)
        for field, matched in field_matches.items():
            field_match_counts[field] += int(matched)
        exact_invoice_numbers += int(
            extracted.get("invoice_number") == case["expected"].get("invoice_number")
        )
        for field in SCALAR_FIELDS:
            if case["expected"].get(field) is None:
                missing_fields += 1
                correctly_missing_fields += int(extracted.get(field) is None)
        invoice_match = all(field_matches.values())
        exact_invoices += int(invoice_match)
        document_results.append({
            "document": case["id"],
            "success": True,
            "processing_time_seconds": round(elapsed, 6),
            "field_matches": field_matches,
            "field_values": {
                field: {
                    "actual": extracted.get(field),
                    "expected": case["expected"].get(field),
                }
                for field in EVALUATED_FIELDS
            },
            "invoice_exact_match": invoice_match,
        })

    total_documents = len(cases)
    total_processing_time = sum(item["processing_time_seconds"] for item in document_results)
    summary = {
        "dataset": "synthetic_labeled_invoice_fixtures",
        "real_world_dataset": False,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "provider": settings.ai_provider,
        "model": settings.ollama_model,
        "embedding_model": settings.embedding_model_name,
        "embedding_dimension": settings.embedding_dimension,
        "inference_device": "CPU",
        "hardware": "Intel Core i7-1355U, 16 GB RAM, Intel Iris Xe integrated graphics",
        "ollama_context_length": settings.ollama_context_length,
        "input_representation": "labeled synthetic extracted text; OCR accuracy not evaluated",
        "dataset_size": total_documents,
        "successful_documents": successful_documents,
        "failed_documents": total_documents - successful_documents,
        "field_level_accuracy": (
            round(matching_fields / evaluated_fields, 4) if evaluated_fields else None
        ),
        "field_level_comparison_count": evaluated_fields,
        "scalar_field_comparisons": successful_documents * len(SCALAR_FIELDS),
        "line_item_list_comparisons": successful_documents,
        "field_level_accuracy_unit": (
            "one comparison per scalar field and one all-or-nothing ordered line_items "
            "list comparison per successful extraction"
        ),
        "field_level_accuracy_by_field": {
            field: (
                round(matches / successful_documents, 4)
                if successful_documents
                else None
            )
            for field, matches in field_match_counts.items()
        },
        "exact_invoice_number_accuracy": (
            round(exact_invoice_numbers / successful_documents, 4)
            if successful_documents
            else None
        ),
        "missing_field_handling_accuracy": (
            round(correctly_missing_fields / missing_fields, 4)
            if missing_fields
            else None
        ),
        "invoice_level_accuracy": (
            round(exact_invoices / successful_documents, 4) if successful_documents else None
        ),
        "accuracy_denominator": (
            "successful extractions only; failures are reported separately"
        ),
        "processing_time_seconds": round(total_processing_time, 6),
        "average_processing_time_seconds": (
            round(total_processing_time / total_documents, 6) if total_documents else None
        ),
        "document_success_rate": (
            round(successful_documents / total_documents, 4) if total_documents else None
        ),
        "document_failure_rate": (
            round((total_documents - successful_documents) / total_documents, 4)
            if total_documents
            else None
        ),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps({"summary": summary, "documents": document_results}, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
