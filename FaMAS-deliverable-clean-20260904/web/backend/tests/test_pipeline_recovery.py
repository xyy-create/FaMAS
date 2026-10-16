from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.processing_job import ProcessingJob
from app.services.pipeline_runner import recover_interrupted_pipeline_jobs

from conftest import create_knowledge_base, create_user


def test_recover_interrupted_pipeline_jobs_marks_running_pipeline_jobs_failed(
    db_session: Session,
    runtime_dir,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "project_dir", runtime_dir)
    monkeypatch.setattr(settings, "storage_dir", runtime_dir / "web" / "storage")
    user = create_user(db_session, "owner")
    knowledge_base = create_knowledge_base(db_session)
    document = _create_document(db_session, knowledge_base.id, user.id)
    running_job = ProcessingJob(
        document_id=document.id,
        stage="build_graph",
        status="running",
        log_path="",
        error_message="",
    )
    pending_job = ProcessingJob(
        document_id=document.id,
        stage="parse_pdf",
        status="pending",
        log_path="",
        error_message="",
    )
    upload_job = ProcessingJob(
        document_id=document.id,
        stage="upload",
        status="success",
        log_path="",
        error_message="",
    )
    db_session.add_all([running_job, pending_job, upload_job])
    db_session.commit()

    recovered_count = recover_interrupted_pipeline_jobs(db_session)

    db_session.refresh(document)
    db_session.refresh(running_job)
    db_session.refresh(pending_job)
    db_session.refresh(upload_job)
    assert recovered_count == 1
    assert running_job.status == "failed"
    assert pending_job.status == "pending"
    assert "server restart" in running_job.error_message
    assert running_job.completed_at is not None
    assert pending_job.completed_at is None
    assert document.status == "failed"
    assert document.processing_completed_at is not None
    assert upload_job.status == "success"
    assert upload_job.completed_at is None


def test_recover_interrupted_pipeline_jobs_ignores_finished_jobs(db_session: Session) -> None:
    user = create_user(db_session, "finished_owner")
    knowledge_base = create_knowledge_base(db_session)
    document = _create_document(db_session, knowledge_base.id, user.id)
    success_job = ProcessingJob(
        document_id=document.id,
        stage="build_graph",
        status="success",
        log_path="",
        error_message="",
    )
    failed_job = ProcessingJob(
        document_id=document.id,
        stage="parse_pdf",
        status="failed",
        log_path="",
        error_message="previous failure",
    )
    db_session.add_all([success_job, failed_job])
    db_session.commit()

    recovered_count = recover_interrupted_pipeline_jobs(db_session)

    db_session.refresh(success_job)
    db_session.refresh(failed_job)
    assert recovered_count == 0
    assert success_job.status == "success"
    assert failed_job.status == "failed"
    assert failed_job.error_message == "previous failure"


def _create_document(db: Session, knowledge_base_id: int, owner_user_id: int) -> Document:
    document = Document(
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
        filename="document.pdf",
        original_path="/tmp/document.pdf",
        file_size_bytes=128,
        status="build_graph_running",
        is_deleted=False,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
