from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.processing_job import ProcessingJob

from conftest import auth_headers, create_knowledge_base, create_user


def test_processing_jobs_for_different_documents_can_queue_together(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "pipeline_worker_enabled", True)
    user = create_user(db_session, "queue_owner")
    knowledge_base = create_knowledge_base(db_session)
    first_document = _create_document(db_session, knowledge_base.id, user.id, "first.pdf")
    second_document = _create_document(db_session, knowledge_base.id, user.id, "second.pdf")

    first_response = client.post(
        f"/api/documents/{first_document.id}/parse",
        headers=auth_headers(user),
    )
    second_response = client.post(
        f"/api/documents/{second_document.id}/build-graph",
        headers=auth_headers(user),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    jobs = list(
        db_session.scalars(
            select(ProcessingJob).where(
                ProcessingJob.document_id.in_([first_document.id, second_document.id])
            )
        )
    )
    assert {(job.document_id, job.stage, job.status) for job in jobs} == {
        (first_document.id, "parse_pdf", "pending"),
        (second_document.id, "build_graph", "pending"),
    }


def test_processing_job_reuses_same_document_same_stage_active_job(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "pipeline_worker_enabled", True)
    user = create_user(db_session, "same_stage_owner")
    knowledge_base = create_knowledge_base(db_session)
    document = _create_document(db_session, knowledge_base.id, user.id, "same.pdf")

    first_response = client.post(
        f"/api/documents/{document.id}/parse",
        headers=auth_headers(user),
    )
    second_response = client.post(
        f"/api/documents/{document.id}/parse",
        headers=auth_headers(user),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["id"] == first_response.json()["id"]


def test_processing_job_rejects_same_document_different_active_stage(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "pipeline_worker_enabled", True)
    user = create_user(db_session, "different_stage_owner")
    knowledge_base = create_knowledge_base(db_session)
    document = _create_document(db_session, knowledge_base.id, user.id, "blocked.pdf")

    first_response = client.post(
        f"/api/documents/{document.id}/parse",
        headers=auth_headers(user),
    )
    second_response = client.post(
        f"/api/documents/{document.id}/build-graph",
        headers=auth_headers(user),
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["detail"] == (
        "This document already has a processing job pending or running."
    )


def _create_document(db: Session, knowledge_base_id: int, owner_user_id: int, filename: str) -> Document:
    document = Document(
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
        filename=filename,
        original_path=f"/tmp/{filename}",
        file_size_bytes=128,
        status="uploaded",
        is_deleted=False,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
