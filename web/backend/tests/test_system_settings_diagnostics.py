from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.processing_job import ProcessingJob

from conftest import auth_headers, create_knowledge_base, create_user


def test_system_settings_hide_diagnostic_paths_outside_development(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    admin = create_user(db_session, "admin", role="admin")
    monkeypatch.setattr(settings, "runtime_mode", "production")
    monkeypatch.setattr(settings, "enable_diagnostics", False)
    monkeypatch.setattr(settings, "project_dir", Path("F:/private/project"))
    monkeypatch.setattr(settings, "storage_dir", Path("F:/private/project/web/storage"))

    response = client.get("/api/settings/system", headers=auth_headers(admin))

    assert response.status_code == 200
    storage = response.json()["storage"]
    assert storage["diagnostics_enabled"] is False
    assert storage["chunk_size_bytes"] == settings.upload_chunk_size_bytes
    assert storage["max_upload_bytes"] == settings.max_upload_bytes
    assert "project_dir" not in storage
    assert "storage_dir" not in storage


def test_system_settings_show_diagnostic_paths_in_development(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    admin = create_user(db_session, "diagnostic_admin", role="admin")
    monkeypatch.setattr(settings, "runtime_mode", "development")
    monkeypatch.setattr(settings, "enable_diagnostics", True)
    monkeypatch.setattr(settings, "project_dir", Path("F:/local/project"))
    monkeypatch.setattr(settings, "storage_dir", Path("F:/local/project/web/storage"))

    response = client.get("/api/settings/system", headers=auth_headers(admin))

    assert response.status_code == 200
    storage = response.json()["storage"]
    assert storage["diagnostics_enabled"] is True
    assert storage["project_dir"] == "F:\\local\\project"
    assert storage["storage_dir"] == "F:\\local\\project\\web\\storage"


def test_system_settings_reports_pipeline_queue_counts(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    admin = create_user(db_session, "queue_admin", role="admin")
    user = create_user(db_session, "queue_user")
    knowledge_base = create_knowledge_base(db_session)
    first_document = _create_document(db_session, knowledge_base.id, user.id, "pending.pdf")
    second_document = _create_document(db_session, knowledge_base.id, user.id, "running.pdf")
    monkeypatch.setattr(settings, "pipeline_worker_enabled", True)
    monkeypatch.setattr(settings, "pipeline_worker_concurrency", 2)
    db_session.add_all(
        [
            ProcessingJob(document_id=first_document.id, stage="parse_pdf", status="pending"),
            ProcessingJob(document_id=second_document.id, stage="build_graph", status="running"),
        ]
    )
    db_session.commit()

    response = client.get("/api/settings/system", headers=auth_headers(admin))

    assert response.status_code == 200
    jobs = response.json()["jobs"]
    assert jobs["active_job_limit"] == 2
    assert jobs["active_job_count"] == 2
    assert jobs["pending_job_count"] == 1
    assert jobs["running_job_count"] == 1
    assert jobs["queue_slots_available"] == 1


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
