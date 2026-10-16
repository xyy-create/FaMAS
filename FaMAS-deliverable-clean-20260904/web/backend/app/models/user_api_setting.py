from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now_naive
from app.db.base import Base


class UserApiSetting(Base):
    __tablename__ = "user_api_settings"
    __table_args__ = (UniqueConstraint("user_id", "provider", name="uq_user_api_provider"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(64), index=True)
    model_name: Mapped[str] = mapped_column(String(128))
    base_url: Mapped[str] = mapped_column(String(512), default="")
    encrypted_api_key: Mapped[str] = mapped_column(String(2048), default="")
    temperature: Mapped[str] = mapped_column(String(32), default="0.2")
    max_tokens: Mapped[str] = mapped_column(String(32), default="4096")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now_naive)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utc_now_naive,
        onupdate=utc_now_naive,
    )
