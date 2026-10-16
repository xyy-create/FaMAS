"""Add is_new flag to knowledge graph overrides.

Revision ID: 0009_add_kg_override_is_new
Revises: 0008_add_kg_item_overrides
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0009_add_kg_override_is_new"
down_revision: str | None = "0008_add_kg_item_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "kg_item_overrides"
COLUMN = "is_new"
INDEX_NAME = "ix_kg_item_overrides_is_new"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN not in columns:
        with op.batch_alter_table(TABLE, recreate="auto") as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()))

    inspector = sa.inspect(bind)
    if not any(index.get("name") == INDEX_NAME for index in inspector.get_indexes(TABLE)):
        op.create_index(INDEX_NAME, TABLE, [COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    if any(index.get("name") == INDEX_NAME for index in inspector.get_indexes(TABLE)):
        op.drop_index(INDEX_NAME, table_name=TABLE)

    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN in columns:
        with op.batch_alter_table(TABLE, recreate="auto") as batch_op:
            batch_op.drop_column(COLUMN)
