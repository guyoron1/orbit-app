"""add push_tokens table

Revision ID: a1b2c3d4e5f6
Revises: e0dd26ea0b33
Create Date: 2026-03-30 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'e0dd26ea0b33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create push_tokens table if it doesn't exist."""
    conn = op.get_bind()
    tables = inspect(conn).get_table_names()
    if "push_tokens" not in tables:
        op.create_table(
            "push_tokens",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("token", sa.String(500), nullable=False, unique=True),
            sa.Column("platform", sa.String(20), nullable=False),
            sa.Column("active", sa.Boolean(), server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade() -> None:
    """Drop push_tokens table."""
    op.drop_table("push_tokens")
