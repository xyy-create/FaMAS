"""Reconcile legacy document owner constraints.

Revision ID: 0002_reconcile_legacy_document_owner_constraints
Revises: 0001_initial_web_schema
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0002_reconcile_legacy_document_owner_constraints"
down_revision: str | None = "0001_initial_web_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DOCUMENTS_TABLE = "documents"
OWNER_INDEX_NAME = "ix_documents_owner_user_id"
OWNER_FK_NAME = "fk_documents_owner_user_id_users"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if DOCUMENTS_TABLE not in inspector.get_table_names():
        return

    if not _has_owner_foreign_key(inspector):
        with op.batch_alter_table(DOCUMENTS_TABLE, recreate="auto") as batch_op:
            batch_op.create_foreign_key(
                OWNER_FK_NAME,
                "users",
                ["owner_user_id"],
                ["id"],
            )

    inspector = sa.inspect(bind)
    if not _has_owner_index(inspector):
        op.create_index(OWNER_INDEX_NAME, DOCUMENTS_TABLE, ["owner_user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if DOCUMENTS_TABLE not in inspector.get_table_names():
        return

    if _has_owner_index(inspector):
        op.drop_index(OWNER_INDEX_NAME, table_name=DOCUMENTS_TABLE)

    inspector = sa.inspect(bind)
    if _has_owner_foreign_key(inspector):
        with op.batch_alter_table(DOCUMENTS_TABLE, recreate="auto") as batch_op:
            batch_op.drop_constraint(OWNER_FK_NAME, type_="foreignkey")


def _has_owner_index(inspector: sa.Inspector) -> bool:
    return any(
        index.get("name") == OWNER_INDEX_NAME
        or index.get("column_names") == ["owner_user_id"]
        for index in inspector.get_indexes(DOCUMENTS_TABLE)
    )


def _has_owner_foreign_key(inspector: sa.Inspector) -> bool:
    return any(
        fk.get("referred_table") == "users"
        and fk.get("constrained_columns") == ["owner_user_id"]
        and fk.get("referred_columns") == ["id"]
        for fk in inspector.get_foreign_keys(DOCUMENTS_TABLE)
    )
