from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.default_knowledge_base import (
    ADMIN_CHEMISTRY_BOOK_TITLE,
    ADMIN_CHEMISTRY_BOOK_SOURCE_DIR_NAME,
    ADMIN_CHEMISTRY_KNOWLEDGE_BASE_NAME,
    ADMIN_CHEMISTRY_KNOWLEDGE_BASE_SLUG,
    DEFAULT_KNOWLEDGE_BASE_SLUG,
)
from app.db import seed as seed_module
from app.db.seed import ensure_default_knowledge_base_documents
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User


def test_default_knowledge_base_seed_prunes_non_dataset_documents(
    db_session: Session,
    runtime_dir: Path,
    monkeypatch,
) -> None:
    project_dir = runtime_dir / "project"
    source_root = project_dir / "默认知识库"
    source_root.mkdir(parents=True, exist_ok=True)

    book_a_dir = project_dir / "book_a"
    book_b_dir = project_dir / "book_b"
    book_a_dir.mkdir(parents=True, exist_ok=True)
    book_b_dir.mkdir(parents=True, exist_ok=True)
    (book_a_dir / "artifact.txt").write_text("a", encoding="utf-8")
    (book_b_dir / "artifact.txt").write_text("b", encoding="utf-8")

    monkeypatch.setattr(seed_module.settings, "project_dir", project_dir)

    spec_a = type("Spec", (), {})()
    spec_a.title = "Book A"
    spec_a.filename = "Book A.pdf"
    spec_a.directory = book_a_dir
    spec_a.subject = "subject-a"
    spec_a.grade = "grade-a"
    spec_a.publisher = "publisher-a"
    spec_a.textbook_version = "version-a"
    spec_a.status = "passed"

    spec_b = type("Spec", (), {})()
    spec_b.title = "Book B"
    spec_b.filename = "Book B.pdf"
    spec_b.directory = book_b_dir
    spec_b.subject = "subject-b"
    spec_b.grade = "grade-b"
    spec_b.publisher = "publisher-b"
    spec_b.textbook_version = "version-b"
    spec_b.status = "degraded"

    monkeypatch.setattr(
        seed_module,
        "load_default_knowledge_book_specs",
        lambda _project_dir: [spec_a, spec_b],
    )

    knowledge_base = KnowledgeBase(
        name="小初高知识全集",
        slug=DEFAULT_KNOWLEDGE_BASE_SLUG,
        owner_user_id=None,
        is_deleted=False,
    )
    db_session.add(knowledge_base)
    db_session.commit()
    db_session.refresh(knowledge_base)

    keep_doc = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=None,
        filename="old-a.pdf",
        original_path="old-a.pdf",
        file_size_bytes=1,
        subject="old",
        grade="old",
        publisher="old",
        textbook="Book A",
        textbook_version="old",
        status="uploaded",
        is_deleted=False,
    )
    restore_doc = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=None,
        filename="old-b.pdf",
        original_path="old-b.pdf",
        file_size_bytes=1,
        subject="old",
        grade="old",
        publisher="old",
        textbook="Book B",
        textbook_version="old",
        status="deleted",
        is_deleted=True,
    )
    prune_doc = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=None,
        filename="legacy.pdf",
        original_path="legacy.pdf",
        file_size_bytes=1,
        subject="old",
        grade="old",
        publisher="old",
        textbook="Legacy Doc",
        textbook_version="old",
        status="graph_ready",
        is_deleted=False,
    )
    db_session.add_all([keep_doc, restore_doc, prune_doc])
    db_session.commit()

    ensure_default_knowledge_base_documents(db_session)
    db_session.commit()
    db_session.expire_all()

    active_titles = {
        row.textbook
        for row in db_session.scalars(
            select(Document).where(
                Document.knowledge_base_id == knowledge_base.id,
                Document.is_deleted.is_(False),
            )
        )
    }
    assert active_titles == {"Book A", "Book B"}

    prune_doc = db_session.scalar(select(Document).where(Document.id == prune_doc.id))
    restore_doc = db_session.scalar(select(Document).where(Document.id == restore_doc.id))
    keep_doc = db_session.scalar(select(Document).where(Document.id == keep_doc.id))

    assert prune_doc is not None and prune_doc.is_deleted is True and prune_doc.status == "deleted"
    assert restore_doc is not None and restore_doc.is_deleted is False and restore_doc.status == "graph_ready"
    assert keep_doc is not None and keep_doc.is_deleted is False and keep_doc.status == "graph_ready"


def test_admin_chemistry_knowledge_base_seed_creates_admin_owned_graph(
    db_session: Session,
    runtime_dir: Path,
    monkeypatch,
) -> None:
    project_dir = runtime_dir / "project"
    source_root = project_dir / "默认知识库"
    book_dir = source_root / ADMIN_CHEMISTRY_BOOK_SOURCE_DIR_NAME
    book_dir.mkdir(parents=True, exist_ok=True)
    (book_dir / "merged_nodes.json").write_text("{\"nodes\": []}", encoding="utf-8")
    (book_dir / "merged_edges.json").write_text("{\"edges\": []}", encoding="utf-8")
    (book_dir / "triples.json").write_text("{\"triples\": []}", encoding="utf-8")

    monkeypatch.setattr(seed_module.settings, "project_dir", project_dir)

    admin = User(
        username="admin",
        password_hash=seed_module.hash_password("Adminpass123"),
        role="admin",
        is_active=True,
        approval_status="approved",
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)

    seed_module.ensure_admin_chemistry_knowledge_base(db_session)
    db_session.commit()
    db_session.expire_all()

    knowledge_base = db_session.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.name == ADMIN_CHEMISTRY_KNOWLEDGE_BASE_NAME,
            KnowledgeBase.slug == ADMIN_CHEMISTRY_KNOWLEDGE_BASE_SLUG,
            KnowledgeBase.owner_user_id == admin.id,
            KnowledgeBase.is_deleted.is_(False),
        )
    )
    assert knowledge_base is not None

    document = db_session.scalar(
        select(Document).where(
            Document.knowledge_base_id == knowledge_base.id,
            Document.textbook == ADMIN_CHEMISTRY_BOOK_TITLE,
            Document.is_deleted.is_(False),
        )
    )
    assert document is not None
    assert document.owner_user_id == admin.id
    assert document.status == "graph_ready"

    job = db_session.scalar(
        select(seed_module.ProcessingJob).where(
            seed_module.ProcessingJob.document_id == document.id,
            seed_module.ProcessingJob.stage == "build_graph",
        )
    )
    assert job is not None
    assert job.status in {"success", "degraded"}

    target_root = seed_module.settings.storage_dir / "knowledge_graph" / "runs" / f"web_doc_{document.id}_{job.id}"
    assert (target_root / "standard_outputs" / "merged_nodes.json").exists()
    assert (target_root / "standard_outputs" / "merged_edges.json").exists()
    assert (target_root / "standard_outputs" / "triples.json").exists()
