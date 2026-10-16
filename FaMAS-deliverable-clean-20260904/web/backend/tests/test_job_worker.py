from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from app.models.document import Document
from app.models.processing_job import ProcessingJob
from app.services.job_worker import claim_next_pending_pipeline_job, process_next_pending_pipeline_job

from conftest import create_knowledge_base, create_user


def test_process_next_pending_pipeline_job_runs_oldest_pending_job(
    db_session: Session,
    db_session_factory: sessionmaker[Session],
) -> None:
    user = create_user(db_session, "worker_owner")
    knowledge_base = create_knowledge_base(db_session)
    document = _create_document(db_session, knowledge_base.id, user.id)
    first_job = _create_job(db_session, document.id, "parse_pdf", "pending")
    second_job = _create_job(db_session, document.id, "build_graph", "pending")
    called_job_ids: list[int] = []

    processed = process_next_pending_pipeline_job(
        runner=called_job_ids.append,
        session_factory=db_session_factory,
    )

    assert processed is True
    assert called_job_ids == [first_job.id]
    assert second_job.id not in called_job_ids
    db_session.refresh(first_job)
    db_session.refresh(document)
    assert first_job.status == "running"
    assert document.status == "parse_pdf_running"


def test_process_next_pending_pipeline_job_ignores_running_and_finished_jobs(
    db_session: Session,
    db_session_factory: sessionmaker[Session],
) -> None:
    user = create_user(db_session, "idle_worker_owner")
    knowledge_base = create_knowledge_base(db_session)
    document = _create_document(db_session, knowledge_base.id, user.id)
    _create_job(db_session, document.id, "parse_pdf", "running")
    _create_job(db_session, document.id, "build_graph", "success")
    called_job_ids: list[int] = []

    processed = process_next_pending_pipeline_job(
        runner=called_job_ids.append,
        session_factory=db_session_factory,
    )

    assert processed is False
    assert called_job_ids == []


def test_claim_next_pending_pipeline_job_claims_each_job_once(
    db_session: Session,
    db_session_factory: sessionmaker[Session],
) -> None:
    user = create_user(db_session, "claim_owner")
    knowledge_base = create_knowledge_base(db_session)
    first_document = _create_document(db_session, knowledge_base.id, user.id)
    second_document = _create_document(db_session, knowledge_base.id, user.id)
    first_job = _create_job(db_session, first_document.id, "parse_pdf", "pending")
    second_job = _create_job(db_session, second_document.id, "build_graph", "pending")

    first_claim = claim_next_pending_pipeline_job(session_factory=db_session_factory)
    second_claim = claim_next_pending_pipeline_job(session_factory=db_session_factory)
    empty_claim = claim_next_pending_pipeline_job(session_factory=db_session_factory)

    assert first_claim == first_job.id
    assert second_claim == second_job.id
    assert empty_claim is None


def _create_document(db: Session, knowledge_base_id: int, owner_user_id: int) -> Document:
    document = Document(
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
        filename="document.pdf",
        original_path="/tmp/document.pdf",
        file_size_bytes=128,
        status="uploaded",
        is_deleted=False,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _create_job(db: Session, document_id: int, stage: str, status: str) -> ProcessingJob:
    job = ProcessingJob(
        document_id=document_id,
        stage=stage,
        status=status,
        log_path="",
        error_message="",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job
