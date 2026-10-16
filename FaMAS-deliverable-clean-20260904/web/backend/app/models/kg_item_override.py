from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now_naive
from app.db.base import Base


class KgItemOverride(Base):
    __tablename__ = "kg_item_overrides"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "document_id",
            "item_kind",
            "item_id",
            name="uq_kg_item_override_user_document_item",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), index=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), index=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    item_kind: Mapped[str] = mapped_column(String(16), index=True)
    item_id: Mapped[str] = mapped_column(String(255), index=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    patch_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
