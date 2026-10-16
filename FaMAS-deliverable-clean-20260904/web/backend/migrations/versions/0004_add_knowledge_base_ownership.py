"""Add knowledge base ownership.

Revision ID: 0004_add_knowledge_base_ownership
Revises: 0003_add_user_token_version
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0004_add_knowledge_base_ownership"
down_revision: str | None = "0003_add_user_token_version"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KNOWLEDGE_BASES_TABLE = "knowledge_bases"
OWNER_INDEX_NAME = "ix_knowledge_bases_owner_user_id"
DELETED_INDEX_NAME = "ix_knowledge_bases_is_deleted"
NAME_INDEX_NAME = "ix_knowledge_bases_name"
SLUG_INDEX_NAME = "ix_knowledge_bases_slug"
OWNER_FK_NAME = "fk_knowledge_bases_owner_user_id_users"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if KNOWLEDGE_BASES_TABLE not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns(KNOWLEDGE_BASES_TABLE)}
    with op.batch_alter_table(KNOWLEDGE_BASES_TABLE, recreate="auto") as batch_op:
        if "owner_user_id" not in existing_columns:
            batch_op.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        if "is_deleted" not in existing_columns:
            batch_op.add_column(sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()))

    inspector = sa.inspect(bind)
    if not _has_owner_foreign_key(inspector):
        with op.batch_alter_table(KNOWLEDGE_BASES_TABLE, recreate="auto") as batch_op:
            batch_op.create_foreign_key(
                OWNER_FK_NAME,
                "users",
                ["owner_user_id"],
                ["id"],
            )

    _ensure_nonunique_index(inspector, NAME_INDEX_NAME, ["name"])
    inspector = sa.inspect(bind)
    _ensure_nonunique_index(inspector, SLUG_INDEX_NAME, ["slug"])
    inspector = sa.inspect(bind)
    if not _has_index(inspector, OWNER_INDEX_NAME, ["owner_user_id"]):
        op.create_index(OWNER_INDEX_NAME, KNOWLEDGE_BASES_TABLE, ["owner_user_id"])
    inspector = sa.inspect(bind)
    if not _has_index(inspector, DELETED_INDEX_NAME, ["is_deleted"]):
        op.create_index(DELETED_INDEX_NAME, KNOWLEDGE_BASES_TABLE, ["is_deleted"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if KNOWLEDGE_BASES_TABLE not in inspector.get_table_names():
        return

    for index_name in [DELETED_INDEX_NAME, OWNER_INDEX_NAME]:
        inspector = sa.inspect(bind)
        if _has_index_named(inspector, index_name):
            op.drop_index(index_name, table_name=KNOWLEDGE_BASES_TABLE)

    inspector = sa.inspect(bind)
    if _has_owner_foreign_key(inspector):
        with op.batch_alter_table(KNOWLEDGE_BASES_TABLE, recreate="auto") as batch_op:
            batch_op.drop_constraint(OWNER_FK_NAME, type_="foreignkey")

    inspector = sa.inspect(bind)
    existing_columns = {column["name"] for column in inspector.get_columns(KNOWLEDGE_BASES_TABLE)}
    with op.batch_alter_table(KNOWLEDGE_BASES_TABLE, recreate="auto") as batch_op:
        if "is_deleted" in existing_columns:
            batch_op.drop_column("is_deleted")
        if "owner_user_id" in existing_columns:
            batch_op.drop_column("owner_user_id")

    _ensure_unique_index(NAME_INDEX_NAME, ["name"])
    _ensure_unique_index(SLUG_INDEX_NAME, ["slug"])


def _ensure_nonunique_index(inspector: sa.Inspector, index_name: str, columns: list[str]) -> None:
    index = _find_index(inspector, index_name, columns)
    if index and not index.get("unique"):
        return
    if index:
        op.drop_index(str(index["name"]), table_name=KNOWLEDGE_BASES_TABLE)
    op.create_index(index_name, KNOWLEDGE_BASES_TABLE, columns)


def _ensure_unique_index(index_name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    index = _find_index(inspector, index_name, columns)
    if index and index.get("unique"):
        return
    if index:
        op.drop_index(str(index["name"]), table_name=KNOWLEDGE_BASES_TABLE)
    op.create_index(index_name, KNOWLEDGE_BASES_TABLE, columns, unique=True)


def _find_index(inspector: sa.Inspector, index_name: str, columns: list[str]) -> dict | None:
    for index in inspector.get_indexes(KNOWLEDGE_BASES_TABLE):
        if index.get("name") == index_name or index.get("column_names") == columns:
            return index
    return None


def _has_index(inspector: sa.Inspector, index_name: str, columns: list[str]) -> bool:
    return _find_index(inspector, index_name, columns) is not None


def _has_index_named(inspector: sa.Inspector, index_name: str) -> bool:
    return any(index.get("name") == index_name for index in inspector.get_indexes(KNOWLEDGE_BASES_TABLE))


def _has_owner_foreign_key(inspector: sa.Inspector) -> bool:
    return any(
        fk.get("referred_table") == "users"
        and fk.get("constrained_columns") == ["owner_user_id"]
        and fk.get("referred_columns") == ["id"]
        for fk in inspector.get_foreign_keys(KNOWLEDGE_BASES_TABLE)
    )
