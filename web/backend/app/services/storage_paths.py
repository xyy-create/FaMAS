from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.models.document import Document


def user_storage_dir(user_id: int | None) -> Path:
    user_part = f"user_{user_id}" if user_id is not None else "unowned"
    return settings.storage_dir / "users" / user_part


def document_storage_dir(document: Document) -> Path:
    return user_storage_dir(document.owner_user_id) / "documents" / f"doc_{document.id}"


def document_source_dir(document: Document) -> Path:
    return document_storage_dir(document) / "source"


def document_jobs_dir(document: Document) -> Path:
    return document_storage_dir(document) / "jobs"


def document_pipeline_dir(document: Document) -> Path:
    return document_storage_dir(document) / "pipeline"


def original_pdf_path(document: Document, safe_filename: str) -> Path:
    return document_source_dir(document) / safe_filename


def pipeline_pdf_path(document: Document) -> Path:
    return document_pipeline_dir(document) / f"pipeline_doc_{document.id}.pdf"


def job_log_dir(document: Document, run_id: str) -> Path:
    return document_jobs_dir(document) / run_id


def knowledge_graph_run_dir(run_id: str) -> Path:
    return settings.storage_dir / "knowledge_graph" / "runs" / run_id


def knowledge_graph_run_images_dir(run_id: str) -> Path:
    return knowledge_graph_run_dir(run_id) / "images"


def knowledge_graph_run_artifacts_dir(run_id: str) -> Path:
    return knowledge_graph_run_dir(run_id) / "standard_outputs"


def knowledge_graph_run_report_dir(run_id: str) -> Path:
    return knowledge_graph_run_dir(run_id) / "reports"
