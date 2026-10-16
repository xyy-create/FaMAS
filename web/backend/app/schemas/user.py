from pydantic import BaseModel
from datetime import datetime


class UserProfile(BaseModel):
    id: int
    username: str
    role: str
    is_active: bool
    approval_status: str = "approved"


class UserManagementItem(UserProfile):
    created_at: datetime
    document_count: int = 0
    active_job_count: int = 0
    latest_job_stage: str = ""
    latest_job_status: str = ""


class UserDocumentOverview(BaseModel):
    id: int
    filename: str
    status: str
    subject: str = ""
    grade: str = ""
    publisher: str = ""
    latest_job_stage: str = ""
    latest_job_status: str = ""
    latest_job_error: str = ""
    uploaded_at: datetime


class UserApiProviderOverview(BaseModel):
    provider: str
    user_key_configured: bool = False
    system_fallback_available: bool = False
    effective_source: str = "none"
    model_name: str = ""


class UserGraphOverrideOverview(BaseModel):
    id: int
    owner_user_id: int
    owner_username: str
    document_id: int
    document_filename: str
    item_kind: str
    item_id: str
    is_new: bool = False
    is_hidden: bool = False
    summary: str = ""
    updated_at: datetime


class UserGraphAnnotationOverview(BaseModel):
    id: int
    owner_user_id: int
    owner_username: str
    document_id: int
    document_filename: str
    target_kind: str
    target_id: str
    tags: list[str] = []
    note: str = ""
    updated_at: datetime


class UserOverview(BaseModel):
    user: UserManagementItem
    documents: list[UserDocumentOverview]
    api_settings: list[UserApiProviderOverview]
    graph_overrides: list[UserGraphOverrideOverview] = []
    graph_annotations: list[UserGraphAnnotationOverview] = []


class UserStatusUpdate(BaseModel):
    is_active: bool


class UserPasswordReset(BaseModel):
    new_password: str
