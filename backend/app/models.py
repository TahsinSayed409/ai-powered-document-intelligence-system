from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)
    storage_path = Column(String(500), nullable=False)
    status = Column(String(50), default="pending", nullable=False)
    validation_status = Column(String(50), default="UNKNOWN")
    error_message = Column(Text, nullable=True)
    file_size = Column(Integer, default=0)
    created_at = Column(DateTime, default=utcnow)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow)
    invoice_number = Column(String(255), nullable=True)
    invoice_date = Column(String(50), nullable=True)
    supplier_name = Column(String(255), nullable=True)
    customer_name = Column(String(255), nullable=True)
    subtotal = Column(Float, nullable=True)
    tax = Column(Float, nullable=True)
    total = Column(Float, nullable=True)
    currency = Column(String(20), nullable=True)
    extracted_data = Column(JSON, nullable=True)
    validation_result = Column(JSON, nullable=True)
    comparison_result = Column(JSON, nullable=True)


class ProcessingJob(Base):
    __tablename__ = "processing_jobs"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    job_name = Column(String(100), nullable=False)
    status = Column(String(50), default="queued")
    progress = Column(Integer, default=0)
    retries = Column(Integer, default=0)
    started_at = Column(DateTime, default=utcnow)
    finished_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)


class InvoiceLineItem(Base):
    __tablename__ = "invoice_line_items"
    __table_args__ = (UniqueConstraint("document_id", "ordinal"),)

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    ordinal = Column(Integer, nullable=False)
    description = Column(Text, nullable=True)
    quantity = Column(Float, nullable=True)
    unit_price = Column(Float, nullable=True)
    tax = Column(Float, nullable=True)
    line_total = Column(Float, nullable=True)
    evidence = Column(Text, nullable=True)
    confidence = Column(Float, nullable=True)


class ValidationIssue(Base):
    __tablename__ = "validation_issues"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    severity = Column(String(20), nullable=False)
    field = Column(String(100), nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class ManualCorrection(Base):
    __tablename__ = "manual_corrections"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    field_name = Column(String(100), nullable=False)
    old_value = Column(Text, nullable=True)
    new_value = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow)


class ComparisonResult(Base):
    __tablename__ = "comparison_results"

    id = Column(Integer, primary_key=True, index=True)
    left_document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    right_document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    comparison_data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=utcnow)


class SearchIndex(Base):
    __tablename__ = "search_index"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    text = Column(Text, nullable=False)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=utcnow)
