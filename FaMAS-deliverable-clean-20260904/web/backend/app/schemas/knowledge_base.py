from datetime import datetime

from pydantic import BaseModel


class KnowledgeBaseResponse(BaseModel):
    id: int
    owner_user_id: int | None = None
    name: str
    slug: str
    is_system: bool = False
    document_count: int = 0
    created_at: datetime


class KnowledgeBaseCreate(BaseModel):
    name: str


class KnowledgeBaseUpdate(BaseModel):
    name: str
