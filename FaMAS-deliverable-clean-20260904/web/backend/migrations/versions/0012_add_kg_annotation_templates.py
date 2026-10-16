"""Add knowledge graph annotation templates.

Revision ID: 0012_add_kg_annotation_templates
Revises: 0011_rekey_kg_item_annotations
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0012_add_kg_annotation_templates"
down_revision: str | None = "0011_rekey_kg_item_annotations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "kg_annotation_templates"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE in set(inspector.get_table_names()):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=False),
        sa.Column("target_kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("tags_json", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_kg_annotation_templates_is_public"), TABLE, ["is_public"], unique=False)
    op.create_index(op.f("ix_kg_annotation_templates_name"), TABLE, ["name"], unique=False)
    op.create_index(op.f("ix_kg_annotation_templates_owner_user_id"), TABLE, ["owner_user_id"], unique=False)
    op.create_index(op.f("ix_kg_annotation_templates_target_kind"), TABLE, ["target_kind"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if TABLE not in set(inspector.get_table_names()):
        return

    op.drop_index(op.f("ix_kg_annotation_templates_target_kind"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_annotation_templates_owner_user_id"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_annotation_templates_name"), table_name=TABLE)
    op.drop_index(op.f("ix_kg_annotation_templates_is_public"), table_name=TABLE)
    op.drop_table(TABLE)
