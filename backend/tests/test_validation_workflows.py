from app.services.validation import detect_duplicate, validate_invoice


def _invoice():
    return {
        "invoice_number": "INV-8",
        "invoice_date": "2026-02-01",
        "supplier_name": "Northwind Ltd",
        "customer_name": "Contoso",
        "subtotal": 100.0,
        "tax": 10.0,
        "total": 110.0,
        "line_items": [
            {"description": "Widget", "quantity": 2.0, "unit_price": 50.0, "line_total": 100.0},
        ],
    }


def test_uncertain_extraction_is_flagged_for_manual_review():
    invoice = _invoice()
    invoice["customer_name"] = None
    invoice["uncertain_fields"] = ["customer_name"]

    result = validate_invoice(invoice)

    assert result["status"] == "REQUIRES_REVIEW"
    assert any("Uncertain customer name" in issue["message"] for issue in result["issues"])


def test_duplicate_candidates_are_included_in_validation():
    invoice = _invoice()
    existing = _invoice()
    result = validate_invoice(invoice, [existing])

    assert result["status"] == "REQUIRES_REVIEW"
    assert result["duplicate_candidates"][0]["classification"] == "duplicate"


def test_line_item_arithmetic_inconsistency_is_invalid():
    invoice = _invoice()
    invoice["line_items"][0]["line_total"] = 95.0

    result = validate_invoice(invoice)

    assert result["status"] == "INVALID"
    assert any(issue["field"] == "line_items[1].line_total" for issue in result["issues"])


def test_missing_identity_fields_do_not_create_false_duplicate():
    result = detect_duplicate(
        {"invoice_number": None, "supplier_name": None, "invoice_date": None, "total": None},
        {"invoice_number": None, "supplier_name": None, "invoice_date": None, "total": None},
    )

    assert result["classification"] == "distinct"
