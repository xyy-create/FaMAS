from __future__ import annotations

import platform
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.runtime_security import secret_key_is_development_value
from app.core.security import hash_password, verify_password
from app.core.validation import validate_password_strength
from app.db.default_knowledge_base import DEFAULT_KNOWLEDGE_BASE_NAME
from app.db.default_knowledge_base import DEFAULT_KNOWLEDGE_BASE_SLUG
from app.db.session import get_db
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.processing_job import ProcessingJob
from app.models.user import User
from app.schemas.user import UserProfile

router = APIRouter(prefix="/api/settings/system", tags=["system-settings"])


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("")
def system_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if user.role != "admin":
        return _user_settings(user, db)

    default_kb = db.scalar(
        select(KnowledgeBase).where(
            KnowledgeBase.slug == DEFAULT_KNOWLEDGE_BASE_SLUG,
            KnowledgeBase.is_deleted.is_(False),
        )
    )
    if default_kb is None:
        default_kb = db.scalar(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.owner_user_id.is_(None),
                KnowledgeBase.is_deleted.is_(False),
            )
            .order_by(KnowledgeBase.created_at.asc())
        )
    active_job_count = _active_job_count(db)
    pending_job_count = _job_count_by_status(db, "pending")
    running_job_count = _job_count_by_status(db, "running")
    has_active_jobs = active_job_count > 0
    active_job_limit = settings.pipeline_worker_concurrency if settings.pipeline_worker_enabled else 0
    queue_slots_available = max(0, active_job_limit - running_job_count)
    return {
        "admin": UserProfile(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            approval_status=user.approval_status,
        ),
        "runtime": {
            "frontend": "Vue + Vite",
            "backend": "Python + FastAPI",
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "database": _database_label(),
            "mock_pipeline": settings.pipeline_mock,
            "runtime_mode": settings.runtime_mode,
            "frontend_dist": _frontend_dist_label(),
        },
        "modes": {
            "registration": _registration_mode_label(),
            "registration_requires_approval": settings.registration_mode == "approval",
            "example_kg_fallback": settings.example_kg_fallback,
            "pipeline_stop_at": settings.pipeline_stop_at,
            "pipeline_worker_enabled": settings.pipeline_worker_enabled,
            "pipeline_worker_concurrency": settings.pipeline_worker_concurrency,
            "mineru_model_source": settings.mineru_model_source,
            "mineru_device_mode": settings.mineru_device_mode,
        },
        "storage": _storage_settings(),
        "jobs": {
            "active_job_limit": active_job_limit,
            "active_job_count": active_job_count,
            "pending_job_count": pending_job_count,
            "running_job_count": running_job_count,
            "queue_slots_available": queue_slots_available,
            "has_active_job": has_active_jobs,
        },
        "knowledge_base": {
            "id": default_kb.id if default_kb else None,
            "name": default_kb.name if default_kb else DEFAULT_KNOWLEDGE_BASE_NAME,
            "multi_kb_management": "reserved",
        },
        "public_access": _public_access_status(),
    }


@router.post("/account/password")
@router.post("/admin/password")
def change_account_password(
    payload: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect.",
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
    return {"status": "ok"}


def _user_settings(user: User, db: Session) -> dict[str, Any]:
    document_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.owner_user_id == user.id,
            Document.is_deleted.is_(False),
        )
    )
    active_job_count = _active_job_count(db, user=user)
    pending_job_count = _job_count_by_status(db, "pending", user=user)
    running_job_count = _job_count_by_status(db, "running", user=user)
    active_job_limit = settings.pipeline_worker_concurrency if settings.pipeline_worker_enabled else 0
    return {
        "admin": UserProfile(
            id=user.id,
            username=user.username,
            role=user.role,
            is_active=user.is_active,
            approval_status=user.approval_status,
        ),
        "runtime": {
            "frontend": "Vue + Vite",
            "backend": "Python + FastAPI",
            "database": _database_label(),
            "mock_pipeline": settings.pipeline_mock,
            "runtime_mode": settings.runtime_mode,
            "frontend_dist": _frontend_dist_label(),
        },
        "modes": {
            "registration": _registration_mode_label(),
            "registration_requires_approval": settings.registration_mode == "approval",
        },
        "storage": {},
        "jobs": {
            "active_job_limit": active_job_limit,
            "active_job_count": active_job_count,
            "pending_job_count": pending_job_count,
            "running_job_count": running_job_count,
            "queue_slots_available": max(0, active_job_limit - running_job_count),
            "has_active_job": active_job_count > 0,
        },
        "usage": {
            "document_count": document_count or 0,
        },
        "knowledge_base": {
            "name": DEFAULT_KNOWLEDGE_BASE_NAME,
            "multi_kb_management": "reserved",
        },
    }


def _database_label() -> str:
    if settings.database_url.startswith("sqlite"):
        return "SQLite"
    if settings.database_url.startswith("postgresql"):
        return "PostgreSQL"
    return settings.database_url.split(":", 1)[0]


def _active_job_count(db: Session, user: User | None = None) -> int:
    return _pipeline_job_count(db, ["pending", "running"], user=user)


def _job_count_by_status(db: Session, status_value: str, user: User | None = None) -> int:
    return _pipeline_job_count(db, [status_value], user=user)


def _pipeline_job_count(db: Session, statuses: list[str], user: User | None = None) -> int:
    statement = select(func.count(ProcessingJob.id)).where(
        ProcessingJob.stage.in_(["parse_pdf", "build_graph", "full_pipeline"]),
        ProcessingJob.status.in_(statuses),
    )
    if user is not None:
        statement = statement.join(Document, ProcessingJob.document_id == Document.id).where(
            Document.owner_user_id == user.id,
            Document.is_deleted.is_(False),
        )
    return db.scalar(statement) or 0


def _frontend_dist_label() -> str:
    frontend_dist = settings.web_dir / "frontend" / "dist" / "index.html"
    return "built" if frontend_dist.exists() else "not built"


def _frontend_dist_ready() -> bool:
    return (settings.web_dir / "frontend" / "dist" / "index.html").exists()


def _storage_settings() -> dict[str, Any]:
    storage = {
        "diagnostics_enabled": settings.enable_diagnostics,
        "chunk_size_bytes": settings.upload_chunk_size_bytes,
        "max_upload_bytes": settings.max_upload_bytes,
    }
    if settings.enable_diagnostics:
        storage.update(
            {
                "project_dir": str(settings.project_dir),
                "web_dir": str(settings.web_dir),
                "storage_dir": str(settings.storage_dir),
                "user_storage_dir": str(settings.user_storage_dir),
                "upload_dir": str(settings.upload_dir),
                "job_log_dir": str(settings.job_log_dir),
            }
        )
    return storage


def _public_access_status() -> dict[str, Any]:
    checks = {
        "single_port_frontend_ready": _frontend_dist_ready(),
        "registration_approval_enabled": settings.registration_mode == "approval",
        "secret_key_hardened": not secret_key_is_development_value(settings.secret_key),
        "public_url_configured": bool(settings.public_url),
    }
    return {
        "public_url": settings.public_url,
        "recommended_local_target": "http://127.0.0.1:8000",
        "checks": checks,
        "ready_for_temporary_public_access": all(checks.values()),
    }


def _registration_mode_label() -> str:
    if settings.registration_mode == "approval":
        return "approval"
    return "immediate"
