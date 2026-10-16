"""Add QA conversation history.

Revision ID: 0005_add_qa_conversations
Revises: 0004_add_knowledge_base_ownership
Create Date: 2026-08-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0005_add_qa_conversations"
down_revision: str | None = "0004_add_knowledge_base_ownership"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())

    if "qa_conversations" not in existing_tables:
        op.create_table(
            "qa_conversations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("knowledge_base_id", sa.Integer(), nullable=False),
            sa.Column("document_id", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("provider", sa.String(length=64), nullable=False),
            sa.Column("answer_mode", sa.String(length=32), nullable=False),
            sa.Column("answer_style", sa.String(length=32), nullable=False),
            sa.Column("is_deleted", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
            sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"]),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_qa_conversations_document_id"), "qa_conversations", ["document_id"], unique=False)
        op.create_index(op.f("ix_qa_conversations_is_deleted"), "qa_conversations", ["is_deleted"], unique=False)
        op.create_index(
            op.f("ix_qa_conversations_knowledge_base_id"),
            "qa_conversations",
            ["knowledge_base_id"],
            unique=False,
        )
        op.create_index(op.f("ix_qa_conversations_user_id"), "qa_conversations", ["user_id"], unique=False)

    inspector = sa.inspect(op.get_bind())
    if "qa_messages" not in set(inspector.get_table_names()):
        op.create_table(
            "qa_messages",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("conversation_id", sa.Integer(), nullable=False),
            sa.Column("role", sa.String(length=32), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("citations_json", sa.Text(), nullable=False),
            sa.Column("metadata_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["conversation_id"], ["qa_conversations.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_qa_messages_conversation_id"), "qa_messages", ["conversation_id"], unique=False)
        op.create_index(op.f("ix_qa_messages_created_at"), "qa_messages", ["created_at"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    if "qa_messages" in existing_tables:
        op.drop_index(op.f("ix_qa_messages_created_at"), table_name="qa_messages")
        op.drop_index(op.f("ix_qa_messages_conversation_id"), table_name="qa_messages")
        op.drop_table("qa_messages")

    inspector = sa.inspect(op.get_bind())
    if "qa_conversations" in set(inspector.get_table_names()):
        op.drop_index(op.f("ix_qa_conversations_user_id"), table_name="qa_conversations")
        op.drop_index(op.f("ix_qa_conversations_knowledge_base_id"), table_name="qa_conversations")
        op.drop_index(op.f("ix_qa_conversations_is_deleted"), table_name="qa_conversations")
        op.drop_index(op.f("ix_qa_conversations_document_id"), table_name="qa_conversations")
        op.drop_table("qa_conversations")
