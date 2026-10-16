from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import secrets
import hashlib
from typing import Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import bearer_scheme, extract_access_token, get_current_user
from app.core.config import settings
from app.core.security import decode_access_token
from app.core.time import utc_now_naive
from app.db.session import get_db
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.kg_annotation_template import KgAnnotationTemplate
from app.models.kg_item_annotation import KgItemAnnotation
from app.models.kg_item_override import KgItemOverride
from app.models.knowledge_base import KnowledgeBase
from app.models.processing_job import ProcessingJob
from app.models.user import User
from app.schemas.kg_item_override import (
    KgEdgeOverrideCreate,
    KgItemOverrideResponse,
    KgItemOverrideUpdate,
    KgNodeOverrideCreate,
)
from app.schemas.kg_annotation_template import (
    KgAnnotationTemplateCreate,
    KgAnnotationTemplateResponse,
    KgAnnotationTemplateUpdate,
)
from app.schemas.kg_item_annotation import KgItemAnnotationResponse, KgItemAnnotationUpdate
from app.services.knowledge_base_access import get_accessible_knowledge_base
from app.services.storage_paths import (
    knowledge_graph_run_artifacts_dir,
    knowledge_graph_run_images_dir,
)
from app.services.pipeline_runner import run_document_pipeline

router = APIRouter(prefix="/api/knowledge-graph", tags=["knowledge-graph"])

ARTIFACT_FILENAMES = {
    "merged_nodes.json": "merged_nodes",
    "merged_edges.json": "merged_edges",
    "triples.json": "triples",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
KG_OVERRIDE_KINDS = {"node", "edge"}
KG_ANNOTATION_KINDS = {"node", "edge", "image"}
KG_ANNOTATION_TAGS = {
    "重点",
    "难点",
    "易错点",
    "考点",
    "图片证据",
    "适合课堂讲解",
    "适合问答引用",
    "需人工复核",
    "已确认",
    "错误抽取",
}
KG_OVERRIDE_PATCH_FIELDS = {
    "title",
    "label",
    "description",
    "source_note",
    "importance",
    "note",
    "subject_tag",
    "user_evidence",
    "evidence_confidence",
    "predicate",
    "source_node_id",
    "target_node_id",
    "relation_description",
    "image_paths",
}


@router.get("/summary")
def graph_summary(
    knowledge_base_id: int,
    document_id: int | None = Query(None),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    documents = _select_documents(db, knowledge_base_id, document_id, _user)
    available_run_ids = _available_processed_run_ids(db, documents)
    source = _graph_source(_user, available_run_ids)
    counts = _artifact_counts(source=source, run_ids=available_run_ids, documents=documents, user=_user, db=db)
    return {
        "source": source,
        "knowledge_base_id": knowledge_base_id,
        "knowledge_base_name": _knowledge_base_name(db, knowledge_base_id),
        "document_id": document_id,
        "documents": [
            {
                "id": document.id,
                "filename": document.filename,
                "status": document.status,
                "subject": document.subject,
                "grade": document.grade,
                "publisher": document.publisher,
                "textbook": document.textbook,
                "textbook_version": document.textbook_version,
            }
            for document in documents
        ],
        "metadata": _metadata_summary(documents),
        "processed_run_ids": available_run_ids,
        "counts": counts,
    }


@router.get("/image")
def graph_image(
    knowledge_base_id: int,
    request: Request,
    image_path: str = Query(..., min_length=1),
    document_id: int | None = Query(None),
    access_token: str | None = Query(None),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> FileResponse:
    user = _resolve_request_user(db, credentials, request, access_token)
    documents = _select_documents(db, knowledge_base_id, document_id, user)
    run_ids = _available_processed_run_ids(db, documents)
    image_file = _resolve_processed_image_path(run_ids, image_path)
    if image_file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge graph image not found.",
        )
    return FileResponse(image_file)


@router.get("/overrides", response_model=list[KgItemOverrideResponse])
def list_graph_overrides(
    knowledge_base_id: int,
    document_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KgItemOverrideResponse]:
    documents = _select_documents(db, knowledge_base_id, document_id, user)
    document_ids = [document.id for document in documents]
    if not document_ids:
        return []

    statement = select(KgItemOverride).where(
        KgItemOverride.knowledge_base_id == knowledge_base_id,
        KgItemOverride.document_id.in_(document_ids),
    )
    if user.role != "admin":
        statement = statement.where(KgItemOverride.owner_user_id == user.id)
    statement = statement.order_by(KgItemOverride.updated_at.desc())
    return [_override_to_response(item) for item in db.scalars(statement)]


@router.get("/annotations", response_model=list[KgItemAnnotationResponse])
def list_graph_annotations(
    knowledge_base_id: int,
    document_id: int | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KgItemAnnotationResponse]:
    documents = _select_documents(db, knowledge_base_id, document_id, user)
    document_ids = [document.id for document in documents]
    if not document_ids:
        return []

    statement = select(KgItemAnnotation).where(
        KgItemAnnotation.knowledge_base_id == knowledge_base_id,
        KgItemAnnotation.document_id.in_(document_ids),
    )
    if user.role != "admin":
        statement = statement.where(KgItemAnnotation.owner_user_id == user.id)
    statement = statement.order_by(KgItemAnnotation.updated_at.desc())
    return [_annotation_to_response(item) for item in db.scalars(statement)]


@router.get("/annotation-templates", response_model=list[KgAnnotationTemplateResponse])
def list_annotation_templates(
    target_kind: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KgAnnotationTemplateResponse]:
    statement = select(KgAnnotationTemplate).where(KgAnnotationTemplate.is_public.is_(True))
    if target_kind:
        _validate_annotation_kind(target_kind)
        statement = statement.where(KgAnnotationTemplate.target_kind == target_kind)
    statement = statement.order_by(KgAnnotationTemplate.updated_at.desc())
    return [_template_to_response(item) for item in db.scalars(statement)]


@router.post("/annotation-templates", response_model=KgAnnotationTemplateResponse)
def create_annotation_template(
    payload: KgAnnotationTemplateCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KgAnnotationTemplateResponse:
    _require_admin(user)
    _validate_annotation_kind(payload.target_kind)
    name = payload.name.strip()[:120]
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="模板名称不能为空。")
    template = KgAnnotationTemplate(
        owner_user_id=user.id,
        target_kind=payload.target_kind,
        name=name,
        tags_json=json.dumps(_clean_annotation_tags(payload.tags), ensure_ascii=False),
        note=payload.note.strip()[:2000],
        is_public=True,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _template_to_response(template)


@router.put("/annotation-templates/{template_id}", response_model=KgAnnotationTemplateResponse)
def update_annotation_template(
    template_id: int,
    payload: KgAnnotationTemplateUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KgAnnotationTemplateResponse:
    _require_admin(user)
    template = db.get(KgAnnotationTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Annotation template not found.")
    name = payload.name.strip()[:120]
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="模板名称不能为空。")
    template.name = name
    template.tags_json = json.dumps(_clean_annotation_tags(payload.tags), ensure_ascii=False)
    template.note = payload.note.strip()[:2000]
    template.updated_at = _now_for_override()
    db.commit()
    db.refresh(template)
    return _template_to_response(template)


@router.delete("/annotation-templates/{template_id}")
def delete_annotation_template(
    template_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(user)
    template = db.get(KgAnnotationTemplate, template_id)
    if template is not None:
        db.delete(template)
        db.commit()
    return {"deleted": template is not None}


@router.put("/annotations/{target_kind}/{target_id:path}", response_model=KgItemAnnotationResponse)
def upsert_graph_annotation(
    target_kind: str,
    target_id: str,
    payload: KgItemAnnotationUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KgItemAnnotationResponse:
    _validate_annotation_kind(target_kind)
    document = _get_accessible_document_for_override(db, payload.knowledge_base_id, payload.document_id, user)
    cleaned_tags = _clean_annotation_tags(payload.tags)
    cleaned_note = payload.note.strip()[:2000]
    annotation = db.scalar(
        select(KgItemAnnotation).where(
            KgItemAnnotation.owner_user_id == user.id,
            KgItemAnnotation.document_id == document.id,
            KgItemAnnotation.target_kind == target_kind,
            KgItemAnnotation.target_hash == _target_hash(target_id),
        )
    )
    if annotation is None:
        annotation = KgItemAnnotation(
            knowledge_base_id=payload.knowledge_base_id,
            document_id=document.id,
            owner_user_id=user.id,
            target_kind=target_kind,
            target_id=target_id,
            target_hash=_target_hash(target_id),
            tags_json=json.dumps(cleaned_tags, ensure_ascii=False),
            note=cleaned_note,
        )
        db.add(annotation)
    else:
        annotation.tags_json = json.dumps(cleaned_tags, ensure_ascii=False)
        annotation.note = cleaned_note
        annotation.updated_at = _now_for_override()
    db.commit()
    db.refresh(annotation)
    return _annotation_to_response(annotation)


@router.delete("/annotations/{target_kind}/{target_id:path}")
def delete_graph_annotation(
    target_kind: str,
    target_id: str,
    knowledge_base_id: int,
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _validate_annotation_kind(target_kind)
    document = _get_accessible_document_for_override(db, knowledge_base_id, document_id, user)
    annotation = db.scalar(
        select(KgItemAnnotation).where(
            KgItemAnnotation.owner_user_id == user.id,
            KgItemAnnotation.document_id == document.id,
            KgItemAnnotation.target_kind == target_kind,
            KgItemAnnotation.target_hash == _target_hash(target_id),
        )
    )
    if annotation is not None:
        db.delete(annotation)
        db.commit()
    return {"deleted": annotation is not None}


@router.post("/overrides/nodes", response_model=KgItemOverrideResponse)
def create_graph_node_override(
    payload: KgNodeOverrideCreate,
    background_tasks: BackgroundTasks,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KgItemOverrideResponse:
    document = _get_accessible_document_for_override(db, payload.knowledge_base_id, payload.document_id, user)
    patch = _clean_override_patch(payload.model_dump(exclude={"knowledge_base_id", "document_id", "source_context_ids"}))
    if not patch.get("title"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新增节点必须填写节点名称。")
    override = KgItemOverride(
        knowledge_base_id=payload.knowledge_base_id,
        document_id=document.id,
        owner_user_id=user.id,
        item_kind="node",
        item_id=f"web_node_{secrets.token_hex(8)}",
        is_new=True,
        is_hidden=False,
        patch_json=json.dumps(patch, ensure_ascii=False, sort_keys=True),
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    job = _queue_graph_refresh_job(db, background_tasks, document.id, payload.source_context_ids)
    if job is not None:
        response.headers["X-Graph-Refresh-Job-Id"] = str(job.id)
    return _override_to_response(override)


@router.post("/overrides/edges", response_model=KgItemOverrideResponse)
def create_graph_edge_override(
    payload: KgEdgeOverrideCreate,
    background_tasks: BackgroundTasks,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KgItemOverrideResponse:
    document = _get_accessible_document_for_override(db, payload.knowledge_base_id, payload.document_id, user)
    patch = _clean_override_patch(payload.model_dump(exclude={"knowledge_base_id", "document_id", "source_context_ids"}))
    if not patch.get("source_node_id") or not patch.get("target_node_id"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="新增关系必须选择主体节点和客体节点。")
    override = KgItemOverride(
        knowledge_base_id=payload.knowledge_base_id,
        document_id=document.id,
        owner_user_id=user.id,
        item_kind="edge",
        item_id=f"web_edge_{secrets.token_hex(8)}",
        is_new=True,
        is_hidden=False,
        patch_json=json.dumps(patch, ensure_ascii=False, sort_keys=True),
    )
    db.add(override)
    db.commit()
    db.refresh(override)
    job = _queue_graph_refresh_job(db, background_tasks, document.id, payload.source_context_ids)
    if job is not None:
        response.headers["X-Graph-Refresh-Job-Id"] = str(job.id)
    return _override_to_response(override)


@router.put("/overrides/{item_kind}/{item_id}", response_model=KgItemOverrideResponse)
def upsert_graph_override(
    item_kind: str,
    item_id: str,
    payload: KgItemOverrideUpdate,
    background_tasks: BackgroundTasks,
    response: Response,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KgItemOverrideResponse:
    _validate_override_kind(item_kind)
    document = _get_accessible_document_for_override(db, payload.knowledge_base_id, payload.document_id, user)
    patch = _clean_override_patch(payload.patch)
    override = db.scalar(
        select(KgItemOverride).where(
            KgItemOverride.owner_user_id == user.id,
            KgItemOverride.document_id == document.id,
            KgItemOverride.item_kind == item_kind,
            KgItemOverride.item_id == item_id,
        )
    )
    if override is None:
        override = KgItemOverride(
            knowledge_base_id=payload.knowledge_base_id,
            document_id=document.id,
            owner_user_id=user.id,
            item_kind=item_kind,
            item_id=item_id,
            is_hidden=payload.is_hidden,
            patch_json=json.dumps(patch, ensure_ascii=False, sort_keys=True),
        )
        db.add(override)
    else:
        override.is_hidden = payload.is_hidden
        override.patch_json = json.dumps(patch, ensure_ascii=False, sort_keys=True)
        override.updated_at = _now_for_override()
    db.commit()
    db.refresh(override)
    job = _queue_graph_refresh_job(db, background_tasks, document.id, payload.source_context_ids)
    if job is not None:
        response.headers["X-Graph-Refresh-Job-Id"] = str(job.id)
    return _override_to_response(override)


@router.delete("/overrides/{item_kind}/{item_id}")
def delete_graph_override(
    item_kind: str,
    item_id: str,
    knowledge_base_id: int,
    document_id: int,
    background_tasks: BackgroundTasks,
    response: Response,
    source_context_ids: list[str] = Query(default=[]),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _validate_override_kind(item_kind)
    document = _get_accessible_document_for_override(db, knowledge_base_id, document_id, user)
    override = db.scalar(
        select(KgItemOverride).where(
            KgItemOverride.owner_user_id == user.id,
            KgItemOverride.document_id == document.id,
            KgItemOverride.item_kind == item_kind,
            KgItemOverride.item_id == item_id,
        )
    )
    if override is not None:
        db.delete(override)
        db.commit()
        job = _queue_graph_refresh_job(db, background_tasks, document.id, source_context_ids)
        if job is not None:
            response.headers["X-Graph-Refresh-Job-Id"] = str(job.id)
    return {"deleted": override is not None}


def _queue_graph_refresh_job(
    db: Session,
    background_tasks: BackgroundTasks,
    document_id: int,
    source_context_ids: list[str],
) -> ProcessingJob | None:
    source_context_ids = _clean_source_context_ids(source_context_ids)
    active_job = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.document_id == document_id,
            ProcessingJob.stage.in_(["build_graph", "full_pipeline"]),
            ProcessingJob.status.in_(["pending", "running"]),
        )
    )
    if active_job is not None:
        return active_job

    job = ProcessingJob(
        document_id=document_id,
        stage="build_graph",
        status="pending",
        log_path="",
        error_message="",
        payload_json=json.dumps(
            {
                "schema_version_id": None,
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


def _clean_source_context_ids(source_context_ids: list[str]) -> list[str]:
    cleaned: list[str] = []
    for source_context_id in source_context_ids:
        value = str(source_context_id or "").strip()
        if not value or value in cleaned:
            continue
        cleaned.append(value)
    return cleaned


@router.get("/{language}/{artifact_name}")
def graph_artifact(
    language: str,
    artifact_name: str,
    knowledge_base_id: int,
    document_id: int | None = Query(None),
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if artifact_name not in ARTIFACT_FILENAMES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge graph artifact not found.",
        )

    documents = _select_documents(db, knowledge_base_id, document_id, _user)
    run_ids = _available_processed_run_ids(db, documents)

    if run_ids:
        run_contexts = _run_contexts_by_id(db, documents)
        return _load_processed_artifact(
            artifact_name,
            run_ids,
            _overrides_by_run_id(db, _user, documents),
            _annotations_by_run_id(db, _user, documents),
            run_contexts,
        )
    if not _can_use_example_fallback(_user):
        return _empty_artifact(ARTIFACT_FILENAMES[artifact_name])
    return _load_example_artifact(language, artifact_name)


def _select_documents(
    db: Session,
    knowledge_base_id: int,
    document_id: int | None,
    user: User,
) -> list[Document]:
    get_accessible_knowledge_base(db, knowledge_base_id, user)

    statement = select(Document).join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id).where(
        Document.knowledge_base_id == knowledge_base_id,
        Document.is_deleted.is_(False),
    )
    if document_id is not None:
        statement = statement.where(Document.id == document_id)
    if user.role != "admin":
        statement = statement.where(
            or_(
                Document.owner_user_id == user.id,
                KnowledgeBase.owner_user_id.is_(None),
            )
        )
    documents = list(db.scalars(statement.order_by(Document.uploaded_at.asc())))
    if document_id is not None and not documents:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return documents


def _get_accessible_document_for_override(
    db: Session,
    knowledge_base_id: int,
    document_id: int,
    user: User,
) -> Document:
    documents = _select_documents(db, knowledge_base_id, document_id, user)
    if not documents:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return documents[0]


def _validate_override_kind(item_kind: str) -> None:
    if item_kind not in KG_OVERRIDE_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="修正对象只能是 node 或 edge。",
        )


def _clean_override_patch(patch: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for key, value in patch.items():
        if key not in KG_OVERRIDE_PATCH_FIELDS:
            continue
        if value is None:
            cleaned[key] = ""
        elif isinstance(value, str):
            cleaned[key] = value.strip()[:2000]
        elif isinstance(value, bool):
            cleaned[key] = value
        elif isinstance(value, int | float):
            cleaned[key] = value
        elif key == "image_paths" and isinstance(value, list):
            cleaned[key] = [str(item).strip()[:1024] for item in value if str(item).strip()][:20]
    return cleaned


def _validate_annotation_kind(target_kind: str) -> None:
    if target_kind not in KG_ANNOTATION_KINDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="标注对象只能是 node、edge 或 image。",
        )


def _require_admin(user: User) -> None:
    if user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can manage public annotation templates.",
        )


def _clean_annotation_tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        text = str(tag or "").strip()
        if text not in KG_ANNOTATION_TAGS or text in cleaned:
            continue
        cleaned.append(text)
    return cleaned[:10]


def _target_hash(target_id: str) -> str:
    return hashlib.sha256(target_id.encode("utf-8")).hexdigest()


def _override_to_response(override: KgItemOverride) -> KgItemOverrideResponse:
    return KgItemOverrideResponse(
        id=override.id,
        knowledge_base_id=override.knowledge_base_id,
        document_id=override.document_id,
        owner_user_id=override.owner_user_id,
        item_kind=override.item_kind,
        item_id=override.item_id,
        is_new=override.is_new,
        is_hidden=override.is_hidden,
        patch=_load_override_patch(override),
        created_at=override.created_at,
        updated_at=override.updated_at,
    )


def _annotation_to_response(annotation: KgItemAnnotation) -> KgItemAnnotationResponse:
    return KgItemAnnotationResponse(
        id=annotation.id,
        knowledge_base_id=annotation.knowledge_base_id,
        document_id=annotation.document_id,
        owner_user_id=annotation.owner_user_id,
        target_kind=annotation.target_kind,
        target_id=annotation.target_id,
        tags=_load_annotation_tags(annotation),
        note=annotation.note,
        created_at=annotation.created_at,
        updated_at=annotation.updated_at,
    )


def _template_to_response(template: KgAnnotationTemplate) -> KgAnnotationTemplateResponse:
    return KgAnnotationTemplateResponse(
        id=template.id,
        owner_user_id=template.owner_user_id,
        target_kind=template.target_kind,
        name=template.name,
        tags=_load_template_tags(template),
        note=template.note,
        is_public=template.is_public,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _load_override_patch(override: KgItemOverride) -> dict[str, Any]:
    try:
        value = json.loads(override.patch_json or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _load_annotation_tags(annotation: KgItemAnnotation) -> list[str]:
    try:
        value = json.loads(annotation.tags_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return _clean_annotation_tags([str(item) for item in value])


def _load_template_tags(template: KgAnnotationTemplate) -> list[str]:
    try:
        value = json.loads(template.tags_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return _clean_annotation_tags([str(item) for item in value])


def _now_for_override():
    return utc_now_naive()


def _resolve_request_user(
    db: Session,
    credentials: HTTPAuthorizationCredentials | None,
    request: Request,
    access_token: str | None,
) -> User:
    token = extract_access_token(credentials, request, access_token)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated.",
        )

    payload = decode_access_token(token, secret_key=settings.secret_key)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )
    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        )
    try:
        user_id = int(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload.",
        ) from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive.",
        )
    return user


def _graph_source(user: User, run_ids: list[str]) -> str:
    if run_ids:
        return "processed"
    if _can_use_example_fallback(user):
        return "example"
    return "empty"


def _can_use_example_fallback(user: User) -> bool:
    return user.role == "admin" and settings.example_kg_fallback


def _knowledge_base_name(db: Session, knowledge_base_id: int) -> str:
    knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
    return knowledge_base.name if knowledge_base else ""


def _metadata_summary(documents: list[Document]) -> dict[str, str]:
    return {
        "subject": _join_distinct(document.subject for document in documents),
        "grade": _join_distinct(document.grade for document in documents),
        "publisher": _join_distinct(document.publisher for document in documents),
        "textbook": _join_distinct(document.textbook for document in documents),
        "textbook_version": _join_distinct(document.textbook_version for document in documents),
    }


def _join_distinct(values: Any) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text_value = str(value or "").strip()
        if not text_value or text_value in seen:
            continue
        seen.add(text_value)
        result.append(text_value)
    return ", ".join(result)


def _latest_successful_run_id(db: Session, document: Document) -> str | None:
    jobs = list(db.scalars(
        select(ProcessingJob)
        .where(
            ProcessingJob.document_id == document.id,
            ProcessingJob.stage.in_(["build_graph", "full_pipeline"]),
            ProcessingJob.status.in_(["success", "degraded", "failed"]),
        )
        .order_by(ProcessingJob.completed_at.desc().nullslast(), ProcessingJob.created_at.desc())
    ))
    for job in jobs:
        run_id = f"web_doc_{document.id}_{job.id}"
        if job.status in {"success", "degraded"}:
            return run_id
        if all(_processed_artifact_path(run_id, filename).exists() for filename in ARTIFACT_FILENAMES):
            return run_id
    return None


def _available_processed_run_ids(db: Session, documents: list[Document]) -> list[str]:
    run_ids: list[str] = []
    for document in documents:
        run_id = _latest_successful_run_id(db, document)
        if not run_id:
            continue
        if all(_processed_artifact_path(run_id, filename).exists() for filename in ARTIFACT_FILENAMES):
            run_ids.append(run_id)
    return run_ids


def _overrides_by_run_id(
    db: Session,
    user: User,
    documents: list[Document],
) -> dict[str, dict[str, dict[str, KgItemOverride]]]:
    if not documents:
        return {}

    run_by_document_id = {
        document.id: run_id
        for document in documents
        if (run_id := _latest_successful_run_id(db, document))
    }
    if not run_by_document_id:
        return {}

    overrides = db.scalars(
        select(KgItemOverride).where(
            KgItemOverride.owner_user_id == user.id,
            KgItemOverride.document_id.in_(run_by_document_id.keys()),
        )
    )
    result: dict[str, dict[str, dict[str, KgItemOverride]]] = {}
    for override in overrides:
        run_id = run_by_document_id.get(override.document_id)
        if not run_id:
            continue
        result.setdefault(run_id, {"node": {}, "edge": {}})
        result[run_id].setdefault(override.item_kind, {})[override.item_id] = override
    return result


def _annotations_by_run_id(
    db: Session,
    user: User,
    documents: list[Document],
) -> dict[str, dict[str, dict[str, KgItemAnnotation]]]:
    if not documents:
        return {}

    run_by_document_id = {
        document.id: run_id
        for document in documents
        if (run_id := _latest_successful_run_id(db, document))
    }
    if not run_by_document_id:
        return {}

    annotations = db.scalars(
        select(KgItemAnnotation).where(
            KgItemAnnotation.owner_user_id == user.id,
            KgItemAnnotation.document_id.in_(run_by_document_id.keys()),
        )
    )
    result: dict[str, dict[str, dict[str, KgItemAnnotation]]] = {}
    for annotation in annotations:
        run_id = run_by_document_id.get(annotation.document_id)
        if not run_id:
            continue
        result.setdefault(run_id, {"node": {}, "edge": {}, "image": {}})
        result[run_id].setdefault(annotation.target_kind, {})[annotation.target_id] = annotation
    return result


def _run_contexts_by_id(db: Session, documents: list[Document]) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for document in documents:
        run_id = _latest_successful_run_id(db, document)
        if not run_id:
            continue
        contexts[run_id] = {
            "document_id": document.id,
            "document_name": document.filename,
            "knowledge_base_id": document.knowledge_base_id,
        }
    return contexts


def _apply_artifact_overrides(
    artifact: dict[str, Any],
    key: str,
    run_overrides: dict[str, dict[str, KgItemOverride]],
) -> dict[str, Any]:
    node_overrides = run_overrides.get("node", {})
    edge_overrides = run_overrides.get("edge", {})
    hidden_nodes = {item_id for item_id, override in node_overrides.items() if override.is_hidden}
    hidden_edges = {item_id for item_id, override in edge_overrides.items() if override.is_hidden}

    if key == "merged_nodes":
        nodes = []
        for node in artifact.get("nodes", []):
            if not isinstance(node, dict):
                continue
            node_id = _item_id(node, key)
            override = node_overrides.get(node_id)
            if override is not None and override.is_hidden:
                continue
            nodes.append(_apply_node_override(node, override))
        nodes.extend(
            _override_to_new_node(override)
            for override in node_overrides.values()
            if override.is_new and not override.is_hidden
        )
        return {**artifact, "nodes": nodes}

    if key == "merged_edges":
        edges = []
        for edge in artifact.get("edges", []):
            if not isinstance(edge, dict):
                continue
            edge_id = _item_id(edge, key)
            override = edge_overrides.get(edge_id)
            if override is not None and override.is_hidden:
                continue
            patched_edge = _apply_edge_override(edge, override)
            if patched_edge.get("source_node_id") in hidden_nodes or patched_edge.get("target_node_id") in hidden_nodes:
                continue
            edges.append(patched_edge)
        for override in edge_overrides.values():
            if not override.is_new or override.is_hidden:
                continue
            new_edge = _override_to_new_edge(override)
            if new_edge.get("source_node_id") in hidden_nodes or new_edge.get("target_node_id") in hidden_nodes:
                continue
            edges.append(new_edge)
        return {**artifact, "edges": edges}

    triples = []
    for triple in artifact.get("triples", []):
        if not isinstance(triple, dict):
            continue
        if triple.get("subject_node_id") in hidden_nodes or triple.get("object_node_id") in hidden_nodes:
            continue
        edge_id = str(triple.get("edge_id") or "")
        if edge_id in hidden_edges:
            continue
        patched_triple = json.loads(json.dumps(triple, ensure_ascii=False))
        edge_override = edge_overrides.get(edge_id)
        if edge_override is not None:
            patch = _load_override_patch(edge_override)
            if patch.get("predicate"):
                patched_triple["predicate"] = patch["predicate"]
            if patch.get("source_node_id"):
                patched_triple["subject_node_id"] = patch["source_node_id"]
            if patch.get("target_node_id"):
                patched_triple["object_node_id"] = patch["target_node_id"]
            if (
                patched_triple.get("subject_node_id") in hidden_nodes
                or patched_triple.get("object_node_id") in hidden_nodes
            ):
                continue
        triples.append(patched_triple)
    for override in edge_overrides.values():
        if not override.is_new or override.is_hidden:
            continue
        new_triple = _override_to_new_triple(override)
        if new_triple.get("subject_node_id") in hidden_nodes or new_triple.get("object_node_id") in hidden_nodes:
            continue
        triples.append(new_triple)
    return {**artifact, "triples": triples}


def _apply_artifact_annotations(
    artifact: dict[str, Any],
    key: str,
    run_annotations: dict[str, dict[str, KgItemAnnotation]],
) -> dict[str, Any]:
    if not run_annotations:
        return artifact

    node_annotations = run_annotations.get("node", {})
    edge_annotations = run_annotations.get("edge", {})
    image_annotations = run_annotations.get("image", {})
    patched = json.loads(json.dumps(artifact, ensure_ascii=False))

    if key == "merged_nodes":
        nodes = patched.get("nodes", [])
        if isinstance(nodes, list):
            for node in nodes:
                if not isinstance(node, dict):
                    continue
                _attach_item_annotation(node, "properties", node_annotations.get(_item_id(node, key)))
                _attach_figure_annotations(_item_properties(node), image_annotations)
        return patched

    if key == "merged_edges":
        edges = patched.get("edges", [])
        if isinstance(edges, list):
            for edge in edges:
                if not isinstance(edge, dict):
                    continue
                _attach_item_annotation(edge, "properties", edge_annotations.get(_item_id(edge, key)))
                _attach_figure_annotations(_item_properties(edge), image_annotations)
        return patched

    triples = patched.get("triples", [])
    if isinstance(triples, list):
        for triple in triples:
            if not isinstance(triple, dict):
                continue
            edge_id = str(triple.get("edge_id") or "")
            _attach_item_annotation(triple, "properties", edge_annotations.get(edge_id))
            _attach_figure_annotations(triple, image_annotations)
    return patched


def _apply_artifact_source_context(
    artifact: dict[str, Any],
    key: str,
    source_context: dict[str, Any] | None,
) -> dict[str, Any]:
    if not source_context:
        return artifact
    patched = json.loads(json.dumps(artifact, ensure_ascii=False))
    list_key = {
        "merged_nodes": "nodes",
        "merged_edges": "edges",
        "triples": "triples",
    }[key]
    items = patched.get(list_key, [])
    if not isinstance(items, list):
        return patched
    for item in items:
        if not isinstance(item, dict):
            continue
        properties = _item_properties(item)
        properties["web_source_document_id"] = source_context["document_id"]
        properties["web_source_document_name"] = source_context["document_name"]
    return patched


def _attach_item_annotation(
    item: dict[str, Any],
    properties_key: str,
    annotation: KgItemAnnotation | None,
) -> None:
    if annotation is None:
        return
    payload = _annotation_payload(annotation)
    if not payload:
        return
    properties = item.setdefault(properties_key, {})
    if not isinstance(properties, dict):
        properties = {}
        item[properties_key] = properties
    properties["web_annotations"] = payload


def _attach_figure_annotations(
    container: dict[str, Any],
    image_annotations: dict[str, KgItemAnnotation],
) -> None:
    figures = container.get("figures")
    if not isinstance(figures, list):
        return
    for figure in figures:
        if not isinstance(figure, dict):
            continue
        annotation = _find_figure_annotation(figure, image_annotations)
        if annotation is not None:
            payload = _annotation_payload(annotation)
            if payload:
                figure["web_annotations"] = payload


def _find_figure_annotation(
    figure: dict[str, Any],
    image_annotations: dict[str, KgItemAnnotation],
) -> KgItemAnnotation | None:
    candidates = [
        str(figure.get("figure_id") or ""),
        str(figure.get("id") or ""),
        str(figure.get("image_path") or ""),
    ]
    for candidate in candidates:
        if candidate and candidate in image_annotations:
            return image_annotations[candidate]
    return None


def _annotation_payload(annotation: KgItemAnnotation) -> dict[str, Any]:
    tags = _load_annotation_tags(annotation)
    note = annotation.note.strip()
    payload: dict[str, Any] = {}
    if tags:
        payload["tags"] = tags
    if note:
        payload["note"] = note
    return payload


def _item_properties(item: dict[str, Any]) -> dict[str, Any]:
    properties = item.get("properties")
    if isinstance(properties, dict):
        return properties
    properties = {}
    item["properties"] = properties
    return properties


def _apply_node_override(node: dict[str, Any], override: KgItemOverride | None) -> dict[str, Any]:
    patched = json.loads(json.dumps(node, ensure_ascii=False))
    if override is None:
        return patched

    patch = _load_override_patch(override)
    if patch.get("label"):
        patched["label"] = patch["label"]
    properties = patched.setdefault("properties", {})
    if not isinstance(properties, dict):
        properties = {}
        patched["properties"] = properties
    for source_key, target_key in {
        "title": "title",
        "description": "description",
        "source_note": "来源说明",
        "importance": "重要程度",
        "note": "备注",
        "subject_tag": "学科标签",
        "user_evidence": "用户补充证据",
        "evidence_confidence": "证据可信度",
    }.items():
        value = patch.get(source_key)
        if value not in (None, ""):
            properties[target_key] = value
    if patch.get("image_paths"):
        properties["figures"] = [
            {"image_path": image_path, "description": "用户关联图片"}
            for image_path in patch["image_paths"]
        ]
    properties["web_override"] = True
    return patched


def _apply_edge_override(edge: dict[str, Any], override: KgItemOverride | None) -> dict[str, Any]:
    patched = json.loads(json.dumps(edge, ensure_ascii=False))
    if override is None:
        return patched

    patch = _load_override_patch(override)
    if patch.get("predicate"):
        patched["predicate"] = patch["predicate"]
    if patch.get("source_node_id"):
        patched["source_node_id"] = patch["source_node_id"]
    if patch.get("target_node_id"):
        patched["target_node_id"] = patch["target_node_id"]
    properties = patched.setdefault("properties", {})
    if not isinstance(properties, dict):
        properties = {}
        patched["properties"] = properties
    for source_key, target_key in {
        "relation_description": "rationale",
        "source_note": "来源说明",
        "importance": "重要程度",
        "note": "备注",
        "user_evidence": "用户补充证据",
        "evidence_confidence": "证据可信度",
    }.items():
        value = patch.get(source_key)
        if value not in (None, ""):
            properties[target_key] = value
    if patch.get("image_paths"):
        properties["figures"] = [
            {"image_path": image_path, "description": "用户关联图片"}
            for image_path in patch["image_paths"]
        ]
    properties["web_override"] = True
    return patched


def _override_to_new_node(override: KgItemOverride) -> dict[str, Any]:
    patch = _load_override_patch(override)
    properties = {
        "title": patch.get("title") or "用户新增节点",
        "description": patch.get("description") or "",
        "来源说明": patch.get("source_note") or "用户新增",
        "重要程度": patch.get("importance") or "",
        "备注": patch.get("note") or "",
        "学科标签": patch.get("subject_tag") or "",
        "用户补充证据": patch.get("user_evidence") or "",
        "证据可信度": patch.get("evidence_confidence") or "",
        "web_override": True,
        "web_created": True,
    }
    if patch.get("image_paths"):
        properties["figures"] = [
            {"image_path": image_path, "description": "用户关联图片"}
            for image_path in patch["image_paths"]
        ]
    return {
        "node_id": override.item_id,
        "label": patch.get("label") or "KnowledgePoint",
        "properties": {key: value for key, value in properties.items() if value not in (None, "")},
        "source_context_id": "web_override",
        "revision_round": 0,
        "status": "active",
        "audit_refs": [],
        "original_node_ids": [],
    }


def _override_to_new_edge(override: KgItemOverride) -> dict[str, Any]:
    patch = _load_override_patch(override)
    properties = {
        "rationale": patch.get("relation_description") or "",
        "来源说明": patch.get("source_note") or "用户新增",
        "重要程度": patch.get("importance") or "",
        "备注": patch.get("note") or "",
        "用户补充证据": patch.get("user_evidence") or "",
        "证据可信度": patch.get("evidence_confidence") or "",
        "web_override": True,
        "web_created": True,
    }
    if patch.get("image_paths"):
        properties["figures"] = [
            {"image_path": image_path, "description": "用户关联图片"}
            for image_path in patch["image_paths"]
        ]
    return {
        "edge_id": override.item_id,
        "predicate": patch.get("predicate") or "related_to",
        "source_node_id": patch.get("source_node_id") or "",
        "target_node_id": patch.get("target_node_id") or "",
        "properties": {key: value for key, value in properties.items() if value not in (None, "")},
        "source_context_id": "web_override",
        "revision_round": 0,
        "status": "active",
        "audit_refs": [],
        "original_edge_ids": [],
    }


def _override_to_new_triple(override: KgItemOverride) -> dict[str, Any]:
    patch = _load_override_patch(override)
    evidence = []
    if patch.get("user_evidence"):
        evidence.append(
            {
                "source_path": "web_override",
                "section": {"id": "web_override", "title": "用户补充"},
                "quote_or_summary": patch["user_evidence"],
            }
        )
    return {
        "triple_id": f"web_triple_{override.item_id.removeprefix('web_edge_')}",
        "subject_node_id": patch.get("source_node_id") or "",
        "predicate": patch.get("predicate") or "related_to",
        "object_node_id": patch.get("target_node_id") or "",
        "edge_id": override.item_id,
        "evidence": evidence,
        "confidence": 1.0 if patch.get("evidence_confidence") == "已确认" else 0.75,
    }


def _load_processed_artifact(
    artifact_name: str,
    run_ids: list[str],
    overrides_by_run_id: dict[str, dict[str, dict[str, KgItemOverride]]] | None = None,
    annotations_by_run_id: dict[str, dict[str, dict[str, KgItemAnnotation]]] | None = None,
    run_contexts_by_id: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    key = ARTIFACT_FILENAMES[artifact_name]
    if len(run_ids) == 1:
        artifact_path = _processed_artifact_path(run_ids[0], artifact_name)
        if artifact_path.exists():
            artifact = _read_json(artifact_path)
            artifact = _apply_artifact_overrides(
                artifact,
                key,
                overrides_by_run_id.get(run_ids[0], {}) if overrides_by_run_id else {},
            )
            artifact = _apply_artifact_annotations(
                artifact,
                key,
                annotations_by_run_id.get(run_ids[0], {}) if annotations_by_run_id else {},
            )
            return _apply_artifact_source_context(
                artifact,
                key,
                run_contexts_by_id.get(run_ids[0]) if run_contexts_by_id else None,
            )
        return _empty_artifact(key)

    artifacts = [
        _apply_artifact_source_context(
            _apply_artifact_annotations(
                _apply_artifact_overrides(
                    _read_json(path),
                    key,
                    overrides_by_run_id.get(run_id, {}) if overrides_by_run_id else {},
                ),
                key,
                annotations_by_run_id.get(run_id, {}) if annotations_by_run_id else {},
            ),
            key,
            run_contexts_by_id.get(run_id) if run_contexts_by_id else None,
        )
        for run_id in run_ids
        if (path := _processed_artifact_path(run_id, artifact_name)).exists()
    ]
    if not artifacts:
        return _empty_artifact(key)
    return _merge_artifacts(key, artifacts)


def _processed_artifact_path(run_id: str, artifact_name: str) -> Path:
    storage_path = knowledge_graph_run_artifacts_dir(run_id) / artifact_name
    if storage_path.exists():
        return storage_path

    direct_path = _processed_artifact_dir(run_id) / "standard_outputs" / artifact_name
    if direct_path.exists():
        return direct_path

    kg_prefixed_path = _processed_artifact_dir(f"kg_{run_id}") / "standard_outputs" / artifact_name
    if kg_prefixed_path.exists():
        return kg_prefixed_path

    return direct_path


def _processed_artifact_dir(run_id: str) -> Path:
    return (
        settings.project_dir
        / "code_implement"
        / "data"
        / "output"
        / "kg_extraction_outputs"
        / run_id
    )


def _resolve_processed_image_path(run_ids: list[str], image_path: str) -> Path | None:
    relative = _safe_image_relative_path(image_path)
    if relative is None:
        return None

    for run_id in run_ids:
        storage_candidate = _storage_image_candidate(run_id, relative)
        if storage_candidate is not None and storage_candidate.exists() and storage_candidate.is_file():
            return storage_candidate
        for run_dir in _processed_ipa_run_dirs(run_id):
            for candidate in _image_candidates(run_dir, relative):
                if candidate.exists() and candidate.is_file():
                    return candidate
    return None


def _safe_image_relative_path(image_path: str) -> PurePosixPath | None:
    normalized = image_path.replace("\\", "/").split("?", 1)[0].split("#", 1)[0].strip()
    if not normalized:
        return None
    image_index = normalized.rfind("images/")
    relative_text = normalized[image_index:] if image_index >= 0 else f"images/{PurePosixPath(normalized).name}"
    relative = PurePosixPath(relative_text)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    if relative.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    return relative


def _processed_ipa_run_dirs(run_id: str) -> list[Path]:
    root = settings.project_dir / "code_implement" / "data" / "intermediate" / "ipa_outputs" / "full_pipeline"
    if not root.exists():
        return []
    dirs = [path for path in root.iterdir() if path.is_dir() and run_id in path.name]
    return sorted(dirs, key=lambda path: path.stat().st_mtime, reverse=True)


def _storage_image_candidate(run_id: str, relative: PurePosixPath) -> Path | None:
    storage_root = knowledge_graph_run_images_dir(run_id)
    if not storage_root.exists():
        return None
    if relative.parts and relative.parts[0] == "images":
        relative_path = Path(*relative.parts[1:])
    else:
        relative_path = Path(*relative.parts)
    if not relative_path.parts:
        return None
    return storage_root / relative_path


def _image_candidates(run_dir: Path, relative: PurePosixPath) -> list[Path]:
    relative_path = Path(*relative.parts)
    filename = relative.name
    candidates = [
        run_dir / "inputs" / "sections" / relative_path,
        run_dir / "enhanced_markdown" / "sections" / relative_path,
    ]
    for image_dir in [
        run_dir / "inputs" / "sections" / "images",
        run_dir / "enhanced_markdown" / "sections" / "images",
    ]:
        if image_dir.exists():
            candidates.extend(sorted(image_dir.glob(filename)))
    return candidates


def _load_example_artifact(language: str, artifact_name: str) -> dict[str, Any]:
    safe_language = language if language in {"en", "zh"} else "en"
    path = (
        settings.web_dir
        / "frontend"
        / "public"
        / "chemistry"
        / "data"
        / safe_language
        / artifact_name
    )
    if not path.exists():
        path = (
            settings.web_dir
            / "frontend"
            / "public"
            / "chemistry"
            / "data"
            / "en"
            / artifact_name
        )
    return _read_json(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cannot read knowledge graph artifact: {path.name}",
        ) from exc
    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid knowledge graph artifact: {path.name}",
        )
    return data


def _empty_artifact(key: str) -> dict[str, Any]:
    if key == "merged_nodes":
        return {"schema_version": "kg.merged_nodes.v1", "nodes": []}
    if key == "merged_edges":
        return {"schema_version": "kg.merged_edges.v1", "edges": []}
    return {"schema_version": "kg.triples.v1", "triples": []}


def _merge_artifacts(key: str, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    list_key = {
        "merged_nodes": "nodes",
        "merged_edges": "edges",
        "triples": "triples",
    }[key]
    merged_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for artifact in artifacts:
        for item in artifact.get(list_key, []):
            if not isinstance(item, dict):
                continue
            item_id = _item_id(item, key)
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            merged_items.append(item)
    schema_version = artifacts[0].get("schema_version", f"kg.{key}.v1")
    return {"schema_version": schema_version, "run_id": "merged_default_kb", list_key: merged_items}


def _item_id(item: dict[str, Any], key: str) -> str:
    if key == "merged_nodes":
        return str(item.get("node_id") or item.get("id") or "")
    if key == "merged_edges":
        return str(item.get("edge_id") or item.get("id") or "")
    return str(item.get("triple_id") or item.get("id") or "")


def _artifact_counts(
    *,
    source: str,
    run_ids: list[str],
    documents: list[Document] | None = None,
    user: User | None = None,
    db: Session | None = None,
) -> dict[str, int]:
    if source == "example":
        nodes = _load_example_artifact("en", "merged_nodes.json").get("nodes", [])
        edges = _load_example_artifact("en", "merged_edges.json").get("edges", [])
        triples = _load_example_artifact("en", "triples.json").get("triples", [])
        return {
            "nodes": len(nodes) if isinstance(nodes, list) else 0,
            "edges": len(edges) if isinstance(edges, list) else 0,
            "triples": len(triples) if isinstance(triples, list) else 0,
        }
    if source == "empty":
        return {"nodes": 0, "edges": 0, "triples": 0}

    overrides_by_run_id = _overrides_by_run_id(db, user, documents or []) if db is not None and user is not None else {}
    nodes = _load_processed_artifact("merged_nodes.json", run_ids, overrides_by_run_id).get("nodes", [])
    edges = _load_processed_artifact("merged_edges.json", run_ids, overrides_by_run_id).get("edges", [])
    triples = _load_processed_artifact("triples.json", run_ids, overrides_by_run_id).get("triples", [])
    return {
        "nodes": len(nodes) if isinstance(nodes, list) else 0,
        "edges": len(edges) if isinstance(edges, list) else 0,
        "triples": len(triples) if isinstance(triples, list) else 0,
    }
