import csv

import pymupdf as fitz
from openpyxl import Workbook

from app.services.ai_extractor import extract_invoice_data
from app.services.document_processor import _attach_evidence_pages, extract_document_text
from app.services.table_extractor import extract_table_line_items
from app.services.validation import validate_invoice


_MISSING_RESPONSE = {
    "invoice_number": None,
    "invoice_date": None,
    "supplier_name": None,
    "customer_name": None,
    "subtotal": None,
    "tax": None,
    "total": None,
    "currency": None,
    "line_items": [],
    "uncertain_fields": [],
    "field_assessments": [
        {
            "field": field,
            "status": "missing",
            "confidence": 0.0,
            "evidence": None,
        }
        for field in (
            "invoice_number",
            "invoice_date",
            "supplier_name",
            "customer_name",
            "subtotal",
            "tax",
            "total",
            "currency",
        )
    ],
}


def _write_csv(path):
    rows = [
        ["Field", "Value", "Product", "Quantity", "Unit Price", "Tax", "Line Total"],
        ["Invoice Number", "CSV-100", "", "", "", "", ""],
        ["Invoice Date", "2026-04-04", "", "", "", "", ""],
        ["Supplier", "Northwind Supply", "", "", "", "", ""],
        ["Customer", "Example Clinic", "", "", "", "", ""],
        ["Subtotal", "30.00", "", "", "", "", ""],
        ["Tax", "3.00", "", "", "", "", ""],
        ["Grand Total", "33.00", "", "", "", "", ""],
        ["", "", "Paper", "2", "12.50", "2.50", "25.00"],
        ["", "", "Pens", "1", "5.00", "0.50", "5.00"],
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerows(rows)


def _write_xlsx(path):
    workbook = Workbook()
    metadata = workbook.active
    metadata.title = "Invoice"
    metadata.append([
        "Invoice Number",
        "Supplier",
        "Invoice Date",
        "Customer",
        "Subtotal",
        "Tax",
        "Grand Total",
    ])
    metadata.append([
        "XLS-100",
        "Northwind Supply",
        "2026-04-04",
        "Example Clinic",
        "30.00",
        "3.00",
        "33.00",
    ])

    items = workbook.create_sheet("Items")
    items.append(["Item Code", "Description", "Qty", "Rate", "Tax", "Amount"])
    items.append(["P-1", "Paper", 2, 12.5, 2.5, 25.0])
    items.append(["P-2", "Pens", 1, 5.0, 0.5, 5.0])

    notes = workbook.create_sheet("Notes")
    notes.append(["Payment terms", "Net 30"])
    workbook.save(path)
    workbook.close()


def _assert_two_items(extracted):
    items = extracted["line_items"]
    assert len(items) == 2
    assert [item["description"] for item in items] == ["Paper", "Pens"]
    assert [item["quantity"] for item in items] == [2.0, 1.0]
    assert [item["unit_price"] for item in items] == [12.5, 5.0]
    assert [item["line_total"] for item in items] == [25.0, 5.0]


def test_csv_grid_extracts_multiple_line_items_without_calling_ollama(
    tmp_path,
    monkeypatch,
):
    csv_path = tmp_path / "invoice.csv"
    _write_csv(csv_path)
    parsed = extract_document_text(str(csv_path), "csv")
    monkeypatch.setattr(
        "app.services.ai_extractor.llm_extract_invoice",
        lambda _text: (_ for _ in ()).throw(AssertionError("Ollama should be skipped")),
    )

    extracted = extract_invoice_data(
        parsed["raw_text"],
        csv_path.name,
        parsed["tables"],
        parsed["source_type"],
    )

    _assert_two_items(extracted)
    assert extracted["invoice_number"] == "CSV-100"
    assert extracted["subtotal"] == 30.0
    assert extracted["total"] == 33.0
    assert extracted["source_type"] == "structured_table"
    assert extracted["llm_calls"] == 0
    _attach_evidence_pages(extracted, parsed["page_texts"])
    assert [item["source_sheet"] for item in extracted["line_items"]] == [
        "csv",
        "csv",
    ]


def test_csv_metadata_and_summary_rows_with_item_description_are_extracted(
    tmp_path,
    monkeypatch,
):
    csv_path = tmp_path / "invoice.csv"
    rows = [
        ["invoice_no", "invoice_date", "vendor", "bill_to", "currency"],
        ["CSV-2026-1006", "2026-10-30", "Delta Catering Services", "Oakwood Events", "USD"],
        [],
        ["item_description", "qty", "unit_price", "amount"],
        ["Lunch Box", "15", "8", "120"],
        ["Bottled Water", "15", "1.5", "22.5"],
        [],
        ["subtotal", "142.5"],
        ["tax", "14.25"],
        ["total", "156.75"],
    ]
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerows(rows)

    parsed = extract_document_text(str(csv_path), "csv")
    monkeypatch.setattr(
        "app.services.ai_extractor.llm_extract_invoice",
        lambda _text: (_ for _ in ()).throw(AssertionError("Ollama should be skipped")),
    )

    extracted = extract_invoice_data(
        parsed["raw_text"],
        csv_path.name,
        parsed["tables"],
        parsed["source_type"],
    )

    assert extracted["invoice_number"] == "CSV-2026-1006"
    assert extracted["invoice_date"] == "2026-10-30"
    assert extracted["supplier_name"] == "Delta Catering Services"
    assert extracted["customer_name"] == "Oakwood Events"
    assert extracted["currency"] == "USD"
    assert extracted["subtotal"] == 142.5
    assert extracted["tax"] == 14.25
    assert extracted["total"] == 156.75
    assert [
        (
            item["description"],
            item["quantity"],
            item["unit_price"],
            item["line_total"],
        )
        for item in extracted["line_items"]
    ] == [
        ("Lunch Box", 15.0, 8.0, 120.0),
        ("Bottled Water", 15.0, 1.5, 22.5),
    ]
    assert extracted["source_type"] == "structured_table"
    assert extracted["llm_calls"] == 0
    assert extracted["table_header_count"] == 1
    assert not extracted["uncertain_fields"]

    assessments = {
        assessment["field"]: assessment
        for assessment in extracted["field_assessments"]
    }
    assert all(assessment["status"] == "found" for assessment in assessments.values())
    assert all(assessment["confidence"] == 1.0 for assessment in assessments.values())
    for field, value in {
        "invoice_number": "CSV-2026-1006",
        "invoice_date": "2026-10-30",
        "supplier_name": "Delta Catering Services",
        "customer_name": "Oakwood Events",
        "currency": "USD",
    }.items():
        assessment = assessments[field]
        assert assessment["status"] == "found"
        assert value in assessment["evidence"]
        assert assessment["evidence"] in parsed["raw_text"]

    for field, value in {
        "subtotal": "142.5",
        "tax": "14.25",
        "total": "156.75",
    }.items():
        assessment = assessments[field]
        assert assessment["status"] == "found"
        assert value in assessment["evidence"]
        assert assessment["evidence"] in parsed["raw_text"]

    _attach_evidence_pages(extracted, parsed["page_texts"])
    assert all(
        assessments[field]["source_page"] == 1
        and assessments[field]["source_sheet"] == "csv"
        for field in assessments
    )
    assert all(
        item["source_page"] == 1 and item["source_sheet"] == "csv"
        for item in extracted["line_items"]
    )
    assert all(item["evidence"] in parsed["raw_text"] for item in extracted["line_items"])


def test_xlsx_multiple_sheets_map_metadata_and_item_columns_deterministically(
    tmp_path,
    monkeypatch,
):
    xlsx_path = tmp_path / "invoice.xlsx"
    _write_xlsx(xlsx_path)
    parsed = extract_document_text(str(xlsx_path), "xlsx")
    monkeypatch.setattr(
        "app.services.ai_extractor.llm_extract_invoice",
        lambda _text: (_ for _ in ()).throw(AssertionError("Ollama should be skipped")),
    )

    extracted = extract_invoice_data(
        parsed["raw_text"],
        xlsx_path.name,
        parsed["tables"],
        parsed["source_type"],
    )

    _assert_two_items(extracted)
    assert extracted["invoice_number"] == "XLS-100"
    assert extracted["invoice_date"] == "2026-04-04"
    assert extracted["supplier_name"] == "Northwind Supply"
    assert extracted["customer_name"] == "Example Clinic"
    assert extracted["total"] == 33.0
    assert len(parsed["pages"]) == 3
    assert extracted["llm_calls"] == 0
    _attach_evidence_pages(extracted, parsed["page_texts"])
    invoice_date = next(
        item for item in extracted["field_assessments"]
        if item["field"] == "invoice_date"
    )
    assert invoice_date["source_page"] == 1
    assert [item["source_sheet"] for item in extracted["line_items"]] == [
        "Items",
        "Items",
    ]


def test_xlsx_metadata_and_line_items_in_different_columns(tmp_path, monkeypatch):
    xlsx_path = tmp_path / "columns.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append([
        "Field",
        "Value",
        "Item Code",
        "Description",
        "Qty",
        "Unit Price",
        "Tax",
        "Line Total",
    ])
    for field, value in [
        ("Invoice Number", "XLS-COLUMNS"),
        ("Invoice Date", "2026-04-04"),
        ("Supplier", "Northwind Supply"),
        ("Subtotal", "25.00"),
        ("Tax", "2.50"),
        ("Grand Total", "27.50"),
    ]:
        sheet.append([field, value])
    sheet.append([None, None, "A-17", "Paper", 2, 12.5, 2.5, 25.0])
    workbook.save(xlsx_path)
    workbook.close()
    parsed = extract_document_text(str(xlsx_path), "xlsx")
    monkeypatch.setattr(
        "app.services.ai_extractor.llm_extract_invoice",
        lambda _text: (_ for _ in ()).throw(AssertionError("Ollama should be skipped")),
    )

    extracted = extract_invoice_data(
        parsed["raw_text"],
        xlsx_path.name,
        parsed["tables"],
        parsed["source_type"],
    )

    assert extracted["invoice_number"] == "XLS-COLUMNS"
    assert len(extracted["line_items"]) == 1
    assert extracted["line_items"][0]["description"] == "Paper"
    assert extracted["line_items"][0]["quantity"] == 2.0
    assert extracted["line_items"][0]["unit_price"] == 12.5
    assert extracted["line_items"][0]["line_total"] == 25.0


def test_digital_pdf_table_rows_reach_model_and_are_preserved(tmp_path, monkeypatch):
    pdf_path = tmp_path / "invoice.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(
        fitz.Rect(40, 40, 560, 750),
        "\n".join([
            "Invoice Number: PDF-100",
            "Item | Description | Qty | Unit Price | Line Total",
            "P-1 | Paper | 2 | 12.50 | 25.00",
            "P-2 | Pens | 1 | 5.00 | 5.00",
        ]),
        fontsize=12,
    )
    document.save(pdf_path)
    document.close()
    parsed = extract_document_text(str(pdf_path), "pdf")
    llm_inputs = []
    monkeypatch.setattr(
        "app.services.ai_extractor.llm_extract_invoice",
        lambda text: (llm_inputs.append(text) or _MISSING_RESPONSE.copy()),
    )

    extracted = extract_invoice_data(
        parsed["raw_text"],
        pdf_path.name,
        parsed["tables"],
        parsed["source_type"],
    )

    _assert_two_items(extracted)
    assert len(llm_inputs) == 1
    assert "Item | Description | Qty | Unit Price | Line Total" in llm_inputs[0]
    assert "P-2 | Pens | 1 | 5.00 | 5.00" in llm_inputs[0]
    _attach_evidence_pages(extracted, parsed["page_texts"])
    assert [item["source_page"] for item in extracted["line_items"]] == [1, 1]


def test_digital_pdf_field_evidence_is_retained_and_page_mapped(tmp_path, monkeypatch):
    pdf_path = tmp_path / "digital_invoice.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Invoice Number: PDF-VALID-1")
    document.save(pdf_path)
    document.close()
    parsed = extract_document_text(str(pdf_path), "pdf")

    provider_result = {
        **_MISSING_RESPONSE,
        "field_assessments": [
            dict(item) for item in _MISSING_RESPONSE["field_assessments"]
        ],
        "invoice_number": "PDF-VALID-1",
    }
    invoice_number_assessment = next(
        item for item in provider_result["field_assessments"]
        if item["field"] == "invoice_number"
    )
    invoice_number_assessment.update(
        status="found",
        confidence=0.99,
        evidence="Invoice Number: PDF-VALID-1",
    )
    monkeypatch.setattr(
        "app.services.ai_extractor.llm_extract_invoice",
        lambda _text: provider_result,
    )

    extracted = extract_invoice_data(
        parsed["raw_text"],
        pdf_path.name,
        parsed["tables"],
        parsed["source_type"],
    )
    _attach_evidence_pages(extracted, parsed["page_texts"])

    assessment = next(
        item for item in extracted["field_assessments"]
        if item["field"] == "invoice_number"
    )
    assert assessment["evidence"] == "Invoice Number: PDF-VALID-1"
    assert assessment["source_page"] == 1


def test_page_two_evidence_is_not_assigned_to_page_one(tmp_path):
    pdf_path = tmp_path / "two_page.pdf"
    document = fitz.open()
    first = document.new_page()
    first.insert_text((72, 72), "Invoice Number: ACCEPT-SCAN-002")
    second = document.new_page()
    second.insert_text(
        (72, 72),
        "Remittance note: Include ACCEPT-SCAN-002 with payment. Page two.",
    )
    document.save(pdf_path)
    document.close()
    parsed = extract_document_text(str(pdf_path), "pdf")
    extraction = {
        "field_assessments": [
            {
                "field": "invoice_number",
                "evidence": (
                    "Remittance note: Include ACCEPT-SCAN-002 with payment. Page two."
                ),
            },
            {
                "field": "invoice_number",
                "evidence": "ACCEPT-SCAN-002",
            },
        ],
        "line_items": [],
    }

    _attach_evidence_pages(extraction, parsed["page_texts"])

    assert extraction["field_assessments"][0]["source_page"] == 2
    assert "source_page" not in extraction["field_assessments"][1]


def test_structured_rows_leave_missing_values_null_and_flag_bad_arithmetic():
    line_items, _ = extract_table_line_items([{
        "rows": [
            ["Description", "Quantity", "Unit Price", "Line Total"],
            ["Paper", "", "12.50", "25.00"],
            ["Pens", "1", "", "5.00"],
        ],
    }])
    extracted = {
        "subtotal": 25.0,
        "tax": None,
        "total": 25.0,
        "line_items": line_items,
    }

    result = validate_invoice(extracted)

    assert result["status"] != "INVALID"
    assert line_items[0]["quantity"] is None
    assert line_items[1]["unit_price"] is None
    assert not any(
        issue["field"].endswith(".line_total")
        for issue in result["issues"]
    )


def test_table_parser_ignores_repeated_headers_and_adjustment_rows():
    line_items, header_count = extract_table_line_items([{
        "rows": [
            ["Item Code", "Description", "Qty", "Rate", "Amount"],
            ["P-1", "", "2", "12.50", "25.00"],
            ["Item Code", "Description", "Qty", "Rate", "Amount"],
            ["Discount", "", "", "", "-2.00"],
            ["Tax", "", "", "", "3.00"],
            ["P-2", "Pens", "1", "5.00", "5.00"],
        ],
    }])

    assert header_count == 2
    assert len(line_items) == 2
    assert line_items[0]["description"] == "P-1"
    assert line_items[0]["quantity"] == 2.0
    assert line_items[1]["description"] == "Pens"


def test_subtotal_reconciliation_tolerates_separate_adjustments():
    result = validate_invoice({
        "subtotal": 30.0,
        "tax": 3.0,
        "total": 35.0,
        "line_items": [
            {
                "description": "Paper",
                "quantity": 2.0,
                "unit_price": 12.5,
                "line_total": 25.0,
            },
        ],
    })

    assert result["status"] == "WARNING"
    assert all(issue["severity"] != "error" for issue in result["issues"])


def test_incorrect_line_total_is_flagged():
    result = validate_invoice({
        "subtotal": 30.0,
        "tax": 0.0,
        "total": 30.0,
        "line_items": [{
            "description": "Paper",
            "quantity": 2.0,
            "unit_price": 12.5,
            "line_total": 23.0,
        }],
    })

    assert result["status"] == "INVALID"
    assert any(issue["field"] == "line_items[1].line_total" for issue in result["issues"])
