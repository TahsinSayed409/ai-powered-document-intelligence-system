from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr


class LineItem(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str | None
    quantity: float | None
    unit_price: float | None
    tax: float | None
    line_total: float | None
    evidence: str | None
    confidence: float = Field(ge=0, le=1)


InvoiceField = Literal[
    "invoice_number",
    "invoice_date",
    "supplier_name",
    "customer_name",
    "subtotal",
    "tax",
    "total",
    "currency",
]


class FieldAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    field: InvoiceField
    status: Literal["found", "missing", "uncertain"]
    confidence: float = Field(ge=0, le=1)
    evidence: str | None


class InvoiceExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    invoice_number: str | None
    invoice_date: str | None
    supplier_name: str | None
    customer_name: str | None
    subtotal: float | None
    tax: float | None
    total: float | None
    currency: str | None
    line_items: list[LineItem]
    uncertain_fields: list[InvoiceField]
    field_assessments: list[FieldAssessment] = Field(min_length=8, max_length=8)


class ValidationIssue(BaseModel):
    severity: Literal["info", "warning", "error"]
    field: str
    message: str


class ValidationResult(BaseModel):
    status: Literal["VALID", "WARNING", "INVALID", "REQUIRES_REVIEW"]
    issues: list[ValidationIssue] = Field(default_factory=list)
    summary: str


class DocumentResponse(BaseModel):
    id: int
    filename: str
    file_type: str
    status: str
    validation_status: str
    invoice_number: str | None = None
    invoice_date: str | None = None
    supplier_name: str | None = None
    customer_name: str | None = None
    subtotal: float | None = None
    tax: float | None = None
    total: float | None = None
    currency: str | None = None
    extracted_data: dict[str, Any] | None = None
    validation_result: dict[str, Any] | None = None
    error_message: str | None = None


class CompareRequest(BaseModel):
    left_document_id: int
    right_document_id: int


class CorrectionRequest(BaseModel):
    field_name: str
    value: StrictStr | StrictFloat | StrictInt | None
