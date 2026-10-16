from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now_naive
from app.db.base import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    owner_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    original_path: Mapped[str] = mapped_column(String(1024))
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    subject: Mapped[str] = mapped_column(String(128), default="")
    grade: Mapped[str] = mapped_column(String(128), default="")
    publisher: Mapped[str] = mapped_column(String(128), default="")
    textbook: Mapped[str] = mapped_column(String(255), default="")
    textbook_version: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    is_deleted: Mapped[bool] = mapped_column(default=False)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processing_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    knowledge_base: Mapped["KnowledgeBase"] = relationship(back_populates="documents")
    owner: Mapped["User"] = relationship()
    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="document")
    schema_versions: Mapped[list["DocumentSchemaVersion"]] = relationship(back_populates="document")
