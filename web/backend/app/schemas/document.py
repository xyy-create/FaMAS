from datetime import datetime

from pydantic import BaseModel

from app.schemas.processing_job import ProcessingJobResponse


class DocumentResponse(BaseModel):
    id: int
    knowledge_base_id: int
    owner_user_id: int | None = None
    filename: str
    file_size_bytes: int
    subject: str = ""
    grade: str = ""
    publisher: str = ""
    textbook: str = ""
    textbook_version: str = ""
    status: str
    uploaded_at: datetime
    processing_started_at: datetime | None
    processing_completed_at: datetime | None
    latest_job: ProcessingJobResponse | None = None
