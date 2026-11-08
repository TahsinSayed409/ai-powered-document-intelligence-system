from __future__ import annotations

import logging
import time
from datetime import timedelta

from sqlalchemy import or_
from sqlalchemy.exc import SQLAlchemyError

from app.db import Base, SessionLocal, engine
from app.models import Document, ProcessingJob, utcnow
from app.services.document_processor import MAX_JOB_ATTEMPTS, process_document

logger = logging.getLogger(__name__)
POLL_INTERVAL_SECONDS = 1
STALE_JOB_SECONDS = 3600


def recover_stale_jobs() -> None:
    db = SessionLocal()
    try:
        cutoff = utcnow() - timedelta(seconds=STALE_JOB_SECONDS)
        now = utcnow()
        stale_ids = [
            job_id
            for (job_id,) in db.query(ProcessingJob.id).filter(
                ProcessingJob.status == "running",
                ProcessingJob.started_at < cutoff,
            ).all()
        ]
        for job_id in stale_ids:
            message = "Worker lease expired before processing completed."
            requeued = db.query(ProcessingJob).filter(
                ProcessingJob.id == job_id,
                ProcessingJob.status == "running",
                ProcessingJob.started_at < cutoff,
                ProcessingJob.retries < MAX_JOB_ATTEMPTS,
            ).update(
                {
                    ProcessingJob.status: "queued",
                    ProcessingJob.finished_at: now,
                    ProcessingJob.error_message: message,
                },
                synchronize_session=False,
            )
            failed = 0
            if not requeued:
                failed = db.query(ProcessingJob).filter(
                    ProcessingJob.id == job_id,
                    ProcessingJob.status == "running",
                    ProcessingJob.started_at < cutoff,
                    ProcessingJob.retries >= MAX_JOB_ATTEMPTS,
                ).update(
                    {
                        ProcessingJob.status: "failed",
                        ProcessingJob.finished_at: now,
                        ProcessingJob.error_message: message,
                    },
                    synchronize_session=False,
                )
            if requeued or failed:
                job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
                document = db.query(Document).filter(Document.id == job.document_id).first()
                if document:
                    document.status = "queued" if requeued else "failed"
                    document.error_message = message if failed else None
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not recover stale processing jobs")
        raise
    finally:
        db.close()


def claim_next_job() -> tuple[int, int] | None:
    db = SessionLocal()
    try:
        now = utcnow()
        job = db.query(ProcessingJob).filter(
            ProcessingJob.status == "queued",
            or_(ProcessingJob.finished_at.is_(None), ProcessingJob.finished_at <= now),
        ).order_by(ProcessingJob.id).first()
        if job is None:
            return None

        job_id = job.id
        document_id = job.document_id
        claimed = db.query(ProcessingJob).filter(
            ProcessingJob.id == job_id,
            ProcessingJob.status == "queued",
        ).update(
            {
                ProcessingJob.status: "running",
                ProcessingJob.retries: ProcessingJob.retries + 1,
                ProcessingJob.started_at: now,
                ProcessingJob.finished_at: None,
                ProcessingJob.progress: 0,
            },
            synchronize_session=False,
        )
        if claimed != 1:
            db.rollback()
            return None
        document = db.query(Document).filter(Document.id == document_id).first()
        if document:
            document.status = "processing"
        db.commit()
        return job_id, document_id
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Could not claim a processing job")
        raise
    finally:
        db.close()


def run_worker() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Starting database-backed document processing worker")
    while True:
        try:
            recover_stale_jobs()
            claimed = claim_next_job()
            if claimed is None:
                time.sleep(POLL_INTERVAL_SECONDS)
                continue
            job_id, document_id = claimed
            process_document(document_id, job_id)
        except SQLAlchemyError:
            time.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_worker()
