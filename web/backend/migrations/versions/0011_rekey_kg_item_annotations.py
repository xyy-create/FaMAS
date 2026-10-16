"""Rekey knowledge graph annotations by target hash.

Revision ID: 0011_rekey_kg_item_annotations
Revises: 0010_add_kg_item_annotations
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence
import hashlib

from alembic import op
import sqlalchemy as sa

revision: str = "0011_rekey_kg_item_annotations"
down_revision: str | None = "0010_add_kg_item_annotations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "kg_item_annotations"
UNIQUE_NAME = "uq_kg_item_annotation_user_document_target"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return

    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "target_hash" in columns:
        return

    op.add_column(TABLE, sa.Column("target_hash", sa.String(length=64), nullable=True))

    rows = bind.execute(sa.text(f"SELECT id, target_id FROM {TABLE}")).mappings()
    for row in rows:
        target_hash = hashlib.sha256(str(row["target_id"]).encode("utf-8")).hexdigest()
        bind.execute(
            sa.text(f"UPDATE {TABLE} SET target_hash = :target_hash WHERE id = :id"),
            {"target_hash": target_hash, "id": row["id"]},
        )

    inspector = sa.inspect(bind)
    if any(index.get("name") == "ix_kg_item_annotations_target_id" for index in inspector.get_indexes(TABLE)):
        op.drop_index("ix_kg_item_annotations_target_id", table_name=TABLE)

    with op.batch_alter_table(TABLE, recreate="always") as batch_op:
        batch_op.alter_column("target_id", existing_type=sa.String(length=1024), type_=sa.Text(), nullable=False)
        batch_op.alter_column("target_hash", existing_type=sa.String(length=64), nullable=False)
        batch_op.drop_constraint(UNIQUE_NAME, type_="unique")
        batch_op.create_unique_constraint(
            UNIQUE_NAME,
            ["owner_user_id", "document_id", "target_kind", "target_hash"],
        )

    op.create_index(op.f("ix_kg_item_annotations_target_hash"), TABLE, ["target_hash"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if "target_hash" not in columns:
        return

    if any(index.get("name") == "ix_kg_item_annotations_target_hash" for index in inspector.get_indexes(TABLE)):
        op.drop_index("ix_kg_item_annotations_target_hash", table_name=TABLE)

    with op.batch_alter_table(TABLE, recreate="always") as batch_op:
        batch_op.alter_column("target_id", existing_type=sa.Text(), type_=sa.String(length=1024), nullable=False)
        batch_op.drop_constraint(UNIQUE_NAME, type_="unique")
        batch_op.create_unique_constraint(
            UNIQUE_NAME,
            ["owner_user_id", "document_id", "target_kind", "target_id"],
        )
        batch_op.drop_column("target_hash")

    op.create_index(op.f("ix_kg_item_annotations_target_id"), TABLE, ["target_id"], unique=False)
