from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.time import utc_now_naive
from app.db.base import Base


class ApiSetting(Base):
    __tablename__ = "api_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), unique=True, index=True)
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
