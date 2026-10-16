from __future__ import annotations

import os
import shutil
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from pypdf import PdfWriter

from app.core.config import settings
from app.core.runtime_security import strict_runtime_mode_enabled
from app.core.security import hash_password
from app.core.validation import validate_password_strength
from app.core.time import utc_now_naive
from app.db.default_knowledge_base import (
    ADMIN_CHEMISTRY_BOOK_TITLE,
    ADMIN_CHEMISTRY_BOOK_FILENAME,
    ADMIN_CHEMISTRY_BOOK_SOURCE_DIR_NAME,
    ADMIN_CHEMISTRY_KNOWLEDGE_BASE_NAME,
    ADMIN_CHEMISTRY_KNOWLEDGE_BASE_SLUG,
    DEFAULT_KNOWLEDGE_BASE_NAME,
    DEFAULT_KNOWLEDGE_BASE_SLUG,
    default_knowledge_base_source_root,
    load_default_knowledge_book_specs,
)
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.processing_job import ProcessingJob
from app.models.user import User

DEFAULT_ADMIN_USERNAME = "admin"


def seed_initial_data(db: Session) -> None:
    ensure_default_knowledge_base(db)
    ensure_admin_user(db)
    ensure_legacy_document_owner(db)
    if settings.seed_default_knowledge_base:
        ensure_default_knowledge_base_documents(db)
        ensure_admin_chemistry_knowledge_base(db)
    db.commit()


def ensure_default_knowledge_base(db: Session) -> None:
    statement = select(KnowledgeBase).where(
        KnowledgeBase.is_deleted.is_(False),
        KnowledgeBase.slug.in_([DEFAULT_KNOWLEDGE_BASE_SLUG, "default"]),
    )
    existing = db.scalar(statement.order_by(KnowledgeBase.created_at.asc()))
    if existing is not None:
        existing.name = DEFAULT_KNOWLEDGE_BASE_NAME
        existing.slug = DEFAULT_KNOWLEDGE_BASE_SLUG
        existing.owner_user_id = None
        existing.is_deleted = False
        return

    db.add(
        KnowledgeBase(
            name=DEFAULT_KNOWLEDGE_BASE_NAME,
            slug=DEFAULT_KNOWLEDGE_BASE_SLUG,
            owner_user_id=None,
            is_deleted=False,
        )
    )


def ensure_admin_user(db: Session) -> None:
    statement = select(User).where(User.username == DEFAULT_ADMIN_USERNAME)
    existing = db.scalar(statement)
    if existing is not None:
        return

    raw_password = os.getenv("FAMAS_ADMIN_PASSWORD")
    if not raw_password:
        raise RuntimeError(
            "FAMAS_ADMIN_PASSWORD is required when the admin account does not exist."
        )
    password_error = validate_password_strength(raw_password)
    if password_error and strict_runtime_mode_enabled(settings.runtime_mode):
        raise RuntimeError(
            "FAMAS_ADMIN_PASSWORD does not meet the password policy for "
            f"{settings.runtime_mode} mode: {password_error}"
        )

    db.add(
        User(
            username=DEFAULT_ADMIN_USERNAME,
            password_hash=hash_password(raw_password),
            role="admin",
            is_active=True,
            approval_status="approved",
        )
    )


def ensure_legacy_document_owner(db: Session) -> None:
    admin = db.scalar(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
    if admin is None:
        return

    documents = list(
        db.scalars(
            select(Document)
            .join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id)
            .where(
                Document.owner_user_id.is_(None),
                KnowledgeBase.owner_user_id.is_not(None),
            )
        )
    )
    for document in documents:
        document.owner_user_id = admin.id


def ensure_default_knowledge_base_documents(db: Session) -> None:
    source_root = default_knowledge_base_source_root(settings.project_dir)
    if not source_root.exists():
        return

    specs = load_default_knowledge_book_specs(settings.project_dir)
    if not specs:
        return

    default_kb = db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.slug == DEFAULT_KNOWLEDGE_BASE_SLUG,
            KnowledgeBase.is_deleted.is_(False),
        )
    )
    if default_kb is None:
        return

    spec_titles = {spec.title for spec in specs}
    existing_documents = list(
        db.scalars(
            select(Document).where(
                Document.knowledge_base_id == default_kb.id,
                Document.is_deleted.is_(False),
            )
        )
    )
    for document in existing_documents:
        if document.textbook not in spec_titles:
            document.is_deleted = True
            document.status = "deleted"

    for spec in specs:
        _ensure_seeded_book_document(
            db,
            default_kb,
            spec,
            owner_user_id=None,
        )


def ensure_admin_chemistry_knowledge_base(db: Session) -> None:
    admin = db.scalar(select(User).where(User.username == DEFAULT_ADMIN_USERNAME))
    if admin is None:
        return

    source_root = default_knowledge_base_source_root(settings.project_dir)
    if not source_root.exists():
        return

    chemistry_source_dir = source_root / ADMIN_CHEMISTRY_BOOK_SOURCE_DIR_NAME
    if not chemistry_source_dir.exists():
        return

    chemistry_kb = db.scalar(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.is_deleted.is_(False),
            KnowledgeBase.owner_user_id == admin.id,
            or_(
                KnowledgeBase.name == ADMIN_CHEMISTRY_KNOWLEDGE_BASE_NAME,
                KnowledgeBase.slug == ADMIN_CHEMISTRY_KNOWLEDGE_BASE_SLUG,
            ),
        )
        .order_by(KnowledgeBase.created_at.asc())
    )
    if chemistry_kb is None:
        chemistry_kb = KnowledgeBase(
            name=ADMIN_CHEMISTRY_KNOWLEDGE_BASE_NAME,
            slug=ADMIN_CHEMISTRY_KNOWLEDGE_BASE_SLUG,
            owner_user_id=admin.id,
            is_deleted=False,
        )
        db.add(chemistry_kb)
        db.flush()
    else:
        chemistry_kb.name = ADMIN_CHEMISTRY_KNOWLEDGE_BASE_NAME
        chemistry_kb.slug = ADMIN_CHEMISTRY_KNOWLEDGE_BASE_SLUG
        chemistry_kb.owner_user_id = admin.id
        chemistry_kb.is_deleted = False

    chemistry_spec = type("ChemistryBookSpec", (), {})()
    chemistry_spec.title = ADMIN_CHEMISTRY_BOOK_TITLE
    chemistry_spec.filename = ADMIN_CHEMISTRY_BOOK_FILENAME
    chemistry_spec.directory = chemistry_source_dir
    chemistry_spec.subject = "化学"
    chemistry_spec.grade = "高一"
    chemistry_spec.publisher = "苏教版"
    chemistry_spec.textbook_version = "必修"
    chemistry_spec.status = "passed"

    _ensure_seeded_book_document(
        db,
        chemistry_kb,
        chemistry_spec,
        owner_user_id=admin.id,
    )


def _ensure_seeded_book_document(
    db: Session,
    knowledge_base: KnowledgeBase,
    spec,
    *,
    owner_user_id: int | None,
) -> None:
    document = db.scalar(
        select(Document)
        .where(
            Document.knowledge_base_id == knowledge_base.id,
            Document.textbook == spec.title,
        )
        .order_by(Document.is_deleted.asc(), Document.id.asc())
    )
    if document is None:
        document = Document(
            knowledge_base_id=knowledge_base.id,
            owner_user_id=owner_user_id,
            filename=spec.filename,
            original_path=str((spec.directory / "source.pdf").resolve()),
            file_size_bytes=_book_artifact_size(spec.directory),
            subject=spec.subject,
            grade=spec.grade,
            publisher=spec.publisher,
            textbook=spec.title,
            textbook_version=spec.textbook_version,
            status="graph_ready",
            is_deleted=False,
            uploaded_at=utc_now_naive(),
            processing_started_at=utc_now_naive(),
            processing_completed_at=utc_now_naive(),
        )
        db.add(document)
        db.flush()
    else:
        document.owner_user_id = owner_user_id
        document.filename = spec.filename
        document.file_size_bytes = _book_artifact_size(spec.directory)
        document.subject = spec.subject
        document.grade = spec.grade
        document.publisher = spec.publisher
        document.textbook = spec.title
        document.textbook_version = spec.textbook_version
        document.status = "graph_ready"
        document.is_deleted = False
        if document.uploaded_at is None:
            document.uploaded_at = utc_now_naive()
        document.processing_started_at = document.processing_started_at or utc_now_naive()
        document.processing_completed_at = document.processing_completed_at or utc_now_naive()

    job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.document_id == document.id,
            ProcessingJob.stage == "build_graph",
        )
        .order_by(ProcessingJob.created_at.desc())
    )
    if job is None:
        job = ProcessingJob(
            document_id=document.id,
            stage="build_graph",
            status="success" if spec.status == "passed" else "degraded",
            log_path="",
            error_message="",
            created_at=utc_now_naive(),
            started_at=utc_now_naive(),
            completed_at=utc_now_naive(),
        )
        db.add(job)
        db.flush()
    else:
        job.status = "success" if spec.status == "passed" else "degraded"
        job.log_path = ""
        job.error_message = ""
        if job.started_at is None:
            job.started_at = utc_now_naive()
        if job.completed_at is None:
            job.completed_at = utc_now_naive()

    run_id = f"web_doc_{document.id}_{job.id}"
    target_root = settings.storage_dir / "knowledge_graph" / "runs" / run_id
    source_pdf = _ensure_placeholder_pdf(target_root / "source.pdf", spec.title)
    document.original_path = str(source_pdf)
    _materialize_default_knowledge_graph(spec.directory, target_root)


def _materialize_default_knowledge_graph(source_dir: Path, target_root: Path) -> None:
    source_outputs = source_dir
    if not source_outputs.exists():
        return

    target_outputs = target_root / "standard_outputs"
    if target_outputs.exists():
        return

    target_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_outputs, target_outputs, dirs_exist_ok=True)
    (target_root / "reports").mkdir(parents=True, exist_ok=True)
    (target_root / "images").mkdir(parents=True, exist_ok=True)


def _ensure_placeholder_pdf(path: Path, title: str) -> Path:
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    writer.add_blank_page(width=1, height=1)
    writer.add_metadata({"/Title": title})
    with path.open("wb") as output:
        writer.write(output)
    return path


def _book_artifact_size(source_dir: Path) -> int:
    total = 0
    for path in source_dir.iterdir():
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total
