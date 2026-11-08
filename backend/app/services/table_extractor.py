from __future__ import annotations

import math
import re
from typing import Any


_HEADER_ALIASES = {
    "description": {
        "description",
        "itemdescription",
        "item",
        "product",
        "service",
        "details",
    },
    "item_code": {"itemcode", "productcode", "sku", "code"},
    "quantity": {"quantity", "qty", "units"},
    "unit_price": {"unitprice", "rate", "price", "unitcost", "cost"},
    "tax": {"tax", "vat", "gst"},
    "line_total": {
        "linetotal",
        "amount",
        "total",
        "extendedamount",
        "extendedprice",
    },
}
_METADATA_ALIASES = {
    "invoice_number": {"invoiceno", "invoicenumber", "invoice", "invno", "inv"},
    "invoice_date": {"invoicedate", "date"},
    "supplier_name": {"supplier", "vendor", "seller", "from", "billfrom"},
    "customer_name": {"customer", "client", "billto", "shipto", "to"},
    "subtotal": {"subtotal", "netamount"},
    "tax": {"tax", "vat", "gst"},
    "total": {"grandtotal", "total", "totaldue", "amountdue", "amountpayable"},
    "currency": {"currency"},
}
_NON_ITEM_LABELS = {
    "discount",
    "grandtotal",
    "subtotal",
    "tax",
    "vat",
    "gst",
    "total",
}


def _normalized_header(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").casefold())


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"nan", "nat", "none"} else text


def _number(value: Any) -> float | None:
    text = _cell(value)
    if not text:
        return None
    cleaned = re.sub(r"[^0-9,.\-+]", "", text)
    if not cleaned or cleaned in {".", ",", "-", "+"}:
        return None
    if cleaned.count(".") > 1:
        return None
    if "," in cleaned:
        if re.fullmatch(r"[+-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?", cleaned):
            cleaned = cleaned.replace(",", "")
        elif "." not in cleaned and re.fullmatch(r"[+-]?\d+,\d{1,2}", cleaned):
            cleaned = cleaned.replace(",", ".")
        else:
            return None
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return parsed if math.isfinite(parsed) else None


def extract_table_line_items(
    tables: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    line_items: list[dict[str, Any]] = []
    header_count = 0

    for table in tables:
        rows = table.get("rows") or []
        processed_rows: set[int] = set()
        for header_index, header_row in enumerate(rows):
            normalized = [_normalized_header(value) for value in header_row]
            columns: dict[str, int] = {}
            for field, aliases in _HEADER_ALIASES.items():
                matches = [index for index, value in enumerate(normalized) if value in aliases]
                if matches:
                    columns[field] = (
                        matches[0]
                        if field != "description"
                        else next(
                            (index for index in matches if normalized[index] in {
                                "description", "product", "service", "details",
                            }),
                            matches[0],
                        )
                    )

            if (
                not any(field in columns for field in ("description", "item_code"))
                or not any(field in columns for field in ("quantity", "unit_price", "line_total"))
            ):
                continue

            header_count += 1
            for row_index in range(header_index + 1, len(rows)):
                if row_index in processed_rows:
                    continue
                processed_rows.add(row_index)
                row = rows[row_index]
                values = [_cell(value) for value in row]
                if not any(values):
                    continue
                first_text = next((value for value in values if value), "")
                first_value = _normalized_header(first_text)
                if (
                    first_value in _NON_ITEM_LABELS
                    or re.match(
                        r"^(?:discount|subtotal|grand\s*total|tax|vat|gst|total)\b",
                        first_text,
                        flags=re.IGNORECASE,
                    )
                ):
                    continue
                row_headers = [_normalized_header(value) for value in values]
                if (
                    any(value in _HEADER_ALIASES["description"] for value in row_headers)
                    and any(
                        value in (
                            _HEADER_ALIASES["quantity"]
                            | _HEADER_ALIASES["unit_price"]
                            | _HEADER_ALIASES["line_total"]
                        )
                        for value in row_headers
                    )
                ):
                    continue

                def at(field: str) -> str:
                    index = columns.get(field)
                    return values[index] if index is not None and index < len(values) else ""

                description = at("description") or at("item_code") or None
                quantity = _number(at("quantity"))
                unit_price = _number(at("unit_price"))
                tax = _number(at("tax"))
                line_total = _number(at("line_total"))
                if not any(value is not None for value in (
                    description,
                    quantity,
                    unit_price,
                    tax,
                    line_total,
                )):
                    continue

                evidence = " | ".join(value for value in values if value)
                line_items.append({
                    "description": description,
                    "quantity": quantity,
                    "unit_price": unit_price,
                    "tax": tax,
                    "line_total": line_total,
                    "evidence": evidence,
                    "confidence": 1.0,
                })

    return line_items, header_count


def extract_labeled_metadata(
    tables: list[dict[str, Any]],
) -> tuple[dict[str, tuple[str, str]], int]:
    metadata: dict[str, tuple[str, str]] = {}
    line_header_rows: set[tuple[int, int]] = set()
    for table_index, table in enumerate(tables):
        for row_index, row in enumerate(table.get("rows") or []):
            normalized = [_normalized_header(value) for value in row]
            if (
                any(value in _HEADER_ALIASES["description"] for value in normalized)
                and any(value in (
                    _HEADER_ALIASES["quantity"]
                    | _HEADER_ALIASES["unit_price"]
                    | _HEADER_ALIASES["line_total"]
                ) for value in normalized)
            ):
                line_header_rows.add((table_index, row_index))

    for table_index, table in enumerate(tables):
        rows = table.get("rows") or []
        for row_index, row in enumerate(rows):
            if (table_index, row_index) in line_header_rows:
                continue
            values = [_cell(value) for value in row]
            normalized = [_normalized_header(value) for value in values]
            metadata_columns = [
                (column, field)
                for column, label in enumerate(normalized)
                for field, aliases in _METADATA_ALIASES.items()
                if label in aliases
            ]
            if len(metadata_columns) > 1 and row_index + 1 < len(rows):
                next_values = [_cell(value) for value in rows[row_index + 1]]
                evidence = " | ".join(value for value in values if value)
                next_evidence = " | ".join(value for value in next_values if value)
                for column, field in metadata_columns:
                    value = next_values[column] if column < len(next_values) else ""
                    if value and field not in metadata:
                        metadata[field] = (
                            value,
                            f"{evidence}\n{next_evidence}",
                        )
                continue

            row_evidence = " | ".join(value for value in values if value)
            for field, aliases in _METADATA_ALIASES.items():
                for column, label in enumerate(normalized):
                    if label not in aliases or field in metadata:
                        continue
                    value = next(
                        (candidate for candidate in values[column + 1:] if candidate),
                        "",
                    )
                    if value:
                        metadata[field] = (
                            value,
                            row_evidence,
                        )

            if row_index + 1 < len(rows):
                next_values = [_cell(value) for value in rows[row_index + 1]]
                for column, label in enumerate(normalized):
                    for field, aliases in _METADATA_ALIASES.items():
                        if label not in aliases or field in metadata:
                            continue
                        value = next_values[column] if column < len(next_values) else ""
                        if value:
                            next_evidence = " | ".join(
                                _cell(candidate)
                                for candidate in rows[row_index + 1]
                                if _cell(candidate)
                            )
                            metadata[field] = (
                                value,
                                f"{row_evidence}\n{next_evidence}",
                            )

    return metadata, len(line_header_rows)
