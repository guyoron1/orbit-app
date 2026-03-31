"""add email_verified to users

Revision ID: e0dd26ea0b33
Revises: fe7fce7ba8ae
Create Date: 2026-03-30 20:54:25.938593

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision: str = 'e0dd26ea0b33'
down_revision: Union[str, Sequence[str], None] = 'fe7fce7ba8ae'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add email_verified column to users table."""
    conn = op.get_bind()
    columns = [col["name"] for col in inspect(conn).get_columns("users")]
    if "email_verified" not in columns:
        op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=True, server_default=sa.text("false")))


def downgrade() -> None:
    """Remove email_verified column."""
    op.drop_column("users", "email_verified")
