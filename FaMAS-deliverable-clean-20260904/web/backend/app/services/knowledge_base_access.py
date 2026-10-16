from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User


def visible_knowledge_base_statement(user: User):
    statement = select(KnowledgeBase).where(KnowledgeBase.is_deleted.is_(False))
    if user.role != "admin":
        statement = statement.where(
            or_(
                KnowledgeBase.owner_user_id == user.id,
                KnowledgeBase.owner_user_id.is_(None),
            )
        )
    return statement.order_by(KnowledgeBase.created_at.asc())


def get_accessible_knowledge_base(db: Session, knowledge_base_id: int, user: User) -> KnowledgeBase:
    knowledge_base = db.get(KnowledgeBase, knowledge_base_id)
    if not can_access_knowledge_base(user, knowledge_base):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Knowledge base not found.",
        )
    return knowledge_base


def can_access_knowledge_base(user: User, knowledge_base: KnowledgeBase | None) -> bool:
    if knowledge_base is None or knowledge_base.is_deleted:
        return False
    return user.role == "admin" or knowledge_base.owner_user_id in {None, user.id}


def can_manage_knowledge_base(user: User, knowledge_base: KnowledgeBase | None) -> bool:
    if knowledge_base is None or knowledge_base.is_deleted:
        return False
    return user.role == "admin" or knowledge_base.owner_user_id == user.id


def document_count_for_user(db: Session, knowledge_base: KnowledgeBase, user: User) -> int:
    statement = select(func.count(Document.id)).where(
        Document.knowledge_base_id == knowledge_base.id,
        Document.is_deleted.is_(False),
    )
    if user.role != "admin" and knowledge_base.owner_user_id is not None:
        statement = statement.where(Document.owner_user_id == user.id)
    return int(db.scalar(statement) or 0)


def can_view_document(user: User, document: Document | None) -> bool:
    if document is None or document.is_deleted:
        return False
    if user.role == "admin" or document.owner_user_id == user.id:
        return True
    knowledge_base = document.knowledge_base
    return knowledge_base is not None and knowledge_base.owner_user_id is None


def can_manage_document(user: User, document: Document | None) -> bool:
    if document is None or document.is_deleted:
        return False
    return user.role == "admin" or document.owner_user_id == user.id


def normalize_knowledge_base_name(name: str) -> str:
    normalized = " ".join(name.strip().split())
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge base name is required.",
        )
    if len(normalized) > 80:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge base name must be 80 characters or fewer.",
        )
    return normalized


def build_knowledge_base_slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_-]+", "-", name.strip().lower()).strip("-")
    return slug[:64] or "knowledge-base"
