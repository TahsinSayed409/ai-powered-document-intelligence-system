import math
import re
from typing import Any


def normalize_text(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


def round_money(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 2)


def validate_invoice(
    extracted: dict[str, Any],
    existing_invoices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    status = "VALID"
    uncertain_fields = set(extracted.get("uncertain_fields") or [])
    duplicate_candidates = []

    required_fields = [
        "invoice_number",
        "invoice_date",
        "supplier_name",
        "customer_name",
        "subtotal",
        "tax",
        "total",
    ]
    for field in required_fields:
        value = extracted.get(field)
        if value in (None, "", "null"):
            issues.append({
                "severity": "warning",
                "field": field,
                "message": (
                    f"Uncertain {field.replace('_', ' ')}; manual review is required."
                    if field in uncertain_fields
                    else f"Missing {field.replace('_', ' ')}."
                ),
            })
            if status == "VALID":
                status = "REQUIRES_REVIEW" if field in uncertain_fields else "WARNING"
        elif field in uncertain_fields:
            issues.append({
                "severity": "warning",
                "field": field,
                "message": f"Uncertain {field.replace('_', ' ')}; manual review is required.",
            })
            status = "REQUIRES_REVIEW"

    if extracted.get("line_items"):
        line_items = extracted["line_items"]
        complete_line_totals = all(item.get("line_total") is not None for item in line_items)
        line_total = sum(float(item["line_total"]) for item in line_items if item.get("line_total") is not None)
        for index, item in enumerate(line_items, start=1):
            quantity = item.get("quantity")
            unit_price = item.get("unit_price")
            item_total = item.get("line_total")
            if quantity is not None and float(quantity) < 0:
                issues.append({
                    "severity": "warning",
                    "field": f"line_items[{index}].quantity",
                    "message": "Line item quantity is negative; review the source document.",
                })
            if quantity is not None and unit_price is not None and item_total is not None:
                expected_item_total = float(quantity) * float(unit_price)
                if not math.isclose(expected_item_total, float(item_total), abs_tol=0.02, rel_tol=0.01):
                    issues.append({
                        "severity": "error",
                        "field": f"line_items[{index}].line_total",
                        "message": "Line total is inconsistent with quantity multiplied by unit price.",
                    })
                    status = "INVALID"
        subtotal = extracted.get("subtotal")
        if subtotal is not None and complete_line_totals and not math.isclose(
            float(subtotal), line_total, abs_tol=0.02, rel_tol=0.01
        ):
            issues.append({
                "severity": "warning",
                "field": "subtotal",
                "message": (
                    "Subtotal does not match the sum of line item totals; review "
                    "rounding, discounts, or other invoice adjustments."
                ),
            })
            if status == "VALID":
                status = "WARNING"
        elif subtotal is not None and not complete_line_totals:
            issues.append({
                "severity": "warning",
                "field": "line_items",
                "message": "Some line items have no line total; subtotal could not be fully verified.",
            })
            if status == "VALID":
                status = "WARNING"

    subtotal = extracted.get("subtotal")
    tax = extracted.get("tax")
    total = extracted.get("total")
    if subtotal is not None and total is not None:
        expected_delta = float(subtotal) + float(tax or 0)
        if abs(float(total) - expected_delta) > 0.02:
            issues.append({
                "severity": "warning",
                "field": "total",
                "message": (
                    "Total is inconsistent with subtotal and tax; review rounding "
                    "or additional charges/discounts."
                ),
            })
            if status == "VALID":
                status = "WARNING"

    if extracted.get("invoice_number") and extracted.get("supplier_name"):
        supplier = normalize_text(extracted.get("supplier_name"))
        if len(supplier) < 3:
            issues.append({
                "severity": "warning",
                "field": "supplier_name",
                "message": "Supplier name is unusually short or incomplete.",
            })

    for existing in existing_invoices or []:
        duplicate = detect_duplicate(extracted, existing)
        if duplicate["classification"] != "distinct":
            duplicate_candidates.append({
                "classification": duplicate["classification"],
                "score": duplicate["score"],
                "invoice_number": existing.get("invoice_number"),
            })
            issues.append({
                "severity": "warning",
                "field": "invoice_number",
                "message": f"Invoice resembles an existing {duplicate['classification'].replace('_', ' ')}.",
            })
            if status != "INVALID":
                status = "REQUIRES_REVIEW"

    if not issues:
        summary = "No validation issues found."
    else:
        severity_labels = {"error": 3, "warning": 2, "info": 1}
        highest = max(issues, key=lambda x: severity_labels.get(x["severity"], 0))
        summary = f"Validation reported {len(issues)} issue(s). Highest severity: {highest['severity'].upper()}."

    if any(issue["severity"] == "error" for issue in issues):
        status = "INVALID"
    elif status != "REQUIRES_REVIEW" and issues and status == "VALID":
        status = "WARNING"

    return {
        "status": status,
        "issues": issues,
        "summary": summary,
        "duplicate_candidates": duplicate_candidates,
    }


def compare_documents(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
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
    result = {"matched": [], "mismatched": [], "missing": [], "warnings": []}

    for field in fields:
        a = first.get(field)
        b = second.get(field)
        if a in (None, "") and b in (None, ""):
            continue
        if a in (None, "") or b in (None, ""):
            result["missing"].append({"field": field, "left": a, "right": b})
            continue
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=0.02):
                result["matched"].append({"field": field, "value": a})
            else:
                result["mismatched"].append({"field": field, "left": a, "right": b})
        else:
            if normalize_text(str(a)) == normalize_text(str(b)):
                result["matched"].append({"field": field, "value": a})
            else:
                result["mismatched"].append({"field": field, "left": a, "right": b})

    first_items = first.get("line_items") or []
    remaining_items = list(second.get("line_items") or [])
    for item_number, left_item in enumerate(first_items, start=1):
        left_description = normalize_text(left_item.get("description"))
        match_index = next(
            (
                index
                for index, right_item in enumerate(remaining_items)
                if normalize_text(right_item.get("description")) == left_description
            ),
            None,
        )
        field_prefix = f"line_items[{left_description or item_number}]"
        if match_index is None:
            result["missing"].append({
                "field": field_prefix,
                "left": left_item,
                "right": None,
            })
            continue
        right_item = remaining_items.pop(match_index)
        item_fields = ("quantity", "unit_price", "tax", "line_total")
        for field in item_fields:
            left_value = left_item.get(field)
            right_value = right_item.get(field)
            if left_value is None and right_value is None:
                continue
            if left_value is None or right_value is None:
                result["missing"].append({
                    "field": f"{field_prefix}.{field}",
                    "left": left_value,
                    "right": right_value,
                })
            elif isinstance(left_value, (int, float)) and isinstance(right_value, (int, float)):
                if math.isclose(float(left_value), float(right_value), rel_tol=0.0, abs_tol=0.02):
                    result["matched"].append({
                        "field": f"{field_prefix}.{field}",
                        "value": left_value,
                    })
                else:
                    result["mismatched"].append({
                        "field": f"{field_prefix}.{field}",
                        "left": left_value,
                        "right": right_value,
                    })
            elif normalize_text(str(left_value)) != normalize_text(str(right_value)):
                result["mismatched"].append({
                    "field": f"{field_prefix}.{field}",
                    "left": left_value,
                    "right": right_value,
                })
        if normalize_text(right_item.get("description")) != left_description:
            result["mismatched"].append({
                "field": f"{field_prefix}.description",
                "left": left_item.get("description"),
                "right": right_item.get("description"),
            })

    for item_number, right_item in enumerate(remaining_items, start=1):
        result["missing"].append({
            "field": f"right_line_items[{item_number}]",
            "left": None,
            "right": right_item,
        })

    if result["mismatched"]:
        result["status"] = "MISMATCH"
    elif result["missing"]:
        result["status"] = "PARTIAL"
    else:
        result["status"] = "MATCH"
    return result


def detect_duplicate(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    left_number = normalize_text(first.get("invoice_number"))
    right_number = normalize_text(second.get("invoice_number"))
    same_number = bool(left_number and right_number and left_number == right_number)
    left_supplier = normalize_text(first.get("supplier_name"))
    right_supplier = normalize_text(second.get("supplier_name"))
    same_supplier = bool(left_supplier and right_supplier and left_supplier == right_supplier)
    left_date = normalize_text(first.get("invoice_date"))
    right_date = normalize_text(second.get("invoice_date"))
    same_date = bool(left_date and right_date and left_date == right_date)
    same_amount = False
    if first.get("total") is not None and second.get("total") is not None:
        same_amount = math.isclose(float(first["total"]), float(second["total"]), rel_tol=0.01, abs_tol=0.02)

    score = sum([
        1 if same_number else 0,
        1 if same_supplier else 0,
        1 if same_date else 0,
        1 if same_amount else 0,
    ])
    if score >= 3:
        classification = "duplicate"
    elif score >= 2:
        classification = "possible_duplicate"
    else:
        classification = "distinct"

    return {
        "classification": classification,
        "score": score,
        "same_invoice_number": same_number,
        "same_supplier": same_supplier,
        "same_date": same_date,
        "same_amount": same_amount,
    }
