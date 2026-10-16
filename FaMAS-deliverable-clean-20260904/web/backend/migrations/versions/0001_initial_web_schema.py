"""Initial FaMAS Web schema.

Revision ID: 0001_initial_web_schema
Revises:
Create Date: 2026-08-17
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_web_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("encrypted_api_key", sa.String(length=2048), nullable=False),
        sa.Column("temperature", sa.String(length=32), nullable=False),
        sa.Column("max_tokens", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_api_settings_provider"), "api_settings", ["provider"], unique=True)

    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_knowledge_bases_name"), "knowledge_bases", ["name"], unique=True)
    op.create_index(op.f("ix_knowledge_bases_slug"), "knowledge_bases", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("approval_status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    op.create_table(
        "documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("original_path", sa.String(length=1024), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=128), nullable=False),
        sa.Column("grade", sa.String(length=128), nullable=False),
        sa.Column("publisher", sa.String(length=128), nullable=False),
        sa.Column("textbook", sa.String(length=255), nullable=False),
        sa.Column("textbook_version", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(), nullable=True),
        sa.Column("processing_completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_documents_knowledge_base_id"), "documents", ["knowledge_base_id"], unique=False)
    op.create_index(op.f("ix_documents_owner_user_id"), "documents", ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_documents_status"), "documents", ["status"], unique=False)

    op.create_table(
        "user_api_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("encrypted_api_key", sa.String(length=2048), nullable=False),
        sa.Column("temperature", sa.String(length=32), nullable=False),
        sa.Column("max_tokens", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "provider", name="uq_user_api_provider"),
    )
    op.create_index(op.f("ix_user_api_settings_provider"), "user_api_settings", ["provider"], unique=False)
    op.create_index(op.f("ix_user_api_settings_user_id"), "user_api_settings", ["user_id"], unique=False)

    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("log_path", sa.String(length=1024), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_processing_jobs_document_id"), "processing_jobs", ["document_id"], unique=False)
    op.create_index(op.f("ix_processing_jobs_stage"), "processing_jobs", ["stage"], unique=False)
    op.create_index(op.f("ix_processing_jobs_status"), "processing_jobs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_processing_jobs_status"), table_name="processing_jobs")
    op.drop_index(op.f("ix_processing_jobs_stage"), table_name="processing_jobs")
    op.drop_index(op.f("ix_processing_jobs_document_id"), table_name="processing_jobs")
    op.drop_table("processing_jobs")

    op.drop_index(op.f("ix_user_api_settings_user_id"), table_name="user_api_settings")
    op.drop_index(op.f("ix_user_api_settings_provider"), table_name="user_api_settings")
    op.drop_table("user_api_settings")

    op.drop_index(op.f("ix_documents_status"), table_name="documents")
    op.drop_index(op.f("ix_documents_owner_user_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_knowledge_base_id"), table_name="documents")
    op.drop_table("documents")

    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")

    op.drop_index(op.f("ix_knowledge_bases_slug"), table_name="knowledge_bases")
    op.drop_index(op.f("ix_knowledge_bases_name"), table_name="knowledge_bases")
    op.drop_table("knowledge_bases")

    op.drop_index(op.f("ix_api_settings_provider"), table_name="api_settings")
    op.drop_table("api_settings")
