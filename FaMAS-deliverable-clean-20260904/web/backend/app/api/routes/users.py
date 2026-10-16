import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.security import hash_password
from app.core.validation import validate_password_strength
from app.db.session import get_db
from app.models.api_setting import ApiSetting
from app.models.document import Document
from app.models.kg_item_annotation import KgItemAnnotation
from app.models.kg_item_override import KgItemOverride
from app.models.processing_job import ProcessingJob
from app.models.user import User
from app.models.user_api_setting import UserApiSetting
from app.schemas.user import (
    UserApiProviderOverview,
    UserDocumentOverview,
    UserGraphAnnotationOverview,
    UserGraphOverrideOverview,
    UserManagementItem,
    UserOverview,
    UserPasswordReset,
    UserStatusUpdate,
)

router = APIRouter(prefix="/api/users", tags=["users"])

PROCESSING_STAGES = ["parse_pdf", "build_graph", "full_pipeline"]
ACTIVE_JOB_STATUSES = ["pending", "running"]
SUPPORTED_PROVIDERS = ["dashscope", "deepseek"]


@router.get("", response_model=list[UserManagementItem])
def list_users(
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[UserManagementItem]:
    users = list(db.scalars(select(User).order_by(User.created_at.asc(), User.id.asc())))
    return [_to_management_item(db, user) for user in users]


@router.get("/{user_id}/overview", response_model=UserOverview)
def user_overview(
    user_id: int,
    _admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> UserOverview:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    return UserOverview(
        user=_to_management_item(db, user),
        documents=_user_documents(db, user),
        api_settings=_user_api_settings(db, user),
        graph_overrides=_user_graph_overrides(db, user),
        graph_annotations=_user_graph_annotations(db, user),
    )


@router.put("/{user_id}/status", response_model=UserManagementItem)
def update_user_status(
    user_id: int,
    payload: UserStatusUpdate,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> UserManagementItem:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    if user.id == admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot change your own active status.",
        )
    if user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin accounts cannot be disabled here.",
        )

    user.is_active = payload.is_active
    if payload.is_active:
        user.approval_status = "approved"
    db.commit()
    db.refresh(user)
    return _to_management_item(db, user)


@router.put("/{user_id}/password", response_model=UserManagementItem)
def reset_user_password(
    user_id: int,
    payload: UserPasswordReset,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> UserManagementItem:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found.",
        )
    if user.id == admin.id or user.role == "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Admin passwords must be changed from Settings.",
        )
    password_error = validate_password_strength(payload.new_password)
    if password_error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=password_error,
        )

    user.password_hash = hash_password(payload.new_password)
    user.token_version += 1
    db.commit()
    db.refresh(user)
    return _to_management_item(db, user)


def _to_management_item(db: Session, user: User) -> UserManagementItem:
    document_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.owner_user_id == user.id,
            Document.is_deleted.is_(False),
        )
    )
    active_job_count = db.scalar(
        select(func.count(ProcessingJob.id))
        .join(Document, ProcessingJob.document_id == Document.id)
        .where(
            Document.owner_user_id == user.id,
            Document.is_deleted.is_(False),
            ProcessingJob.stage.in_(PROCESSING_STAGES),
            ProcessingJob.status.in_(ACTIVE_JOB_STATUSES),
        )
    )
    latest_job = db.scalar(
        select(ProcessingJob)
        .join(Document, ProcessingJob.document_id == Document.id)
        .where(
            Document.owner_user_id == user.id,
            Document.is_deleted.is_(False),
            ProcessingJob.stage.in_(PROCESSING_STAGES),
        )
        .order_by(ProcessingJob.created_at.desc())
    )
    return UserManagementItem(
        id=user.id,
        username=user.username,
        role=user.role,
        is_active=user.is_active,
        approval_status=user.approval_status,
        created_at=user.created_at,
        document_count=document_count or 0,
        active_job_count=active_job_count or 0,
        latest_job_stage=latest_job.stage if latest_job else "",
        latest_job_status=latest_job.status if latest_job else "",
    )


def _user_documents(db: Session, user: User) -> list[UserDocumentOverview]:
    documents = list(db.scalars(
        select(Document)
        .where(
            Document.owner_user_id == user.id,
            Document.is_deleted.is_(False),
        )
        .order_by(Document.uploaded_at.desc())
    ))
    return [_to_document_overview(db, document) for document in documents]


def _to_document_overview(db: Session, document: Document) -> UserDocumentOverview:
    latest_job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.document_id == document.id,
            ProcessingJob.stage.in_(PROCESSING_STAGES),
        )
        .order_by(ProcessingJob.created_at.desc())
    )
    return UserDocumentOverview(
        id=document.id,
        filename=document.filename,
        status=document.status,
        subject=document.subject,
        grade=document.grade,
        publisher=document.publisher,
        latest_job_stage=latest_job.stage if latest_job else "",
        latest_job_status=latest_job.status if latest_job else "",
        latest_job_error=latest_job.error_message if latest_job else "",
        uploaded_at=document.uploaded_at,
    )


def _user_api_settings(db: Session, user: User) -> list[UserApiProviderOverview]:
    results: list[UserApiProviderOverview] = []
    for provider in SUPPORTED_PROVIDERS:
        user_setting = db.scalar(
            select(UserApiSetting).where(
                UserApiSetting.user_id == user.id,
                UserApiSetting.provider == provider,
            )
        )
        system_setting = db.scalar(select(ApiSetting).where(ApiSetting.provider == provider))
        user_key_configured = bool(user_setting and user_setting.encrypted_api_key)
        system_fallback_available = bool(system_setting and system_setting.encrypted_api_key)
        effective_source = "none"
        model_name = ""
        if user_key_configured:
            effective_source = "user"
            model_name = user_setting.model_name
        elif system_fallback_available:
            effective_source = "system"
            model_name = system_setting.model_name
        results.append(
            UserApiProviderOverview(
                provider=provider,
                user_key_configured=user_key_configured,
                system_fallback_available=system_fallback_available,
                effective_source=effective_source,
                model_name=model_name,
            )
        )
    return results


def _user_graph_overrides(db: Session, user: User) -> list[UserGraphOverrideOverview]:
    records = list(db.execute(
        select(KgItemOverride, Document)
        .join(Document, KgItemOverride.document_id == Document.id)
        .where(
            KgItemOverride.owner_user_id == user.id,
            Document.is_deleted.is_(False),
        )
        .order_by(KgItemOverride.updated_at.desc())
    ))
    return [
        UserGraphOverrideOverview(
            id=override.id,
            owner_user_id=user.id,
            owner_username=user.username,
            document_id=document.id,
            document_filename=document.filename,
            item_kind=override.item_kind,
            item_id=override.item_id,
            is_new=override.is_new,
            is_hidden=override.is_hidden,
            summary=_override_summary(override),
            updated_at=override.updated_at,
        )
        for override, document in records
    ]


def _user_graph_annotations(db: Session, user: User) -> list[UserGraphAnnotationOverview]:
    records = list(db.execute(
        select(KgItemAnnotation, Document)
        .join(Document, KgItemAnnotation.document_id == Document.id)
        .where(
            KgItemAnnotation.owner_user_id == user.id,
            Document.is_deleted.is_(False),
        )
        .order_by(KgItemAnnotation.updated_at.desc())
    ))
    return [
        UserGraphAnnotationOverview(
            id=annotation.id,
            owner_user_id=user.id,
            owner_username=user.username,
            document_id=document.id,
            document_filename=document.filename,
            target_kind=annotation.target_kind,
            target_id=annotation.target_id,
            tags=_annotation_tags(annotation),
            note=annotation.note,
            updated_at=annotation.updated_at,
        )
        for annotation, document in records
    ]


def _override_summary(override: KgItemOverride) -> str:
    patch = _json_object(override.patch_json)
    for key in ["title", "predicate", "relation_description", "description", "note"]:
        value = str(patch.get(key) or "").strip()
        if value:
            return value[:120]
    if override.is_hidden:
        return "已隐藏"
    if override.is_new:
        return "用户新增"
    return "人工修正"


def _annotation_tags(annotation: KgItemAnnotation) -> list[str]:
    value = _json_list(annotation.tags_json)
    return [str(item).strip() for item in value if str(item).strip()]


def _json_object(text: str) -> dict:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _json_list(text: str) -> list:
    try:
        value = json.loads(text or "[]")
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []
