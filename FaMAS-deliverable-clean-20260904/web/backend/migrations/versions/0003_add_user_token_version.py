"""Add user token version.

Revision ID: 0003_add_user_token_version
Revises: 0002_reconcile_legacy_document_owner_constraints
Create Date: 2026-08-24
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0003_add_user_token_version"
down_revision: str | None = "0002_reconcile_legacy_document_owner_constraints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USERS_TABLE = "users"
TOKEN_VERSION_COLUMN = "token_version"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if USERS_TABLE not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns(USERS_TABLE)}
    if TOKEN_VERSION_COLUMN in existing_columns:
        return

    op.add_column(
        USERS_TABLE,
        sa.Column(
            TOKEN_VERSION_COLUMN,
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if USERS_TABLE not in inspector.get_table_names():
        return
    existing_columns = {column["name"] for column in inspector.get_columns(USERS_TABLE)}
    if TOKEN_VERSION_COLUMN not in existing_columns:
        return

    op.drop_column(USERS_TABLE, TOKEN_VERSION_COLUMN)
