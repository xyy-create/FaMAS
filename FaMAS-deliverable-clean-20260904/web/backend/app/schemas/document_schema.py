from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentSchemaVersionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    document_id: int
    owner_user_id: int | None
    version_number: int
    title: str
    source: str
    prompt_text: str
    schema_definition: dict[str, Any] = Field(alias="schema")
    is_active: bool
    created_at: datetime
    updated_at: datetime


class DocumentSchemaVersionCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(default="自定义 schema", max_length=255)
    prompt_text: str = ""
    schema_definition: dict[str, Any] = Field(alias="schema")
    activate: bool = False


class DocumentSchemaVersionUpdate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = Field(default=None, max_length=255)
    prompt_text: str | None = None
    schema_definition: dict[str, Any] | None = Field(default=None, alias="schema")


class DocumentSchemaTemplateRequest(BaseModel):
    title: str = Field(default="系统推荐 schema", max_length=255)
    prompt_text: str = ""
    activate: bool = True


class DocumentSchemaLlmRewriteRequest(BaseModel):
    instruction: str = ""
    preset: str = ""
    provider: str = "dashscope"
    model_name: str | None = None
    activate: bool = False
