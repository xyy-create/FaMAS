from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

import pytest

from app.core.config import settings
from app.core.security import verify_password
from app.db.seed import ensure_admin_user
from app.models.user import User


def test_public_runtime_rejects_weak_initial_admin_password(
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "runtime_mode", "public")
    monkeypatch.setenv("FAMAS_ADMIN_PASSWORD", "66666666")

    with pytest.raises(RuntimeError, match="FAMAS_ADMIN_PASSWORD"):
        ensure_admin_user(db_session)

    assert db_session.scalar(select(User).where(User.username == "admin")) is None


def test_public_runtime_accepts_strong_initial_admin_password(
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "runtime_mode", "public")
    monkeypatch.setenv("FAMAS_ADMIN_PASSWORD", "Adminpass123")

    ensure_admin_user(db_session)
    db_session.commit()

    admin = db_session.scalar(select(User).where(User.username == "admin"))
    assert admin is not None
    assert admin.role == "admin"
    assert verify_password("Adminpass123", admin.password_hash)


def test_development_runtime_keeps_initial_admin_password_flexible(
    db_session: Session,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "runtime_mode", "development")
    monkeypatch.setenv("FAMAS_ADMIN_PASSWORD", "66666666")

    ensure_admin_user(db_session)
    db_session.commit()

    admin = db_session.scalar(select(User).where(User.username == "admin"))
    assert admin is not None
    assert verify_password("66666666", admin.password_hash)
