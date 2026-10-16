from collections.abc import Generator

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.base import Base

connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}

engine = create_engine(settings.database_url, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

APP_TABLES = {
    "api_settings",
    "documents",
    "document_schema_versions",
    "kg_annotation_templates",
    "kg_item_annotations",
    "kg_item_overrides",
    "knowledge_bases",
    "processing_jobs",
    "qa_conversations",
    "qa_messages",
    "user_api_settings",
    "users",
}


def init_db() -> None:
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    from app import models  # noqa: F401

    if settings.auto_migrate_database:
        _migrate_database_to_head()
        return

    if settings.auto_create_tables:
        Base.metadata.create_all(bind=engine)
        _ensure_document_metadata_columns()
        _ensure_user_columns()


def _migrate_database_to_head() -> None:
    if _has_unversioned_app_schema():
        if not settings.database_url.startswith("sqlite"):
            raise RuntimeError(
                "The database has application tables but no Alembic revision. "
                "Create a backup and stamp or migrate it manually."
            )
        if settings.auto_create_tables:
            Base.metadata.create_all(bind=engine)
        _ensure_document_metadata_columns()
        _ensure_user_columns()
        command.stamp(_alembic_config(), "head")
        return

    command.upgrade(_alembic_config(), "head")


def _has_unversioned_app_schema() -> bool:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    if not table_names.intersection(APP_TABLES):
        return False
    if "alembic_version" not in table_names:
        return True

    with engine.connect() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    return version is None


def _alembic_config() -> Config:
    config = Config(str(settings.backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(settings.backend_dir / "migrations"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def _ensure_document_metadata_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "documents" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("documents")}
    required_columns = {
        "owner_user_id": "INTEGER",
        "subject": "VARCHAR(128) DEFAULT '' NOT NULL",
        "grade": "VARCHAR(128) DEFAULT '' NOT NULL",
        "publisher": "VARCHAR(128) DEFAULT '' NOT NULL",
        "textbook": "VARCHAR(255) DEFAULT '' NOT NULL",
        "textbook_version": "VARCHAR(128) DEFAULT '' NOT NULL",
    }

    with engine.begin() as connection:
        for column_name, column_definition in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(f"ALTER TABLE documents ADD COLUMN {column_name} {column_definition}")
                )


def _ensure_user_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("users")}
    required_columns = {
        "approval_status": "VARCHAR(32) DEFAULT 'approved' NOT NULL",
    }

    with engine.begin() as connection:
        for column_name, column_definition in required_columns.items():
            if column_name not in existing_columns:
                connection.execute(
                    text(f"ALTER TABLE users ADD COLUMN {column_name} {column_definition}")
                )


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
