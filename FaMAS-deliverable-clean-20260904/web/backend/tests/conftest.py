from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
import shutil
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import models  # noqa: F401
from app.core.config import settings
from app.core.security import create_access_token, hash_password
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.knowledge_base import KnowledgeBase
from app.models.user import User
from app.services.login_rate_limit import clear_login_rate_limits


@pytest.fixture(autouse=True)
def reset_login_rate_limits() -> Generator[None, None, None]:
    clear_login_rate_limits()
    yield
    clear_login_rate_limits()


@pytest.fixture
def runtime_dir() -> Generator[Path, None, None]:
    path = Path(__file__).resolve().parents[1] / ".test_runtime" / uuid.uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def db_session_factory(runtime_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[sessionmaker[Session], None, None]:
    monkeypatch.setattr(settings, "secret_key", "test-secret-key")
    monkeypatch.setattr(settings, "secret_encryption_key", "test-secret-key")
    monkeypatch.setattr(settings, "legacy_secret_encryption_keys", ())
    monkeypatch.setattr(settings, "registration_mode", "immediate")
    monkeypatch.setattr(settings, "pipeline_worker_enabled", False)
    monkeypatch.setattr(settings, "seed_default_knowledge_base", False)
    monkeypatch.setattr(settings, "storage_dir", runtime_dir / "storage")
    monkeypatch.setattr(settings, "user_storage_dir", runtime_dir / "storage" / "users")
    monkeypatch.setattr(settings, "upload_dir", runtime_dir / "storage" / "uploads")
    monkeypatch.setattr(settings, "job_log_dir", runtime_dir / "storage" / "jobs")
    monkeypatch.setattr(settings, "chunk_upload_dir", runtime_dir / "storage" / "chunk_uploads")

    engine = create_engine(
        f"sqlite:///{runtime_dir / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    try:
        yield session_factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def db_session(db_session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    with db_session_factory() as session:
        yield session


@pytest.fixture
def client(db_session_factory: sessionmaker[Session]) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        with db_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def create_user(
    db: Session,
    username: str,
    *,
    role: str = "user",
    password: str = "password123",
    is_active: bool = True,
    approval_status: str = "approved",
) -> User:
    user = User(
        username=username,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
        approval_status=approval_status,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_knowledge_base(db: Session, name: str = "小初高知识全集", owner_user_id: int | None = None) -> KnowledgeBase:
    slug = name.lower().replace(" ", "-")
    knowledge_base = KnowledgeBase(name=name, slug=slug, owner_user_id=owner_user_id, is_deleted=False)
    db.add(knowledge_base)
    db.commit()
    db.refresh(knowledge_base)
    return knowledge_base


def auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(
        str(user.id),
        secret_key=settings.secret_key,
        expires_in_seconds=3600,
        token_version=user.token_version,
    )
    return {"Authorization": f"Bearer {token}"}
