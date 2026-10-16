from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseResponse, KnowledgeBaseUpdate
from app.services.knowledge_base_access import (
    build_knowledge_base_slug,
    can_manage_knowledge_base,
    document_count_for_user,
    get_accessible_knowledge_base,
    normalize_knowledge_base_name,
    visible_knowledge_base_statement,
)

router = APIRouter(prefix="/api/knowledge-bases", tags=["knowledge-bases"])


@router.get("", response_model=list[KnowledgeBaseResponse])
def list_knowledge_bases(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[KnowledgeBaseResponse]:
    knowledge_bases = list(db.scalars(visible_knowledge_base_statement(user)))
    return [_to_response(db, knowledge_base, user) for knowledge_base in knowledge_bases]


@router.post("", response_model=KnowledgeBaseResponse)
def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeBaseResponse:
    name = normalize_knowledge_base_name(payload.name)
    _ensure_name_available(db, name, user)
    knowledge_base = KnowledgeBase(
        owner_user_id=user.id,
        name=name,
        slug=build_knowledge_base_slug(name),
        is_deleted=False,
    )
    db.add(knowledge_base)
    db.commit()
    db.refresh(knowledge_base)
    return _to_response(db, knowledge_base, user)


@router.put("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(
    knowledge_base_id: int,
    payload: KnowledgeBaseUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeBaseResponse:
    knowledge_base = get_accessible_knowledge_base(db, knowledge_base_id, user)
    if not can_manage_knowledge_base(user, knowledge_base):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot modify this knowledge base.",
        )

    name = normalize_knowledge_base_name(payload.name)
    _ensure_name_available(db, name, user, current_id=knowledge_base.id)
    knowledge_base.name = name
    knowledge_base.slug = build_knowledge_base_slug(name)
    db.commit()
    db.refresh(knowledge_base)
    return _to_response(db, knowledge_base, user)


@router.delete("/{knowledge_base_id}", response_model=KnowledgeBaseResponse)
def delete_knowledge_base(
    knowledge_base_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> KnowledgeBaseResponse:
    knowledge_base = get_accessible_knowledge_base(db, knowledge_base_id, user)
    if not can_manage_knowledge_base(user, knowledge_base):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete this knowledge base.",
        )

    knowledge_base.is_deleted = True
    document_statement = select(Document).where(
        Document.knowledge_base_id == knowledge_base.id,
        Document.is_deleted.is_(False),
    )
    if user.role != "admin":
        document_statement = document_statement.where(Document.owner_user_id == user.id)
    for document in db.scalars(document_statement):
        document.is_deleted = True
        document.status = "deleted"

    response = _to_response(db, knowledge_base, user)
    db.commit()
    return response


def _ensure_name_available(
    db: Session,
    name: str,
    user: User,
    *,
    current_id: int | None = None,
) -> None:
    statement = select(KnowledgeBase).where(
        KnowledgeBase.name == name,
        KnowledgeBase.is_deleted.is_(False),
        or_(
            KnowledgeBase.owner_user_id == user.id,
            KnowledgeBase.owner_user_id.is_(None),
        ),
    )
    if current_id is not None:
        statement = statement.where(KnowledgeBase.id != current_id)
    if db.scalar(statement) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Knowledge base name already exists.",
        )


def _to_response(db: Session, knowledge_base: KnowledgeBase, user: User) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(
        id=knowledge_base.id,
        owner_user_id=knowledge_base.owner_user_id,
        name=knowledge_base.name,
        slug=knowledge_base.slug,
        is_system=knowledge_base.owner_user_id is None,
        document_count=document_count_for_user(db, knowledge_base, user),
        created_at=knowledge_base.created_at,
    )
