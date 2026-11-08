from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, Document, ProcessingJob, ValidationIssue, utcnow
from app.services.document_processor import _record_failure
from app.worker import claim_next_job


def _session_factory(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'worker-test.db'}")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def test_worker_claim_is_durable_and_increments_attempt(monkeypatch, tmp_path):
    engine, session_factory = _session_factory(tmp_path)
    try:
        db = session_factory()
        document = Document(
            filename="queued.pdf",
            file_type="pdf",
            storage_path="queued.pdf",
            status="queued",
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        job = ProcessingJob(
            document_id=document.id,
            job_name="extract_and_validate",
            status="queued",
            retries=0,
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        expected = (job.id, document.id)
        db.close()
        monkeypatch.setattr("app.worker.SessionLocal", session_factory)

        assert claim_next_job() == expected

        db = session_factory()
        claimed_job = db.query(ProcessingJob).filter(ProcessingJob.id == expected[0]).one()
        claimed_document = db.query(Document).filter(Document.id == expected[1]).one()
        assert claimed_job.status == "running"
        assert claimed_job.retries == 1
        assert claimed_document.status == "processing"
        db.close()
    finally:
        engine.dispose()


def test_failure_is_scheduled_for_retry_then_exhausted(tmp_path):
    engine, session_factory = _session_factory(tmp_path)
    try:
        db = session_factory()
        document = Document(
            filename="failure.csv",
            file_type="csv",
            storage_path="failure.csv",
            status="processing",
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        job = ProcessingJob(
            document_id=document.id,
            job_name="extract_and_validate",
            status="running",
            retries=1,
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        _record_failure(
            db,
            document,
            job,
            ValueError("provider unavailable"),
            stage="ai_extraction",
        )
        db.refresh(job)
        db.refresh(document)
        assert job.status == "queued"
        assert "stage=ai_extraction" in job.error_message
        assert "provider unavailable" not in job.error_message
        assert db.query(ValidationIssue).filter(
            ValidationIssue.document_id == document.id,
            ValidationIssue.field == "processing.ai_extraction",
        ).count() == 1
        assert job.finished_at > utcnow()
        assert document.status == "queued"

        job.status = "running"
        job.retries = 3
        db.commit()
        _record_failure(
            db,
            document,
            job,
            ValueError("provider unavailable"),
            stage="ai_extraction",
        )
        db.refresh(job)
        db.refresh(document)
        assert job.status == "failed"
        assert document.status == "failed"
        assert job.finished_at <= utcnow() + timedelta(seconds=1)
        db.close()
    finally:
        engine.dispose()
