"""Generate small synthetic invoice files for Phase 5 acceptance testing."""

import argparse
import csv
import json
from pathlib import Path

import pymupdf
from openpyxl import Workbook
from PIL import Image, ImageDraw, ImageFont


FIXTURE_DIR = Path(__file__).parents[1] / "tests" / "fixtures" / "acceptance_documents"
FONT_PATH = Path(r"C:\Windows\Fonts\arial.ttf")


def _supplier_for(invoice_number: str) -> str:
    supplier_by_document = {
        "PDF": "Maple Office Supply Ltd",
        "SCAN": "Cedar Office Supply Ltd",
        "PNG": "Pine Office Supply Ltd",
        "XLSX": "Willow Office Supply Ltd",
        "CSV": "Birch Office Supply Ltd",
        "JPG": "Oak Office Supply Ltd",
    }
    document_type = invoice_number.split("-")[1]
    return supplier_by_document[document_type]


def _invoice_text(invoice_number: str) -> str:
    return "\n".join([
        "INVOICE",
        f"Invoice Number: {invoice_number}",
        "Invoice Date: 2026-10-25",
        f"Supplier: {_supplier_for(invoice_number)}",
        "Bill To: Northstar Clinic",
        "Currency: USD",
        "Item | Description | Qty | Unit Price | Line Total",
        "A-17 | Paper ream | 2 | 12.50 | 25.00",
        "B-04 | Pens | 1 | 5.00 | 5.00",
        "Subtotal: 30.00",
        "Tax: 3.00",
        "Grand Total: 33.00",
    ])


def _raster_invoice(
    invoice_number: str,
    include_customer: bool = True,
    include_subtotal: bool = True,
) -> Image.Image:
    image = Image.new("RGB", (1800, 2200), "white")
    draw = ImageDraw.Draw(image)
    if FONT_PATH.is_file():
        font = ImageFont.truetype(str(FONT_PATH), 62)
    else:
        font = ImageFont.load_default(size=48)

    lines = [
        "INVOICE",
        f"Invoice Number: {invoice_number}",
        "Invoice Date: 2026-10-25",
        f"Supplier: {_supplier_for(invoice_number)}",
        "Bill To: Northstar Clinic" if include_customer else "Bill To:",
        "Currency: USD",
        "Item | Description | Qty | Unit Price | Line Total",
        "A-17 | Paper ream | 2 | 12.50 | 25.00",
        "B-04 | Pens | 1 | 5.00 | 5.00",
    ]
    if include_subtotal:
        lines.append("Subtotal: 30.00")
    lines.extend(["Tax: 3.00", "Grand Total: 33.00"])
    for index, line in enumerate(lines):
        draw.text((120, 110 + index * 160), line, fill="black", font=font)
    return image


def _write_digital_pdf(path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_textbox(
        pymupdf.Rect(54, 60, 560, 740),
        _invoice_text("ACCEPT-PDF-001"),
        fontsize=14,
        lineheight=1.6,
        fontname="helv",
    )
    document.save(path)
    document.close()


def _write_scanned_pdf(path: Path) -> None:
    invoice_image = _raster_invoice(
        "ACCEPT-SCAN-002",
        include_customer=False,
        include_subtotal=False,
    )
    note = Image.new("RGB", (1800, 2200), "white")
    draw = ImageDraw.Draw(note)
    font = (
        ImageFont.truetype(str(FONT_PATH), 62)
        if FONT_PATH.is_file()
        else ImageFont.load_default(size=48)
    )
    draw.text((120, 120), "Remittance note: Include ACCEPT-SCAN-002", fill="black", font=font)
    draw.text((120, 280), "with payment. Page two.", fill="black", font=font)

    document = pymupdf.open()
    for image in (invoice_image, note):
        page = document.new_page(width=648, height=792)
        page.insert_image(page.rect, stream=_image_bytes(image, "PNG"))
    document.save(path)
    document.close()


def _image_bytes(image: Image.Image, format_name: str) -> bytes:
    from io import BytesIO

    stream = BytesIO()
    image.save(stream, format=format_name)
    return stream.getvalue()


def _write_spreadsheet(path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Invoice"
    sheet.append(["Field", "Value"])
    for field, value in [
        ("Invoice Number", "ACCEPT-XLSX-004"),
        ("Invoice Date", "2026-10-25"),
        ("Supplier", _supplier_for("ACCEPT-XLSX-004")),
        ("Bill To", "Northstar Clinic"),
        ("Currency", "USD"),
        ("Subtotal", "30.00"),
        ("Tax", "3.00"),
        ("Grand Total", "33.00"),
    ]:
        sheet.append([field, value])

    items = workbook.create_sheet("Items")
    items.append(["Item Code", "Description", "Qty", "Unit Price", "Tax", "Amount"])
    items.append(["A-17", "Paper ream", 2, 12.5, 2.5, 25.0])
    items.append(["B-04", "Pens", 1, 5.0, 0.5, 5.0])

    notes = workbook.create_sheet("Notes")
    notes.append(["Payment terms", "Net 30"])
    workbook.save(path)
    workbook.close()


def _write_csv(path: Path) -> None:
    rows = [
        ["Field", "Value", "Product", "Quantity", "Unit Price", "Tax", "Line Total"],
        ["Invoice Number", "ACCEPT-CSV-005", "", "", "", "", ""],
        ["Invoice Date", "2026-10-25", "", "", "", "", ""],
        ["Supplier", _supplier_for("ACCEPT-CSV-005"), "", "", "", "", ""],
        ["Bill To", "Northstar Clinic", "", "", "", "", ""],
        ["Currency", "USD", "", "", "", "", ""],
        ["Subtotal", "30.00", "", "", "", "", ""],
        ["Tax", "3.00", "", "", "", "", ""],
        ["Grand Total", "33.00", "", "", "", "", ""],
        ["", "", "Paper ream", "2", "12.50", "2.50", "25.00"],
        ["", "", "Pens", "1", "5.00", "0.50", "5.00"],
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerows(rows)


def generate_fixtures(output_dir: Path = FIXTURE_DIR) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    digital_pdf = output_dir / "digital_invoice.pdf"
    scanned_pdf = output_dir / "scanned_invoice.pdf"
    png = output_dir / "image_invoice.png"
    jpg = output_dir / "image_invoice.jpg"
    xlsx = output_dir / "spreadsheet_invoice.xlsx"
    csv_path = output_dir / "table_invoice.csv"

    _write_digital_pdf(digital_pdf)
    _write_scanned_pdf(scanned_pdf)
    _raster_invoice("ACCEPT-PNG-003").save(png, dpi=(200, 200))
    _raster_invoice("ACCEPT-JPG-006").save(jpg, format="JPEG", quality=94, dpi=(200, 200))
    _write_spreadsheet(xlsx)
    _write_csv(csv_path)

    manifest = {
        "synthetic": True,
        "documents": [
            {
                "filename": "digital_invoice.pdf",
                "format": "digital PDF",
                "expected_invoice_number": "ACCEPT-PDF-001",
                "expected_pages": 1,
                "expected_ocr": False,
                "expected_line_item_count": 2,
            },
            {
                "filename": "scanned_invoice.pdf",
                "format": "two-page image-only scanned PDF",
                "expected_invoice_number": "ACCEPT-SCAN-002",
                "expected_pages": 2,
                "expected_ocr": True,
                "expected_line_item_count": 2,
                "expected_missing_fields": ["customer_name", "subtotal"],
                "page_two_marker": "Page two",
            },
            {
                "filename": "image_invoice.png",
                "format": "PNG invoice image",
                "expected_invoice_number": "ACCEPT-PNG-003",
                "expected_pages": 1,
                "expected_ocr": True,
                "expected_line_item_count": 2,
            },
            {
                "filename": "spreadsheet_invoice.xlsx",
                "format": "XLSX invoice",
                "expected_invoice_number": "ACCEPT-XLSX-004",
                "expected_pages": 3,
                "expected_ocr": False,
                "expected_line_item_count": 2,
            },
            {
                "filename": "table_invoice.csv",
                "format": "CSV invoice",
                "expected_invoice_number": "ACCEPT-CSV-005",
                "expected_pages": 1,
                "expected_ocr": False,
                "expected_line_item_count": 2,
            },
            {
                "filename": "image_invoice.jpg",
                "format": "JPG invoice image",
                "expected_invoice_number": "ACCEPT-JPG-006",
                "expected_pages": 1,
                "expected_ocr": True,
                "expected_line_item_count": 2,
            },
        ],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return [output_dir / document["filename"] for document in manifest["documents"]]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=FIXTURE_DIR)
    args = parser.parse_args()
    for fixture in generate_fixtures(args.output_dir):
        print(fixture)
