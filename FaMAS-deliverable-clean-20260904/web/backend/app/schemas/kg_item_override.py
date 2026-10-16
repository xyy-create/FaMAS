from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class KgItemOverrideUpdate(BaseModel):
    knowledge_base_id: int
    document_id: int
    is_hidden: bool = False
    patch: dict[str, Any] = Field(default_factory=dict)
    source_context_ids: list[str] = Field(default_factory=list)


class KgNodeOverrideCreate(BaseModel):
    knowledge_base_id: int
    document_id: int
    source_context_ids: list[str] = Field(default_factory=list)
    title: str
    label: str = "KnowledgePoint"
    description: str = ""
    source_note: str = ""
    importance: str = ""
    note: str = ""
    subject_tag: str = ""
    user_evidence: str = ""
    evidence_confidence: str = ""
    image_paths: list[str] = Field(default_factory=list)


class KgEdgeOverrideCreate(BaseModel):
    knowledge_base_id: int
    document_id: int
    source_context_ids: list[str] = Field(default_factory=list)
    source_node_id: str
    target_node_id: str
    predicate: str = "related_to"
    relation_description: str = ""
    source_note: str = ""
    importance: str = ""
    note: str = ""
    user_evidence: str = ""
    evidence_confidence: str = ""
    image_paths: list[str] = Field(default_factory=list)


class KgItemOverrideResponse(BaseModel):
    id: int
    knowledge_base_id: int
    document_id: int
    owner_user_id: int
    item_kind: str
    item_id: str
    is_new: bool
    is_hidden: bool
    patch: dict[str, Any]
    created_at: datetime
    updated_at: datetime
