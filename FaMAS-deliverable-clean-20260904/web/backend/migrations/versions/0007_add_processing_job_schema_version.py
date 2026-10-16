"""Add processing job schema version.

Revision ID: 0007_add_processing_job_schema_version
Revises: 0006_add_document_schema_versions
Create Date: 2026-08-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0007_add_processing_job_schema_version"
down_revision: str | None = "0006_add_document_schema_versions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "processing_jobs"
COLUMN = "schema_version_id"
INDEX_NAME = "ix_processing_jobs_schema_version_id"
FK_NAME = "fk_processing_jobs_schema_version_id_document_schema_versions"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN not in columns:
        with op.batch_alter_table(TABLE, recreate="auto") as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.Integer(), nullable=True))

    inspector = sa.inspect(bind)
    if not _has_schema_foreign_key(inspector):
        with op.batch_alter_table(TABLE, recreate="auto") as batch_op:
            batch_op.create_foreign_key(
                FK_NAME,
                "document_schema_versions",
                [COLUMN],
                ["id"],
            )

    inspector = sa.inspect(bind)
    if not _has_schema_index(inspector):
        op.create_index(INDEX_NAME, TABLE, [COLUMN])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return

    if _has_schema_index(inspector):
        op.drop_index(INDEX_NAME, table_name=TABLE)

    inspector = sa.inspect(bind)
    if _has_schema_foreign_key(inspector):
        with op.batch_alter_table(TABLE, recreate="auto") as batch_op:
            batch_op.drop_constraint(FK_NAME, type_="foreignkey")

    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN in columns:
        with op.batch_alter_table(TABLE, recreate="auto") as batch_op:
            batch_op.drop_column(COLUMN)


def _has_schema_index(inspector: sa.Inspector) -> bool:
    return any(
        index.get("name") == INDEX_NAME
        or index.get("column_names") == [COLUMN]
        for index in inspector.get_indexes(TABLE)
    )


def _has_schema_foreign_key(inspector: sa.Inspector) -> bool:
    return any(
        fk.get("referred_table") == "document_schema_versions"
        and fk.get("constrained_columns") == [COLUMN]
        and fk.get("referred_columns") == ["id"]
        for fk in inspector.get_foreign_keys(TABLE)
    )
