from datetime import datetime

from pydantic import BaseModel


class ApiSettingUpsert(BaseModel):
    provider: str
    model_name: str
    base_url: str = ""
    api_key: str | None = None
    temperature: str = "0.2"
    max_tokens: str = "4096"


class ApiSettingResponse(BaseModel):
    id: int
    provider: str
    model_name: str
    base_url: str
    masked_api_key: str
    has_api_key: bool
    key_source: str = "user"
    temperature: str
    max_tokens: str
    created_at: datetime
    updated_at: datetime


class ApiSettingTestResponse(BaseModel):
    provider: str
    model_name: str
    ok: bool
    status_code: int | None = None
    message: str
    response_preview: str = ""
