from datetime import datetime

from pydantic import BaseModel, Field


class KgItemAnnotationUpdate(BaseModel):
    knowledge_base_id: int
    document_id: int
    tags: list[str] = Field(default_factory=list)
    note: str = ""


class KgItemAnnotationResponse(BaseModel):
    id: int
    knowledge_base_id: int
    document_id: int
    owner_user_id: int
    target_kind: str
    target_id: str
    tags: list[str]
    note: str
    created_at: datetime
    updated_at: datetime
