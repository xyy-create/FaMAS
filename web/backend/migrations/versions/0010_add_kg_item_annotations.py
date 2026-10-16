"""Add knowledge graph item annotations.

Revision ID: 0010_add_kg_item_annotations
Revises: 0009_add_kg_override_is_new
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0010_add_kg_item_annotations"
down_revision: str | None = "0009_add_kg_override_is_new"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "kg_item_annotations"


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
        sa.Column("target_kind", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.Text(), nullable=False),
        sa.Column("target_hash", sa.String(length=64), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "document_id",
            "target_kind",
            "target_hash",
            name="uq_kg_item_annotation_user_document_target",
        ),
    )
    op.create_index(op.f("ix_kg_item_annotations_document_id"), TABLE, ["document_id"], unique=False)
    op.create_index(op.f("ix_kg_item_annotations_knowledge_base_id"), TABLE, ["knowledge_base_id"], unique=False)
    op.create_index(op.f("ix_kg_item_annotations_owner_user_id"), TABLE, ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_kg_item_annotations_target_hash"), TABLE, ["target_hash"], unique=False)
    op.create_index(op.f("ix_kg_item_annotations_target_kind"), TABLE, ["target_kind"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names()):
        return

    op.drop_index(op.f("ix_kg_item_annotations_target_kind"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_item_annotations_target_hash"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_item_annotations_owner_user_id"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_item_annotations_knowledge_base_id"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_item_annotations_document_id"), table_name=TABLE)
    op.drop_table(TABLE)
