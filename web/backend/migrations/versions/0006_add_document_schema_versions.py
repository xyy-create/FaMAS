"""Add document schema versions.

Revision ID: 0006_add_document_schema_versions
Revises: 0005_add_qa_conversations
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0006_add_document_schema_versions"
down_revision: str | None = "0005_add_qa_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "document_schema_versions" in set(inspector.get_table_names()):
        return

    op.create_table(
        "document_schema_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("schema_json", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_schema_version_number"),
    )
    op.create_index(
        op.f("ix_document_schema_versions_document_id"),
        "document_schema_versions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_schema_versions_is_active"),
        "document_schema_versions",
        ["is_active"],
        unique=False,
    )
    op.create_index(
        op.f("ix_document_schema_versions_owner_user_id"),
        "document_schema_versions",
        ["owner_user_id"],
        unique=False,
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "document_schema_versions" not in set(inspector.get_table_names()):
        return

    op.drop_index(op.f("ix_document_schema_versions_owner_user_id"), table_name="document_schema_versions")
    op.drop_index(op.f("ix_document_schema_versions_is_active"), table_name="document_schema_versions")
    op.drop_index(op.f("ix_document_schema_versions_document_id"), table_name="document_schema_versions")
    op.drop_table("document_schema_versions")
