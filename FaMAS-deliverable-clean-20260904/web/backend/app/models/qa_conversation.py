from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.time import utc_now_naive
from app.db.base import Base


class QaConversation(Base):
    __tablename__ = "qa_conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    document_id: Mapped[int | None] = mapped_column(ForeignKey("documents.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    provider: Mapped[str] = mapped_column(String(64), default="dashscope")
    answer_mode: Mapped[str] = mapped_column(String(32), default="strict")
    answer_style: Mapped[str] = mapped_column(String(32), default="textbook")
    is_deleted: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)

    messages: Mapped[list["QaMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="QaMessage.created_at",
    )


class QaMessage(Base):
    __tablename__ = "qa_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("qa_conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(32))
    content: Mapped[str] = mapped_column(Text, default="")
    citations_json: Mapped[str] = mapped_column(Text, default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive, index=True)

    conversation: Mapped["QaConversation"] = relationship(back_populates="messages")
