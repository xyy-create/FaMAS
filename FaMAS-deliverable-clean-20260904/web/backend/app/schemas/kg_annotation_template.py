from datetime import datetime

from pydantic import BaseModel, Field


class KgAnnotationTemplateCreate(BaseModel):
    target_kind: str
    name: str
    tags: list[str] = Field(default_factory=list)
    note: str = ""


class KgAnnotationTemplateUpdate(BaseModel):
    name: str
    tags: list[str] = Field(default_factory=list)
    note: str = ""


class KgAnnotationTemplateResponse(BaseModel):
    id: int
    owner_user_id: int
    target_kind: str
    name: str
    tags: list[str]
    note: str
    is_public: bool
    created_at: datetime
    updated_at: datetime
