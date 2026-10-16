"""Add knowledge graph item overrides.

Revision ID: 0008_add_kg_item_overrides
Revises: 0007_add_processing_job_schema_version
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0008_add_kg_item_overrides"
down_revision: str | None = "0007_add_processing_job_schema_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "kg_item_overrides"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE in set(inspector.get_table_names()):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("knowledge_base_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("item_kind", sa.String(length=16), nullable=False),
        sa.Column("item_id", sa.String(length=255), nullable=False),
        sa.Column("is_hidden", sa.Boolean(), nullable=False),
        sa.Column("patch_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "document_id",
            "item_kind",
            "item_id",
            name="uq_kg_item_override_user_document_item",
        ),
    )
    op.create_index(op.f("ix_kg_item_overrides_document_id"), TABLE, ["document_id"], unique=False)
    op.create_index(op.f("ix_kg_item_overrides_is_hidden"), TABLE, ["is_hidden"], unique=False)
    op.create_index(op.f("ix_kg_item_overrides_item_id"), TABLE, ["item_id"], unique=False)
    op.create_index(op.f("ix_kg_item_overrides_item_kind"), TABLE, ["item_kind"], unique=False)
    op.create_index(op.f("ix_kg_item_overrides_knowledge_base_id"), TABLE, ["knowledge_base_id"], unique=False)
    op.create_index(op.f("ix_kg_item_overrides_owner_user_id"), TABLE, ["owner_user_id"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names()):
        return

    op.drop_index(op.f("ix_kg_item_overrides_owner_user_id"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_item_overrides_knowledge_base_id"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_item_overrides_item_kind"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_item_overrides_item_id"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_item_overrides_is_hidden"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_item_overrides_document_id"), table_name=TABLE)
    op.drop_table(TABLE)
