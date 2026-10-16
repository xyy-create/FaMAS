"""Add processing job payload JSON.

Revision ID: 0013_add_processing_job_payload_json
Revises: 0012_add_kg_annotation_templates
Create Date: 2026-09-01
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0013_add_processing_job_payload_json"
down_revision: str | None = "0012_add_kg_annotation_templates"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "processing_jobs"
COLUMN = "payload_json"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN not in columns:
        with op.batch_alter_table(TABLE, recreate="auto") as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.Text(), nullable=False, server_default="{}"))
        with op.batch_alter_table(TABLE, recreate="auto") as batch_op:
            batch_op.alter_column(COLUMN, server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(TABLE)}
    if COLUMN in columns:
        with op.batch_alter_table(TABLE, recreate="auto") as batch_op:
            batch_op.drop_column(COLUMN)
