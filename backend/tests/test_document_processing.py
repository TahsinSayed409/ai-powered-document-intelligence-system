import time

import pandas as pd
import pymupdf as fitz
import pytesseract
import xlwt
import pytest
from PIL import Image

from app.services.document_processor import (
    OCRUnavailableError,
    _ocr_image,
    extract_document_text,
    extract_pdf_text,
    extract_spreadsheet_text,
)


def _mock_ocr(monkeypatch):
    monkeypatch.setattr(
        "app.services.document_processor._verify_tesseract",
        lambda *_args: None,
    )
    monkeypatch.setattr(
        pytesseract,
        "image_to_data",
        lambda *_args, **_kwargs: {
            "text": ["Invoice", "No", "INV-900"],
            "conf": ["95", "90", "85"],
        },
    )


def test_extracts_a_thousand_page_pdf_efficiently(tmp_path):
    pdf_path = tmp_path / "large.pdf"
    document = fitz.open()
    for page_number in range(1000):
        page = document.new_page()
        page.insert_text((72, 72), f"Invoice page {page_number + 1}")
    document.save(pdf_path)
    document.close()

    started = time.perf_counter()
    extracted = extract_pdf_text(str(pdf_path))
    elapsed = time.perf_counter() - started

    assert len(extracted["pages"]) == 1000
    assert "Invoice page 1000" in extracted["raw_text"]
    assert elapsed < 30


def test_extracts_digital_pdf_text(tmp_path):
    pdf_path = tmp_path / "digital.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Invoice No: INV-42")
    document.save(pdf_path)
    document.close()

    extracted = extract_document_text(str(pdf_path), "pdf")

    assert "INV-42" in extracted["raw_text"]
    assert extracted["pages"][0]["word_count"] == 3


def test_ocr_supports_jpg_png_and_multipage_tiff(tmp_path, monkeypatch):
    _mock_ocr(monkeypatch)
    single_page = Image.new("RGB", (50, 50), "white")
    jpg_path = tmp_path / "invoice.jpg"
    png_path = tmp_path / "invoice.png"
    single_page.save(jpg_path)
    single_page.save(png_path)

    first_frame = Image.new("RGB", (50, 50), "white")
    second_frame = Image.new("RGB", (50, 50), "white")
    tiff_path = tmp_path / "multipage.tiff"
    first_frame.save(tiff_path, save_all=True, append_images=[second_frame])

    for path, file_type in [(jpg_path, "jpg"), (png_path, "png")]:
        extracted = extract_document_text(str(path), file_type)
        assert "INV-900" in extracted["raw_text"]
        assert extracted["pages"][0]["ocr_confidence"] > 0.8

    tiff_extracted = extract_document_text(str(tiff_path), "tiff")
    assert len(tiff_extracted["pages"]) == 2
    assert tiff_extracted["raw_text"].count("INV-900") == 2


def test_scanned_pdf_page_uses_ocr_fallback(tmp_path, monkeypatch):
    _mock_ocr(monkeypatch)
    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 100), "white").save(image_path)
    pdf_path = tmp_path / "scan.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_image(page.rect, filename=str(image_path))
    document.save(pdf_path)
    document.close()

    extracted = extract_pdf_text(str(pdf_path))

    assert extracted["pages"][0]["has_images"] is True
    assert "INV-900" in extracted["raw_text"]


def test_missing_tesseract_is_reported_as_an_operational_error(monkeypatch):
    def missing_tesseract(*_args, **_kwargs):
        raise pytesseract.TesseractNotFoundError()

    monkeypatch.setattr(pytesseract, "image_to_data", missing_tesseract)

    try:
        _ocr_image(Image.new("L", (20, 20), "white"))
    except OCRUnavailableError as exc:
        assert "Install Tesseract" in str(exc)
    else:
        raise AssertionError("Missing native OCR must be reported explicitly.")


def test_excel_and_csv_support_and_multiple_sheets(tmp_path):
    xlsx_path = tmp_path / "multiple.xlsx"
    with pd.ExcelWriter(xlsx_path, engine="openpyxl") as writer:
        pd.DataFrame([{"Invoice": "X-1", "Total": 20}]).to_excel(
            writer, sheet_name="Invoices", index=False
        )
        pd.DataFrame([{"Supplier": "Northwind"}]).to_excel(
            writer, sheet_name="Suppliers", index=False
        )

    xlsx_result = extract_spreadsheet_text(str(xlsx_path))
    assert [sheet["sheet_name"] for sheet in xlsx_result["pages"]] == ["Invoices", "Suppliers"]
    assert "Northwind" in xlsx_result["raw_text"]

    xls_path = tmp_path / "legacy.xls"
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("Legacy")
    sheet.write(0, 0, "Invoice")
    sheet.write(0, 1, "Total")
    sheet.write(1, 0, "OLD-1")
    sheet.write(1, 1, 45)
    workbook.save(str(xls_path))
    xls_result = extract_spreadsheet_text(str(xls_path))
    assert xls_result["pages"][0]["sheet_name"] == "Legacy"
    assert "OLD-1" in xls_result["raw_text"]

    csv_path = tmp_path / "invoice.csv"
    csv_path.write_text("Invoice,Total\nCSV-1,31.50\n", encoding="utf-8")
    csv_result = extract_document_text(str(csv_path), "csv")
    assert "CSV-1" in csv_result["raw_text"]
    assert "31.50" in csv_result["raw_text"]


def test_corrupt_pdf_fails_explicitly(tmp_path):
    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"not a PDF")

    with pytest.raises(fitz.FileDataError):
        extract_document_text(str(corrupt_path), "pdf")
