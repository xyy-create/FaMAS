from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_schema_version import DocumentSchemaVersion
from app.models.processing_job import ProcessingJob
from app.services.pipeline_runner import _build_pipeline_command
from app.services.storage_paths import knowledge_graph_run_report_dir

from conftest import create_knowledge_base, create_user


def test_build_pipeline_command_reuses_previous_schema_for_same_document(
    db_session: Session,
    runtime_dir,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "project_dir", runtime_dir)
    monkeypatch.setattr(settings, "pipeline_schema_cache_enabled", True)
    user = create_user(db_session, "schema_owner")
    knowledge_base = create_knowledge_base(db_session)
    source_pdf = runtime_dir / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    document = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        filename="document.pdf",
        original_path=str(source_pdf),
        file_size_bytes=source_pdf.stat().st_size,
        status="graph_ready",
        is_deleted=False,
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    previous_job = ProcessingJob(
        document_id=document.id,
        stage="build_graph",
        status="success",
        log_path="",
        error_message="",
    )
    current_job = ProcessingJob(
        document_id=document.id,
        stage="build_graph",
        status="pending",
        log_path="",
        error_message="",
    )
    db_session.add_all([previous_job, current_job])
    db_session.commit()
    db_session.refresh(previous_job)
    db_session.refresh(current_job)

    schema_path = runtime_dir / "schema" / "final_schema.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    schema_path.write_text("{}", encoding="utf-8")
    previous_run_id = f"web_doc_{document.id}_{previous_job.id}"
    manifest_path = knowledge_graph_run_report_dir(previous_run_id) / f"{previous_run_id}_full_pipeline_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"schema_agent": {"schema_path": str(schema_path)}}),
        encoding="utf-8",
    )

    command = _build_pipeline_command(db_session, document, current_job, f"web_doc_{document.id}_{current_job.id}")

    assert "--no-schema-agent" in command
    assert "--reuse-schema-path-when-schema-agent-disabled" in command
    assert "--allow-schema-mismatch" in command
    assert command[command.index("--schema-path") + 1] == str(schema_path)


def test_build_pipeline_command_prefers_active_web_schema(
    db_session: Session,
    runtime_dir,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "storage_dir", runtime_dir / "storage")
    monkeypatch.setattr(settings, "project_dir", runtime_dir)
    monkeypatch.setattr(settings, "pipeline_schema_cache_enabled", True)
    user = create_user(db_session, "web_schema_owner")
    knowledge_base = create_knowledge_base(db_session)
    source_pdf = runtime_dir / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    document = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        filename="document.pdf",
        original_path=str(source_pdf),
        file_size_bytes=source_pdf.stat().st_size,
        status="graph_ready",
        is_deleted=False,
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    previous_job = ProcessingJob(
        document_id=document.id,
        stage="build_graph",
        status="success",
        log_path="",
        error_message="",
    )
    current_job = ProcessingJob(
        document_id=document.id,
        stage="build_graph",
        status="pending",
        log_path="",
        error_message="",
    )
    active_schema = DocumentSchemaVersion(
        document_id=document.id,
        owner_user_id=user.id,
        version_number=1,
        title="启用 schema",
        source="user",
        schema_json=json.dumps({"schema_version": "web.v1"}, ensure_ascii=False),
        prompt_text="",
        is_active=True,
    )
    db_session.add_all([previous_job, current_job, active_schema])
    db_session.commit()
    db_session.refresh(previous_job)
    db_session.refresh(current_job)

    old_schema_path = runtime_dir / "old_schema" / "final_schema.json"
    old_schema_path.parent.mkdir(parents=True, exist_ok=True)
    old_schema_path.write_text("{}", encoding="utf-8")
    previous_run_id = f"web_doc_{document.id}_{previous_job.id}"
    manifest_path = knowledge_graph_run_report_dir(previous_run_id) / f"{previous_run_id}_full_pipeline_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps({"schema_agent": {"schema_path": str(old_schema_path)}}),
        encoding="utf-8",
    )

    command = _build_pipeline_command(db_session, document, current_job, f"web_doc_{document.id}_{current_job.id}")

    schema_path = command[command.index("--schema-path") + 1]
    assert schema_path != str(old_schema_path)
    assert schema_path.endswith("web_schema_v1.json")
    assert json.loads(open(schema_path, encoding="utf-8").read()) == {"schema_version": "web.v1"}


def test_build_pipeline_command_can_use_job_schema_override(
    db_session: Session,
    runtime_dir,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "storage_dir", runtime_dir / "storage")
    monkeypatch.setattr(settings, "project_dir", runtime_dir)
    user = create_user(db_session, "job_schema_owner")
    knowledge_base = create_knowledge_base(db_session)
    source_pdf = runtime_dir / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    document = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        filename="document.pdf",
        original_path=str(source_pdf),
        file_size_bytes=source_pdf.stat().st_size,
        status="graph_ready",
        is_deleted=False,
    )
    active_schema = DocumentSchemaVersion(
        document=document,
        owner_user_id=user.id,
        version_number=1,
        title="启用 schema",
        source="user",
        schema_json=json.dumps({"schema_version": "active.v1"}, ensure_ascii=False),
        prompt_text="",
        is_active=True,
    )
    override_schema = DocumentSchemaVersion(
        document=document,
        owner_user_id=user.id,
        version_number=2,
        title="临时 schema",
        source="user",
        schema_json=json.dumps({"schema_version": "override.v1"}, ensure_ascii=False),
        prompt_text="",
        is_active=False,
    )
    db_session.add_all([document, active_schema, override_schema])
    db_session.commit()
    db_session.refresh(document)
    db_session.refresh(override_schema)

    current_job = ProcessingJob(
        document_id=document.id,
        schema_version_id=override_schema.id,
        stage="build_graph",
        status="pending",
        log_path="",
        error_message="",
    )
    db_session.add(current_job)
    db_session.commit()
    db_session.refresh(current_job)

    command = _build_pipeline_command(db_session, document, current_job, f"web_doc_{document.id}_{current_job.id}")

    schema_path = command[command.index("--schema-path") + 1]
    assert schema_path.endswith("web_schema_v2.json")
    assert json.loads(open(schema_path, encoding="utf-8").read()) == {"schema_version": "override.v1"}


def test_build_pipeline_command_includes_source_context_ids(
    db_session: Session,
    runtime_dir,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "project_dir", runtime_dir)
    user = create_user(db_session, "context_owner")
    knowledge_base = create_knowledge_base(db_session)
    source_pdf = runtime_dir / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")
    document = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        filename="document.pdf",
        original_path=str(source_pdf),
        file_size_bytes=source_pdf.stat().st_size,
        status="graph_ready",
        is_deleted=False,
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)

    current_job = ProcessingJob(
        document_id=document.id,
        stage="build_graph",
        status="pending",
        log_path="",
        error_message="",
        payload_json=json.dumps(
            {"source_context_ids": ["s001_ch1_s1", "s002_ch1_s2"]},
            ensure_ascii=False,
        ),
    )
    db_session.add(current_job)
    db_session.commit()
    db_session.refresh(current_job)

    command = _build_pipeline_command(db_session, document, current_job, f"web_doc_{document.id}_{current_job.id}")

    source_context_args = [
        command[index + 1]
        for index, value in enumerate(command)
        if value == "--source-context-id"
    ]
    assert source_context_args == ["s001_ch1_s1", "s002_ch1_s2"]
