from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import re
import secrets
import shutil
from urllib.parse import unquote

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Header, HTTPException, Query, status
from pypdf import PdfReader
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.time import utc_now_naive
from app.db.session import get_db
from app.models.document import Document
from app.models.document_schema_version import DocumentSchemaVersion
from app.models.knowledge_base import KnowledgeBase
from app.models.processing_job import ProcessingJob
from app.models.user import User
from app.schemas.document import DocumentResponse
from app.schemas.processing_job import ProcessingJobResponse
from app.services.knowledge_base_access import can_manage_knowledge_base
from app.services.knowledge_base_access import can_manage_document
from app.services.knowledge_base_access import can_view_document
from app.services.knowledge_base_access import get_accessible_knowledge_base
from app.services.pipeline_runner import repair_usable_pipeline_job, run_document_pipeline
from app.services.storage_paths import original_pdf_path

router = APIRouter(prefix="/api/documents", tags=["documents"])

PROCESSING_STAGES = {"parse_pdf", "build_graph", "full_pipeline"}


class DocumentMetadataUpdate(BaseModel):
    subject: str = ""
    grade: str = ""
    publisher: str = ""
    textbook: str = ""
    textbook_version: str = ""


class BatchDeleteDocumentsRequest(BaseModel):
    document_ids: list[int]


class BatchDeleteDocumentsResponse(BaseModel):
    deleted_ids: list[int]
    deleted_count: int


class ProcessingJobCreateRequest(BaseModel):
    schema_version_id: int | None = None
    source_context_ids: list[str] = Field(default_factory=list)


class ChunkedUploadInitRequest(BaseModel):
    filename: str
    file_size_bytes: int
    knowledge_base_id: int
    subject: str = ""
    grade: str = ""
    publisher: str = ""
    textbook: str = ""
    textbook_version: str = ""


class ChunkedUploadInitResponse(BaseModel):
    upload_id: str
    chunk_size_bytes: int
    total_chunks: int


class ChunkUploadResponse(BaseModel):
    upload_id: str
    chunk_index: int
    received_chunks: int
    total_chunks: int


@router.get("", response_model=list[DocumentResponse])
def list_documents(
    knowledge_base_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[Document]:
    statement = select(Document).join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id).where(
        Document.is_deleted.is_(False)
    )
    if knowledge_base_id is not None:
        get_accessible_knowledge_base(db, knowledge_base_id, user)
        statement = statement.where(Document.knowledge_base_id == knowledge_base_id)
    if user.role != "admin":
        statement = statement.where(
            or_(
                Document.owner_user_id == user.id,
                KnowledgeBase.owner_user_id.is_(None),
            )
        )
    statement = statement.order_by(Document.uploaded_at.desc())
    documents = list(db.scalars(statement))
    _backfill_missing_metadata(db, documents)
    _backfill_usable_pipeline_status(db, documents)
    return [_to_document_response(document, db) for document in documents]


@router.post("", response_model=DocumentResponse)
async def upload_document(
    content: bytes = Body(..., media_type="application/pdf"),
    knowledge_base_id: int = Query(...),
    filename: str = Header("document.pdf", alias="X-Filename"),
    subject: str = Header("", alias="X-Subject"),
    grade: str = Header("", alias="X-Grade"),
    publisher: str = Header("", alias="X-Publisher"),
    textbook: str = Header("", alias="X-Textbook"),
    textbook_version: str = Header("", alias="X-Textbook-Version"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Document:
    if not content.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed.",
        )

    knowledge_base = get_accessible_knowledge_base(db, knowledge_base_id, user)
    if not can_manage_knowledge_base(user, knowledge_base):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify this knowledge base.",
        )

    filename = _decode_header_filename(filename)
    safe_name = _build_safe_filename(filename)
    inferred_metadata = _infer_document_metadata(filename, content)
    provided_metadata = {
        "subject": _decode_header_text(subject),
        "grade": _decode_header_text(grade),
        "publisher": _decode_header_text(publisher),
        "textbook": _decode_header_text(textbook),
        "textbook_version": _decode_header_text(textbook_version),
    }
    metadata = {
        key: provided_metadata[key] or inferred_metadata[key]
        for key in provided_metadata
    }

    document = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        filename=filename,
        original_path="",
        file_size_bytes=len(content),
        subject=metadata["subject"],
        grade=metadata["grade"],
        publisher=metadata["publisher"],
        textbook=metadata["textbook"],
        textbook_version=metadata["textbook_version"],
        status="uploaded",
        is_deleted=False,
        uploaded_at=utc_now_naive(),
    )
    db.add(document)
    db.flush()

    target_path = original_pdf_path(document, safe_name)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(content)
    document.original_path = str(target_path)

    db.add(
        ProcessingJob(
            document_id=document.id,
            stage="upload",
            status="success",
            log_path="",
            error_message="",
            created_at=utc_now_naive(),
            completed_at=utc_now_naive(),
        )
    )
    db.commit()
    db.refresh(document)
    return _to_document_response(document, db)


@router.post("/chunked/init", response_model=ChunkedUploadInitResponse)
def init_chunked_upload(
    payload: ChunkedUploadInitRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChunkedUploadInitResponse:
    knowledge_base = get_accessible_knowledge_base(db, payload.knowledge_base_id, user)
    if not can_manage_knowledge_base(user, knowledge_base):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify this knowledge base.",
        )
    if payload.file_size_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File size is required.",
        )
    if payload.file_size_bytes > settings.max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"PDF is too large. Maximum size is {_format_size(settings.max_upload_bytes)}.",
        )

    filename = _decode_header_filename(payload.filename)
    safe_name = _build_safe_filename(filename)
    upload_id = secrets.token_urlsafe(18)
    upload_dir = _chunk_upload_dir(user.id, upload_id)
    upload_dir.mkdir(parents=True, exist_ok=False)

    total_chunks = _total_chunks(payload.file_size_bytes)
    manifest = {
        "upload_id": upload_id,
        "owner_user_id": user.id,
        "knowledge_base_id": knowledge_base.id,
        "filename": filename,
        "safe_filename": safe_name,
        "file_size_bytes": payload.file_size_bytes,
        "chunk_size_bytes": settings.upload_chunk_size_bytes,
        "total_chunks": total_chunks,
        "metadata": {
            "subject": payload.subject.strip(),
            "grade": payload.grade.strip(),
            "publisher": payload.publisher.strip(),
            "textbook": payload.textbook.strip(),
            "textbook_version": payload.textbook_version.strip(),
        },
        "created_at": utc_now_naive().isoformat(),
    }
    _chunk_manifest_path(upload_dir).write_text(json.dumps(manifest), encoding="utf-8")
    return ChunkedUploadInitResponse(
        upload_id=upload_id,
        chunk_size_bytes=settings.upload_chunk_size_bytes,
        total_chunks=total_chunks,
    )


@router.put("/chunked/{upload_id}/chunks/{chunk_index}", response_model=ChunkUploadResponse)
def upload_document_chunk(
    upload_id: str,
    chunk_index: int,
    content: bytes = Body(..., media_type="application/octet-stream"),
    user: User = Depends(get_current_user),
) -> ChunkUploadResponse:
    upload_dir, manifest = _load_chunk_manifest(user.id, upload_id)
    total_chunks = int(manifest["total_chunks"])
    if chunk_index < 0 or chunk_index >= total_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid chunk index.",
        )
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chunk content is required.",
        )
    max_chunk_size = int(manifest["chunk_size_bytes"])
    if len(content) > max_chunk_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Chunk is larger than the configured chunk size.",
        )

    chunk_path = _chunk_path(upload_dir, chunk_index)
    chunk_path.write_bytes(content)
    return ChunkUploadResponse(
        upload_id=upload_id,
        chunk_index=chunk_index,
        received_chunks=_received_chunk_count(upload_dir),
        total_chunks=total_chunks,
    )


@router.post("/chunked/{upload_id}/complete", response_model=DocumentResponse)
def complete_chunked_upload(
    upload_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    upload_dir, manifest = _load_chunk_manifest(user.id, upload_id)
    total_chunks = int(manifest["total_chunks"])
    missing_chunks = [
        index
        for index in range(total_chunks)
        if not _chunk_path(upload_dir, index).exists()
    ]
    if missing_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Upload is incomplete. Missing {len(missing_chunks)} chunks.",
        )

    merged_path = upload_dir / "merged.pdf"
    with merged_path.open("wb") as output:
        for index in range(total_chunks):
            output.write(_chunk_path(upload_dir, index).read_bytes())

    actual_size = merged_path.stat().st_size
    expected_size = int(manifest["file_size_bytes"])
    if actual_size != expected_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Merged PDF size does not match the expected file size.",
        )

    with merged_path.open("rb") as input_file:
        header = input_file.read(4)
    if header != b"%PDF":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are allowed.",
        )

    knowledge_base = get_accessible_knowledge_base(db, int(manifest["knowledge_base_id"]), user)
    if not can_manage_knowledge_base(user, knowledge_base):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify this knowledge base.",
        )

    filename = str(manifest["filename"])
    metadata = _merged_metadata(
        provided=manifest.get("metadata", {}),
        inferred=_infer_document_metadata_from_path(filename, merged_path),
    )
    document = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=user.id,
        filename=filename,
        original_path="",
        file_size_bytes=actual_size,
        subject=metadata["subject"],
        grade=metadata["grade"],
        publisher=metadata["publisher"],
        textbook=metadata["textbook"],
        textbook_version=metadata["textbook_version"],
        status="uploaded",
        is_deleted=False,
        uploaded_at=utc_now_naive(),
    )
    db.add(document)
    db.flush()

    target_path = original_pdf_path(document, str(manifest["safe_filename"]))
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(merged_path), target_path)
    document.original_path = str(target_path)
    db.add(
        ProcessingJob(
            document_id=document.id,
            stage="upload",
            status="success",
            log_path="",
            error_message="",
            created_at=utc_now_naive(),
            completed_at=utc_now_naive(),
        )
    )
    db.commit()
    db.refresh(document)
    shutil.rmtree(upload_dir, ignore_errors=True)
    return _to_document_response(document, db)


@router.post("/{document_id}/parse", response_model=ProcessingJobResponse)
def create_parse_job(
    document_id: int,
    background_tasks: BackgroundTasks,
    payload: ProcessingJobCreateRequest | None = Body(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProcessingJob:
    return _create_processing_job(
        document_id=document_id,
        stage="parse_pdf",
        schema_version_id=payload.schema_version_id if payload else None,
        payload=payload,
        background_tasks=background_tasks,
        user=user,
        db=db,
    )


@router.post("/{document_id}/build-graph", response_model=ProcessingJobResponse)
def create_build_graph_job(
    document_id: int,
    background_tasks: BackgroundTasks,
    payload: ProcessingJobCreateRequest | None = Body(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProcessingJob:
    return _create_processing_job(
        document_id=document_id,
        stage="build_graph",
        schema_version_id=payload.schema_version_id if payload else None,
        payload=payload,
        background_tasks=background_tasks,
        user=user,
        db=db,
    )


@router.post("/{document_id}/process", response_model=ProcessingJobResponse)
def create_processing_job(
    document_id: int,
    background_tasks: BackgroundTasks,
    payload: ProcessingJobCreateRequest | None = Body(default=None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProcessingJob:
    return _create_processing_job(
        document_id=document_id,
        stage="full_pipeline",
        schema_version_id=payload.schema_version_id if payload else None,
        payload=payload,
        background_tasks=background_tasks,
        user=user,
        db=db,
    )


@router.get("/{document_id}/jobs", response_model=list[ProcessingJobResponse])
def list_processing_jobs(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ProcessingJob]:
    document = db.get(Document, document_id)
    if not can_view_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    statement = (
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document.id)
        .order_by(ProcessingJob.created_at.desc())
    )
    return list(db.scalars(statement))


@router.put("/{document_id}/metadata", response_model=DocumentResponse)
def update_document_metadata(
    document_id: int,
    payload: DocumentMetadataUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    document = db.get(Document, document_id)
    if not can_manage_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    document.subject = payload.subject.strip()
    document.grade = payload.grade.strip()
    document.publisher = payload.publisher.strip()
    document.textbook = payload.textbook.strip()
    document.textbook_version = payload.textbook_version.strip()
    db.commit()
    db.refresh(document)
    return _to_document_response(document, db)


@router.get("/{document_id}/jobs/{job_id}/logs")
def read_processing_job_logs(
    document_id: int,
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    job = _get_document_job(db, document_id, job_id, user)
    if not job.log_path:
        return {"stdout": "", "stderr": "", "traceback": ""}

    log_dir = Path(job.log_path)
    return {
        "stdout": _sanitize_job_log(_read_log_file(log_dir / "stdout.log")),
        "stderr": _sanitize_job_log(_read_log_file(log_dir / "stderr.log")),
        "traceback": _sanitize_job_log(_read_log_file(log_dir / "traceback.log")),
    }


@router.post("/batch-delete", response_model=BatchDeleteDocumentsResponse)
def batch_delete_documents(
    payload: BatchDeleteDocumentsRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatchDeleteDocumentsResponse:
    document_ids = list(dict.fromkeys(payload.document_ids))
    if not document_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one document id is required.",
        )

    documents = list(db.scalars(select(Document).where(Document.id.in_(document_ids))))
    documents_by_id = {document.id: document for document in documents}
    inaccessible_ids = [
        document_id
        for document_id in document_ids
        if not can_manage_document(user, documents_by_id.get(document_id))
    ]
    if inaccessible_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or more documents were not found.",
        )

    deleted_ids: list[int] = []
    for document_id in document_ids:
        document = documents_by_id[document_id]
        document.is_deleted = True
        document.status = "deleted"
        deleted_ids.append(document.id)

    db.commit()
    return BatchDeleteDocumentsResponse(
        deleted_ids=deleted_ids,
        deleted_count=len(deleted_ids),
    )


@router.delete("/{document_id}", response_model=DocumentResponse)
def delete_document(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentResponse:
    document = db.get(Document, document_id)
    if not can_manage_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    document.is_deleted = True
    document.status = "deleted"
    db.commit()
    db.refresh(document)
    return _to_document_response(document, db)


def _create_processing_job(
    *,
    document_id: int,
    stage: str,
    schema_version_id: int | None,
    payload: ProcessingJobCreateRequest | None,
    background_tasks: BackgroundTasks,
    user: User,
    db: Session,
) -> ProcessingJob:
    document = db.get(Document, document_id)
    if not can_manage_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    active_job = _active_processing_job_for_document(db, document.id)
    if active_job is not None:
        if active_job.stage == stage:
            return active_job
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document already has a processing job pending or running.",
        )

    if schema_version_id is not None and stage == "parse_pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="解析 PDF 阶段不能指定 schema 版本。",
        )
    source_context_ids = _clean_source_context_ids(payload.source_context_ids if payload else [])
    if source_context_ids and stage == "parse_pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="PDF parsing jobs cannot restrict source contexts.",
        )
    if schema_version_id is not None:
        schema_version = db.get(DocumentSchemaVersion, schema_version_id)
        if schema_version is None or schema_version.document_id != document.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Schema version not found.",
            )

    document.status = f"{stage}_pending"
    document.processing_started_at = None
    document.processing_completed_at = None
    job = ProcessingJob(
        document_id=document.id,
        schema_version_id=schema_version_id,
        stage=stage,
        status="pending",
        log_path="",
        error_message="",
        payload_json=json.dumps(
            {
                "schema_version_id": schema_version_id,
                "source_context_ids": source_context_ids,
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        created_at=utc_now_naive(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    if not settings.pipeline_worker_enabled:
        background_tasks.add_task(run_document_pipeline, job.id)
    return job


def _active_processing_job_for_document(db: Session, document_id: int) -> ProcessingJob | None:
    return db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.document_id == document_id,
            ProcessingJob.stage.in_(PROCESSING_STAGES),
            ProcessingJob.status.in_(["pending", "running"]),
        )
        .order_by(ProcessingJob.created_at.asc())
    )


def _clean_source_context_ids(source_context_ids: list[str]) -> list[str]:
    cleaned: list[str] = []
    for source_context_id in source_context_ids:
        value = str(source_context_id or "").strip()
        if not value or value in cleaned:
            continue
        cleaned.append(value)
    return cleaned


def _get_document_job(db: Session, document_id: int, job_id: int, user: User) -> ProcessingJob:
    document = db.get(Document, document_id)
    if not can_view_document(user, document):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    job = db.get(ProcessingJob, job_id)
    if job is None or job.document_id != document.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Processing job not found.",
        )
    return job


def _read_log_file(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-20000:]
    except OSError:
        return ""


def _sanitize_job_log(text: str) -> str:
    sanitized = text
    replacements = [
        (settings.storage_dir, "<STORAGE_DIR>"),
        (settings.backend_dir, "<BACKEND_DIR>"),
        (settings.web_dir, "<WEB_DIR>"),
        (settings.project_dir, "<PROJECT_DIR>"),
    ]
    for path_value, replacement in sorted(
        replacements,
        key=lambda item: len(str(item[0])),
        reverse=True,
    ):
        raw_text = str(path_value)
        escaped_text = raw_text.replace("\\", "\\\\")
        sanitized = sanitized.replace(escaped_text, replacement)
        sanitized = sanitized.replace(raw_text, replacement)
    return sanitized


def _build_safe_filename(filename: str) -> str:
    name = Path(filename).name
    if not name.lower().endswith(".pdf"):
        name = f"{name}.pdf"
    stem = Path(name).stem[:72]
    name = f"{stem}.pdf"
    return "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in name)


def _decode_header_filename(filename: str) -> str:
    try:
        decoded = unquote(filename)
    except Exception:
        decoded = filename
    return Path(decoded or "document.pdf").name


def _decode_header_text(value: str) -> str:
    try:
        decoded = unquote(value)
    except Exception:
        decoded = value
    return decoded.strip()


def _total_chunks(file_size_bytes: int) -> int:
    return max(1, (file_size_bytes + settings.upload_chunk_size_bytes - 1) // settings.upload_chunk_size_bytes)


def _chunk_upload_dir(user_id: int | None, upload_id: str) -> Path:
    safe_upload_id = re.sub(r"[^A-Za-z0-9_-]", "", upload_id)
    user_part = f"user_{user_id}" if user_id is not None else "unowned"
    return settings.chunk_upload_dir / user_part / safe_upload_id


def _chunk_manifest_path(upload_dir: Path) -> Path:
    return upload_dir / "manifest.json"


def _chunk_path(upload_dir: Path, chunk_index: int) -> Path:
    return upload_dir / f"chunk_{chunk_index:06d}.part"


def _load_chunk_manifest(user_id: int | None, upload_id: str) -> tuple[Path, dict]:
    upload_dir = _chunk_upload_dir(user_id, upload_id)
    manifest_path = _chunk_manifest_path(upload_dir)
    if not manifest_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found.",
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload session is invalid.",
        ) from exc
    if manifest.get("owner_user_id") != user_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found.",
        )
    return upload_dir, manifest


def _received_chunk_count(upload_dir: Path) -> int:
    return len(list(upload_dir.glob("chunk_*.part")))


def _merged_metadata(provided: object, inferred: dict[str, str]) -> dict[str, str]:
    provided_dict = provided if isinstance(provided, dict) else {}
    return {
        key: str(provided_dict.get(key, "") or inferred[key]).strip()
        for key in ["subject", "grade", "publisher", "textbook", "textbook_version"]
    }


def _format_size(bytes_value: int) -> str:
    value = float(bytes_value)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{bytes_value} B"


def _backfill_missing_metadata(db: Session, documents: list[Document]) -> None:
    changed = False
    for document in documents:
        if any([document.subject, document.grade, document.publisher, document.textbook, document.textbook_version]):
            continue
        source_path = Path(document.original_path)
        if not source_path.exists():
            continue
        try:
            content = source_path.read_bytes()
        except OSError:
            continue
        metadata = _infer_document_metadata(document.filename, content)
        if not any(metadata.values()):
            continue
        document.subject = metadata["subject"]
        document.grade = metadata["grade"]
        document.publisher = metadata["publisher"]
        document.textbook = metadata["textbook"]
        document.textbook_version = metadata["textbook_version"]
        changed = True
    if changed:
        db.commit()


def _backfill_usable_pipeline_status(db: Session, documents: list[Document]) -> None:
    changed = False
    for document in documents:
        job = db.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.document_id == document.id,
                ProcessingJob.stage.in_(["build_graph", "full_pipeline"]),
            )
            .order_by(ProcessingJob.created_at.desc())
        )
        if job is not None and repair_usable_pipeline_job(job, document):
            changed = True
    if changed:
        db.commit()


def _infer_document_metadata(filename: str, content: bytes) -> dict[str, str]:
    text = _metadata_source_text(filename, content)
    return {
        "subject": _infer_subject(text),
        "grade": _infer_grade(text),
        "publisher": _infer_publisher(text),
        "textbook": _infer_textbook(filename, text),
        "textbook_version": _infer_textbook_version(text),
    }


def _infer_document_metadata_from_path(filename: str, pdf_path: Path) -> dict[str, str]:
    chunks = [filename, Path(filename).stem]
    try:
        with pdf_path.open("rb") as input_file:
            reader = PdfReader(input_file)
            for page in reader.pages[:3]:
                chunks.append(page.extract_text() or "")
    except Exception:
        pass
    text = "\n".join(chunks)
    return {
        "subject": _infer_subject(text),
        "grade": _infer_grade(text),
        "publisher": _infer_publisher(text),
        "textbook": _infer_textbook(filename, text),
        "textbook_version": _infer_textbook_version(text),
    }


def _metadata_source_text(filename: str, content: bytes) -> str:
    chunks = [filename, Path(filename).stem]
    try:
        reader = PdfReader(BytesIO(content))
        for page in reader.pages[:3]:
            chunks.append(page.extract_text() or "")
    except Exception:
        pass
    return "\n".join(chunks)


def _infer_subject(text: str) -> str:
    normalized = text.lower()
    subject_patterns = [
        ("history", ["\u5386\u53f2", "history"]),
        ("chemistry", ["\u5316\u5b66", "chemistry"]),
        ("physics", ["\u7269\u7406", "physics"]),
        ("biology", ["\u751f\u7269", "biology"]),
        ("geography", ["\u5730\u7406", "geography"]),
        ("mathematics", ["\u6570\u5b66", "math", "mathematics"]),
        ("chinese", ["\u8bed\u6587", "chinese"]),
        ("english", ["\u82f1\u8bed", "english"]),
    ]
    for subject, patterns in subject_patterns:
        if any(pattern in normalized for pattern in patterns):
            return subject
    return ""


def _infer_grade(text: str) -> str:
    normalized = text.lower()
    if any(
        pattern in normalized
        for pattern in [
            "\u9ad8\u4e2d",
            "\u9ad8\u4e00",
            "\u9ad8\u4e8c",
            "\u9ad8\u4e09",
            "\u666e\u901a\u9ad8\u4e2d",
            "high school",
        ]
    ):
        return "high_school"
    if any(
        pattern in normalized
        for pattern in ["\u521d\u4e2d", "\u521d\u4e00", "\u521d\u4e8c", "\u521d\u4e09", "junior"]
    ):
        return "junior_high"
    if any(pattern in normalized for pattern in ["\u5c0f\u5b66", "primary"]):
        return "primary_school"
    return ""


def _infer_publisher(text: str) -> str:
    normalized = text.lower()
    publisher_patterns = [
        ("renjiao", ["\u4eba\u6559\u7248", "\u4eba\u6c11\u6559\u80b2\u51fa\u7248\u793e", "pep"]),
        ("sujiao", ["\u82cf\u6559\u7248", "\u6c5f\u82cf\u51e4\u51f0\u6559\u80b2\u51fa\u7248\u793e", "\u6c5f\u82cf\u6559\u80b2\u51fa\u7248\u793e"]),
        ("beishida", ["\u5317\u5e08\u5927\u7248", "\u5317\u4eac\u5e08\u8303\u5927\u5b66\u51fa\u7248\u793e"]),
        ("yuelu", ["\u5cb3\u9e93\u7248", "\u5cb3\u9e93\u4e66\u793e"]),
        ("tongbian", ["\u7edf\u7f16\u7248", "\u6559\u80b2\u90e8\u7ec4\u7ec7\u7f16\u5199"]),
    ]
    for publisher, patterns in publisher_patterns:
        if any(pattern in normalized for pattern in patterns):
            return publisher
    return ""


def _infer_textbook(filename: str, text: str) -> str:
    stem = Path(filename).stem
    cleaned_stem = re.sub(r"[-_ ]?test$", "", stem, flags=re.IGNORECASE).strip(" -_")
    textbook_patterns = [
        r"\u4e2d\u5916\u5386\u53f2\u7eb2\u8981[\uff08(]\u4e0a[\uff09)]",
        r"\u4e2d\u5916\u5386\u53f2\u7eb2\u8981[\uff08(]\u4e0b[\uff09)]",
        r"\u5316\u5b66\u5fc5\u4fee\u7b2c\u4e00\u518c",
        r"\u5316\u5b66\u5fc5\u4fee\u7b2c\u4e8c\u518c",
        r"\u7269\u7406\u5fc5\u4fee\u7b2c\u4e00\u518c",
        r"\u751f\u7269\u5b66\u5fc5\u4fee",
        r"\u6570\u5b66\u5fc5\u4fee\u7b2c\u4e00\u518c",
    ]
    for pattern in textbook_patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    if any(
        keyword in cleaned_stem
        for keyword in [
            "\u5386\u53f2",
            "\u5316\u5b66",
            "\u7269\u7406",
            "\u751f\u7269",
            "\u5730\u7406",
            "\u6570\u5b66",
            "\u8bed\u6587",
            "\u82f1\u8bed",
        ]
    ):
        return cleaned_stem
    return ""


def _infer_textbook_version(text: str) -> str:
    normalized = text.lower()
    if "\u9009\u62e9\u6027\u5fc5\u4fee" in normalized:
        return "selective_compulsory"
    if "\u5fc5\u4fee" in normalized or "compulsory" in normalized:
        return "compulsory"
    return ""


def _to_document_response(document: Document, db: Session) -> DocumentResponse:
    latest_job = db.scalar(
        select(ProcessingJob)
        .where(ProcessingJob.document_id == document.id)
        .order_by(ProcessingJob.created_at.desc())
    )
    latest_job_response = (
        ProcessingJobResponse(
            id=latest_job.id,
            document_id=latest_job.document_id,
            schema_version_id=latest_job.schema_version_id,
            stage=latest_job.stage,
            status=latest_job.status,
            log_path=latest_job.log_path,
            error_message=latest_job.error_message,
            created_at=latest_job.created_at,
            started_at=latest_job.started_at,
            completed_at=latest_job.completed_at,
        )
        if latest_job is not None
        else None
    )
    return DocumentResponse(
        id=document.id,
        knowledge_base_id=document.knowledge_base_id,
        owner_user_id=document.owner_user_id,
        filename=document.filename,
        file_size_bytes=document.file_size_bytes,
        subject=document.subject,
        grade=document.grade,
        publisher=document.publisher,
        textbook=document.textbook,
        textbook_version=document.textbook_version,
        status=document.status,
        uploaded_at=document.uploaded_at,
        processing_started_at=document.processing_started_at,
        processing_completed_at=document.processing_completed_at,
        latest_job=latest_job_response,
    )
