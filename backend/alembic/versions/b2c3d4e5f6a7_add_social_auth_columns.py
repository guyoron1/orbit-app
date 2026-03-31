"""add social auth columns to users

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-30 22:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add auth_provider and auth_provider_id columns to users table."""
    conn = op.get_bind()
    columns = [col["name"] for col in inspect(conn).get_columns("users")]

    if "auth_provider" not in columns:
        op.add_column("users", sa.Column("auth_provider", sa.String(20), server_default="email"))

    if "auth_provider_id" not in columns:
        op.add_column("users", sa.Column("auth_provider_id", sa.String(255), nullable=True, unique=True))


def downgrade() -> None:
    """Remove social auth columns."""
    op.drop_column("users", "auth_provider_id")
    op.drop_column("users", "auth_provider")
