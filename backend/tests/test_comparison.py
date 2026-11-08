import pytest

from app.services.validation import compare_documents


@pytest.mark.parametrize(
    ("left_type", "right_type"),
    [("pdf", "pdf"), ("pdf", "xlsx")],
)
def test_comparison_detects_line_item_and_invoice_discrepancies(left_type, right_type):
    left = {
        "source_type": left_type,
        "invoice_number": "INV-10",
        "supplier_name": "Northwind Ltd",
        "subtotal": 100.0,
        "tax": 10.0,
        "total": 110.0,
        "line_items": [{
            "description": "Widget",
            "quantity": 2.0,
            "unit_price": 50.0,
            "line_total": 100.0,
        }],
    }
    right = {
        **left,
        "source_type": right_type,
        "total": 111.0,
        "line_items": [{
            "description": "Widget",
            "quantity": 2.0,
            "unit_price": 50.0,
            "line_total": 101.0,
        }],
    }

    result = compare_documents(left, right)

    assert result["status"] == "MISMATCH"
    assert {item["field"] for item in result["mismatched"]} >= {
        "total",
        "line_items[widget].line_total",
    }


def test_comparison_reports_missing_line_items():
    result = compare_documents(
        {"invoice_number": "INV-10", "line_items": [{"description": "Widget"}]},
        {"invoice_number": "INV-10", "line_items": []},
    )

    assert result["status"] == "PARTIAL"
    assert result["missing"][0]["field"] == "line_items[widget]"
