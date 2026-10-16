from datetime import datetime

from pydantic import BaseModel


class ProcessingJobResponse(BaseModel):
    id: int
    document_id: int
    schema_version_id: int | None = None
    stage: str
    status: str
    log_path: str
    error_message: str
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
